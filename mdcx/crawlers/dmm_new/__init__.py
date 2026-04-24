import asyncio
import html as html_utils
import json
import random
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import override
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from parsel import Selector

from mdcx.base.web import check_url, get_url_content_length, normalize_media_url
from mdcx.config.enums import DownloadableFile
from mdcx.config.manager import manager
from mdcx.config.models import Website
from mdcx.models.types import CrawlerInput
from mdcx.signals import signal
from mdcx.utils import collapse_inline_script_splits
from mdcx.utils.dataclass import update_valid
from mdcx.utils.gather_group import GatherGroup
from mdcx.web_async import AsyncWebClient

from ..base import (
    Context,
    CralwerException,
    CrawlerData,
    DetailPageParser,
    GenericBaseCrawler,
    is_valid,
)
from .parsers import (
    Category,
    DigitalParser,
    MediaVariant,
    MonoParser,
    RentalParser,
    parse_category,
    parse_media_variant,
)
from .tv import (
    DmmDigitalPackageImage,
    DmmDigitalResponse,
    DmmTvResponse,
    FanzaResp,
    dmm_digital_payload,
    dmm_tv_com_payload,
    fanza_tv_payload,
)


@dataclass
class DMMContext(Context):
    number_00: str | None = None
    number_no_00: str | None = None
    detail_media_variants: dict[str, MediaVariant] = field(default_factory=dict)
    final_images_resolved: bool = False


class DmmCrawler(GenericBaseCrawler[DMMContext]):
    supports_browser = False
    mono = MonoParser()
    digital = DigitalParser()
    rental = RentalParser()
    _merge_priority = (
        Category.MONTHLY,
        Category.PRIME,
        Category.RENTAL,
        Category.MONO,
        Category.FANZA_TV,
        Category.DMM_TV,
        Category.DIGITAL,
    )
    _streaming_only_categories = frozenset((Category.FANZA_TV, Category.DMM_TV))

    @staticmethod
    def _log(message: str) -> None:
        signal.add_log(f"🎬 [DMM] {message}")

    @staticmethod
    def _clean_html_text(content: str) -> str:
        cleaned = html_utils.unescape(str(content or "").strip())
        if not cleaned:
            return ""

        cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
        cleaned = re.sub(r"(?i)</p\s*>", "\n", cleaned)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _dedupe_urls(urls: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for url in urls:
            normalized = str(url or "").strip()
            if not normalized:
                continue
            normalized = DmmCrawler._with_https(normalized)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _normalize_image_urls(urls: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        normalized_urls: list[str] = []
        for url in urls:
            normalized = DmmCrawler._with_https(normalize_media_url(str(url or "").strip()))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_urls.append(normalized)
        return normalized_urls

    @staticmethod
    def _prefer_dmm_image_url(url: str) -> str:
        normalized = DmmCrawler._with_https(normalize_media_url(str(url or "").strip()))
        if not normalized:
            return ""
        if "pics.dmm.co.jp" in normalized:
            return normalized.replace("pics.dmm.co.jp", "awsimgsrc.dmm.co.jp/pics_dig").replace("/adult/", "/")
        return normalized

    @staticmethod
    def _is_dmm_image_url(url: str) -> bool:
        normalized = str(url or "").strip()
        if normalized.startswith("//"):
            normalized = "https:" + normalized
        host = urlsplit(normalized).netloc.lower()
        return host.endswith("dmm.co.jp") or host.endswith("dmm.com")

    def _build_aws_thumb_candidates(self, ctx: DMMContext, thumb_url: str) -> list[str]:
        normalized = self._with_https(str(thumb_url or "").strip())
        if "pics.dmm.co.jp" not in normalized:
            return []

        candidates = [
            normalized.replace("pics.dmm.co.jp", "awsimgsrc.dmm.co.jp/pics_dig").replace("/adult/", "/"),
        ]
        if ctx.number_00:
            candidates.append(
                f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{ctx.number_00}/{ctx.number_00}pl.jpg"
            )
        if ctx.number_no_00:
            candidates.append(
                f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{ctx.number_no_00}/{ctx.number_no_00}pl.jpg"
            )
        return self._dedupe_urls(candidates)

    def _build_poster_candidates(self, thumb_url: str, poster_url: str) -> list[str]:
        candidates: list[str] = []
        if poster_url:
            candidates.append(poster_url)
        if thumb_url:
            candidates.append(thumb_url.replace("pl.jpg", "ps.jpg"))
        return self._dedupe_urls(candidates)

    async def _validate_image_url(self, ctx: DMMContext, image_url: str, *, label: str) -> str:
        normalized = self._with_https(normalize_media_url(str(image_url or "").strip()))
        if not normalized:
            return ""
        if not self._is_dmm_image_url(normalized):
            return normalized

        validated = await check_url(normalized)
        if not validated:
            ctx.debug(f"{label} 无效，已丢弃: {normalized}")
            return ""

        validated_url = self._with_https(normalize_media_url(str(validated).strip()))
        if validated_url != normalized:
            ctx.debug(f"{label} 重定向: {normalized} -> {validated_url}")
        return validated_url

    async def _validate_preferred_image_url(self, ctx: DMMContext, image_url: str, *, label: str) -> str:
        normalized = self._with_https(normalize_media_url(str(image_url or "").strip()))
        if not normalized:
            return ""

        preferred = self._prefer_dmm_image_url(normalized)
        if not self._is_dmm_image_url(preferred):
            return preferred

        validated = await check_url(preferred)
        if not validated:
            ctx.debug(f"{label} 抽检失败，回退全量校验: {preferred}")
            return ""

        validated_url = self._with_https(normalize_media_url(str(validated).strip()))
        if preferred != normalized and validated_url == preferred:
            ctx.debug(f"{label} 高清图命中: {normalized} -> {validated_url}")
        elif validated_url != preferred:
            ctx.debug(f"{label} 重定向: {preferred} -> {validated_url}")
        return validated_url

    async def _pick_first_valid_image(self, ctx: DMMContext, image_urls: Sequence[str], *, label: str) -> str:
        candidates = self._dedupe_urls(image_urls)
        for index, image_url in enumerate(candidates):
            validated = await self._validate_image_url(ctx, image_url, label=label)
            if validated:
                if index > 0:
                    self._log(f"图片[{label}回退命中]: {validated}")
                return validated
        if candidates:
            self._log(f"图片[{label}]候选全部失效: {len(candidates)}")
        return ""

    async def _sanitize_image_list(self, ctx: DMMContext, image_urls: Sequence[str], *, label: str) -> list[str]:
        candidates = self._normalize_image_urls(image_urls)
        if not candidates:
            return []

        sample_indexes = list(range(len(candidates)))
        if len(candidates) > 3:
            sample_indexes = sorted(random.sample(range(len(candidates)), 3))

        sampled_candidates = [(index, candidates[index]) for index in sample_indexes]
        sampled_results = await asyncio.gather(
            *[
                self._validate_preferred_image_url(ctx, image_url, label=f"{label}[{index + 1}]")
                for index, image_url in sampled_candidates
            ]
        )
        validated_by_index = {
            index: validated for (index, _), validated in zip(sampled_candidates, sampled_results, strict=True)
        }

        if all(sampled_results):
            self._log(f"图片[{label}抽检通过]: 随机抽检 {len(sampled_candidates)}/{len(candidates)}，整批升级 AWS")
            valid_urls: list[str] = []
            for index, image_url in enumerate(candidates):
                resolved_url = validated_by_index.get(index) or self._prefer_dmm_image_url(image_url) or image_url
                if resolved_url not in valid_urls:
                    valid_urls.append(resolved_url)
            return valid_urls

        passed_count = sum(1 for image_url in sampled_results if image_url)
        self._log(f"图片[{label}抽检失败]: 随机抽检 {passed_count}/{len(sampled_candidates)} 通过，回退全量校验")

        remaining_candidates = [
            (index, image_url) for index, image_url in enumerate(candidates) if not validated_by_index.get(index)
        ]
        if remaining_candidates:
            # 复用抽检结果，避免回退后对同一批图片重复发起校验请求。
            remaining_results = await asyncio.gather(
                *[
                    self._validate_image_url(ctx, image_url, label=f"{label}[{index + 1}]")
                    for index, image_url in remaining_candidates
                ]
            )
            for (index, _), validated in zip(remaining_candidates, remaining_results, strict=True):
                validated_by_index[index] = validated

        valid_urls: list[str] = []
        for index in range(len(candidates)):
            image_url = validated_by_index.get(index, "")
            if image_url and image_url not in valid_urls:
                valid_urls.append(image_url)
        if len(valid_urls) != len(candidates):
            self._log(f"图片[{label}过滤]: 保留 {len(valid_urls)}/{len(candidates)}")
        return valid_urls

    async def _sanitize_candidate_images(
        self,
        ctx: DMMContext,
        category: Category,
        detail_url: str,
        item: CrawlerData,
    ) -> CrawlerData:
        label = f"{category.value}:{detail_url}"
        original_thumb = str(item.thumb or "") if is_valid(item.thumb) else ""
        item.thumb = await self._pick_first_valid_image(
            ctx,
            [*self._build_aws_thumb_candidates(ctx, original_thumb), original_thumb],
            label=f"{label} thumb",
        )
        return item

    async def _finalize_result_images(
        self,
        ctx: DMMContext,
        item,
        *,
        label: str,
        validate_thumb: bool,
    ):
        original_thumb = (
            self._with_https(str(getattr(item, "thumb", "") or "").strip())
            if is_valid(getattr(item, "thumb", None))
            else ""
        )
        if validate_thumb:
            item.thumb = await self._pick_first_valid_image(
                ctx,
                [*self._build_aws_thumb_candidates(ctx, original_thumb), original_thumb],
                label=f"{label} thumb",
            )
        else:
            item.thumb = self._with_https(normalize_media_url(original_thumb))

        original_poster = (
            self._with_https(str(getattr(item, "poster", "") or "").strip())
            if is_valid(getattr(item, "poster", None))
            else ""
        )
        item.poster = await self._pick_first_valid_image(
            ctx,
            self._build_poster_candidates(
                str(getattr(item, "thumb", "") or "") if is_valid(getattr(item, "thumb", None)) else "", original_poster
            ),
            label=f"{label} poster",
        )

        if is_valid(getattr(item, "extrafanart", None)):
            extrafanart = list(getattr(item, "extrafanart", []) or [])
            if DownloadableFile.EXTRAFANART in manager.config.download_files:
                item.extrafanart = await self._sanitize_image_list(ctx, extrafanart, label=f"{label} extrafanart")
            else:
                item.extrafanart = self._dedupe_urls(extrafanart)
        return item

    @classmethod
    def _canonicalize_detail_url(cls, url: str) -> str:
        normalized = cls._normalize_search_result_url(url)
        if not normalized:
            return ""

        split = urlsplit(normalized)
        query_pairs = [
            (k, v) for k, v in parse_qsl(split.query, keep_blank_values=True) if k.lower() not in ("i3_ref", "i3_ord")
        ]
        query = urlencode(query_pairs, doseq=True)
        return urlunsplit((split.scheme.lower(), split.netloc.lower(), split.path, query, ""))

    @classmethod
    def _image_category_rank(cls, category: Category) -> int:
        priority = tuple(reversed(cls._merge_priority))
        if category in priority:
            return priority.index(category)
        return len(priority)

    @staticmethod
    def _is_bluray_variant(variant: MediaVariant) -> bool:
        return variant == MediaVariant.BLURAY

    @classmethod
    def _pick_preferred_image_candidate(
        cls,
        ctx: DMMContext,
        candidate_results: list[tuple[Category, str, CrawlerData | Exception]],
        detail_order: dict[str, int],
    ) -> tuple[Category, MediaVariant, CrawlerData] | None:
        ranked_candidates: list[tuple[tuple[int, int, int, str], Category, MediaVariant, CrawlerData]] = []

        for category, detail_url, item in candidate_results:
            if isinstance(item, Exception) or not is_valid(item.thumb):
                continue

            canonical_url = cls._canonicalize_detail_url(str(item.external_id or detail_url))
            variant = ctx.detail_media_variants.get(canonical_url, MediaVariant.UNKNOWN)
            sort_key = (
                1 if cls._is_bluray_variant(variant) else 0,
                cls._image_category_rank(category),
                detail_order.get(canonical_url, len(detail_order)),
                canonical_url,
            )
            ranked_candidates.append((sort_key, category, variant, item))

        if not ranked_candidates:
            return None

        ranked_candidates.sort(key=lambda item: item[0])
        _, category, variant, data = ranked_candidates[0]
        return category, variant, data

    def __init__(self, client: AsyncWebClient, base_url: str = "", browser=None):
        super().__init__(client, base_url, browser)

    @staticmethod
    def _extract_digital_content_id(detail_url: str) -> str:
        if not (matched := re.search(r"[?&]id=([^&/#]+)", str(detail_url or ""), flags=re.IGNORECASE)):
            return ""
        return matched.group(1).strip().lower()

    @staticmethod
    def _build_digital_api_headers(detail_url: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Origin": "https://video.dmm.co.jp",
            "Referer": detail_url,
        }

    async def _http_request_with_retry(self, method: str, url: str, **kwargs):
        """
        带重试机制的 HTTP 请求

        Args:
            method: HTTP 方法 ('GET', 'POST', 'HEAD')
            url: 请求 URL
            **kwargs: 其他请求参数

        Returns:
            (response, error) 元组
        """
        max_retries = manager.config.retry  # 从配置获取重试次数

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if method.upper() == "POST":
                    if "json_data" in kwargs:
                        response, error = await self.async_client.post_json(url, **kwargs)
                    else:
                        response, error = await self.async_client.post_text(url, **kwargs)
                elif method.upper() == "GET":
                    response, error = await self.async_client.get_text(url, **kwargs)
                elif method.upper() == "HEAD":
                    response, error = await self.async_client.request("HEAD", url, **kwargs)
                else:
                    response, error = await self.async_client.request(method, url, **kwargs)

                # 如果请求成功，直接返回
                if response is not None:
                    return response, error

                # 记录失败信息
                last_error = error

            except Exception as e:
                last_error = str(e)

            # 重试前等待（指数退避）
            if attempt < max_retries:
                wait_time = min(2**attempt, 10)  # 最多等待10秒
                await asyncio.sleep(wait_time)

        # 所有重试都失败了
        return None, f"请求失败，已重试 {max_retries} 次: {last_error}"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.DMM

    @classmethod
    @override
    def base_url_(cls) -> str:
        # DMM 不支持自定义 URL
        return ""

    @override
    def new_context(self, input: CrawlerInput) -> DMMContext:
        return DMMContext(input=input)

    @override
    def _get_cookies(self, ctx) -> dict[str, str] | None:
        return {"age_check_done": "1"}

    @override
    async def _generate_search_url(self, ctx) -> list[str] | None:
        number = ctx.input.number.lower()

        if x := re.findall(r"[A-Za-z]+-?(\d+)", number):
            digits = x[0]
            if len(digits) >= 5 and digits.startswith("00"):
                number = number.replace(digits, digits[2:])
            elif len(digits) == 4:
                number = number.replace("-", "0")  # https://github.com/sqzw-x/mdcx/issues/393

        # 搜索结果多，但snis-027没结果
        number_00 = number.replace("-", "00")
        # 搜索结果少
        number_no_00 = number.replace("-", "")
        ctx.number_00 = number_00
        ctx.number_no_00 = number_no_00

        return [
            f"https://www.dmm.co.jp/search/=/searchstr={number_00}/sort=ranking/",
            f"https://www.dmm.co.jp/search/=/searchstr={number_no_00}/sort=ranking/",
            f"https://www.dmm.com/search/=/searchstr={number_no_00}/sort=ranking/",  # 写真
        ]

    @staticmethod
    def _normalize_search_result_url(raw_url: str, *, search_url: str = "") -> str:
        normalized = str(raw_url or "").strip()
        if not normalized:
            return ""

        normalized = collapse_inline_script_splits(normalized)
        normalized = html_utils.unescape(normalized)
        try:
            normalized = normalized.encode("utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            pass
        normalized = html_utils.unescape(normalized).replace("\\/", "/").strip()
        if search_url:
            normalized = urljoin(search_url, normalized)
        return normalized

    @staticmethod
    def _is_search_detail_url(url: str) -> bool:
        normalized = str(url or "").strip()
        if not normalized:
            return False
        if re.search(r"^https?://tv\.dmm\.co\.jp/list/\?[^#]*\bcontent=", normalized, flags=re.IGNORECASE):
            return True
        if re.search(r"^https?://tv\.dmm\.com/[^#]*[?&]seasonId=", normalized, flags=re.IGNORECASE):
            return True
        if re.search(r"^https?://video\.dmm\.co\.jp/av/content/\?[^#]*\bid=", normalized, flags=re.IGNORECASE):
            return True
        if re.search(
            r"^https?://(?:www\.)?dmm\.(?:co\.jp|com)/[^\"'<>]+/-/detail/=/cid=[^/?#]+/",
            normalized,
            flags=re.IGNORECASE,
        ):
            return True
        return False

    @classmethod
    def _extract_search_detail_urls(cls, html: Selector, search_url: str) -> list[str]:
        detail_urls: list[str] = []
        seen: set[str] = set()

        def _append_candidate(raw_url: str):
            normalized = cls._normalize_search_result_url(raw_url, search_url=search_url)
            if not normalized or not cls._is_search_detail_url(normalized):
                return
            if normalized in seen:
                return
            seen.add(normalized)
            detail_urls.append(normalized)

        for href in html.xpath("//a[@href]/@href").getall():
            _append_candidate(href)

        raw_html = collapse_inline_script_splits(html.get() or "")
        for pattern in (
            r'(?:detailUrl|detail_url)\\":\\"(.*?)\\"',
            r'"(?:detailUrl|detail_url)":"(.*?)"',
        ):
            for raw_url in re.findall(pattern, raw_html):
                _append_candidate(raw_url)

        return detail_urls

    @override
    async def _parse_search_page(self, ctx, html, search_url) -> list[str] | None:
        if "404 Not Found" in html.css("span.d-txten::text").get(""):
            raise CralwerException("404! 页面地址错误！")

        url_list = self._extract_search_detail_urls(html, search_url)
        if not url_list:
            ctx.debug(f"没有找到搜索结果: {ctx.input.number} {search_url=}")
            return None

        number_parts: re.Match[str] | None = re.search(r"(\d*[a-z]+)?-?(\d+)", ctx.input.number.lower())
        if not number_parts:
            ctx.debug(f"无法从番号 {ctx.input.number} 提取前缀和数字")
            return None
        prefix = number_parts.group(1) or ""
        digits = number_parts.group(2)
        n1 = f"{prefix}{digits:0>5}"
        n2 = f"{prefix}{digits}"

        res = []
        for u in url_list:
            # https://tv.dmm.co.jp/list/?content=mide00726&i3_ref=search&i3_ord=1
            # https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=mide00726/?i3_ref=search&i3_ord=2
            # https://www.dmm.com/mono/dvd/-/detail/=/cid=n_709mmrak089sp/?i3_ref=search&i3_ord=1
            if re.search(rf"[^a-z]{n1}[^0-9]", u, flags=re.IGNORECASE) or re.search(
                rf"[^a-z]{n2}[^0-9]", u, flags=re.IGNORECASE
            ):
                res.append(u)

        return res

    @classmethod
    def _get_parser(cls, category: Category):
        match category:
            case Category.PRIME | Category.MONTHLY | Category.MONO:
                return cls.mono
            case Category.DIGITAL:
                return cls.digital
            case Category.RENTAL:
                return cls.rental

    @classmethod
    def _sanitize_detail_result(cls, category: Category, result: CrawlerData) -> CrawlerData:
        # FANZA TV / DMM TV 提供的是上架时间，不应覆盖作品发行日期。
        if category in cls._streaming_only_categories:
            result.release = ""
            result.year = ""
        return result

    @classmethod
    def _merge_detail_results(
        cls, ctx: Context, categorized_results: list[tuple[Category, CrawlerData | Exception]]
    ) -> tuple[CrawlerData | None, str]:
        merged_by_category: dict[Category, CrawlerData] = {}
        streaming_date_fallbacks: dict[Category, tuple[str, str]] = {}
        best_trailer = ""

        for category, item in categorized_results:
            if isinstance(item, Exception):  # 预计只会返回空值, 不会抛出异常
                ctx.debug(f"预料之外的异常: {item}")
                continue

            if category in cls._streaming_only_categories:
                release_fallback, year_fallback = streaming_date_fallbacks.get(category, ("", ""))
                if not release_fallback and is_valid(item.release):
                    release_fallback = str(item.release)
                if not year_fallback and is_valid(item.year):
                    year_fallback = str(item.year)
                streaming_date_fallbacks[category] = (release_fallback, year_fallback)

            result = cls._sanitize_detail_result(category, item)

            if is_valid(result.trailer):
                candidate_trailer = str(result.trailer)
                if cls._is_hls_playlist_trailer(candidate_trailer):
                    ctx.debug(f"跳过 m3u8 预告片候选: url={candidate_trailer}")
                else:
                    candidate_rank = cls._trailer_quality_rank(candidate_trailer)
                    source_hint = f" external_id={result.external_id}" if is_valid(result.external_id) else ""
                    ctx.debug(f"trailer 候选: rank={candidate_rank}{source_hint} url={candidate_trailer}")

                    previous_best = best_trailer
                    best_trailer = cls._pick_higher_quality_trailer(best_trailer, candidate_trailer)
                    if best_trailer != previous_best:
                        if previous_best:
                            prev_rank = cls._trailer_quality_rank(previous_best)
                            ctx.debug(
                                f"trailer 最优更新: rank {prev_rank} -> {candidate_rank}; "
                                f"old={previous_best}; new={best_trailer}"
                            )
                        else:
                            ctx.debug(f"trailer 初始最优: rank={candidate_rank}; url={best_trailer}")

            category_res = merged_by_category.get(category)
            if category_res is None:
                merged_by_category[category] = result
            else:
                merged_by_category[category] = update_valid(category_res, result, is_valid)

        res = None
        for category in cls._merge_priority:
            category_res = merged_by_category.get(category)
            if category_res is None:
                continue
            if res is None:
                res = category_res
            else:
                res = update_valid(res, category_res, is_valid)

        if res is not None:
            for category in reversed(cls._merge_priority):
                if category not in cls._streaming_only_categories:
                    continue
                release_fallback, year_fallback = streaming_date_fallbacks.get(category, ("", ""))
                if not is_valid(res.release) and release_fallback:
                    res.release = release_fallback
                if not is_valid(res.year) and year_fallback:
                    res.year = year_fallback
                if is_valid(res.release) and is_valid(res.year):
                    break

        return res, best_trailer

    @override
    async def _detail(self, ctx: DMMContext, detail_urls: list[str]) -> CrawlerData | None:
        d = defaultdict(list)
        detail_order: dict[str, int] = {}
        for url in detail_urls:
            category = parse_category(url)
            d[category].append(url)
            canonical_url = self._canonicalize_detail_url(url)
            if canonical_url and canonical_url not in detail_order:
                detail_order[canonical_url] = len(detail_order)

        # 设置 GatherGroup 的整体超时时间，给单个请求更多时间
        # 因为我们已经在单个请求中实现了重试机制
        total_timeout = manager.config.timeout * (manager.config.retry + 1) * 2  # 给足够的时间
        task_categories: list[Category] = []
        task_urls: list[str] = []

        async with GatherGroup[CrawlerData](timeout=total_timeout) as group:
            for url in d[Category.FANZA_TV]:
                task_categories.append(Category.FANZA_TV)
                task_urls.append(url)
                group.add(self.fetch_fanza_tv(ctx, url))
            for url in d[Category.DMM_TV]:
                task_categories.append(Category.DMM_TV)
                task_urls.append(url)
                group.add(self.fetch_dmm_tv(ctx, url))

            for category in (
                Category.DIGITAL,
                Category.MONO,
                Category.RENTAL,
                Category.PRIME,
                Category.MONTHLY,
            ):  # 优先级
                parser = self._get_parser(category)
                if parser is None:
                    continue
                for u in sorted(d[category]):
                    task_categories.append(category)
                    task_urls.append(u)
                    if category == Category.DIGITAL:
                        group.add(self.fetch_digital(ctx, u))
                    else:
                        group.add(self.fetch_and_parse(ctx, u, parser))

        if not task_categories:
            return None

        candidate_results = list(zip(task_categories, task_urls, group.results, strict=True))
        sanitized_results = await asyncio.gather(
            *[
                self._sanitize_candidate_images(ctx, category, detail_url, item)
                if not isinstance(item, Exception)
                else asyncio.sleep(0, result=item)
                for category, detail_url, item in candidate_results
            ]
        )
        candidate_results = [
            (category, detail_url, item)
            for (category, detail_url, _), item in zip(candidate_results, sanitized_results, strict=True)
        ]
        res, best_trailer = self._merge_detail_results(
            ctx,
            [(category, item) for category, _, item in candidate_results],
        )

        if res is not None and best_trailer:
            if not is_valid(res.trailer):
                ctx.debug(f"trailer 最终采用最优候选(补全空值): {best_trailer}")
            elif str(res.trailer) != best_trailer:
                ctx.debug(f"trailer 最终改写为更高质量: old={res.trailer}; new={best_trailer}")
            res.trailer = best_trailer
        elif res is not None and is_valid(res.trailer) and self._is_hls_playlist_trailer(str(res.trailer)):
            ctx.debug(f"trailer 最终清空 m3u8 链接: old={res.trailer}")
            res.trailer = ""

        preferred_image = self._pick_preferred_image_candidate(ctx, candidate_results, detail_order)
        if res is not None and preferred_image is not None:
            image_category, image_variant, image_source = preferred_image
            preferred_thumb = str(image_source.thumb)
            if not is_valid(res.thumb) or str(res.thumb) != preferred_thumb:
                ctx.debug(
                    "图片重选: "
                    f"category={image_category.value} media={image_variant.value} "
                    f"source={image_source.external_id} thumb={preferred_thumb}"
                )
            res.thumb = preferred_thumb
            preferred_poster = str(image_source.poster).strip() if is_valid(image_source.poster) else ""
            if preferred_poster:
                res.poster = preferred_poster
            if is_valid(image_source.extrafanart):
                res.extrafanart = list(image_source.extrafanart)

        if res is not None:
            await self._finalize_result_images(ctx, res, label="最终图片", validate_thumb=False)
            ctx.final_images_resolved = True

        return res

    @staticmethod
    def _trailer_quality_rank(trailer_url: str) -> int:
        quality_levels = {
            "sm": 1,
            "dm": 2,
            "dmb": 3,
            "mmb": 4,
            "hmb": 5,
            "mhb": 6,
            "hhb": 7,
            "4k": 8,
        }
        alias = {
            "mmbs": "mmb",
            "hmbs": "hmb",
            "mhbs": "mhb",
            "hhbs": "hhb",
            "4ks": "4k",
        }

        if matched := re.search(
            r"_(sm|dm|dmb|mmb|hmb|mhb|hhb|4k|mmbs|hmbs|mhbs|hhbs|4ks)_[a-z]\.mp4$",
            trailer_url,
            flags=re.IGNORECASE,
        ):
            quality = alias.get(matched.group(1).lower(), matched.group(1).lower())
            return quality_levels.get(quality, 0)

        if matched := re.search(
            r"(sm|dm|dmb|mmb|hmb|mhb|hhb|4k|mmbs|hmbs|mhbs|hhbs|4ks)\.mp4$",
            trailer_url,
            flags=re.IGNORECASE,
        ):
            quality = alias.get(matched.group(1).lower(), matched.group(1).lower())
            return quality_levels.get(quality, 0)

        return 0

    @staticmethod
    def _is_hls_playlist_trailer(trailer_url: str) -> bool:
        trailer_url = str(trailer_url or "").lower()
        return ".m3u8" in trailer_url

    @classmethod
    def _pick_higher_quality_trailer(cls, current_url: str, candidate_url: str) -> str:
        if not current_url:
            return candidate_url

        current_rank = cls._trailer_quality_rank(current_url)
        candidate_rank = cls._trailer_quality_rank(candidate_url)

        if candidate_rank > current_rank:
            return candidate_url

        return current_url

    @staticmethod
    def _is_valid_dmm_cid(cid: str) -> bool:
        return bool(cid and "." not in cid and re.search(r"[a-z]", cid, flags=re.IGNORECASE) and re.search(r"\d", cid))

    @classmethod
    def _build_pv_trailer_from_thumbnail(cls, thumbnail_url: str) -> str:
        thumbnail_url = cls._with_https(str(thumbnail_url or "").strip())
        matched = re.search(
            r"https?://pics\.litevideo\.dmm\.co\.jp/pv/([^/?#]+)/([^/?#]+)\.jpg(?:[?#].*)?$",
            thumbnail_url,
            flags=re.IGNORECASE,
        )
        if not matched:
            return ""
        token, stem = matched.groups()
        if not cls._is_valid_dmm_cid(stem):
            return ""
        return f"https://cc3001.dmm.co.jp/pv/{token}/{stem}mhb.mp4"

    @classmethod
    def _build_freepv_trailer_from_cid(cls, cid: str, quality_suffix: str = "_sm_w") -> str:
        cid = str(cid or "").strip().lower()
        if not cls._is_valid_dmm_cid(cid):
            return ""
        return f"https://cc3001.dmm.co.jp/litevideo/freepv/{cid[0]}/{cid[:3]}/{cid}/{cid}{quality_suffix}.mp4"

    @staticmethod
    def _extract_litevideo_player_url(detail_html: str) -> str:
        if not detail_html:
            return ""
        if not (matched := re.search(r'<iframe[^>]+src="([^"]+digitalapi[^"]+)"', detail_html, flags=re.IGNORECASE)):
            return ""
        return DmmCrawler._with_https(html_utils.unescape(matched.group(1)))

    @classmethod
    def _extract_litevideo_trailer_candidates(cls, player_html: str) -> list[str]:
        if not player_html:
            return []
        trailers: list[str] = []
        for source in re.findall(
            r'"src":"(\\/\\/cc3001\.dmm\.co\.jp\\/pv\\/[^\"]+?\.mp4)"',
            player_html,
            flags=re.IGNORECASE,
        ):
            trailer_url = cls._with_https(source.replace("\\/", "/"))
            if trailer_url and trailer_url not in trailers:
                trailers.append(trailer_url)
        return trailers

    async def _fetch_litevideo_trailer_candidates(self, ctx: Context, content_cid: str) -> list[str]:
        detail_url = f"https://www.dmm.co.jp/litevideo/-/detail/=/cid={content_cid}/"
        detail_html, error = await self._http_request_with_retry("GET", detail_url)
        if detail_html is None:
            ctx.debug(f"litevideo 详情页请求失败: {content_cid=} {error=}")
            return []

        player_url = self._extract_litevideo_player_url(detail_html)
        if not player_url:
            ctx.debug(f"litevideo 详情页未找到播放器 iframe: {content_cid=}")
            return []

        player_html, error = await self._http_request_with_retry("GET", player_url)
        if player_html is None:
            ctx.debug(f"litevideo 播放器页请求失败: {content_cid=} {error=}")
            return []

        return self._extract_litevideo_trailer_candidates(player_html)

    @classmethod
    def _build_fanza_trailer_url(
        cls,
        sample_movie_url: str,
        sample_movie_thumbnail: str = "",
        fallback_cid: str = "",
    ) -> str:
        raw_url = cls._with_https(str(sample_movie_url or "").strip())
        if not raw_url:
            return ""

        if re.search(r"\.mp4(?:[?#].*)?$", raw_url, flags=re.IGNORECASE):
            return raw_url

        trailer_url = raw_url.replace("hlsvideo", "litevideo")

        if "/pv/" in trailer_url and "playlist.m3u8" in trailer_url:
            return ""

        cid_match = re.search(r"/([^/]+)/playlist\.m3u8", trailer_url)
        if cid_match:
            cid_from_url = cid_match.group(1)
            return trailer_url.replace("playlist.m3u8", cid_from_url + "_sm_w.mp4")
        return ""

    @classmethod
    def _build_fanza_fallback_candidates(cls, sample_movie_thumbnail: str, fallback_cid: str) -> list[str]:
        candidates: list[str] = []

        for suffix in ("_4k_w", "_hhb_w", "_mhb_w", "_hmb_w", "_mmb_w", "_dmb_w", "_dm_w", "_sm_w"):
            trailer = cls._build_freepv_trailer_from_cid(fallback_cid, quality_suffix=suffix)
            if trailer and trailer not in candidates:
                candidates.append(trailer)

        if trailer_from_thumb := cls._build_pv_trailer_from_thumbnail(sample_movie_thumbnail):
            if trailer_from_thumb not in candidates:
                candidates.append(trailer_from_thumb)

        return candidates

    async def _validate_trailer_url(self, ctx: Context, trailer_url: str) -> str:
        trailer_url = self._with_https(str(trailer_url or "").strip())
        if not trailer_url:
            return ""

        cookies = self._get_cookies(ctx)
        checks: list[tuple[str, dict[str, str] | None]] = [
            ("HEAD", None),
            ("GET", {"Range": "bytes=0-0"}),
        ]

        for method, headers in checks:
            response, error = await self.async_client.request(method, trailer_url, headers=headers, cookies=cookies)
            if response is None:
                ctx.debug(f"trailer 校验失败: {method} {trailer_url} {error=}")
                continue

            if response.status_code not in (200, 206):
                continue

            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type or "application/xml" in content_type:
                continue
            if content_type and "video" not in content_type and "octet-stream" not in content_type:
                continue

            return str(response.url)

        return ""

    async def _pick_best_valid_trailer(self, ctx: Context, candidates: list[str]) -> str:
        best_trailer = ""
        for trailer_url in dict.fromkeys(candidates):
            validated = await self._validate_trailer_url(ctx, trailer_url)
            if not validated:
                continue
            best_trailer = self._pick_higher_quality_trailer(best_trailer, validated)
        return best_trailer

    @classmethod
    def _pick_best_unvalidated_trailer(cls, current_url: str, candidates: list[str]) -> str:
        best_trailer = current_url
        for trailer_url in dict.fromkeys(candidates):
            trailer_url = cls._with_https(str(trailer_url or "").strip())
            if not trailer_url:
                continue
            if cls._is_hls_playlist_trailer(trailer_url):
                continue
            best_trailer = cls._pick_higher_quality_trailer(best_trailer, trailer_url)
        return best_trailer

    async def fetch_fanza_tv(self, ctx: Context, detail_url: str) -> CrawlerData:
        cid_match = re.search(r"content=([^&/]+)", detail_url)
        if not cid_match:
            ctx.debug(f"无法从 DMM TV URL 提取 cid: {detail_url}")
            return CrawlerData()
        content_cid = cid_match.group(1).lower()

        # 使用带重试的 HTTP 请求
        response, error = await self._http_request_with_retry(
            "POST", "https://api.tv.dmm.co.jp/graphql", json_data=fanza_tv_payload(content_cid)
        )
        if response is None:
            ctx.debug(f"Fanza TV API 请求失败: {content_cid=} {error=}")
            return CrawlerData()
        try:
            resp = FanzaResp.model_validate(response)
            fanza_data = resp.data.fanzaTvPlus.content if resp.data and resp.data.fanzaTvPlus else None
        except Exception as e:
            ctx.debug(f"Fanza TV API 响应解析失败: {e}")
            return CrawlerData()
        if fanza_data is None:
            ctx.debug(f"Fanza TV API 返回空内容: {content_cid=} {response=}")
            return CrawlerData()
        data = fanza_data

        extrafanart = []
        for sample_pic in data.samplePictures or []:
            if sample_pic and sample_pic.imageLarge:
                extrafanart.append(sample_pic.imageLarge)

        sample_movie = data.sampleMovie
        sample_movie_url = str(sample_movie.url or "") if sample_movie else ""
        sample_movie_thumbnail = str(sample_movie.thumbnail or "") if sample_movie else ""
        duration = data.playInfo.duration if data.playInfo else 0

        trailer = self._build_fanza_trailer_url(
            sample_movie_url,
            sample_movie_thumbnail=sample_movie_thumbnail,
            fallback_cid=content_cid,
        )
        trailer = self._pick_best_unvalidated_trailer("", [trailer] if trailer else [])
        if trailer:
            self._log(f"预告片[详情源直取]: cid={content_cid} rank={self._trailer_quality_rank(trailer)} {trailer}")

        should_try_litevideo = not trailer or self._trailer_quality_rank(trailer) < self._trailer_quality_rank(
            "xhhb.mp4"
        )
        if should_try_litevideo:
            litevideo_candidates = await self._fetch_litevideo_trailer_candidates(ctx, content_cid)
            if litevideo_candidates:
                ctx.debug(f"litevideo 直连预告片候选数: {len(litevideo_candidates)} {content_cid=}")
                self._log(f"预告片[litevideo候选]: cid={content_cid} count={len(litevideo_candidates)}")
                best_litevideo = self._pick_best_unvalidated_trailer("", litevideo_candidates)
                if best_litevideo:
                    self._log(
                        f"预告片[litevideo最优]: cid={content_cid} rank={self._trailer_quality_rank(best_litevideo)} {best_litevideo}"
                    )
                trailer = self._pick_higher_quality_trailer(trailer, best_litevideo)

        if not trailer:
            fallback_candidates = self._build_fanza_fallback_candidates(
                sample_movie_thumbnail=sample_movie_thumbnail,
                fallback_cid=content_cid,
            )
            self._log(f"预告片[兜底校验]: cid={content_cid} count={len(fallback_candidates)}")
            trailer = await self._pick_best_valid_trailer(ctx, fallback_candidates)
            if trailer:
                self._log(f"预告片[兜底命中]: cid={content_cid} rank={self._trailer_quality_rank(trailer)} {trailer}")

        if trailer:
            self._log(f"预告片[最终]: cid={content_cid} rank={self._trailer_quality_rank(trailer)} {trailer}")
        else:
            self._log(f"🟠 预告片[最终]: cid={content_cid} 未获取到可用链接")

        return CrawlerData(
            title=str(data.title or ""),
            outline=str(data.description or ""),
            release=str(data.startDeliveryAt or ""),  # 2025-05-17T20:00:00Z
            tags=[genre.name for genre in (data.genres or []) if genre and genre.name],
            runtime=str(int(duration / 60)) if duration else "",
            actors=[a.name for a in (data.actresses or []) if a and a.name],
            poster=str(data.packageImage or ""),
            thumb=str(data.packageLargeImage or ""),
            score="" if data.reviewSummary is None else str(data.reviewSummary.averagePoint),
            series="" if data.series is None else str(data.series.name or ""),
            directors=[d.name for d in (data.directors or []) if d and d.name],
            studio="" if data.maker is None else str(data.maker.name or ""),
            publisher="" if data.label is None else str(data.label.name or ""),
            extrafanart=extrafanart,
            trailer=trailer,
            external_id=detail_url,
        )

    async def fetch_dmm_tv(self, ctx: Context, detail_url: str) -> CrawlerData:
        season_id = re.search(r"seasonId=(\d+)", detail_url)
        if not season_id:
            ctx.debug(f"无法从 DMM TV URL 提取 seasonId: {detail_url}")
            return CrawlerData()
        season_id = season_id.group(1)

        # 使用带重试的 HTTP 请求
        response, error = await self._http_request_with_retry(
            "POST", "https://api.tv.dmm.com/graphql", json_data=dmm_tv_com_payload(season_id)
        )
        if response is None:
            ctx.debug(f"DMM TV API 请求失败: {season_id=} {error=}")
            return CrawlerData()
        try:
            resp = DmmTvResponse.model_validate(response)
            data = resp.data.video
        except Exception as e:
            ctx.debug(f"DMM TV API 响应解析失败: {e}")
            return CrawlerData()

        studio = ""
        if r := [item.staffName for item in data.staffs if item.roleName in ["制作プロダクション", "制作", "制作著作"]]:
            studio = r[0]

        return CrawlerData(
            title=data.titleName,
            outline=data.description,
            actors=[item.actorName for item in data.casts],
            poster=data.packageImage,
            thumb=data.keyVisualImage,
            tags=[item.name for item in data.genres],
            release=data.startPublicAt,  # 2025-05-17T20:00:00Z
            year=str(data.productionYear),
            score=str(data.reviewSummary.averagePoint),
            directors=[item.staffName for item in data.staffs if item.roleName == "監督"],
            studio=studio,
            publisher=studio,
            external_id=detail_url,
        )

    async def fetch_digital(self, ctx: DMMContext, detail_url: str) -> CrawlerData:
        content_id = self._extract_digital_content_id(detail_url)
        if not content_id:
            ctx.debug(f"无法从数字详情页 URL 提取 id: {detail_url}")
            return CrawlerData()

        response, error = await self._http_request_with_retry(
            "POST",
            "https://api.video.dmm.co.jp/graphql",
            json_data=dmm_digital_payload(content_id),
            headers=self._build_digital_api_headers(detail_url),
            cookies=self._get_cookies(ctx),
        )
        if response is None:
            ctx.debug(f"digital GraphQL 请求失败: {content_id=} {error=}")
            return CrawlerData()

        try:
            resp = DmmDigitalResponse.model_validate(response)
            digital_data = resp.data.ppvContent if resp.data else None
            review = resp.data.reviewSummary if resp.data else None
        except Exception as e:
            ctx.debug(f"digital GraphQL 响应解析失败: {content_id=} {e}")
            return CrawlerData()
        if digital_data is None:
            ctx.debug(f"digital GraphQL 返回空内容: {content_id=} {response=}")
            return CrawlerData()
        data = digital_data

        if not data.id:
            ctx.debug(f"digital GraphQL 返回空内容: {content_id=} {response=}")
            return CrawlerData()

        vr_movie = data.sampleVRMovie or None
        sample_2d_movie = data.sample2DMovie or None
        package_image = data.packageImage or DmmDigitalPackageImage()
        trailer_candidates = [
            str(vr_movie.highestMovieUrl or "") if vr_movie else "",
            str(sample_2d_movie.highestMovieUrl or "") if sample_2d_movie else "",
            self._build_fanza_trailer_url(str(sample_2d_movie.hlsMovieUrl or "")) if sample_2d_movie else "",
        ]
        trailer = self._pick_best_unvalidated_trailer("", trailer_candidates)
        if trailer:
            self._log(f"预告片[digital GraphQL]: cid={content_id} rank={self._trailer_quality_rank(trailer)} {trailer}")

        release = str(data.deliveryStartDate or data.makerReleasedAt or "")
        if release:
            release = release[:10]

        runtime = str(int(data.duration / 60)) if data.duration else ""
        outline = self._clean_html_text(data.description)
        sample_images = [str(item.largeImageUrl or "").strip() for item in (data.sampleImages or []) if item]

        ctx.debug(f"digital GraphQL 请求成功: {content_id=} {detail_url=}")
        return CrawlerData(
            title=str(data.title or ""),
            outline=outline,
            release=release,
            runtime=runtime,
            actors=[item.name for item in (data.actresses or []) if item and item.name],
            directors=[item.name for item in (data.directors or []) if item and item.name],
            thumb=str(package_image.largeUrl or ""),
            poster=str(package_image.mediumUrl or ""),
            score="" if review is None or review.average is None else str(review.average),
            series="" if data.series is None else str(data.series.name or ""),
            studio="" if data.maker is None else str(data.maker.name or ""),
            publisher="" if data.label is None else str(data.label.name or ""),
            tags=[item.name for item in (data.genres or []) if item and item.name],
            extrafanart=[url for url in sample_images if url],
            trailer=trailer,
            external_id=detail_url,
        )

    @staticmethod
    def _with_https(url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        return url

    @staticmethod
    def _extract_mono_trailer_from_ga_event(detail_html: str) -> str:
        if not (matched := re.search(r"gaEventVideoStart\('([^']+)'", detail_html)):
            return ""

        payload = html_utils.unescape(matched.group(1))
        try:
            data = json.loads(payload)
        except Exception:
            return ""

        trailer_url = str(data.get("video_url") or "").replace("\\/", "/")
        return DmmCrawler._with_https(trailer_url)

    @staticmethod
    def _extract_mono_ajax_movie_path(detail_html: str) -> str:
        if matched := re.search(r'data-video-url="([^"]+)"', detail_html):
            return html_utils.unescape(matched.group(1))
        if matched := re.search(r"sampleVideoRePlay\('([^']+)'\)", detail_html):
            return html_utils.unescape(matched.group(1))
        return ""

    @staticmethod
    def _extract_player_iframe_url(ajax_movie_html: str) -> str:
        if matched := re.search(r'src="([^"]+)"', ajax_movie_html):
            return DmmCrawler._with_https(html_utils.unescape(matched.group(1)))
        return ""

    @staticmethod
    def _extract_mono_trailer_from_player(player_html: str) -> str:
        if not (matched := re.search(r"const\s+args\s*=\s*(\{.*?\});", player_html, flags=re.DOTALL)):
            return ""

        try:
            args = json.loads(matched.group(1))
        except Exception:
            return ""

        bitrates = args.get("bitrates") or []
        for item in bitrates:
            if trailer_url := str(item.get("src") or ""):
                return DmmCrawler._with_https(trailer_url)

        return DmmCrawler._with_https(str(args.get("src") or ""))

    async def _fetch_mono_trailer(self, ctx: DMMContext, detail_url: str, detail_html: str) -> str:
        trailer_url = self._extract_mono_trailer_from_ga_event(detail_html)
        if trailer_url:
            return trailer_url

        ajax_movie_path = self._extract_mono_ajax_movie_path(detail_html)
        if not ajax_movie_path:
            return ""

        ajax_movie_url = urljoin(detail_url, ajax_movie_path)
        ajax_movie_html, error = await super()._fetch_detail(ctx, ajax_movie_url, False)
        if ajax_movie_html is None:
            ctx.debug(f"mono ajax-movie 请求失败: {ajax_movie_url=} {error=}")
            return ""

        player_iframe_url = self._extract_player_iframe_url(ajax_movie_html)
        if not player_iframe_url:
            return ""

        player_html, error = await super()._fetch_detail(ctx, player_iframe_url, False)
        if player_html is None:
            ctx.debug(f"mono player 请求失败: {player_iframe_url=} {error=}")
            return ""

        return self._extract_mono_trailer_from_player(player_html)

    async def fetch_and_parse(self, ctx: DMMContext, detail_url: str, parser: DetailPageParser) -> CrawlerData:
        html, error = await self._fetch_detail(ctx, detail_url)
        if html is None:
            ctx.debug(f"详情页请求失败: {error=}")
            return CrawlerData()
        ctx.debug(f"详情页请求成功: {detail_url=}")

        selector = Selector(text=html)
        parsed = await parser.parse(ctx, selector, external_id=detail_url)

        if parse_category(detail_url) == Category.MONO:
            canonical_url = self._canonicalize_detail_url(detail_url)
            ctx.detail_media_variants[canonical_url] = parse_media_variant(selector)

        if parse_category(detail_url) == Category.MONO and not is_valid(parsed.trailer):
            trailer_url = await self._fetch_mono_trailer(ctx, detail_url, html)
            if trailer_url:
                parsed.trailer = trailer_url

        return parsed

    @override
    async def _fetch_detail(self, ctx: DMMContext, url: str, use_browser=None) -> tuple[str | None, str]:
        return await super()._fetch_detail(ctx, url, False)

    async def _get_url_content_length(self, url: str) -> int | None:
        return await get_url_content_length(url)

    @override
    async def post_process(self, ctx, res):
        if not res.number:
            res.number = ctx.input.number
        original_thumb = str(res.thumb or "").strip()
        if not ctx.final_images_resolved:
            await self._finalize_result_images(ctx, res, label="最终图片", validate_thumb=True)
            ctx.final_images_resolved = True

        title_text = str(res.title or "").upper()
        input_mosaic = str(ctx.input.mosaic or "")
        is_youma = res.mosaic in ["有码", "有碼"] or input_mosaic in ["有码", "有碼"]
        use_youma_poster = (
            is_youma
            and DownloadableFile.YOUMA_USE_POSTER in manager.config.download_files
            and DownloadableFile.IGNORE_YOUMA not in manager.config.download_files
        )
        # 对于VR视频或SOD工作室，直接使用ps.jpg而不进行裁剪
        # SOD系列通常采用特殊的宽高比，无法通过裁剪获得最佳效果
        is_sod_studio = "SOD" in (res.studio or "")
        use_direct_download = "VR" in title_text or is_sod_studio
        if use_youma_poster:
            self._log("图片[有码策略]: 启用「有码优先使用 Poster」，跳过 SOD/VR 判定")
            use_direct_download = True

        res.image_download = use_direct_download
        res.originaltitle = res.title
        res.originalplot = res.outline
        res.thumb = self._with_https(normalize_media_url(str(res.thumb or "").strip()))
        if res.thumb and res.thumb != original_thumb and "awsimgsrc.dmm.co.jp" in res.thumb:
            self._log(f"图片[AWS高清图命中]: {res.thumb}")

        res.poster = self._with_https(normalize_media_url(str(res.poster or "").strip()))
        if res.image_download and not res.poster:
            self._log("图片[Poster失效]: 直下封面无可用候选，改为裁剪/回退模式")
            res.image_download = False

        # 对SOD工作室进行图片大小比较（在poster赋值之后）
        if not use_youma_poster and is_sod_studio and res.poster and res.thumb:
            ps_url = res.poster  # ps.jpg
            pl_url = res.thumb  # pl.jpg
            try:
                ps_size = await self._get_url_content_length(ps_url)
                pl_size = await self._get_url_content_length(pl_url)

                if ps_size and pl_size:
                    if ps_size < pl_size * 0.5:
                        self._log(f"图片[SOD判定]: ps过低({ps_size}B) vs pl({pl_size}B)，改为裁剪模式")
                        res.image_download = "VR" in title_text
                    else:
                        self._log(f"图片[SOD判定]: {res.studio} ps分辨率充足({ps_size}B)，保持直接下载")
                else:
                    self._log(f"图片[SOD判定]: {res.studio} 无法获取 ps/pl 大小，保持直接下载")
            except Exception as e:
                self._log(f"图片[SOD判定]失败: {e}，保持直接下载")

        if not res.publisher:
            res.publisher = res.studio
        if len(res.release) >= 4:
            res.year = res.release[:4]
        return res

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        raise NotImplementedError
