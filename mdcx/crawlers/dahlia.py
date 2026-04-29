#!/usr/bin/env python3

import re
from typing import override

from lxml import etree
from parsel import Selector

from ..config.models import Website
from .base import BaseCrawler, CralwerException, CrawlerData


def get_title(html):
    result = html.xpath("//h1/text()")
    return result[0] if result else ""


def get_actor(html):
    actor_result = html.xpath(
        '//div[@class="box_works01_list clearfix"]//span[text()="出演女優"]/following-sibling::p[1]/text()'
    )
    return ",".join(actor_result)


def get_outline(html):
    result = html.xpath("//div[@class='box_works01_text']/p/text()")
    return result[0] if result else ""


def get_runtime(html):
    result = html.xpath('//span[contains(text(), "収録時間")]/following-sibling::*//text()')
    if result:
        result = re.findall(r"\d+", result[0])
    return result[0] if result else ""


def get_series(html):
    result = html.xpath('//span[contains(text(), "系列")]/following-sibling::*//text()')
    return "".join(result).strip() if result else ""


def get_director(html):
    result = html.xpath(
        '//span[contains(text(), "导演") or contains(text(), "導演") or contains(text(), "監督")]/following-sibling::*//text()'
    )
    return result[0] if result else ""


def get_publisher(html):
    result = html.xpath('//span[contains(text(), "メーカー")]/following-sibling::*//text()')
    return result[0] if result else "DAHLIA"


def get_release(html):
    result = html.xpath('//div[@class="view_timer"]//span[text()="配信開始日"]/following-sibling::p[1]/text()')
    return result[0].replace("/", "-") if result else ""


def get_year(release):
    result = re.findall(r"\d{4}", release)
    return result[0] if result else ""


def get_tag(html):
    result = html.xpath('//a[@class="genre"]//text()')
    tag = ""
    for each in result:
        tag += each.strip().replace("，", "") + ","
    return tag.strip(",")


def get_cover(html):
    result = html.xpath("//a[@class='pop_sample']/img/@src")
    return result[0].replace("?output-quality=60", "") if result else ""


def get_extrafanart(html):  # 获取封面链接
    extrafanart_list = html.xpath("//a[@class='pop_img']/@href")
    return extrafanart_list


def get_trailer(html):  # 获取预览片
    result = html.xpath("//a[@class='pop_sample']/@href")
    return result[0] if result else ""


class DahliaCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.DAHLIA

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://dahlia-av.jp"

    @override
    async def _generate_search_url(self, ctx) -> list[str] | str | None:
        number = ctx.input.number.lower().replace("-", "")
        return f"{self.base_url}/works/{number}/"

    @override
    async def _parse_search_page(self, ctx, html: Selector, search_url: str) -> list[str] | str | None:
        return [search_url]

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        html_detail = etree.fromstring(html.get(), etree.HTMLParser())
        title = get_title(html_detail)
        if not title:
            raise CralwerException("数据获取失败: 番号标题不存在")

        actor = get_actor(html_detail)
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        for each in actors:
            title = title.replace(" " + each, "")

        cover_url = get_cover(html_detail)
        poster_url = (
            cover_url.replace("_web_h4", "_h1").replace("_1200.jpg", "_2125.jpg").replace("_tsp.jpg", "_actor.jpg")
        )
        release = get_release(html_detail)
        directors = [item.strip() for item in get_director(html_detail).split(",") if item.strip()]
        studio = get_publisher(html_detail)
        return CrawlerData(
            number=ctx.input.number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=get_outline(html_detail),
            originalplot=get_outline(html_detail),
            tags=[],
            release=release,
            year=get_year(release),
            runtime=get_runtime(html_detail),
            series=get_series(html_detail),
            directors=directors,
            studio=studio,
            publisher=studio,
            thumb=cover_url,
            poster=poster_url,
            extrafanart=get_extrafanart(html_detail),
            trailer=get_trailer(html_detail),
            image_download=True,
            image_cut="right",
            mosaic="有码",
            external_id=detail_url,
        )
