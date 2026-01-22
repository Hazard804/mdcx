import asyncio
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import override

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
        for r in group.results[::-1]:
            if isinstance(r, Exception):  # 预计只会返回空值, 不会抛出异常
                ctx.debug(f"预料之外的异常: {r}")
                continue
            if res is None:
                res = r
            else:
                res = update_valid(res, r, is_valid)

        return res

    async def fetch_fanza_tv(self, ctx: Context, detail_url: str) -> CrawlerData:
        cid = re.search(r"content=([^&/]+)", detail_url)
        if not cid:
            ctx.debug(f"无法从 DMM TV URL 提取 cid: {detail_url}")
            return CrawlerData()
        cid = cid.group(1)

        # 使用带重试的 HTTP 请求
        response, error = await self._http_request_with_retry(
            "POST", "https://api.tv.dmm.co.jp/graphql", json_data=fanza_tv_payload(cid)
        )
        if response is None:
            ctx.debug(f"Fanza TV API 请求失败: {cid=} {error=}")
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

        # https://cc3001.dmm.co.jp/hlsvideo/freepv/s/ssi/ssis00497/playlist.m3u8
        trailer_url = data.sampleMovie.url.replace("hlsvideo", "litevideo")

        # 检测是否为临时链接（包含 /pv/ 路径的临时 URL）
        # 临时链接示例: https://cc3001.dmm.co.jp/pv/{temp_key}/{filename}
        # 支持多种格式：asfb00192_mhb_w, 1start4814k, n_707agvn001_dmb_w 等
        if "/pv/" in trailer_url:
            # 从临时链接中提取文件名
            filename_match = re.search(r"/pv/[^/]+/(.+?)(?:\.mp4)?$", trailer_url)
            if filename_match:
                filename_base = filename_match.group(1).replace(".mp4", "")
                # 去掉质量标记后缀（_*b_w 格式，如 _mhb_w, _dmb_w, _sm_w, _dm_w 等）
                cid = re.sub(r"(_[a-z]+b?_w)?$", "", filename_base)
                # 确保提取到的是有效的产品ID（包含字母和数字）
                if re.search(r"[a-z]", cid, re.IGNORECASE) and re.search(r"\d", cid):
                    # 构建标准格式的链接
                    # 格式: /litevideo/freepv/{prefix}/{three_char}/{full_number}/{filename}.mp4
                    prefix = cid[0]  # 第一个字符
                    three_char = cid[:3]  # 前三个字符
                    # 使用原始文件名但替换为标准格式
                    trailer = (
                        f"https://cc3001.dmm.co.jp/litevideo/freepv/{prefix}/{three_char}/{cid}/{filename_base}.mp4"
                    )
                else:
                    trailer = ""
            else:
                trailer = ""
        else:
            # 原有的标准链接处理逻辑
            cid_match = re.search(r"/([^/]+)/playlist.m3u8", trailer_url)
            if cid_match:
                cid = cid_match.group(1)
                trailer = trailer_url.replace("playlist.m3u8", cid + "_sm_w.mp4")
            else:
                trailer = ""

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

    async def fetch_and_parse(self, ctx: DMMContext, detail_url: str, parser: DetailPageParser) -> CrawlerData:
        html, error = await self._fetch_detail(ctx, detail_url)
        if html is None:
            ctx.debug(f"详情页请求失败: {error=}")
            return CrawlerData()
        ctx.debug(f"详情页请求成功: {detail_url=}")
        return await parser.parse(ctx, Selector(html), external_id=detail_url)

    @override
    async def _fetch_detail(self, ctx: DMMContext, url: str, use_browser=None) -> tuple[str | None, str]:
        if parse_category(url) not in (Category.DIGITAL):
            return await super()._fetch_detail(ctx, url, False)  # 对于确定不需要浏览器的, 强制不使用
        return await super()._fetch_detail(ctx, url, None)

    async def _get_url_content_length(self, url: str) -> int | None:
        """获取URL的Content-Length（文件大小）

        先尝试HEAD请求，如果返回405则改用GET请求并立即关闭连接
        包含重试机制（最多3次重试）
        """
        max_retries = 3
        retry_delays = [0.5, 1.0, 1.5]

        for attempt in range(max_retries):
            try:
                # 先尝试HEAD请求
                async with manager.computed.async_client.request("HEAD", url, timeout=10) as resp:
                    if resp.status == 200:
                        content_length = resp.headers.get("content-length")
                        if content_length:
                            return int(content_length)
                    elif resp.status == 405:
                        # 405 Method Not Allowed，改用GET请求
                        break

            except Exception:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delays[attempt])
                    continue
                return None

        # 使用GET请求获取文件大小
        for attempt in range(max_retries):
            try:
                # 使用stream=True只读取响应头而不下载内容
                async with manager.computed.async_client.request("GET", url, timeout=10) as resp:
                    if resp.status == 200:
                        content_length = resp.headers.get("content-length")
                        if content_length:
                            return int(content_length)
                    return None
            except Exception:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delays[attempt])
                    continue
                return None

        return None

    @override
    async def post_process(self, ctx, res):
        if not res.number:
            res.number = ctx.input.number
        # 对于VR视频或SOD工作室，直接使用ps.jpg而不进行裁剪
        # SOD系列通常采用特殊的宽高比，无法通过裁剪获得最佳效果
        is_sod_studio = "SOD" in (res.studio or "")
        use_direct_download = "VR" in res.title or is_sod_studio

        # 调试：输出studio字段和SOD检测结果
        signal.add_log(
            f"📊 [调试] 视频 {res.number} studio: '{res.studio}', is_sod: {is_sod_studio}, "
            f"poster: {bool(res.poster)}, thumb: {bool(res.thumb)}"
        )

        if is_sod_studio and res.poster and res.thumb:
            # 对SOD工作室，比较ps.jpg和pl.jpg的大小
            # 如果ps.jpg分辨率明显低于pl.jpg，则使用裁剪后的poster而不是直接下载
            ps_url = res.poster  # ps.jpg
            pl_url = res.thumb  # pl.jpg
            try:
                # 获取两个文件的大小
                ps_size = await self._get_url_content_length(ps_url)
                pl_size = await self._get_url_content_length(pl_url)

                if ps_size and pl_size:
                    # 如果ps.jpg大小不足pl.jpg的50%，则认为分辨率太低，改用裁剪版本
                    if ps_size < pl_size * 0.5:
                        signal.add_log(
                            f"SOD工作室ps.jpg分辨率过低({ps_size}B) vs pl.jpg({pl_size}B)，"
                            f"将使用裁剪后的图片而不是直接下载"
                        )
                        use_direct_download = "VR" in res.title
                    else:
                        signal.add_log(
                            f"检测到SOD工作室: {res.studio}，ps.jpg分辨率充足({ps_size}B)，将直接使用原始图片不进行裁剪"
                        )
                else:
                    signal.add_log(f"检测到SOD工作室: {res.studio}，无法获取图片大小，将直接使用原始图片不进行裁剪")
            except Exception as e:
                signal.add_log(f"SOD工作室图片大小比较失败: {e}，将直接使用原始图片不进行裁剪")

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
                    ctx.debug(f"use aws image: {aws_url}")
                    res.thumb = aws_url
                    break
        res.poster = res.thumb.replace("pl.jpg", "ps.jpg")
        if not res.publisher:
            res.publisher = res.studio
        if len(res.release) >= 4:
            res.year = res.release[:4]
        return res

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        raise NotImplementedError
