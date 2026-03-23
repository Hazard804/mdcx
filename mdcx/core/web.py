"""
刮削过程的网络操作
"""

import asyncio
import re
import shutil
import time
import urllib.parse
from asyncio import to_thread
from difflib import SequenceMatcher
from pathlib import Path

import aiofiles
import aiofiles.os
from lxml import etree

from ..base.web import (
    check_url,
    download_extrafanart_task,
    download_file_with_filepath,
    get_amazon_data,
    get_big_pic_by_google,
    get_dmm_trailer,
    get_imgsize,
)
from ..config.enums import DownloadableFile, HDPicSource
from ..config.manager import manager
from ..manual import ManualConfig
from ..models.flags import Flags
from ..models.log_buffer import LogBuffer
from ..models.types import CrawlersResult, OtherInfo
from ..signals import signal
from ..utils import convert_half, get_used_time, split_path
from ..utils.file import check_pic_async, copy_file_async, delete_file_async, move_file_async
from .image import cut_thumb_to_poster


async def get_big_pic_by_amazon(
    result: CrawlersResult,
    originaltitle_amazon: str,
    actor_amazon: list[str],
    series: str = "",
    originaltitle_amazon_raw: str = "",
    series_raw: str = "",
) -> str:
    if not originaltitle_amazon and not originaltitle_amazon_raw:
        return ""
    hd_pic_url = ""
    invalid_actor_names = {
        manager.config.actor_no_name.strip(),
        "未知演员",
        "未知演員",
        "女优不明",
        "女優不明",
        "人物不明",
        "素人",
        "素人(多人)",
        "素人（多人）",
        "素人妻",
        "素人娘",
        "素人(援交)",
        "素人（援交）",
        "素人(偷窃)",
        "素人（偷窃）",
        "素人(患者)",
        "素人（患者）",
        "S级素人",
        "S級素人",
    }

    def is_valid_actor_name(actor_name: str) -> bool:
        actor_name = re.sub(r"\s+", " ", actor_name).strip()
        if not actor_name:
            return False
        return actor_name not in invalid_actor_names

    actor_groups: list[set[str]] = []
    actor_group_key_set: set[tuple[str, ...]] = set()
    actor_keyword_set: set[str] = set()
    actor_search_keywords: list[str] = []
    for actor in actor_amazon:
        if not actor:
            continue
        actor = re.sub(r"\s+", " ", actor).strip()
        if not is_valid_actor_name(actor):
            continue
        group: set[str] = set()
        alias_list = [alias.strip() for alias in re.findall(r"[^\(\)\（\）]+", actor) if alias.strip()]
        for each in alias_list + [actor]:
            each = re.sub(r"\s+", " ", each).strip()
            if not is_valid_actor_name(each):
                continue
            group.add(each)
            actor_keyword_set.add(each)
            if each not in actor_search_keywords:
                actor_search_keywords.append(each)
        if group:
            group_key = tuple(sorted(group))
            if group_key not in actor_group_key_set:
                actor_groups.append(group)
                actor_group_key_set.add(group_key)

    actor_keywords = list(actor_keyword_set)
    actor_keywords_sorted = sorted(actor_keywords, key=len, reverse=True)
    actor_groups_normalized = [{convert_half(alias).upper() for alias in group} for group in actor_groups]
    has_valid_actor = bool(actor_groups_normalized)
    expected_actor_count = len(actor_groups_normalized)
    if not has_valid_actor:
        LogBuffer.log().write("\n 🔎 Amazon搜索：未找到有效演员，切换为标题/番号模式")

    def build_number_regex(number_text: str) -> re.Pattern[str] | None:
        normalized_number = convert_half(number_text or "").upper().strip()
        if not normalized_number:
            return None
        token_list = re.findall(r"[A-Z0-9]+", normalized_number)
        if not token_list:
            return None
        pattern = r"(?<![A-Z0-9])" + r"[^A-Z0-9]*".join(re.escape(token) for token in token_list) + r"(?![A-Z0-9])"
        return re.compile(pattern, flags=re.IGNORECASE)

    number_regex = build_number_regex(result.number)

    def text_has_target_number(text: str) -> bool:
        if not number_regex or not text:
            return False
        return bool(number_regex.search(convert_half(text).upper()))

    def count_actor_group_matches(text: str) -> int:
        if not actor_groups_normalized or not text:
            return 0
        normalized_text = convert_half(re.sub(r"\s+", " ", text or "")).upper()
        return sum(1 for group in actor_groups_normalized if any(alias in normalized_text for alias in group))

    def strip_trailing_media_noise(base_title: str) -> str:
        title = re.sub(r"\s+", " ", base_title).strip()
        if not title:
            return ""
        trim_chars = " 　-—｜|/／・,，、：:()（）[]【】"
        trailing_media_noise = re.compile(
            r"(?:[\s　\-\—\｜\|/／・,，、：:\(\)（）\[\]［］]+)?"
            r"(?:dod|dvd|blu[- ]?ray|software\s+download|ブルーレイ(?:ディスク)?|ソフトウェアダウンロード)"
            r"(?:[\s　\-\—\｜\|/／・,，、：:\(\)（）\[\]［］]+)?$",
            flags=re.I,
        )
        while True:
            updated, count = trailing_media_noise.subn("", title)
            if count == 0:
                break
            updated = updated.strip(trim_chars)
            if not updated or updated == title:
                break
            title = updated
        return title

    def strip_actor_suffix(base_title: str) -> str:
        title = base_title.strip()
        if not title or not actor_keywords_sorted:
            return title
        trim_chars = " 　-—｜|/／・,，、：:()（）[]【】"
        while True:
            changed = False
            for actor in actor_keywords_sorted:
                escaped_actor = re.escape(actor)
                for pattern in (
                    rf"(?:\s|　)+{escaped_actor}$",
                    rf"(?:-|—|｜|/|／|・|,|，|、|：|:)\s*{escaped_actor}$",
                    rf"{escaped_actor}$",
                ):
                    new_title, count = re.subn(pattern, "", title)
                    if count == 0:
                        continue
                    new_title = new_title.strip(trim_chars)
                    if new_title and new_title != title:
                        title = new_title
                        changed = True
                        break
                if changed:
                    break
            if not changed:
                break
        return title

    def normalize_amazon_search_title(base_title: str) -> tuple[str, bool]:
        normalized = re.sub(r"【.*】", "", base_title or "")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return "", False
        cleaned = strip_trailing_media_noise(normalized)
        cleaned = strip_actor_suffix(cleaned)
        cleaned = strip_trailing_media_noise(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned, cleaned != normalized

    originaltitle_amazon, originaltitle_amazon_simplified = normalize_amazon_search_title(originaltitle_amazon)
    originaltitle_amazon_raw, originaltitle_amazon_raw_simplified = normalize_amazon_search_title(
        originaltitle_amazon_raw
    )
    series = strip_trailing_media_noise(re.sub(r"【.*】", "", series).strip())
    series_raw = strip_trailing_media_noise(re.sub(r"【.*】", "", series_raw).strip())
    if originaltitle_amazon_simplified or originaltitle_amazon_raw_simplified:
        LogBuffer.log().write("\n 🔎 Amazon清洗关键词: 已移除标题尾部的演员/媒介噪音")
    search_queue: list[tuple[str, str, bool]] = []
    search_keyword_set: set[str] = set()
    split_keyword_added = False
    actor_fragment_added = False

    def append_search_keyword(keyword: str, *, fallback_series: str = "", is_initial_query: bool = False):
        keyword = re.sub(r"\s+", " ", keyword).strip()
        if keyword and keyword not in search_keyword_set:
            search_queue.append((keyword, fallback_series, is_initial_query))
            search_keyword_set.add(keyword)

    def append_title_search_variants(
        keyword: str,
        *,
        fallback_series: str = "",
        is_initial_query: bool = False,
        prefer_plain_first: bool = False,
    ):
        keyword = re.sub(r"\s+", " ", keyword).strip()
        if not keyword:
            return
        if result.number and not text_has_target_number(keyword):
            numbered_keyword = f"{keyword} {result.number}"
            if prefer_plain_first:
                append_search_keyword(keyword, fallback_series=fallback_series, is_initial_query=is_initial_query)
                append_search_keyword(
                    numbered_keyword, fallback_series=fallback_series, is_initial_query=is_initial_query
                )
                return
            append_search_keyword(numbered_keyword, fallback_series=fallback_series, is_initial_query=is_initial_query)
        append_search_keyword(keyword, fallback_series=fallback_series, is_initial_query=is_initial_query)

    append_title_search_variants(
        originaltitle_amazon,
        fallback_series=series,
        is_initial_query=True,
        prefer_plain_first=originaltitle_amazon_simplified,
    )
    append_title_search_variants(
        originaltitle_amazon_raw,
        fallback_series=series_raw,
        is_initial_query=True,
        prefer_plain_first=originaltitle_amazon_raw_simplified,
    )

    def append_split_keyword(base_title: str):
        for each_name in base_title.split(" "):
            if each_name not in search_keyword_set and (
                len(each_name) > 8
                or (not each_name.encode("utf-8").isalnum() and len(each_name) > 4)
                and each_name not in actor_keywords
            ):
                append_search_keyword(each_name)

    def append_split_keyword_from_replaced_title():
        nonlocal split_keyword_added
        if split_keyword_added:
            return
        split_keyword_added = True
        append_split_keyword(originaltitle_amazon_raw)

    def append_actor_fragment_keywords_from_titles():
        nonlocal actor_fragment_added
        if actor_fragment_added or not actor_keywords_sorted:
            return
        actor_fragment_added = True
        trim_chars = " 　-—｜|/／・,，、：:()（）[]【】"
        for base_title in [originaltitle_amazon_raw, originaltitle_amazon]:
            normalized_base_title = re.sub(r"\s+", " ", base_title).strip()
            if not normalized_base_title:
                continue
            for actor in actor_keywords_sorted:
                index = normalized_base_title.find(actor)
                if index <= 0:
                    continue
                fragment = normalized_base_title[index:].strip(trim_chars)
                if fragment and fragment != normalized_base_title:
                    append_title_search_variants(fragment)

    def append_series_fallback_keywords(base_title: str, fallback_series: str):
        if not fallback_series:
            return
        append_search_keyword(fallback_series)
        if fallback_series in base_title:
            stripped_title = re.sub(re.escape(fallback_series), " ", base_title, count=1)
            append_title_search_variants(stripped_title)

    no_result_tips = (
        "キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。",
        "検索に一致する商品はありませんでした。",
        "No results for",
        "did not match any products",
        "没有找到与",
        "沒有找到與",
        "找不到與",
        "未找到与",
        "您的搜索查询无结果。",
        "请尝试检查您的拼写或使用更多常规术语",
    )

    def is_no_result(html_content: str) -> bool:
        if not html_content:
            return True
        if any(each in html_content for each in no_result_tips):
            return True
        if "s-no-results" in html_content.lower():
            return True
        return False

    media_title_keywords = [
        "dod",
        "dvd",
        "blu-ray",
        "blu ray",
        "software download",
        "ブルーレイ",
        "ブルーレイディスク",
        "ソフトウェアダウンロード",
        "[dvd]",
        "[dod]",
        "[blu-ray]",
        "［dvd］",
        "［dod］",
        "［blu-ray］",
    ]
    metadata_source_fields: list[str] = []
    for raw_field, mapped_field in [
        (result.amazon_raw_director, result.director),
        (result.amazon_raw_studio, result.studio),
        (result.amazon_raw_publisher, result.publisher),
    ]:
        for each_field in [raw_field, mapped_field]:
            each_field = (each_field or "").strip()
            if each_field and each_field not in metadata_source_fields:
                metadata_source_fields.append(each_field)
    if any(
        [
            result.amazon_raw_director and result.amazon_raw_director != result.director,
            result.amazon_raw_studio and result.amazon_raw_studio != result.studio,
            result.amazon_raw_publisher and result.amazon_raw_publisher != result.publisher,
        ]
    ):
        LogBuffer.log().write("\n 🔎 Amazon清洗关键词: 已优先使用未映射字段")
    metadata_keywords: list[str] = []
    for field in metadata_source_fields:
        for each in re.split(r"[,，/／|｜]", field):
            each = each.strip()
            if each:
                metadata_keywords.append(each)
    suffix_cleanup_keywords = sorted(
        set(media_title_keywords + actor_keywords + metadata_keywords),
        key=len,
        reverse=True,
    )

    def clean_amazon_title_for_compare(title: str) -> str:
        cleaned = re.sub(r"【.*?】", " ", title)
        cleaned = re.sub(r"[［\[]\s*(?:dvd|blu[- ]?ray|software\s+download)\s*[］\]]", " ", cleaned, flags=re.I)
        trim_chars = " 　-—｜|/／・,，、：:()（）[]【】!?！？…."
        while True:
            changed = False
            for keyword in suffix_cleanup_keywords:
                escaped_keyword = re.escape(keyword)
                for pattern in (
                    rf"(?:\s|　)+{escaped_keyword}$",
                    rf"(?:-|—|｜|/|／|・|,|，|、|：|:)\s*{escaped_keyword}$",
                    rf"{escaped_keyword}$",
                ):
                    updated = re.sub(pattern, "", cleaned, flags=re.I).strip(trim_chars)
                    if updated and updated != cleaned:
                        cleaned = updated
                        changed = True
                        break
                if changed:
                    break
            if not changed:
                break
        return re.sub(r"\s+", " ", cleaned).strip(trim_chars)

    def normalize_title_for_compare(title: str) -> str:
        wildcard_placeholder = "\u2606"
        wildcard_token = "MDCXWILDCARDTOKEN"
        title = re.sub(r"[●○◯〇◎◉◆◇■□△▲▽▼※＊*]", wildcard_token, title)
        normalized = convert_half(title).lower()
        if number_regex:
            normalized = number_regex.sub(" ", normalized.upper()).lower()
        normalized = re.sub(r"【.*?】", "", normalized)
        normalized = re.sub(r"[［\[]\s*(?:dvd|blu[- ]?ray|software\s+download)\s*[］\]]", "", normalized, flags=re.I)
        normalized = normalized.replace(wildcard_token.lower(), wildcard_placeholder)
        normalized = re.sub(r"[\s　\-\—\｜\|/／・,，、：:()（）\[\]【】!?！？…\.]", "", normalized)
        return normalized

    def calculate_title_confidence(expected_title: str, candidate_title: str) -> float:
        expected = normalize_title_for_compare(clean_amazon_title_for_compare(expected_title))
        candidate = normalize_title_for_compare(clean_amazon_title_for_compare(candidate_title))
        if not expected or not candidate:
            return 0.0
        if expected == candidate:
            return 1.0

        wildcard_placeholder = "\u2606"

        def _strip_wildcard(text: str) -> str:
            return text.replace(wildcard_placeholder, "")

        def _chars_match(ch_a: str, ch_b: str) -> bool:
            return ch_a == ch_b or ch_a == wildcard_placeholder or ch_b == wildcard_placeholder

        def _wildcard_contains(pattern_text: str, target_text: str) -> bool:
            if not pattern_text or not target_text or len(pattern_text) > len(target_text):
                return False
            window = len(pattern_text)
            max_start = len(target_text) - window
            for start in range(max_start + 1):
                if all(_chars_match(pattern_text[index], target_text[start + index]) for index in range(window)):
                    return True
            return False

        def _wildcard_full_match(text_a: str, text_b: str) -> bool:
            if len(text_a) != len(text_b):
                return False
            return all(_chars_match(ch_a, ch_b) for ch_a, ch_b in zip(text_a, text_b, strict=False))

        contain_ratio = 0.0
        expected_plain_len = max(len(_strip_wildcard(expected)), 1)
        candidate_plain_len = max(len(_strip_wildcard(candidate)), 1)
        if _wildcard_contains(expected, candidate):
            contain_ratio = max(
                contain_ratio,
                1.0 if expected_plain_len >= 12 else min(1.0, expected_plain_len / candidate_plain_len),
            )
        if _wildcard_contains(candidate, expected):
            contain_ratio = max(
                contain_ratio,
                1.0 if candidate_plain_len >= 12 else min(1.0, candidate_plain_len / expected_plain_len),
            )

        sequence_ratio = SequenceMatcher(None, expected, candidate).ratio()
        expected_no_wildcard = _strip_wildcard(expected)
        candidate_no_wildcard = _strip_wildcard(candidate)
        if expected_no_wildcard and candidate_no_wildcard:
            sequence_ratio = max(
                sequence_ratio, SequenceMatcher(None, expected_no_wildcard, candidate_no_wildcard).ratio()
            )

        def _bigrams(text: str) -> set[str]:
            if len(text) < 2:
                return {text}
            return {text[i : i + 2] for i in range(len(text) - 1)}

        bigrams_expected = _bigrams(expected_no_wildcard or expected)
        bigrams_candidate = _bigrams(candidate_no_wildcard or candidate)
        jaccard = (
            len(bigrams_expected & bigrams_candidate) / len(bigrams_expected | bigrams_candidate)
            if bigrams_expected and bigrams_candidate
            else 0.0
        )

        score = 0.6 * sequence_ratio + 0.25 * contain_ratio + 0.15 * jaccard
        if _wildcard_full_match(expected, candidate) or _wildcard_full_match(candidate, expected):
            score = max(score, 0.95)
        if contain_ratio >= 0.95 and min(len(expected), len(candidate)) >= 12:
            score = max(score, 0.92)
        return score

    expected_titles: list[str] = []
    expected_title_set: set[str] = set()
    for title_text, fallback_series in [(originaltitle_amazon_raw, series_raw), (originaltitle_amazon, series)]:
        title_text = re.sub(r"\s+", " ", title_text).strip()
        if title_text and title_text not in expected_title_set:
            expected_titles.append(title_text)
            expected_title_set.add(title_text)
        if fallback_series and fallback_series in title_text:
            stripped_title = re.sub(re.escape(fallback_series), " ", title_text, count=1)
            stripped_title = re.sub(r"\s+", " ", stripped_title).strip()
            if stripped_title and stripped_title not in expected_title_set:
                expected_titles.append(stripped_title)
                expected_title_set.add(stripped_title)

    def get_media_priority(pic_ver: str) -> int:
        if not pic_ver:
            return 2
        version_text = pic_ver.strip().lower()
        if "dvd" in version_text:
            return 3
        if "software download" in version_text:
            return 2
        if any(each in version_text for each in ["blu-ray", "blu ray", "ブルーレイ", "ブルーレイディスク"]):
            return 1
        return 0

    def is_supported_pic_ver(pic_ver: str) -> bool:
        return get_media_priority(pic_ver) > 0 or not pic_ver

    async def search_amazon(title: str) -> tuple[bool, str]:
        url_search = (
            "https://www.amazon.co.jp/black-curtain/save-eligibility/black-curtain?returnUrl=/s?k="
            + urllib.parse.quote_plus(urllib.parse.quote_plus(title.replace("&", " ")))
            + "&ref=nb_sb_noss"
        )
        return await get_amazon_data(url_search)

    async def search_amazon_by_actor_fallback() -> str:
        if not actor_search_keywords:
            return ""
        confidence_threshold = 0.75
        best_match: tuple[tuple[int, float, int, int], str, str, str] | None = None
        best_rejected_candidate: tuple[float, str, str, str] | None = None

        def update_best_rejected(score: float, actor_name: str, pic_title: str, reason: str):
            nonlocal best_rejected_candidate
            if best_rejected_candidate is None or score > best_rejected_candidate[0]:
                best_rejected_candidate = (score, actor_name, pic_title, reason)

        LogBuffer.log().write("\n 🔎 Amazon兜底：开始按演员名搜索并匹配标题置信度")
        for actor_name in actor_search_keywords:
            success, html_search = await search_amazon(actor_name)
            if not success or not html_search or is_no_result(html_search):
                continue
            html = etree.fromstring(html_search, etree.HTMLParser())
            pic_card = html.xpath('//div[@data-component-type="s-search-result" and @data-asin]')
            for each in pic_card:
                pic_ver_list = each.xpath('.//a[contains(@class, "a-text-bold")]/text()')
                pic_title_list = each.xpath(".//h2//a//span/text() | .//h2//span/text()")
                pic_url_list = each.xpath('.//img[contains(@class, "s-image")]/@src')
                if not (pic_url_list and pic_title_list):
                    continue
                pic_ver = pic_ver_list[0] if pic_ver_list else ""
                pic_title = pic_title_list[0]
                pic_url = pic_url_list[0]
                if not is_supported_pic_ver(pic_ver):
                    update_best_rejected(0.0, actor_name, pic_title, f"媒介类型不支持({pic_ver})")
                    continue
                if ".jpg" not in pic_url:
                    update_best_rejected(0.0, actor_name, pic_title, "图片地址不是JPG")
                    continue
                cleaned_title = clean_amazon_title_for_compare(pic_title)
                confidence = max(
                    calculate_title_confidence(each_title, cleaned_title) for each_title in expected_titles
                )
                if confidence < confidence_threshold:
                    update_best_rejected(
                        confidence,
                        actor_name,
                        pic_title,
                        f"置信度不足({confidence:.2f} < {confidence_threshold:.2f})",
                    )
                    continue
                url = re.sub(r"\._[_]?AC_[^\.]+\.", ".", pic_url)
                width, _ = await get_imgsize(url)
                width = width or 0
                current_match = (
                    (1 if text_has_target_number(pic_title) else 0, confidence, get_media_priority(pic_ver), width),
                    url,
                    pic_title,
                    actor_name,
                )
                if best_match is None or current_match[0] > best_match[0]:
                    best_match = current_match

        if not best_match:
            if best_rejected_candidate:
                score, rejected_actor, rejected_title, rejected_reason = best_rejected_candidate
                LogBuffer.log().write(
                    f"\n 🟡 Amazon兜底未命中：最高候选分({score:.2f}) 演员({rejected_actor}) "
                    f"原因({rejected_reason}) 标题({rejected_title})"
                )
            else:
                LogBuffer.log().write("\n 🟡 Amazon兜底未命中：演员搜索无可评估候选结果")
            return ""
        (number_match, confidence, media_priority, width), matched_url, matched_title, matched_actor = best_match
        LogBuffer.log().write(
            f"\n 🟢 Amazon兜底命中：演员({matched_actor}) 置信度({confidence:.2f}) 番号命中({bool(number_match)})"
            f" 标题({matched_title})"
        )
        if width > 600 or not width:
            return matched_url
        result.poster = matched_url
        result.poster_from = "Amazon"
        return ""

    def normalize_detail_url(detail_url: str) -> str:
        if not detail_url:
            return ""
        absolute_url = urllib.parse.urljoin("https://www.amazon.co.jp", detail_url)
        decoded_url = urllib.parse.unquote_plus(absolute_url)
        if matched := re.search(r"/dp/([^/?&#]+)", decoded_url):
            return f"https://www.amazon.co.jp/dp/{matched.group(1)}"
        return ""

    def build_candidate_key(detail_url: str, pic_url: str) -> str:
        normalized_detail_url = normalize_detail_url(detail_url)
        if normalized_detail_url:
            return normalized_detail_url
        return re.sub(r"\._[_]?AC_[^\.]+\.", ".", pic_url)

    async def enrich_candidate(candidate: dict[str, object]):
        if candidate["detail_checked"] or not candidate["detail_url"]:
            candidate["detail_checked"] = True
            return
        success, html_detail = await get_amazon_data(str(candidate["detail_url"]))
        candidate["detail_checked"] = True
        if not success or not html_detail:
            return
        html = etree.fromstring(html_detail, etree.HTMLParser())
        detail_actor_names: list[str] = []
        for each_xpath in [
            '//span[contains(@class, "author")]/a/text()',
            '//div[@id="bylineInfo_feature_div"]//a/text()',
            '//div[@id="bylineInfo"]//a/text()',
        ]:
            detail_actor_names.extend(text.strip() for text in html.xpath(each_xpath) if text and text.strip())
        detail_actor_names = list(dict.fromkeys(detail_actor_names))
        detail_texts: list[str] = []
        for each_xpath in [
            '//span[@id="productTitle"]/text()',
            '//ul[@class="a-unordered-list a-vertical a-spacing-mini"]//text()',
            '//div[@id="detailBulletsWrapper_feature_div"]//text()',
            '//div[@id="detailBullets_feature_div"]//text()',
            '//table[@id="productDetails_detailBullets_sections1"]//text()',
            '//div[@id="prodDetails"]//text()',
            '//div[@id="productOverview_feature_div"]//text()',
            '//div[@id="productDescription"]//text()',
        ]:
            detail_texts.extend(text.strip() for text in html.xpath(each_xpath) if text and text.strip())
        detail_title = next((text for text in detail_texts if text), "")
        if detail_title:
            candidate["title_confidence"] = max(
                float(candidate["title_confidence"]),
                max(calculate_title_confidence(each_title, detail_title) for each_title in expected_titles),
            )
        detail_blob = " ".join(detail_actor_names + detail_texts)
        candidate["detail_actor_count"] = len(detail_actor_names)
        candidate["detail_actor_matches"] = max(
            int(candidate["detail_actor_matches"]),
            int(candidate["quick_actor_matches"]),
            count_actor_group_matches(detail_blob),
        )
        candidate["detail_number_match"] = text_has_target_number(detail_blob)

    def candidate_actor_match_count(candidate: dict[str, object]) -> int:
        return max(int(candidate["quick_actor_matches"]), int(candidate["detail_actor_matches"]))

    def candidate_number_match(candidate: dict[str, object]) -> bool:
        return bool(candidate["quick_number_match"] or candidate["detail_number_match"])

    def candidate_score(candidate: dict[str, object]) -> float:
        title_confidence = float(candidate["title_confidence"])
        actor_match_count = candidate_actor_match_count(candidate)
        actor_ratio = actor_match_count / expected_actor_count if expected_actor_count else 0.0
        score = title_confidence * 100
        if candidate_number_match(candidate):
            score += 120
        if has_valid_actor:
            score += actor_ratio * 20
        if (
            expected_actor_count == 1
            and int(candidate["detail_actor_count"]) > 1
            and not candidate_number_match(candidate)
        ):
            score -= 12
        score += int(candidate["media_priority"]) * 2
        return score

    def is_candidate_acceptable(candidate: dict[str, object]) -> bool:
        title_confidence = float(candidate["title_confidence"])
        actor_match_count = candidate_actor_match_count(candidate)
        detail_actor_count = int(candidate["detail_actor_count"])
        number_match = candidate_number_match(candidate)
        if number_match:
            return title_confidence >= 0.55
        if has_valid_actor:
            if expected_actor_count == 1:
                if detail_actor_count > 1:
                    return title_confidence >= 0.92
                return (actor_match_count >= 1 and title_confidence >= 0.78) or title_confidence >= 0.93
            required_actor_matches = min(expected_actor_count, max(2, (expected_actor_count + 1) // 2))
            return title_confidence >= 0.76 and actor_match_count >= required_actor_matches
        return title_confidence >= 0.88

    def candidate_sort_key(candidate: dict[str, object]) -> tuple[float, int, int]:
        return (candidate_score(candidate), int(candidate["media_priority"]), int(candidate["width"]))

    candidate_pool: dict[str, dict[str, object]] = {}
    query_index = 0
    while query_index < len(search_queue):
        current_title, current_series, is_initial_query = search_queue[query_index]
        success, html_search = await search_amazon(current_title)

        if not success or (is_initial_query and is_no_result(html_search)):
            if is_initial_query:
                append_series_fallback_keywords(current_title, current_series)
                append_split_keyword_from_replaced_title()
                append_actor_fragment_keywords_from_titles()
            query_index += 1
            continue

        if result and html_search:
            html = etree.fromstring(html_search, etree.HTMLParser())
            query_has_signal = False
            pic_card = html.xpath('//div[@data-component-type="s-search-result" and @data-asin]')
            for each in pic_card:
                pic_ver_list = each.xpath('.//a[contains(@class, "a-text-bold")]/text()')
                pic_title_list = each.xpath(".//h2//a//span/text() | .//h2//span/text()")
                pic_url_list = each.xpath('.//img[contains(@class, "s-image")]/@src')
                detail_url_list = each.xpath('.//h2//a/@href | .//a[contains(@class, "s-no-outline")]/@href')
                if not (pic_url_list and pic_title_list and detail_url_list):
                    continue
                pic_ver = pic_ver_list[0] if pic_ver_list else ""
                pic_title = pic_title_list[0]
                pic_url = pic_url_list[0]
                detail_url = detail_url_list[0]
                if not (is_supported_pic_ver(pic_ver) and ".jpg" in pic_url):
                    continue
                title_confidence = max(
                    max(calculate_title_confidence(each_title, pic_title) for each_title in expected_titles),
                    calculate_title_confidence(current_title, pic_title),
                )
                collect_threshold = 0.45 if text_has_target_number(current_title) else 0.58
                quick_number_match = text_has_target_number(pic_title)
                quick_actor_matches = count_actor_group_matches(pic_title)
                if title_confidence < collect_threshold and not quick_number_match:
                    continue
                if title_confidence >= 0.8 or quick_number_match:
                    query_has_signal = True
                url = re.sub(r"\._[_]?AC_[^\.]+\.", ".", pic_url)
                each_key = build_candidate_key(detail_url, url)
                normalized_detail_url = normalize_detail_url(detail_url)
                media_priority = get_media_priority(pic_ver)
                candidate = candidate_pool.get(each_key)
                if candidate is None:
                    candidate_pool[each_key] = {
                        "url": url,
                        "detail_url": normalized_detail_url,
                        "pic_title": pic_title,
                        "pic_ver": pic_ver,
                        "media_priority": media_priority,
                        "title_confidence": title_confidence,
                        "quick_actor_matches": quick_actor_matches,
                        "detail_actor_matches": 0,
                        "quick_number_match": quick_number_match,
                        "detail_number_match": False,
                        "detail_actor_count": 0,
                        "detail_checked": False,
                        "width": 0,
                    }
                else:
                    if title_confidence > float(candidate["title_confidence"]) or (
                        title_confidence == float(candidate["title_confidence"])
                        and media_priority > int(candidate["media_priority"])
                    ):
                        candidate["url"] = url
                        candidate["pic_title"] = pic_title
                        candidate["pic_ver"] = pic_ver
                        candidate["media_priority"] = media_priority
                    if normalized_detail_url and (
                        not candidate["detail_url"]
                        or "/dp/" in normalized_detail_url
                        and "/dp/" not in str(candidate["detail_url"])
                    ):
                        candidate["detail_url"] = normalized_detail_url
                    candidate["title_confidence"] = max(float(candidate["title_confidence"]), title_confidence)
                    candidate["quick_actor_matches"] = max(int(candidate["quick_actor_matches"]), quick_actor_matches)
                    candidate["quick_number_match"] = bool(candidate["quick_number_match"] or quick_number_match)

            if is_initial_query and not query_has_signal:
                append_series_fallback_keywords(current_title, current_series)
                append_split_keyword_from_replaced_title()
                append_actor_fragment_keywords_from_titles()

            if (
                "s-pagination-item s-pagination-next s-pagination-button s-pagination-separator" in html_search
                or len(pic_card) > 5
            ):
                amazon_orginaltitle_actor = result.amazon_orginaltitle_actor
                if has_valid_actor and amazon_orginaltitle_actor and amazon_orginaltitle_actor not in current_title:
                    append_search_keyword(f"{current_title} {amazon_orginaltitle_actor}")

        query_index += 1

    if candidate_pool:
        preliminary_candidates = sorted(candidate_pool.values(), key=candidate_sort_key, reverse=True)
        for each_candidate in preliminary_candidates[: min(6, len(preliminary_candidates))]:
            await enrich_candidate(each_candidate)
        accepted_candidates = [candidate for candidate in candidate_pool.values() if is_candidate_acceptable(candidate)]
        if accepted_candidates:
            accepted_candidates = sorted(accepted_candidates, key=candidate_sort_key, reverse=True)
            measured_candidates = accepted_candidates[: min(6, len(accepted_candidates))]
            for each_candidate in measured_candidates:
                width, _ = await get_imgsize(str(each_candidate["url"]))
                each_candidate["width"] = width or 0
            hd_candidates = [
                candidate
                for candidate in measured_candidates
                if int(candidate["width"]) >= 1770
                or 1750 > int(candidate["width"]) > 600
                or not int(candidate["width"])
            ]
            if hd_candidates:
                best_candidate = sorted(hd_candidates, key=candidate_sort_key, reverse=True)[0]
                LogBuffer.log().write(
                    f"\n 🟢 Amazon命中：标题置信度({float(best_candidate['title_confidence']):.2f}) "
                    f"番号命中({candidate_number_match(best_candidate)}) "
                    f"演员命中({candidate_actor_match_count(best_candidate)}/{expected_actor_count or 0}) "
                    f"介质({best_candidate['pic_ver'] or 'unknown'}) 标题({best_candidate['pic_title']})"
                )
                return str(best_candidate["url"])
            best_fallback_candidate = measured_candidates[0]
            result.poster = str(best_fallback_candidate["url"])
            result.poster_from = "Amazon"
            LogBuffer.log().write(
                f"\n 🟡 Amazon命中低清图：标题置信度({float(best_fallback_candidate['title_confidence']):.2f}) "
                f"番号命中({candidate_number_match(best_fallback_candidate)}) "
                f"介质({best_fallback_candidate['pic_ver'] or 'unknown'}) 标题({best_fallback_candidate['pic_title']})"
            )
        else:
            best_rejected_candidate = sorted(candidate_pool.values(), key=candidate_sort_key, reverse=True)[0]
            LogBuffer.log().write(
                f"\n 🟡 Amazon搜索未命中：最高候选分({candidate_score(best_rejected_candidate):.2f}) "
                f"标题置信度({float(best_rejected_candidate['title_confidence']):.2f}) "
                f"番号命中({candidate_number_match(best_rejected_candidate)}) "
                f"演员命中({candidate_actor_match_count(best_rejected_candidate)}/{expected_actor_count or 0}) "
                f"标题({best_rejected_candidate['pic_title']})"
            )

    if not hd_pic_url and result.poster_from != "Amazon" and not candidate_pool:
        hd_pic_url = await search_amazon_by_actor_fallback()

    return hd_pic_url


async def trailer_download(
    result: CrawlersResult,
    folder_new: Path,
    folder_old: Path,
    naming_rule: str,
) -> bool | None:
    start_time = time.time()
    download_files = manager.config.download_files
    keep_files = manager.config.keep_files
    trailer_name = manager.config.trailer_simple_name
    result.trailer = await get_dmm_trailer(result.trailer)  # todo 或许找一个更合适的地方进行统一后处理
    trailer_url = result.trailer
    trailer_old_folder_path = folder_old / "trailers"
    trailer_new_folder_path = folder_new / "trailers"

    # 预告片名字不含视频文件名（只让一个视频去下载即可）
    if trailer_name:
        trailer_folder_path = folder_new / "trailers"
        trailer_file_name = "trailer.mp4"
        trailer_file_path = trailer_folder_path / trailer_file_name

        # 预告片文件夹已在已处理列表时，返回（这时只需要下载一个，其他分集不需要下载）
        if trailer_folder_path in Flags.trailer_deal_set:
            return
        Flags.trailer_deal_set.add(trailer_folder_path)

        # 不下载不保留时删除返回
        if DownloadableFile.TRAILER not in download_files and DownloadableFile.TRAILER not in keep_files:
            # 删除目标文件夹即可，其他文件夹和文件已经删除了
            if await aiofiles.os.path.exists(trailer_folder_path):
                await to_thread(shutil.rmtree, trailer_folder_path, ignore_errors=True)
            return

    else:
        # 预告片带文件名（每个视频都有机会下载，如果已有下载好的，则使用已下载的）
        trailer_file_name = naming_rule + "-trailer.mp4"
        trailer_folder_path = folder_new
        trailer_file_path = trailer_folder_path / trailer_file_name

        # 不下载不保留时删除返回
        if DownloadableFile.TRAILER not in download_files and DownloadableFile.TRAILER not in keep_files:
            # 删除目标文件，删除预告片旧文件夹、新文件夹（deal old file时没删除）
            if await aiofiles.os.path.exists(trailer_file_path):
                await delete_file_async(trailer_file_path)
            if await aiofiles.os.path.exists(trailer_old_folder_path):
                await to_thread(shutil.rmtree, trailer_old_folder_path, ignore_errors=True)
            if trailer_new_folder_path != trailer_old_folder_path and await aiofiles.os.path.exists(
                trailer_new_folder_path
            ):
                await to_thread(shutil.rmtree, trailer_new_folder_path, ignore_errors=True)
            return

    # 选择保留文件，当存在文件时，不下载。（done trailer path 未设置时，把当前文件设置为 done trailer path，以便其他分集复制）
    if DownloadableFile.TRAILER in keep_files and await aiofiles.os.path.exists(trailer_file_path):
        if not Flags.file_done_dic.get(result.number, {}).get("trailer"):
            Flags.file_done_dic[result.number].update({"trailer": trailer_file_path})
            # 带文件名时，删除掉新、旧文件夹，用不到了。（其他分集如果没有，可以复制第一个文件的预告片。此时不删，没机会删除了）
            if not trailer_name:
                if await aiofiles.os.path.exists(trailer_old_folder_path):
                    await to_thread(shutil.rmtree, trailer_old_folder_path, ignore_errors=True)
                if trailer_new_folder_path != trailer_old_folder_path and await aiofiles.os.path.exists(
                    trailer_new_folder_path
                ):
                    await to_thread(shutil.rmtree, trailer_new_folder_path, ignore_errors=True)
        LogBuffer.log().write(f"\n 🍀 Trailer done! (old)({get_used_time(start_time)}s) ")
        return True

    # 带文件名时，选择下载不保留，或者选择保留但没有预告片，检查是否有其他分集已下载或本地预告片
    # 选择下载不保留，当没有下载成功时，不会删除不保留的文件
    done_trailer_path = Flags.file_done_dic.get(result.number, {}).get("trailer")
    if not trailer_name and done_trailer_path and await aiofiles.os.path.exists(done_trailer_path):
        if await aiofiles.os.path.exists(trailer_file_path):
            await delete_file_async(trailer_file_path)
        await copy_file_async(done_trailer_path, trailer_file_path)
        LogBuffer.log().write(f"\n 🍀 Trailer done! (copy trailer)({get_used_time(start_time)}s)")
        return

    # 不下载时返回（选择不下载保留，但本地并不存在，此时返回）
    if DownloadableFile.TRAILER not in download_files:
        return

    if ".fc2.com/" in trailer_url and "mid=" in trailer_url and "/up/" in trailer_url:
        tips = "🟡 FC2 预告片链接为带 mid 参数的临时地址，建议仅用于当前任务立即下载，后续直接复用远程链接可能失效。"
        LogBuffer.log().write("\n " + tips)
        signal.add_log(tips)

    # 下载预告片,检测链接有效性
    content_length = await check_url(trailer_url, length=True)
    if content_length:
        # 创建文件夹
        if trailer_name == 1 and not await aiofiles.os.path.exists(trailer_folder_path):
            await aiofiles.os.makedirs(trailer_folder_path)

        # 开始下载
        download_files = manager.config.download_files
        signal.show_traceback_log(f"🍔 {result.number} download trailer... {trailer_url}")
        trailer_file_path_temp = trailer_file_path
        if await aiofiles.os.path.exists(trailer_file_path):
            trailer_file_path_temp = trailer_file_path.with_suffix(".[DOWNLOAD].mp4")
        if await download_file_with_filepath(trailer_url, trailer_file_path_temp, trailer_folder_path):
            file_size = await aiofiles.os.path.getsize(trailer_file_path_temp)
            if file_size >= content_length or DownloadableFile.IGNORE_SIZE in download_files:
                LogBuffer.log().write(
                    f"\n 🍀 Trailer done! ({result.trailer_from} {file_size}/{content_length})({get_used_time(start_time)}s) "
                )
                signal.show_traceback_log(f"✅ {result.number} trailer done!")
                if trailer_file_path_temp != trailer_file_path:
                    await move_file_async(trailer_file_path_temp, trailer_file_path)
                    await delete_file_async(trailer_file_path_temp)
                done_trailer_path = Flags.file_done_dic.get(result.number, {}).get("trailer")
                if not done_trailer_path:
                    Flags.file_done_dic[result.number].update({"trailer": trailer_file_path})
                    if trailer_name == 0:  # 带文件名，已下载成功，删除掉那些不用的文件夹即可
                        if await aiofiles.os.path.exists(trailer_old_folder_path):
                            await to_thread(shutil.rmtree, trailer_old_folder_path, ignore_errors=True)
                        if trailer_new_folder_path != trailer_old_folder_path and await aiofiles.os.path.exists(
                            trailer_new_folder_path
                        ):
                            await to_thread(shutil.rmtree, trailer_new_folder_path, ignore_errors=True)
                return True
            else:
                LogBuffer.log().write(
                    f"\n 🟠 Trailer size is incorrect! delete it! ({result.trailer_from} {file_size}/{content_length}) "
                )

        # 删除下载失败的文件
        await delete_file_async(trailer_file_path_temp)
        LogBuffer.log().write(f"\n 🟠 Trailer download failed! ({trailer_url}) ")

    if await aiofiles.os.path.exists(trailer_file_path):  # 使用旧文件
        done_trailer_path = Flags.file_done_dic.get(result.number, {}).get("trailer")
        if not done_trailer_path:
            Flags.file_done_dic[result.number].update({"trailer": trailer_file_path})
            if trailer_name == 0:  # 带文件名，已下载成功，删除掉那些不用的文件夹即可
                if await aiofiles.os.path.exists(trailer_old_folder_path):
                    await to_thread(shutil.rmtree, trailer_old_folder_path, ignore_errors=True)
                if trailer_new_folder_path != trailer_old_folder_path and await aiofiles.os.path.exists(
                    trailer_new_folder_path
                ):
                    await to_thread(shutil.rmtree, trailer_new_folder_path, ignore_errors=True)
        LogBuffer.log().write("\n 🟠 Trailer download failed! 将继续使用之前的本地文件！")
        LogBuffer.log().write(f"\n 🍀 Trailer done! (old)({get_used_time(start_time)}s)")
        return True


async def _get_big_thumb(result: CrawlersResult, other: OtherInfo):
    """
    获取背景大图：
    1，官网图片
    2，Amazon 图片
    3，Google 搜图
    """
    start_time = time.time()
    if "thumb" not in manager.config.download_hd_pics:
        return
    number = result.number
    letters = result.letters
    number_lower_line = number.lower()
    number_lower_no_line = number_lower_line.replace("-", "")
    thumb_width = 0

    # faleno.jp 番号检查，都是大图，返回即可
    if result.thumb_from in ["faleno", "dahlia"]:
        if result.thumb:
            LogBuffer.log().write(f"\n 🖼 HD Thumb found! ({result.thumb_from})({get_used_time(start_time)}s)")
        other.poster_big = True
        return result

    # prestige 图片有的是大图，需要检测图片分辨率
    elif result.thumb_from in ["prestige", "mgstage"]:
        if result.thumb:
            thumb_width, h = await get_imgsize(result.thumb)

    # 片商官网查询
    elif HDPicSource.OFFICIAL in manager.config.download_hd_pics:
        # faleno.jp 番号检查
        if re.findall(r"F[A-Z]{2}SS", number):
            req_url = f"https://faleno.jp/top/works/{number_lower_no_line}/"
            response, error = await manager.computed.async_client.get_text(req_url)
            if response is not None:
                temp_url = re.findall(
                    r'src="((https://cdn.faleno.net/top/wp-content/uploads/[^_]+_)([^?]+))\?output-quality=', response
                )
                if temp_url:
                    result.thumb = temp_url[0][0]
                    result.poster = temp_url[0][1] + "2125.jpg"
                    result.thumb_from = "faleno"
                    result.poster_from = "faleno"
                    other.poster_big = True
                    trailer_temp = re.findall(r'class="btn09"><a class="pop_sample" href="([^"]+)', response)
                    if trailer_temp:
                        result.trailer = trailer_temp[0]
                        result.trailer_from = "faleno"
                    LogBuffer.log().write(f"\n 🖼 HD Thumb found! (faleno)({get_used_time(start_time)}s)")
                    return result

        # km-produce.com 番号检查
        number_letter = letters.lower()
        kmp_key = ["vrkm", "mdtm", "mkmp", "savr", "bibivr", "scvr", "slvr", "averv", "kbvr", "cbikmv"]
        prestige_key = ["abp", "abw", "aka", "prdvr", "pvrbst", "sdvr", "docvr"]
        if number_letter in kmp_key:
            req_url = f"https://km-produce.com/img/title1/{number_lower_line}.jpg"
            real_url = await check_url(req_url)
            if real_url:
                result.thumb = real_url
                result.thumb_from = "km-produce"
                LogBuffer.log().write(f"\n 🖼 HD Thumb found! (km-produce)({get_used_time(start_time)}s)")
                return result

        # www.prestige-av.com 番号检查
        elif number_letter in prestige_key:
            number_num = re.findall(r"\d+", number)[0]
            if number_letter == "abw" and int(number_num) > 280:
                pass
            else:
                req_url = f"https://www.prestige-av.com/api/media/goods/prestige/{number_letter}/{number_num}/pb_{number_lower_line}.jpg"
                if number_letter == "docvr":
                    req_url = f"https://www.prestige-av.com/api/media/goods/doc/{number_letter}/{number_num}/pb_{number_lower_line}.jpg"
                if (await get_imgsize(req_url))[0] >= 800:
                    result.thumb = req_url
                    result.poster = req_url.replace("/pb_", "/pf_")
                    result.thumb_from = "prestige"
                    result.poster_from = "prestige"
                    other.poster_big = True
                    LogBuffer.log().write(f"\n 🖼 HD Thumb found! (prestige)({get_used_time(start_time)}s)")
                    return result

    # 使用google以图搜图
    pic_url = result.thumb
    if HDPicSource.GOOGLE in manager.config.download_hd_pics and pic_url and result.thumb_from != "theporndb":
        thumb_url, cover_size = await get_big_pic_by_google(pic_url)
        if thumb_url and cover_size[0] > thumb_width:
            other.thumb_size = cover_size
            pic_domain = re.findall(r"://([^/]+)", thumb_url)[0]
            result.thumb_from = f"Google({pic_domain})"
            result.thumb = thumb_url
            LogBuffer.log().write(f"\n 🖼 HD Thumb found! ({result.thumb_from})({get_used_time(start_time)}s)")

    return result


async def _get_big_poster(result: CrawlersResult, other: OtherInfo):
    start_time = time.time()

    # 未勾选下载高清图poster时，返回
    if "poster" not in manager.config.download_hd_pics:
        return

    # 如果有大图时，直接下载
    if other.poster_big and (await get_imgsize(result.poster))[1] > 600:
        result.image_download = True
        LogBuffer.log().write(f"\n 🖼 HD Poster found! ({result.poster_from})({get_used_time(start_time)}s)")
        return

    # 初始化数据
    number = result.number
    poster_url = result.poster
    hd_pic_url = ""
    poster_width = 0

    # 保持原有类型白名单，仅额外排除素人番号
    if HDPicSource.AMAZON in manager.config.download_hd_pics and result.is_suren:
        LogBuffer.log().write("\n 🔎 Amazon搜索：检测为素人番号，已跳过")
    elif HDPicSource.AMAZON in manager.config.download_hd_pics and result.mosaic in [
        "有码",
        "有碼",
        "流出",
        "无码破解",
        "無碼破解",
        "里番",
        "裏番",
        "动漫",
        "動漫",
    ]:
        originaltitle_amazon_raw = result.originaltitle_amazon
        originaltitle_amazon_replaced = originaltitle_amazon_raw
        series_raw = result.series
        series_replaced = series_raw
        for key, value in ManualConfig.SPECIAL_WORD.items():
            originaltitle_amazon_replaced = originaltitle_amazon_replaced.replace(key, value)
            series_replaced = series_replaced.replace(key, value)
        hd_pic_url = await get_big_pic_by_amazon(
            result,
            originaltitle_amazon_replaced,
            result.actor_amazon,
            series_replaced,
            originaltitle_amazon_raw,
            series_raw,
        )
        if hd_pic_url:
            result.poster = hd_pic_url
            result.poster_from = "Amazon"
        if result.poster_from == "Amazon":
            result.image_download = True

    # 通过番号去 官网 查询获取稍微大一些的封面图，以便去 Google 搜索
    if not hd_pic_url and HDPicSource.OFFICIAL in manager.config.download_hd_pics and result.poster_from != "Amazon":
        letters = result.letters.upper()
        official_url = manager.computed.official_websites.get(letters)
        if official_url:
            url_search = official_url + "/search/list?keyword=" + number.replace("-", "")
            html_search, error = await manager.computed.async_client.get_text(url_search)
            if html_search is not None:
                poster_url_list = re.findall(r'img class="c-main-bg lazyload" data-src="([^"]+)"', html_search)
                if poster_url_list:
                    # 使用官网图作为封面去 google 搜索
                    poster_url = poster_url_list[0]
                    result.poster = poster_url
                    result.poster_from = official_url.split(".")[-2].replace("https://", "")
                    # vr作品或者官网图片高度大于500时，下载封面图开
                    if "VR" in number.upper() or (await get_imgsize(poster_url))[1] > 500:
                        result.image_download = True

    # 使用google以图搜图，放在最后是因为有时有错误，比如 kawd-943
    poster_url = result.poster
    if (
        not hd_pic_url
        and poster_url
        and HDPicSource.GOOGLE in manager.config.download_hd_pics
        and result.poster_from != "theporndb"
    ):
        hd_pic_url, poster_size = await get_big_pic_by_google(poster_url, poster=True)
        if hd_pic_url:
            if "prestige" in result.poster or result.poster_from == "Amazon":
                poster_width, _ = await get_imgsize(poster_url)
            if poster_size[0] > poster_width:
                result.poster = hd_pic_url
                other.poster_size = poster_size
                pic_domain = re.findall(r"://([^/]+)", hd_pic_url)[0]
                result.poster_from = f"Google({pic_domain})"

    # 如果找到了高清链接，则替换
    if hd_pic_url:
        result.image_download = True
        LogBuffer.log().write(f"\n 🖼 HD Poster found! ({result.poster_from})({get_used_time(start_time)}s)")

    return result


async def thumb_download(
    result: CrawlersResult,
    other: OtherInfo,
    cd_part: str,
    folder_new_path: Path,
    thumb_final_path: Path,
) -> bool:
    start_time = time.time()
    poster_path = other.poster_path
    thumb_path = other.thumb_path
    fanart_path = other.fanart_path

    # 本地存在 thumb.jpg，且勾选保留旧文件时，不下载
    if thumb_path and DownloadableFile.THUMB in manager.config.keep_files:
        LogBuffer.log().write(f"\n 🍀 Thumb done! (old)({get_used_time(start_time)}s) ")
        return True

    # 如果thumb不下载，看fanart、poster要不要下载，都不下载则返回
    if DownloadableFile.THUMB not in manager.config.download_files:
        if (
            DownloadableFile.POSTER in manager.config.download_files
            and (DownloadableFile.POSTER not in manager.config.keep_files or not poster_path)
            or DownloadableFile.FANART in manager.config.download_files
            and (DownloadableFile.FANART not in manager.config.keep_files or not fanart_path)
        ):
            pass
        else:
            return True

    # 尝试复制其他分集。看分集有没有下载，如果下载完成则可以复制，否则就自行下载
    if cd_part:
        done_thumb_path = Flags.file_done_dic.get(result.number, {}).get("thumb")
        if (
            done_thumb_path
            and await aiofiles.os.path.exists(done_thumb_path)
            and split_path(done_thumb_path)[0] == split_path(thumb_final_path)[0]
        ):
            await copy_file_async(done_thumb_path, thumb_final_path)
            LogBuffer.log().write(f"\n 🍀 Thumb done! (copy cd-thumb)({get_used_time(start_time)}s) ")
            result.thumb_from = "copy cd-thumb"
            other.thumb_path = thumb_final_path
            return True

    # 获取高清背景图
    await _get_big_thumb(result, other)

    # 下载图片
    cover_url = result.thumb
    cover_from = result.thumb_from
    if cover_url:
        cover_list = result.thumb_list
        while (cover_from, cover_url) in cover_list:
            cover_list.remove((cover_from, cover_url))
        cover_list.insert(0, (cover_from, cover_url))

        thumb_final_path_temp = thumb_final_path
        if await aiofiles.os.path.exists(thumb_final_path):
            thumb_final_path_temp = thumb_final_path.with_suffix(".[DOWNLOAD].jpg")
        for each in cover_list:
            if not each[1]:
                continue
            cover_from, cover_url = each
            if not cover_url:
                LogBuffer.log().write(
                    f"\n 🟠 检测到 Thumb 图片失效! 跳过！({cover_from})({get_used_time(start_time)}s) " + each[1]
                )
                continue
            result.thumb_from = cover_from
            if await download_file_with_filepath(cover_url, thumb_final_path_temp, folder_new_path):
                cover_size = await check_pic_async(thumb_final_path_temp)
                if cover_size:
                    if (
                        not cover_from.startswith("Google")
                        or cover_size == other.thumb_size
                        or (
                            cover_size[0] >= 800
                            and abs(cover_size[0] / cover_size[1] - other.thumb_size[0] / other.thumb_size[1]) <= 0.1
                        )
                    ):
                        # 图片下载正常，替换旧的 thumb.jpg
                        if thumb_final_path_temp != thumb_final_path:
                            await move_file_async(thumb_final_path_temp, thumb_final_path)
                            await delete_file_async(thumb_final_path_temp)
                        if cd_part:
                            Flags.file_done_dic[result.number].update({"thumb": thumb_final_path})
                        other.thumb_marked = False  # 表示还没有走加水印流程
                        LogBuffer.log().write(f"\n 🍀 Thumb done! ({result.thumb_from})({get_used_time(start_time)}s) ")
                        other.thumb_path = thumb_final_path
                        return True
                    else:
                        await delete_file_async(thumb_final_path_temp)
                        LogBuffer.log().write(
                            f"\n 🟠 检测到 Thumb 分辨率不对{str(cover_size)}! 已删除 ({cover_from})({get_used_time(start_time)}s)"
                        )
                        continue
                LogBuffer.log().write(f"\n 🟠 Thumb download failed! {cover_from}: {cover_url} ")
    else:
        LogBuffer.log().write("\n 🟠 Thumb url is empty! ")

    # 下载失败，本地有图
    if thumb_path:
        LogBuffer.log().write("\n 🟠 Thumb download failed! 将继续使用之前的图片！")
        LogBuffer.log().write(f"\n 🍀 Thumb done! (old)({get_used_time(start_time)}s) ")
        return True
    else:
        if DownloadableFile.IGNORE_PIC_FAIL in manager.config.download_files:
            LogBuffer.log().write("\n 🟠 Thumb download failed! (你已勾选「图片下载失败时，不视为失败！」) ")
            LogBuffer.log().write(f"\n 🍀 Thumb done! (none)({get_used_time(start_time)}s)")
            return True
        else:
            LogBuffer.log().write(
                "\n 🔴 Thumb download failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」 "
            )
            LogBuffer.error().write(
                "Thumb download failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」"
            )
            return False


async def poster_download(
    result: CrawlersResult,
    other: OtherInfo,
    cd_part: str,
    folder_new_path: Path,
    poster_final_path: Path,
) -> bool:
    start_time = time.time()
    download_files = manager.config.download_files
    keep_files = manager.config.keep_files
    poster_path = other.poster_path
    thumb_path = other.thumb_path
    fanart_path = other.fanart_path
    image_cut = ""

    # 不下载poster、不保留poster时，返回
    if DownloadableFile.POSTER not in download_files and DownloadableFile.POSTER not in keep_files:
        if poster_path:
            await delete_file_async(poster_path)
        return True

    # 本地有poster时，且勾选保留旧文件时，不下载
    if poster_path and DownloadableFile.POSTER in keep_files:
        LogBuffer.log().write(f"\n 🍀 Poster done! (old)({get_used_time(start_time)}s)")
        return True

    # 不下载时返回
    if DownloadableFile.POSTER not in download_files:
        return True

    # 尝试复制其他分集。看分集有没有下载，如果下载完成则可以复制，否则就自行下载
    if cd_part:
        done_poster_path = Flags.file_done_dic.get(result.number, {}).get("poster")
        if (
            done_poster_path
            and await aiofiles.os.path.exists(done_poster_path)
            and split_path(done_poster_path)[0] == split_path(poster_final_path)[0]
        ):
            await copy_file_async(done_poster_path, poster_final_path)
            result.poster_from = "copy cd-poster"
            other.poster_path = poster_final_path
            LogBuffer.log().write(f"\n 🍀 Poster done! (copy cd-poster)({get_used_time(start_time)}s)")
            return True

    # 勾选复制 thumb时：国产，复制thumb；无码，勾选不裁剪时，也复制thumb
    if thumb_path:
        mosaic = result.mosaic
        number = result.number
        copy_flag = False
        if number.startswith("FC2"):
            image_cut = "center"
            if DownloadableFile.IGNORE_FC2 in download_files:
                copy_flag = True
        elif mosaic == "国产" or mosaic == "國產":
            image_cut = "right"
            if DownloadableFile.IGNORE_GUOCHAN in download_files:
                copy_flag = True
        elif mosaic == "无码" or mosaic == "無碼" or mosaic == "無修正":
            image_cut = "center"
            if DownloadableFile.IGNORE_WUMA in download_files:
                copy_flag = True
        elif mosaic == "有码" or mosaic == "有碼":
            if DownloadableFile.IGNORE_YOUMA in download_files:
                copy_flag = True
        if copy_flag:
            await copy_file_async(thumb_path, poster_final_path)
            other.poster_marked = other.thumb_marked
            result.poster_from = "copy thumb"
            other.poster_path = poster_final_path
            LogBuffer.log().write(f"\n 🍀 Poster done! (copy thumb)({get_used_time(start_time)}s)")
            return True

    if (
        result.mosaic in ["有码", "有碼"]
        and DownloadableFile.YOUMA_USE_POSTER in download_files
        and DownloadableFile.IGNORE_YOUMA not in download_files
    ):
        result.image_download = True
        LogBuffer.log().write("\n 🖼 有码封面策略: 已启用「有码优先使用 Poster」，不走 SOD/VR 裁剪判定")

    # 获取高清 poster
    await _get_big_poster(result, other)

    # 下载图片
    poster_url = result.poster
    poster_from = result.poster_from
    poster_final_path_temp = poster_final_path
    if await aiofiles.os.path.exists(poster_final_path):
        poster_final_path_temp = poster_final_path.with_suffix(".[DOWNLOAD].jpg")
    if result.image_download:
        start_time = time.time()
        if await download_file_with_filepath(poster_url, poster_final_path_temp, folder_new_path):
            poster_size = await check_pic_async(poster_final_path_temp)
            if poster_size:
                if (
                    not poster_from.startswith("Google")
                    or poster_size == other.poster_size
                    or "media-amazon.com" in poster_url
                ):
                    if poster_final_path_temp != poster_final_path:
                        await move_file_async(poster_final_path_temp, poster_final_path)
                        await delete_file_async(poster_final_path_temp)
                    if cd_part:
                        Flags.file_done_dic[result.number].update({"poster": poster_final_path})
                    other.poster_marked = False  # 下载的图，还没加水印
                    other.poster_path = poster_final_path
                    LogBuffer.log().write(f"\n 🍀 Poster done! ({poster_from})({get_used_time(start_time)}s)")
                    return True
                else:
                    await delete_file_async(poster_final_path_temp)
                    LogBuffer.log().write(f"\n 🟠 检测到 Poster 分辨率不对{str(poster_size)}! 已删除 ({poster_from})")

    # 判断之前有没有 poster 和 thumb
    if not poster_path and not thumb_path:
        other.poster_path = None
        if DownloadableFile.IGNORE_PIC_FAIL in download_files:
            LogBuffer.log().write("\n 🟠 Poster download failed! (你已勾选「图片下载失败时，不视为失败！」) ")
            LogBuffer.log().write(f"\n 🍀 Poster done! (none)({get_used_time(start_time)}s)")
            return True
        else:
            LogBuffer.log().write(
                "\n 🔴 Poster download failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」 "
            )
            LogBuffer.error().write(
                "Poster download failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」"
            )
            return False

    # 使用thumb裁剪
    poster_final_path_temp = poster_final_path.with_suffix(".[CUT].jpg")
    if fanart_path:
        thumb_path = fanart_path
    if thumb_path and await asyncio.to_thread(
        cut_thumb_to_poster, result, thumb_path, poster_final_path_temp, image_cut
    ):
        # 裁剪成功，替换旧图
        await move_file_async(poster_final_path_temp, poster_final_path)
        if cd_part:
            Flags.file_done_dic[result.number].update({"poster": poster_final_path})
        other.poster_path = poster_final_path
        other.poster_marked = False
        return True

    # 裁剪失败，本地有图
    if poster_path:
        LogBuffer.log().write("\n 🟠 Poster cut failed! 将继续使用之前的图片！")
        LogBuffer.log().write(f"\n 🍀 Poster done! (old)({get_used_time(start_time)}s) ")
        return True
    else:
        if DownloadableFile.IGNORE_PIC_FAIL in download_files:
            LogBuffer.log().write("\n 🟠 Poster cut failed! (你已勾选「图片下载失败时，不视为失败！」) ")
            LogBuffer.log().write(f"\n 🍀 Poster done! (none)({get_used_time(start_time)}s)")
            return True
        else:
            LogBuffer.log().write(
                "\n 🔴 Poster cut failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」 "
            )
            LogBuffer.error().write("Poster failed！你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」")
            return False


async def fanart_download(
    number: str,
    other: OtherInfo,
    cd_part: str,
    fanart_final_path: Path,
) -> bool:
    """
    复制thumb为fanart
    """
    start_time = time.time()
    thumb_path = other.thumb_path
    fanart_path = other.fanart_path
    download_files = manager.config.download_files
    keep_files = manager.config.keep_files

    # 不保留不下载时删除返回
    if DownloadableFile.FANART not in keep_files and DownloadableFile.FANART not in download_files:
        if fanart_path and await aiofiles.os.path.exists(fanart_path):
            await delete_file_async(fanart_path)
        return True

    # 保留，并且本地存在 fanart.jpg，不下载返回
    if DownloadableFile.FANART in keep_files and fanart_path:
        LogBuffer.log().write(f"\n 🍀 Fanart done! (old)({get_used_time(start_time)}s)")
        return True

    # 不下载时，返回
    if DownloadableFile.FANART not in download_files:
        return True

    # 尝试复制其他分集。看分集有没有下载，如果下载完成则可以复制，否则就自行下载
    if cd_part:
        done_fanart_path = Flags.file_done_dic.get(number, {}).get("fanart")
        if (
            done_fanart_path
            and await aiofiles.os.path.exists(done_fanart_path)
            and done_fanart_path.parent == fanart_final_path.parent
        ):
            if fanart_path:
                await delete_file_async(fanart_path)
            await copy_file_async(done_fanart_path, fanart_final_path)
            other.fanart_path = fanart_final_path
            LogBuffer.log().write(f"\n 🍀 Fanart done! (copy cd-fanart)({get_used_time(start_time)}s)")
            return True

    # 复制thumb
    if thumb_path:
        if fanart_path:
            await delete_file_async(fanart_path)
        await copy_file_async(thumb_path, fanart_final_path)
        other.fanart_path = fanart_final_path
        other.fanart_marked = other.thumb_marked
        LogBuffer.log().write(f"\n 🍀 Fanart done! (copy thumb)({get_used_time(start_time)}s)")
        if cd_part:
            Flags.file_done_dic[number].update({"fanart": fanart_final_path})
        return True
    else:
        # 本地有 fanart 时，不下载
        if fanart_path:
            LogBuffer.log().write("\n 🟠 Fanart copy failed! 未找到 thumb 图片，将继续使用之前的图片！")
            LogBuffer.log().write(f"\n 🍀 Fanart done! (old)({get_used_time(start_time)}s)")
            return True

        else:
            if DownloadableFile.IGNORE_PIC_FAIL in download_files:
                LogBuffer.log().write("\n 🟠 Fanart failed! (你已勾选「图片下载失败时，不视为失败！」) ")
                LogBuffer.log().write(f"\n 🍀 Fanart done! (none)({get_used_time(start_time)}s)")
                return True
            else:
                LogBuffer.log().write(
                    "\n 🔴 Fanart failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」 "
                )
                LogBuffer.error().write(
                    "Fanart 下载失败！你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」"
                )
                return False


async def extrafanart_download(extrafanart: list[str], extrafanart_from: str, folder_new_path: Path) -> bool | None:
    start_time = time.time()
    download_files = manager.config.download_files
    keep_files = manager.config.keep_files
    extrafanart_list = extrafanart
    extrafanart_folder_path = folder_new_path / "extrafanart"

    # 不下载不保留时删除返回
    if DownloadableFile.EXTRAFANART not in download_files and DownloadableFile.EXTRAFANART not in keep_files:
        if await aiofiles.os.path.exists(extrafanart_folder_path):
            await to_thread(shutil.rmtree, extrafanart_folder_path, ignore_errors=True)
        return

    # 本地存在 extrafanart_folder，且勾选保留旧文件时，不下载
    if DownloadableFile.EXTRAFANART in keep_files and await aiofiles.os.path.exists(extrafanart_folder_path):
        LogBuffer.log().write(f"\n 🍀 Extrafanart done! (old)({get_used_time(start_time)}s) ")
        return True

    # 如果 extrafanart 不下载
    if DownloadableFile.EXTRAFANART not in download_files:
        return True

    # 检测链接有效性
    if extrafanart_list and await check_url(extrafanart_list[0]):
        extrafanart_folder_path_temp = extrafanart_folder_path
        if await aiofiles.os.path.exists(extrafanart_folder_path_temp):
            extrafanart_folder_path_temp = extrafanart_folder_path.with_name(
                extrafanart_folder_path.name + "[DOWNLOAD]"
            )
            if not await aiofiles.os.path.exists(extrafanart_folder_path_temp):
                await aiofiles.os.makedirs(extrafanart_folder_path_temp)
        else:
            await aiofiles.os.makedirs(extrafanart_folder_path_temp)

        extrafanart_count = 0
        extrafanart_count_succ = 0
        task_list = []
        for extrafanart_url in extrafanart_list:
            extrafanart_count += 1
            extrafanart_name = "fanart" + str(extrafanart_count) + ".jpg"
            extrafanart_file_path = extrafanart_folder_path_temp / extrafanart_name
            task_list.append((extrafanart_url, extrafanart_file_path, extrafanart_folder_path_temp, extrafanart_name))

        # 使用异步并发执行下载任务
        tasks = [download_extrafanart_task(task) for task in task_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if res is True:
                extrafanart_count_succ += 1
        if extrafanart_count_succ == extrafanart_count:
            if extrafanart_folder_path_temp != extrafanart_folder_path:
                await to_thread(shutil.rmtree, extrafanart_folder_path)
                await aiofiles.os.rename(extrafanart_folder_path_temp, extrafanart_folder_path)
            LogBuffer.log().write(
                f"\n 🍀 ExtraFanart done! ({extrafanart_from} {extrafanart_count_succ}/{extrafanart_count})({get_used_time(start_time)}s)"
            )
            return True
        else:
            LogBuffer.log().write(
                f"\n 🟠 ExtraFanart download failed! ({extrafanart_from} {extrafanart_count_succ}/{extrafanart_count})({get_used_time(start_time)}s)"
            )
            if extrafanart_folder_path_temp != extrafanart_folder_path:
                await to_thread(shutil.rmtree, extrafanart_folder_path_temp)
            else:
                LogBuffer.log().write(f"\n 🍀 ExtraFanart done! (incomplete)({get_used_time(start_time)}s)")
                return False
        LogBuffer.log().write("\n 🟠 ExtraFanart download failed! 将继续使用之前的本地文件！")
    if await aiofiles.os.path.exists(extrafanart_folder_path):  # 使用旧文件
        LogBuffer.log().write(f"\n 🍀 ExtraFanart done! (old)({get_used_time(start_time)}s)")
        return True
