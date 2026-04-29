#!/usr/bin/env python3
import re
from dataclasses import dataclass, field
from typing import override

import zhconv
from lxml import etree
from parsel import Selector

from ..config.models import Website
from ..models.types import CrawlerInput
from .base import BaseCrawler, Context, CralwerException, CrawlerData
from .guochan import get_extra_info, get_number_list


def get_detail_info(html, number, file_path):
    title_h1 = html.xpath('//div[@class="entry-content "]/p/text()')
    title = title_h1[0].replace(number + " ", "").strip() if title_h1 else number
    actor = get_extra_info(title, file_path, info_type="actor")
    tmp_tag = html.xpath('//header//div[@class="categories-wrap"]/a/text()')
    # 标签转简体
    tag = zhconv.convert(tmp_tag[0], "zh-cn") if tmp_tag else ""
    cover_url = html.xpath('//meta[@property="og:image"]/@content')
    cover_url = cover_url[0] if cover_url else ""

    return number, title, actor, cover_url, tag


def get_real_url(html, number_list):
    item_list = html.xpath('//h3[contains(@class,"title")]//a[@href and @title]')
    for each in item_list:
        # href="https://cableav.tv/Xq1Sg3SvZPk/"
        detail_url = each.get("href")
        title = each.xpath("text()")[0]
        if title and detail_url:
            for n in number_list:
                temp_n = re.sub(r"[\W_]", "", n).upper()
                temp_title = re.sub(r"[\W_]", "", title).upper()
                if temp_n in temp_title:
                    return True, n, title, detail_url
    return False, "", "", ""


@dataclass
class CableavContext(Context):
    number_candidates: list[str] = field(default_factory=list)
    matched_number: str = ""


class CableavCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.CABLEAV

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://cableav.tv"

    @override
    def new_context(self, input: CrawlerInput) -> CableavContext:
        return CableavContext(input=input)

    @override
    async def _generate_search_url(self, ctx: CableavContext) -> list[str] | str | None:
        file_path = str(ctx.input.file_path or "")
        number_list, filename_list = get_number_list(ctx.input.number, ctx.input.appoint_number, file_path)
        ctx.number_candidates = number_list[:1] + filename_list
        return [f"{self.base_url}/?s={each}" for each in ctx.number_candidates]

    @override
    async def _parse_search_page(self, ctx: CableavContext, html: Selector, search_url: str) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        result, number, _title, detail_url = get_real_url(search_page, ctx.number_candidates)
        if not result:
            ctx.debug("CableAV 搜索页没有匹配结果")
            return None
        ctx.matched_number = number
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: CableavContext, html: Selector, detail_url: str) -> CrawlerData | None:
        detail_page = etree.fromstring(html.get(), etree.HTMLParser())
        number = ctx.matched_number or ctx.input.number
        file_path = str(ctx.input.file_path or "")
        number, title, actor, cover_url, tag = get_detail_info(detail_page, number, file_path)
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
