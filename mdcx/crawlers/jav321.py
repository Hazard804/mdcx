#!/usr/bin/env python3
import asyncio
import random
import re
from collections.abc import Callable
from typing import override
from urllib.parse import urlsplit

from lxml import etree

from ..base.web import check_url, is_dmm_image_url, normalize_media_url
from ..config.enums import DownloadableFile
from ..config.manager import manager
from ..config.models import Website
from ..models.types import CrawlerResult
from .base import BaseCrawler, CralwerException, CrawlerData

type ImageLogFn = Callable[[str], None] | None


def getTitle(response):
    return str(re.findall(r"<h3>(.+) <small>", response)).strip(" ['']")


def getActor(response):
    if re.search(r'<a href="/star/\S+">(\S+)</a> &nbsp;', response):
        return str(re.findall(r'<a href="/star/\S+">(\S+)</a> &nbsp;', response)).strip(" [',']").replace("'", "")
    elif re.search(r'<a href="/heyzo_star/\S+">(\S+)</a> &nbsp;', response):
        return str(re.findall(r'<a href="/heyzo_star/\S+">(\S+)</a> &nbsp;', response)).strip(" [',']").replace("'", "")
    else:
        return str(re.findall(r"<b>出演者</b>: ([^<]+) &nbsp; <br>", response)).strip(" [',']").replace("'", "")


def getStudio(html):
    result = str(html.xpath('//div[@class="col-md-9"]/a[contains(@href,"/company/")]/text()')).strip(" ['']")
    return result


def getRuntime(response):
    return str(re.findall(r"<b>収録時間</b>: (\d+) \S+<br>", response)).strip(" ['']")


def getSeries(html):
    result = str(html.xpath('//div[@class="col-md-9"]/a[contains(@href,"/series/")]/text()')).strip(" ['']")
    return result


def getWebsite(detail_page):
    return "https:" + detail_page.xpath('//a[contains(text(),"简体中文")]/@href')[0]


def getNum(response, number):
    result = re.findall(r"<b>品番</b>: (\S+)<br>", response)
    return result[0].strip().upper() if result else number


def getScore(response):
    if re.search(r'<b>平均評価</b>: <img data-original="/img/(\d+).gif" />', response):
        score = re.findall(r'<b>平均評価</b>: <img data-original="/img/(\d+).gif" />', response)[0]
        return str(float(score) / 10.0)
    else:
        return str(re.findall(r"<b>平均評価</b>: ([^<]+)<br>", response)).strip(" [',']").replace("'", "")


def getYear(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def getRelease(response):
    return str(re.findall(r"<b>配信開始日</b>: (\d+-\d+-\d+)<br>", response)).strip(" ['']").replace("0000-00-00", "")


def getCover(detail_page):
    cover_url = str(
        detail_page.xpath(
            "/html/body/div[@class='row'][2]/div[@class='col-md-3']/div[@class='col-xs-12 col-md-12'][1]/p/a/img[@class='img-responsive']/@src"
        )
    ).strip(" ['']")
    if cover_url == "":
        cover_url = str(detail_page.xpath("//*[@id='vjs_sample_player']/@poster")).strip(" ['']")
    return cover_url


def getExtraFanart(htmlcode):
    extrafanart_list = htmlcode.xpath(
        "/html/body/div[@class='row'][2]/div[@class='col-md-3']/div[@class='col-xs-12 col-md-12']/p/a/img[@class='img-responsive']/@src"
    )
    return extrafanart_list


def getCoverSmall(detail_page):
    return str(detail_page.xpath('//img[@class="img-responsive"]/@src')[0])


def _prefer_dmm_aws_url(url: str) -> str:
    normalized = normalize_media_url(str(url or "").strip())
    if not normalized:
        return ""
    if "pics.dmm.co.jp" in normalized:
        return normalized.replace("pics.dmm.co.jp", "awsimgsrc.dmm.co.jp/pics_dig").replace("/adult/", "/")
    return normalized


def _iter_dmm_image_candidates(url: str) -> list[str]:
    normalized = normalize_media_url(str(url or "").strip())
    if not normalized:
        return []

    seen: set[str] = set()
    candidates: list[str] = []
    for candidate in (_prefer_dmm_aws_url(normalized), normalized):
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
    return candidates


def _to_poster_url(thumb_url: str) -> str:
    normalized = normalize_media_url(str(thumb_url or "").strip())
    if normalized.endswith("pl.jpg"):
        return normalized[:-6] + "ps.jpg"
    return normalized


def _normalize_thumb_poster(thumb_url: str, poster_url: str) -> tuple[str, str]:
    normalized_thumb = normalize_media_url(str(thumb_url or "").strip())
    normalized_poster = normalize_media_url(str(poster_url or "").strip())

    for candidate in (normalized_thumb, normalized_poster):
        if candidate.endswith("pl.jpg") or candidate.endswith("ps.jpg"):
            base_url = candidate[:-6]
            return base_url + "pl.jpg", base_url + "ps.jpg"

    if normalized_thumb and not normalized_poster:
        return normalized_thumb, normalized_thumb
    if normalized_poster and not normalized_thumb:
        return normalized_poster, normalized_poster
    return normalized_thumb, normalized_poster


def _image_match_key(url: str) -> str:
    normalized = normalize_media_url(str(url or "").strip())
    if not normalized:
        return ""
    if not is_dmm_image_url(normalized):
        return normalized

    split_result = urlsplit(normalized)
    path = split_result.path
    if split_result.netloc.lower() == "awsimgsrc.dmm.co.jp" and path.startswith("/pics_dig/"):
        path = path[len("/pics_dig") :]
    return path.replace("/adult/", "/")


def _remove_cover_from_extrafanart(cover_url: str, image_urls: list[str]) -> list[str]:
    cover_key = _image_match_key(cover_url)
    if not cover_key:
        return image_urls
    return [image_url for image_url in image_urls if _image_match_key(image_url) != cover_key]


def getTag(response):  # 获取演员
    return re.findall(r'<a href="/genre/\S+">(\S+)</a>', response)


def getOutline(detail_page):
    # 修复路径，避免简介含有垃圾信息 "*根据分发方式，内容可能会有所不同"
    return detail_page.xpath("string(/html/body/div[2]/div[1]/div[1]/div[2]/div[3]/div/text())")


def _log_image(log_fn: ImageLogFn, message: str) -> None:
    if log_fn is not None:
        log_fn(message)


async def _validate_dmm_image_if_needed(url: str, label: str, *, log_fn: ImageLogFn = None) -> str:
    normalized = normalize_media_url(str(url or "").strip())
    if not normalized:
        return ""

    if not is_dmm_image_url(normalized):
        return normalized

    for index, candidate in enumerate(_iter_dmm_image_candidates(normalized)):
        validated = await check_url(candidate)
        if not validated:
            continue

        validated_url = normalize_media_url(str(validated).strip())
        if index == 0 and candidate != normalized:
            _log_image(log_fn, f"图片高清图命中: {label} {normalized} -> {validated_url}")
        elif validated_url != normalized:
            _log_image(log_fn, f"图片校验重定向: {label} {normalized} -> {validated_url}")
        return validated_url

    _log_image(log_fn, f"图片校验失败: {label} {normalized}")
    return ""


async def _validate_preferred_dmm_image_if_needed(url: str, label: str, *, log_fn: ImageLogFn = None) -> str:
    normalized = normalize_media_url(str(url or "").strip())
    if not normalized:
        return ""

    preferred = _prefer_dmm_aws_url(normalized)
    if not is_dmm_image_url(preferred):
        return preferred

    validated = await check_url(preferred)
    if not validated:
        _log_image(log_fn, f"图片抽检失败: {label} {preferred}")
        return ""

    validated_url = normalize_media_url(str(validated).strip())
    if preferred != normalized and validated_url == preferred:
        _log_image(log_fn, f"图片高清图命中: {label} {normalized} -> {validated_url}")
    elif validated_url != preferred:
        _log_image(log_fn, f"图片校验重定向: {label} {preferred} -> {validated_url}")
    return validated_url


async def _filter_dmm_extrafanart(image_urls: list[str], *, log_fn: ImageLogFn = None) -> list[str]:
    candidates = _normalize_extrafanart_urls(image_urls)
    if not candidates:
        return []

    sample_indexes = list(range(len(candidates)))
    if len(candidates) > 3:
        sample_indexes = sorted(random.sample(range(len(candidates)), 3))

    sampled_candidates = [(index, candidates[index]) for index in sample_indexes]
    sampled_results = await asyncio.gather(
        *[
            _validate_preferred_dmm_image_if_needed(image_url, f"extrafanart[{index + 1}]", log_fn=log_fn)
            for index, image_url in sampled_candidates
        ]
    )
    validated_by_index = {
        index: validated for (index, _), validated in zip(sampled_candidates, sampled_results, strict=True)
    }

    if all(sampled_results):
        _log_image(log_fn, f"剧照抽检通过: 随机抽检 {len(sampled_candidates)}/{len(candidates)}，整批升级 AWS")
        valid_urls: list[str] = []
        for index, image_url in enumerate(candidates):
            resolved_url = validated_by_index.get(index) or _prefer_dmm_aws_url(image_url) or image_url
            if resolved_url not in valid_urls:
                valid_urls.append(resolved_url)
        return valid_urls

    passed_count = sum(1 for image_url in sampled_results if image_url)
    _log_image(log_fn, f"剧照抽检失败: 随机抽检 {passed_count}/{len(sampled_candidates)} 通过，回退全量校验")

    remaining_candidates = [
        (index, image_url) for index, image_url in enumerate(candidates) if not validated_by_index.get(index)
    ]
    if remaining_candidates:
        remaining_results = await asyncio.gather(
            *[
                _validate_dmm_image_if_needed(image_url, f"extrafanart[{index + 1}]", log_fn=log_fn)
                for index, image_url in remaining_candidates
            ]
        )
        for (index, _), validated in zip(remaining_candidates, remaining_results, strict=True):
            validated_by_index[index] = validated

    valid_urls: list[str] = []
    for index in range(len(candidates)):
        validated_url = validated_by_index.get(index, "")
        if validated_url and validated_url not in valid_urls:
            valid_urls.append(validated_url)
    return valid_urls


async def _resolve_dmm_poster_url(thumb_url: str, poster_url: str, *, log_fn: ImageLogFn = None) -> str:
    candidates = _normalize_extrafanart_urls([poster_url, _to_poster_url(thumb_url)])
    for candidate in candidates:
        validated_url = await _validate_dmm_image_if_needed(candidate, "poster", log_fn=log_fn)
        if validated_url:
            return validated_url
    return ""


def _normalize_extrafanart_urls(image_urls: list[str]) -> list[str]:
    valid_urls: list[str] = []
    for image_url in image_urls:
        normalized = normalize_media_url(str(image_url or "").strip())
        if normalized and normalized not in valid_urls:
            valid_urls.append(normalized)
    return valid_urls


def _split_legacy_names(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，、/／]", value) if item.strip()]


class Jav321Crawler(BaseCrawler):
    UNCENSORED_STUDIOS = {
        "一本道",
        "HEYZO",
        "サムライポルノ",
        "キャットウォーク",
        "サイクロン",
        "ルチャリブレ",
        "スーパーモデルメディア",
        "スタジオテリヤキ",
        "レッドホットコレクション",
        "スカイハイエンターテインメント",
        "小天狗",
        "オリエンタルドリーム",
        "Climax Zipang",
        "CATCHEYE",
        "ファイブスター",
        "アジアンアイズ",
        "ゴリラ",
        "ラフォーレ ガール",
        "MIKADO",
        "ムゲンエンターテインメント",
        "ツバキハウス",
        "ザーメン二郎",
        "トラトラトラ",
        "メルシーボークー",
        "神風",
        "Queen 8",
        "SASUKE",
        "ファンタドリーム",
        "マツエンターテインメント",
        "ピンクパンチャー",
        "ワンピース",
        "ゴールデンドラゴン",
        "Tokyo Hot",
        "Caribbean",
    }

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAV321

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.jav321.com"

    @override
    async def _run(self, ctx) -> CrawlerResult:
        result_url = ctx.input.appoint_url or f"{self.base_url}/search"
        if ctx.input.appoint_url:
            ctx.debug(f"番号地址: {result_url}")
            ctx.debug_info.detail_urls = [result_url]
        else:
            ctx.debug(f'搜索地址: {result_url} {{"sn": {ctx.input.number}}}')
            ctx.debug_info.search_urls = [result_url]

        response, error = await self.async_client.post_text(result_url, data={"sn": ctx.input.number})
        if response is None:
            raise CralwerException(f"网络请求错误: {error}")
        if "AVが見つかりませんでした" in response:
            raise CralwerException("搜索结果: 未匹配到番号")

        detail_page = etree.fromstring(response, etree.HTMLParser())
        detail_url = self._extract_website(detail_page, fallback=result_url)
        if detail_url:
            ctx.debug(f"番号地址: {detail_url}")
            ctx.debug_info.detail_urls = [detail_url]

        data = await self._parse_legacy_detail(ctx, response, detail_page, detail_url)
        data.source = self.site().value
        return await self.post_process(ctx, data.to_result())

    @staticmethod
    def _extract_website(detail_page, fallback: str) -> str:
        try:
            return getWebsite(detail_page)
        except Exception:
            return fallback

    async def _parse_legacy_detail(self, ctx, response: str, detail_page, detail_url: str) -> CrawlerData:
        actor = getActor(response)
        title = getTitle(response).strip()
        if not title:
            raise CralwerException("数据获取失败: 未获取到标题")

        cover_url = getCover(detail_page)
        poster_url = getCoverSmall(detail_page)
        if not cover_url:
            cover_url = poster_url

        release = getRelease(response)
        number = getNum(response, ctx.input.number)
        studio = getStudio(detail_page)
        extrafanart = getExtraFanart(detail_page)
        cover_url, poster_url = _normalize_thumb_poster(cover_url, poster_url)
        extrafanart = _remove_cover_from_extrafanart(cover_url, extrafanart)
        cover_url = await _validate_dmm_image_if_needed(cover_url, "thumb", log_fn=ctx.debug)
        poster_url = await _resolve_dmm_poster_url(cover_url, poster_url, log_fn=ctx.debug)
        if DownloadableFile.EXTRAFANART in manager.config.download_files:
            extrafanart = await _filter_dmm_extrafanart(extrafanart, log_fn=ctx.debug)
        else:
            extrafanart = _normalize_extrafanart_urls(extrafanart)

        mosaic = "无码" if studio in self.UNCENSORED_STUDIOS else "有码"
        actors = _split_legacy_names(actor)
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=getOutline(detail_page),
            originalplot=getOutline(detail_page),
            tags=getTag(response),
            release=release,
            year=getYear(release),
            runtime=getRuntime(response),
            score=getScore(response),
            series=getSeries(detail_page),
            directors=[],
            studio=studio,
            publisher=studio,
            external_id=detail_url,
            thumb=cover_url,
            poster=poster_url,
            extrafanart=extrafanart,
            trailer="",
            image_download=False,
            image_cut="right",
            mosaic=mosaic,
            wanted="",
        )

    @override
    async def _generate_search_url(self, ctx) -> list[str] | str | None:
        return f"{self.base_url}/search"

    @override
    async def _parse_search_page(self, ctx, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx, html, detail_url: str) -> CrawlerData | None:
        return None
