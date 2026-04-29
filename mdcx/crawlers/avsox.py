#!/usr/bin/env python3
import re
from dataclasses import dataclass
from typing import override

from lxml import etree
from parsel import Selector

from ..base.web import get_avsox_domain
from ..config.models import Website
from ..models.types import CrawlerInput
from .base import Context, CralwerException, CrawlerData, GenericBaseCrawler


def get_actor(html):
    result = ",".join(html.xpath("//div[@id='avatar-waterfall']/a/span/text()"))
    return result


def get_web_number(html):
    result = html.xpath('//div[@class="col-md-3 info"]/p/span[@style="color:#CC0000;"]/text()')
    return result[0] if result else ""


def get_title(html):
    result = html.xpath('//div[@class="container"]/h3/text()')
    return result[0] if result else ""


def get_cover(html):
    result = html.xpath('//a[@class="bigImage"]/@href')
    return result[0] if result else ""


def get_poster(html, count):
    poster_url = html.xpath("//div[@id='waterfall']/div[" + str(count) + "]/a/div[@class='photo-frame']/img/@src")[0]
    return poster_url


def get_tag(html):
    result = html.xpath('//span[@class="genre"]/a/text()')
    return ",".join(result)


def get_release(html):
    result = html.xpath(
        '//span[contains(text(),"发行时间:") or contains(text(),"發行日期:") or contains(text(),"発売日:")]/../text()'
    )
    return result[0].strip() if result else ""


def get_year(release):
    return release[:4] if release else release


def get_runtime(html):
    result = html.xpath(
        '//span[contains(text(),"长度:") or contains(text(),"長度:") or contains(text(),"収録時間:")]/../text()'
    )
    return re.findall(r"(\d+)", result[0])[0] if result else ""


def get_series(html):
    result = html.xpath('//p/a[contains(@href,"/series/")]/text()')
    return result[0].strip() if result else ""


def get_studio(html):
    result = html.xpath('//p/a[contains(@href,"/studio/")]/text()')
    return result[0].strip() if result else ""


def get_real_url(number, html):
    page_url = ""
    url_list = html.xpath('//*[@id="waterfall"]/div/a/@href')
    i = 0
    if url_list:
        for i in range(1, len(url_list) + 1):
            number_get = str(
                html.xpath('//*[@id="waterfall"]/div[' + str(i) + ']/a/div[@class="photo-info"]/span/date[1]/text()')
            ).strip(" ['']")
            if number.upper().replace("-PPV", "") == number_get.upper().replace("-PPV", ""):
                page_url = "https:" + url_list[i - 1]
                break
    return page_url, i


@dataclass
class AvsoxContext(Context):
    search_poster: str = ""


class AvsoxCrawler(GenericBaseCrawler[AvsoxContext]):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AVSOX

    @classmethod
    @override
    def base_url_(cls) -> str:
        return ""

    @override
    def new_context(self, input: CrawlerInput) -> AvsoxContext:
        return AvsoxContext(input=input)

    @override
    async def _generate_search_url(self, ctx: AvsoxContext) -> list[str] | str | None:
        avsox_url = await get_avsox_domain()
        return f"{avsox_url}/cn/search/{ctx.input.number}"

    @override
    async def _parse_search_page(self, ctx: AvsoxContext, html: Selector, search_url: str) -> list[str] | str | None:
        html_search = etree.fromstring(html.get(), etree.HTMLParser())
        detail_url, count = get_real_url(ctx.input.number, html_search)
        if not detail_url:
            raise CralwerException("搜索结果: 未匹配到番号")
        ctx.search_poster = get_poster(html_search, count)
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: AvsoxContext, html: Selector, detail_url: str) -> CrawlerData | None:
        detail_page = etree.fromstring(html.get(), etree.HTMLParser())
        web_number = get_web_number(detail_page)
        title = get_title(detail_page).replace(web_number + " ", "").strip()
        if not title:
            raise CralwerException("数据获取失败: 未获取到title")

        actor = get_actor(detail_page)
        release = get_release(detail_page)
        studio = get_studio(detail_page)
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        tags = [item.strip() for item in get_tag(detail_page).split(",") if item.strip()]
        return CrawlerData(
            number=ctx.input.number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            tags=tags,
            release=release,
            year=get_year(release),
            runtime=get_runtime(detail_page),
            series=get_series(detail_page),
            studio=studio,
            publisher=studio,
            thumb=get_cover(detail_page),
            poster=ctx.search_poster,
            extrafanart=[],
            trailer="",
            image_download=bool(ctx.search_poster),
            image_cut="center",
            mosaic="无码",
            external_id=detail_url,
        )
