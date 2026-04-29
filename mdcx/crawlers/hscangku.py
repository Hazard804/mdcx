#!/usr/bin/env python3
import re
from dataclasses import dataclass, field
from typing import override

from lxml import etree
from parsel import Selector

from ..config.manager import manager
from ..config.models import Website
from ..models.types import CrawlerInput
from .base import BaseCrawler, Context, CralwerException, CrawlerData
from .guochan import get_extra_info, get_number_list


def get_detail_info(
    html,
    real_url,
    number,
    file_path,
):
    href = re.split(r"[/.]", real_url)[-2]
    title_h1 = html.xpath(
        '//h3[@class="title" and not(contains(normalize-space(.), "目录")) and not(contains(normalize-space(.), "为你推荐"))]/text()'
    )
    title = title_h1[0].replace(number + " ", "").strip() if title_h1 else number
    actor = get_extra_info(title, file_path, info_type="actor")
    tag = get_extra_info(title, file_path, info_type="tag")
    cover_url = html.xpath(f'//a[@data-original and contains(@href,"{href}")]/@data-original')
    cover_url = cover_url[0] if cover_url else ""

    return number, title, actor, cover_url, tag


def get_real_url(html, number_list, hscangku_url):
    item_list = html.xpath('//a[@class="stui-vodlist__thumb lazyload"]')
    for each in item_list:
        # href="/vodplay/41998-1-1.html"
        detail_url = hscangku_url + each.get("href")
        title = each.xpath("@title")[0]
        if title and detail_url:
            for n in number_list:
                temp_n = re.sub(r"[\W_]", "", n).upper()
                temp_title = re.sub(r"[\W_]", "", title).upper()
                if temp_n in temp_title:
                    return True, n, title, detail_url
    return False, "", "", ""


@dataclass
class HscangkuContext(Context):
    number_candidates: list[str] = field(default_factory=list)
    matched_number: str = ""


class HscangkuCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.HSCANGKU

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.HSCANGKU, "http://hsck.net")

    @override
    def new_context(self, input: CrawlerInput) -> HscangkuContext:
        return HscangkuContext(input=input)

    async def _get_redirected_url(self, url: str) -> str | None:
        response, error = await self.async_client.get_text(url)
        if response is None:
            return None
        if (redirected_url := re.search(r'"(https?://.*?)"', response)) is None:
            return None
        redirected_url = redirected_url.group(1)
        response, error = await self.async_client.request("GET", f"{redirected_url}{url}&p=", allow_redirects=False)
        if response and response.redirect_url:
            return response.redirect_url
        return None

    @override
    async def _generate_search_url(self, ctx: HscangkuContext) -> list[str] | str | None:
        file_path = str(ctx.input.file_path or "")
        number_list, filename_list = get_number_list(ctx.input.number, ctx.input.appoint_number, file_path)
        ctx.number_candidates = number_list[:1] + filename_list
        base_url = await self._get_redirected_url(self.base_url)
        if not base_url:
            raise CralwerException("没有正确的 hscangku_url，无法刮削")
        return [f"{base_url}/vodsearch/-------------.html?wd={each}&submit=" for each in ctx.number_candidates]

    @override
    async def _parse_search_page(self, ctx: HscangkuContext, html: Selector, search_url: str) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        base_url = search_url.split("/vodsearch/", 1)[0]
        result, number, _title, detail_url = get_real_url(search_page, ctx.number_candidates, base_url)
        if not result:
            ctx.debug("hscangku 搜索页没有匹配结果")
            return None
        ctx.matched_number = number
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: HscangkuContext, html: Selector, detail_url: str) -> CrawlerData | None:
        detail_page = etree.fromstring(html.get(), etree.HTMLParser())
        file_path = str(ctx.input.file_path or "")
        number = ctx.matched_number or ctx.input.number
        number, title, actor, cover_url, tag = get_detail_info(detail_page, detail_url, number, file_path)
        if not title:
            raise CralwerException("数据获取失败: 未获取到标题")
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        tags = [item.strip() for item in tag.split(",") if item.strip()]
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            tags=tags,
            thumb=cover_url,
            poster="",
            extrafanart=[],
            image_download=False,
            image_cut="no",
            mosaic="国产",
            external_id=detail_url,
        )
