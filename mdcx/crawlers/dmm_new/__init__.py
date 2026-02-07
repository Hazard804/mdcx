import asyncio
import html as html_utils
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import override
from urllib.parse import urljoin

from parsel import Selector
from patchright._impl._api_structures import SetCookieParam
from patchright.async_api import Browser

from mdcx.base.web import check_url
from mdcx.config.manager import manager
from mdcx.config.models import Website
from mdcx.models.types import CrawlerInput
from mdcx.signals import signal
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
from .parsers import Category, DigitalParser, MonoParser, RentalParser, parse_category
from .tv import DmmTvResponse, FanzaResp, dmm_tv_com_payload, fanza_tv_payload


class DMMContext(Context):
    number_00: str | None = None
    number_no_00: str | None = None


class DmmCrawler(GenericBaseCrawler[DMMContext]):
    mono = MonoParser()
    digital = DigitalParser()
    rental = RentalParser()

    def __init__(self, client: AsyncWebClient, base_url: str = "", browser: Browser | None = None):
        super().__init__(client, base_url, browser)

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
    def _get_cookies_browser(self, ctx: DMMContext) -> Sequence[SetCookieParam] | None:
        return [
            SetCookieParam(name="age_check_done", value="1", domain=".dmm.co.jp", path="/"),
            SetCookieParam(name="age_check_done", value="1", domain=".dmm.com", path="/"),
        ]

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

    @override
    async def _parse_search_page(self, ctx, html, search_url) -> list[str] | None:
        if "404 Not Found" in html.css("span.d-txten::text").get(""):
            raise CralwerException("404! 页面地址错误！")

        # \"detailUrl\":\"https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=ssni00103/?i3_ord=1\u0026i3_ref=search"
        url_list = set(html.re(r'detailUrl\\":\\"(.*?)\\"'))
        if not url_list:
            ctx.debug(f"没有找到搜索结果: {ctx.input.number} {search_url=}")
            return None

        number_parts: re.Match[str] | None = re.search(r"(\d*[a-z]+)?-?(\d+)", ctx.input.number.lower())
        if not number_parts:
            ctx.debug(f"无法从番号 {ctx.input.number} 提取前缀和数字")
            return None
        prefix = number_parts.group(1)
        digits = number_parts.group(2)
        n1 = f"{prefix}{digits:0>5}"
        n2 = f"{prefix}{digits}"

        res = []
        for u in url_list:
            # https://tv.dmm.co.jp/list/?content=mide00726&i3_ref=search&i3_ord=1
            # https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=mide00726/?i3_ref=search&i3_ord=2
            # https://www.dmm.com/mono/dvd/-/detail/=/cid=n_709mmrak089sp/?i3_ref=search&i3_ord=1
            if re.search(rf"[^a-z]{n1}[^0-9]", u) or re.search(rf"[^a-z]{n2}[^0-9]", u):
                res.append(u.encode("utf-8").decode("unicode_escape"))

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

    @override
    async def _detail(self, ctx: DMMContext, detail_urls: list[str]) -> CrawlerData | None:
        d = defaultdict(list)
        for url in detail_urls:
            category = parse_category(url)
            d[category].append(url)

        # 设置 GatherGroup 的整体超时时间，给单个请求更多时间
        # 因为我们已经在单个请求中实现了重试机制
        total_timeout = manager.config.timeout * (manager.config.retry + 1) * 2  # 给足够的时间

        async with GatherGroup[CrawlerData](timeout=total_timeout) as group:
            for url in d[Category.FANZA_TV]:
                group.add(self.fetch_fanza_tv(ctx, url))
            for url in d[Category.DMM_TV]:
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
                    group.add(self.fetch_and_parse(ctx, u, parser))

        res = None
        best_trailer = ""
        for r in group.results[::-1]:
            if isinstance(r, Exception):  # 预计只会返回空值, 不会抛出异常
                ctx.debug(f"预料之外的异常: {r}")
                continue

            if is_valid(r.trailer):
                candidate_trailer = str(r.trailer)
                if self._is_hls_playlist_trailer(candidate_trailer):
                    ctx.debug(f"跳过 m3u8 预告片候选: url={candidate_trailer}")
                    continue
                candidate_rank = self._trailer_quality_rank(candidate_trailer)
                source_hint = f" external_id={r.external_id}" if is_valid(r.external_id) else ""
                ctx.debug(f"trailer 候选: rank={candidate_rank}{source_hint} url={candidate_trailer}")

                previous_best = best_trailer
                best_trailer = self._pick_higher_quality_trailer(best_trailer, candidate_trailer)
                if best_trailer != previous_best:
                    if previous_best:
                        prev_rank = self._trailer_quality_rank(previous_best)
                        ctx.debug(
                            f"trailer 最优更新: rank {prev_rank} -> {candidate_rank}; "
                            f"old={previous_best}; new={best_trailer}"
                        )
                    else:
                        ctx.debug(f"trailer 初始最优: rank={candidate_rank}; url={best_trailer}")

            if res is None:
                res = r
            else:
                res = update_valid(res, r, is_valid)

        if res is not None and best_trailer:
            if not is_valid(res.trailer):
                ctx.debug(f"trailer 最终采用最优候选(补全空值): {best_trailer}")
            elif str(res.trailer) != best_trailer:
                ctx.debug(f"trailer 最终改写为更高质量: old={res.trailer}; new={best_trailer}")
            res.trailer = best_trailer
        elif res is not None and is_valid(res.trailer) and self._is_hls_playlist_trailer(str(res.trailer)):
            ctx.debug(f"trailer 最终清空 m3u8 链接: old={res.trailer}")
            res.trailer = ""

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
        return bool(
            cid
            and "." not in cid
            and re.search(r"[a-z]", cid, flags=re.IGNORECASE)
            and re.search(r"\d", cid)
        )

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
            data = resp.data.fanzaTvPlus.content
        except Exception as e:
            ctx.debug(f"Fanza TV API 响应解析失败: {e}")
            return CrawlerData()

        extrafanart = []
        for sample_pic in data.samplePictures:
            if sample_pic.imageLarge:
                extrafanart.append(sample_pic.imageLarge)

        trailer = self._build_fanza_trailer_url(
            data.sampleMovie.url,
            sample_movie_thumbnail=data.sampleMovie.thumbnail,
            fallback_cid=content_cid,
        )
        trailer = self._pick_best_unvalidated_trailer("", [trailer] if trailer else [])
        if trailer:
            signal.add_log(
                f"🎬 DMM预告片[详情源直取]: cid={content_cid} rank={self._trailer_quality_rank(trailer)} {trailer}"
            )

        should_try_litevideo = not trailer or self._trailer_quality_rank(trailer) < self._trailer_quality_rank("xhhb.mp4")
        if should_try_litevideo:
            litevideo_candidates = await self._fetch_litevideo_trailer_candidates(ctx, content_cid)
            if litevideo_candidates:
                ctx.debug(f"litevideo 直连预告片候选数: {len(litevideo_candidates)} {content_cid=}")
                signal.add_log(f"🎬 DMM预告片[litevideo候选]: cid={content_cid} count={len(litevideo_candidates)}")
                best_litevideo = self._pick_best_unvalidated_trailer("", litevideo_candidates)
                if best_litevideo:
                    signal.add_log(
                        f"🎬 DMM预告片[litevideo最优]: cid={content_cid} rank={self._trailer_quality_rank(best_litevideo)} {best_litevideo}"
                    )
                trailer = self._pick_higher_quality_trailer(trailer, best_litevideo)

        if not trailer:
            fallback_candidates = self._build_fanza_fallback_candidates(
                sample_movie_thumbnail=data.sampleMovie.thumbnail,
                fallback_cid=content_cid,
            )
            signal.add_log(f"🎬 DMM预告片[兜底校验]: cid={content_cid} count={len(fallback_candidates)}")
            trailer = await self._pick_best_valid_trailer(ctx, fallback_candidates)
            if trailer:
                signal.add_log(
                    f"🎬 DMM预告片[兜底命中]: cid={content_cid} rank={self._trailer_quality_rank(trailer)} {trailer}"
                )

        if trailer:
            signal.add_log(f"🎬 DMM预告片[最终]: cid={content_cid} rank={self._trailer_quality_rank(trailer)} {trailer}")
        else:
            signal.add_log(f"🟠 DMM预告片[最终]: cid={content_cid} 未获取到可用链接")

        return CrawlerData(
            title=data.title,
            outline=data.description,
            release=data.startDeliveryAt,  # 2025-05-17T20:00:00Z
            tags=[genre.name for genre in data.genres],
            runtime=str(int(data.playInfo.duration / 60)),
            actors=[a.name for a in data.actresses],
            poster=data.packageImage,
            thumb=data.packageLargeImage,
            score=str(data.reviewSummary.averagePoint),
            series=data.series.name,
            directors=[d.name for d in data.directors],
            studio=data.maker.name,
            publisher=data.label.name,
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

        parsed = await parser.parse(ctx, Selector(html), external_id=detail_url)

        if parse_category(detail_url) == Category.MONO and not is_valid(parsed.trailer):
            trailer_url = await self._fetch_mono_trailer(ctx, detail_url, html)
            if trailer_url:
                parsed.trailer = trailer_url

        return parsed

    @override
    async def _fetch_detail(self, ctx: DMMContext, url: str, use_browser=None) -> tuple[str | None, str]:
        if parse_category(url) not in (Category.DIGITAL):
            return await super()._fetch_detail(ctx, url, False)  # 对于确定不需要浏览器的, 强制不使用
        return await super()._fetch_detail(ctx, url, None)

    async def _get_url_content_length(self, url: str) -> int | None:
        """获取URL的Content-Length（文件大小）

        先尝试HEAD请求，如果返回405则改用GET请求
        包含重试机制（最多3次重试）
        """
        max_retries = 3
        retry_delays = [0.5, 1.0, 1.5]

        for attempt in range(max_retries):
            try:
                # 先尝试HEAD请求
                response, error = await manager.computed.async_client.request("HEAD", url)

                if response is not None:
                    if response.status_code == 200:
                        content_length = response.headers.get("Content-Length")
                        if content_length:
                            signal.add_log(f"HEAD获取文件大小成功: {url} -> {content_length}B")
                            return int(content_length)
                    elif response.status_code == 405:
                        # 405 Method Not Allowed，改用GET请求
                        signal.add_log(f"HEAD请求返回405，将切换为GET请求: {url}")
                        break
                    else:
                        signal.add_log(f"HEAD请求返回{response.status_code}: {url}")
                elif error:
                    signal.add_log(f"HEAD请求异常(尝试{attempt + 1}/{max_retries}): {url} -> {error}")

            except Exception as e:
                signal.add_log(f"HEAD请求异常(尝试{attempt + 1}/{max_retries}): {url} -> {e}")

            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delays[attempt])

        # 使用GET请求获取文件大小
        for attempt in range(max_retries):
            try:
                response, error = await manager.computed.async_client.request("GET", url)

                if response is not None:
                    if response.status_code == 200:
                        content_length = response.headers.get("Content-Length")
                        if content_length:
                            signal.add_log(f"GET获取文件大小成功: {url} -> {content_length}B")
                            return int(content_length)
                        else:
                            signal.add_log(f"GET请求成功但无Content-Length头: {url}")
                    else:
                        signal.add_log(f"GET请求返回{response.status_code}: {url}")
                elif error:
                    signal.add_log(f"GET请求异常(尝试{attempt + 1}/{max_retries}): {url} -> {error}")

                return None

            except Exception as e:
                signal.add_log(f"GET请求异常(尝试{attempt + 1}/{max_retries}): {url} -> {e}")

            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delays[attempt])

        return None

    @override
    async def post_process(self, ctx, res):
        if not res.number:
            res.number = ctx.input.number
        # 对于VR视频或SOD工作室，直接使用ps.jpg而不进行裁剪
        # SOD系列通常采用特殊的宽高比，无法通过裁剪获得最佳效果
        is_sod_studio = "SOD" in (res.studio or "")
        use_direct_download = "VR" in res.title or is_sod_studio

        res.image_download = use_direct_download
        res.originaltitle = res.title
        res.originalplot = res.outline
        # check aws image
        if res.thumb and "pics.dmm.co.jp" in res.thumb:
            aws_urls = [
                res.thumb.replace("pics.dmm.co.jp", "awsimgsrc.dmm.co.jp/pics_dig").replace("/adult/", "/"),
                f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{ctx.number_00}/{ctx.number_00}pl.jpg",
                f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{ctx.number_no_00}/{ctx.number_no_00}pl.jpg",
            ]
            for aws_url in aws_urls:
                if await check_url(aws_url):
                    signal.add_log(f"DMM 使用 AWS 高清图: {aws_url}")
                    res.thumb = aws_url
                    break
        res.poster = res.thumb.replace("pl.jpg", "ps.jpg")

        # 对SOD工作室进行图片大小比较（在poster赋值之后）
        if is_sod_studio and res.poster and res.thumb:
            ps_url = res.poster  # ps.jpg
            pl_url = res.thumb  # pl.jpg
            try:
                ps_size = await self._get_url_content_length(ps_url)
                pl_size = await self._get_url_content_length(pl_url)

                if ps_size and pl_size:
                    if ps_size < pl_size * 0.5:
                        signal.add_log(
                            f"SOD工作室ps.jpg分辨率过低({ps_size}B) vs pl.jpg({pl_size}B)，"
                            f"将使用裁剪后的图片而不是直接下载"
                        )
                        res.image_download = "VR" in res.title
                    else:
                        signal.add_log(
                            f"检测到SOD工作室: {res.studio}，ps.jpg分辨率充足({ps_size}B)，将直接使用原始图片不进行裁剪"
                        )
                else:
                    signal.add_log(f"检测到SOD工作室: {res.studio}，无法获取图片大小，将直接使用原始图片不进行裁剪")
            except Exception as e:
                signal.add_log(f"SOD工作室图片大小比较失败: {e}，将直接使用原始图片不进行裁剪")

        if not res.publisher:
            res.publisher = res.studio
        if len(res.release) >= 4:
            res.year = res.release[:4]
        return res

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        raise NotImplementedError
