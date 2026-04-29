#!/usr/bin/env python3
import json
import re
from typing import override

from lxml import etree

from ..config.enums import FieldRule, Website
from ..config.manager import manager
from ..signals import signal
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def getTitle(html):  # 获取标题
    result = html.xpath("//h1/text()")
    result = result[1] if result else ""
    return result


def getNum(html):  # 获取番号
    result = html.xpath("//h1/text()")
    result = result[0] if result else ""
    return result


def getCover(html):  # 获取封面
    result = html.xpath('//a[@data-fancybox="gallery"]/@href')
    result = result[0] if result else ""
    result = "https:" + result if result.startswith("//") else result
    return result


def getExtraFanart(html):  # 获取剧照
    result = html.xpath('//div[@style="padding: 0"]/a/@href')
    result = ["https:" + u if u.startswith("//") else u for u in result]
    return result


def getStudio(html):  # 使用卖家作为厂家
    result = html.xpath('//div[@class="col-8"]/text()')
    if result:
        result = result[0].strip()
    return result


def getTag(html):  # 获取标签
    result = html.xpath('//p[@class="card-text"]/a[contains(@href, "/tag/")]/text()')
    result = str(result).strip(" []").replace(", ", ",").replace("'", "").strip() if result else ""
    return result


def getOutline(html):  # 获取简介
    result = (
        "".join(html.xpath('//div[@class="col des"]//text()'))
        .strip("[]")
        .replace("',", "")
        .replace("\\n", "")
        .replace("'", "")
        .replace("・", "")
        .strip()
    )
    return result


def getMosaic(tag, title):  # 获取马赛克
    result = "无码" if "無修正" in tag or "無修正" in title else "有码"
    return result


def getTrailerVideoId(html, number):  # 获取 FC2 视频 ID
    result = html.xpath(
        '//div[contains(@class, "player-api")]/@data-id'
        ' | //iframe[contains(@data-src, "/embed/")]/@data-src'
        ' | //iframe[contains(@src, "/embed/")]/@src'
    )
    for item in result:
        item = str(item).strip()
        if not item:
            continue
        if item.isdigit():
            return item
        matched = re.search(r"/embed/(\d+)", item)
        if matched:
            return matched.group(1)
    return number


async def getTrailer(client, html, number):  # 获取预告片
    fc2_video_id = getTrailerVideoId(html, number)
    # FC2 sample 接口返回的是带 mid 参数的临时直链，适合立即下载，不适合长期固化。
    # 注意 path 上的 mid 参数不能丢，否则直链会返回 403。
    req_url = f"https://adult.contents.fc2.com/api/v2/videos/{fc2_video_id}/sample"
    response, error = await client.get_text(req_url)
    if response is None:
        return ""
    try:
        data = json.loads(response)
    except Exception:
        return ""

    trailer_url = data.get("path")
    if isinstance(trailer_url, str) and trailer_url.startswith("http"):
        return trailer_url
    return ""


def normalize_fc2_number(number: str) -> str:
    return number.upper().replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Fc2hubCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.FC2HUB

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.FC2HUB, "https://javten.com")

    @override
    async def _run(self, ctx: Context):
        number = normalize_fc2_number(ctx.input.number)
        real_url = ctx.input.appoint_url
        if not real_url:
            search_url = self.base_url + "/search?kw=" + number
            ctx.debug(f"搜索地址: {search_url}")
            ctx.debug_info.search_urls = [search_url]
            html_search, error = await self.async_client.get_text(search_url)
            if html_search is None:
                raise CralwerException(f"网络请求错误: {error}")
            html = etree.fromstring(html_search, etree.HTMLParser())
            real_urls = html.xpath("//link[contains(@href, $number)]/@href", number="id" + number)
            if not real_urls:
                raise CralwerException("搜索结果: 未匹配到番号！")
            language_not_jp = ["/tw/", "/ko/", "/en/"]
            for url in real_urls:
                if all(la not in url for la in language_not_jp):
                    real_url = url
                    break
            if not real_url:
                raise CralwerException("搜索结果: 未匹配到日文详情页！")

        ctx.debug(f"番号地址: {real_url}")
        ctx.debug_info.detail_urls = [real_url]
        html_content, error = await self.async_client.get_text(real_url)
        if html_content is None:
            raise CralwerException(f"网络请求错误: {error}")
        html_info = etree.fromstring(html_content, etree.HTMLParser())

        title = getTitle(html_info)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        tag = getTag(html_info)
        studio = getStudio(html_info)
        trailer = await getTrailer(self.async_client, html_info, number)
        ctx.debug("预告片: 已获取到带时效参数的临时链接" if trailer else "预告片: 未获取到临时下载链接")
        if trailer:
            signal.add_log("🟡 FC2Hub 预告片链接带时效参数，仅适合立即下载，不建议长期复用远程链接。")
        actor = studio if FieldRule.FC2_SELLER in manager.config.fields_rule else ""

        data = CrawlerData(
            number="FC2-" + str(number),
            title=title,
            originaltitle=title,
            actors=split_csv(actor),
            outline=getOutline(html_info),
            originalplot=getOutline(html_info),
            tags=split_csv(tag),
            release="",
            year="",
            runtime="",
            score="",
            series="FC2系列",
            directors=[],
            studio=studio,
            publisher=studio,
            thumb=str(getCover(html_info)),
            poster="",
            extrafanart=getExtraFanart(html_info),
            trailer=trailer,
            image_download=False,
            image_cut="center",
            mosaic=getMosaic(tag, title),
            external_id=str(real_url).strip("[]"),
            wanted="",
        )
        result = data.to_result()
        result.source = self.site().value
        ctx.debug("数据获取成功！")
        return result

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str) -> CrawlerData | None:
        return None
