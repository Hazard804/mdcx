#!/usr/bin/env python3
import re
from typing import override

from lxml import etree

from ..config.manager import manager
from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def getTitle(html, number):  # 获取标题
    result = html.xpath("//h3/text()")
    result = result[0].replace(f"FC2-{number} ", "") if result else ""
    return result


def getNum(html):  # 获取番号
    result = html.xpath("//h1/text()")
    result = result[0] if result else ""
    return result


def getCover(html):  # 获取封面
    extrafanart = []
    result = html.xpath('//img[@class="responsive"]/@src')
    if result:
        for res in result:
            extrafanart.append(res.replace("../uploadfile", "https://fc2club.top/uploadfile"))
        result = result[0].replace("../uploadfile", "https://fc2club.top/uploadfile")
    else:
        result = ""
    return result, extrafanart


def getStudio(html):  # 使用卖家作为厂家
    result = html.xpath('//strong[contains(text(), "卖家信息")]/../a/text()')
    result = result[0].strip() if result else ""
    return result.replace("本资源官网地址", "")


def getScore(html):  # 获取评分
    try:
        result = html.xpath('//strong[contains(text(), "影片评分")]/../text()')
        result = re.findall(r"\d+", result[0])[0]
    except Exception:
        result = ""
    return result


def getActor(html, studio):  # 获取演员
    result = html.xpath('//strong[contains(text(), "女优名字")]/../a/text()')
    if result:
        result = str(result).strip(" []").replace('"', "").replace("'", "").replace(", ", ",")
    else:
        result = studio if "fc2_seller" in manager.config.fields_rule else ""
    return result


def getTag(html):  # 获取标签
    result = html.xpath('//strong[contains(text(), "影片标签")]/../a/text()')
    result = str(result).strip(" []").replace('"', "").replace("'", "").replace(", ", ",")
    return result


def getOutline(html):  # 获取简介
    result = (
        str(html.xpath('//div[@class="col des"]/text()'))
        .strip("[]")
        .replace("',", "")
        .replace("\\n", "")
        .replace("'", "")
        .replace("・", "")
        .strip()
    )
    return result


def getMosaic(html):  # 获取马赛克
    result = str(html.xpath('//h5/strong[contains(text(), "资源参数")]/../text()'))
    mosaic = "无码" if "无码" in result else "有码"
    return mosaic


def normalize_fc2_number(number: str) -> str:
    return number.upper().replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Fc2clubCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.FC2CLUB

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://fc2club.top"

    @override
    async def _run(self, ctx: Context):
        number = normalize_fc2_number(ctx.input.number)
        real_url = ctx.input.appoint_url or f"{self.base_url}/html/FC2-{number}.html"
        ctx.debug(f"番号地址: {real_url}")
        ctx.debug_info.detail_urls = [real_url]

        html_content, error = await self.async_client.get_text(real_url)
        if html_content is None:
            raise CralwerException(f"网络请求错误: {error}")
        html_info = etree.fromstring(html_content, etree.HTMLParser())

        title = getTitle(html_info, number)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")

        cover_url, extrafanart = getCover(html_info)
        tag = getTag(html_info)
        studio = getStudio(html_info)
        actor = getActor(html_info, studio)
        data = CrawlerData(
            number="FC2-" + str(number),
            title=title,
            originaltitle=title,
            actors=split_csv(actor),
            outline="",
            originalplot="",
            tags=split_csv(tag),
            release="",
            year="",
            runtime="",
            score=getScore(html_info),
            series="FC2系列",
            directors=[],
            studio=studio,
            publisher=studio,
            thumb=cover_url,
            poster="",
            extrafanart=extrafanart,
            trailer="",
            image_download=False,
            image_cut="center",
            mosaic=getMosaic(html_info),
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
