#!/usr/bin/env python3
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import override
from urllib.parse import urlsplit, urlunsplit

from lxml import etree
from parsel import Selector

from ..config.models import Website
from ..models.types import CrawlerInput
from .base import BaseCrawler, Context, CralwerException, CrawlerData
from .guochan import get_extra_info, get_number_list


def normalize_cover_url(cover_url: str) -> str:
    cover_url = (cover_url or "").strip()
    if not cover_url:
        return ""

    if cover_url.startswith("//"):
        cover_url = "https:" + cover_url
    elif cover_url.startswith("/"):
        cover_url = "https://madouqu.com" + cover_url

    if "/wp-content/uploads/" not in cover_url:
        return cover_url

    parsed = urlsplit(cover_url)
    if not parsed.netloc:
        return cover_url

    if parsed.netloc == "i0.wp.com" and parsed.path.startswith("/madouqu.com/wp-content/uploads/"):
        return cover_url

    uploads_path = parsed.path[parsed.path.index("/wp-content/uploads/") :]

    # madouqu 详情页会混入旧镜像域名，统一回站点当前可访问的 WordPress CDN 地址。
    if parsed.netloc == "i0.wp.com":
        return urlunsplit((parsed.scheme or "https", "i0.wp.com", "/madouqu.com" + uploads_path, parsed.query, ""))

    return urlunsplit(("https", "madouqu.com", uploads_path, "", ""))


def get_detail_info(html, number, file_path):
    detail_info = html.xpath('//div[@class="entry-content u-text-format u-clearfix"]//p//text()')
    # detail_info = html.xpath('//div[@class="entry-content u-text-format u-clearfix"]//text()')
    title_h1 = html.xpath('//div[@class="cao_entry_header"]/header/h1/text()')
    title = title_h1[0].replace(number, "").strip() if title_h1 else number
    actor = ""
    number = ""
    for i, t in enumerate(detail_info):
        if re.search(r"番号|番號", t):
            temp_number = re.findall(r"(?:番号|番號)\s*：\s*(.+)\s*", t)
            number = temp_number[0] if temp_number else ""
        if "片名" in t:
            temp_title = re.findall(r"片名\s*：\s*(.+)\s*", t)
            title = temp_title[0] if temp_title else title.replace(number, "").strip()
        if t.endswith("女郎") and i + 1 < len(detail_info) and detail_info[i + 1].startswith("："):
            temp_actor = re.findall(r"：\s*(.+)\s*", detail_info[i + 1])
            actor = temp_actor[0].replace("、", ",") if temp_actor else ""
    number = number if number else title

    studio = html.xpath('string(//span[@class="meta-category"])').strip()
    cover_url = html.xpath('//div[@class="entry-content u-text-format u-clearfix"]/p/img/@src')
    cover_url = cover_url[0] if cover_url else ""
    cover_url = normalize_cover_url(cover_url)
    actor = get_extra_info(title, file_path, info_type="actor") if actor == "" else actor
    # 处理发行时间，年份
    try:
        date_list = html.xpath("//time[@datetime]/@datetime")
        date_obj = datetime.strptime(date_list[0], "%Y-%m-%dT%H:%M:%S%z")
        release = date_obj.strftime("%Y-%m-%d")
        # 该字段应为字符串，nfo_title 替换该字段时 replace 函数第二个参数仅接受字符串参数
        year = str(date_obj.year)
    except Exception:
        release = ""
        year = ""
    return number, title, actor, cover_url, studio, release, year


def get_real_url(html, number_list):
    item_list = html.xpath('//div[@class="entry-media"]/div/a')
    for each in item_list:
        detail_url = each.get("href")
        # lazyload属性容易改变，去掉也能拿到结果
        title = each.xpath("img[@class]/@alt")[0]
        cover_url = each.xpath(".//img/@data-src")
        if not cover_url:
            cover_url = each.xpath(".//img/@src")
        cover_url = normalize_cover_url(cover_url[0] if cover_url else "")
        if title and detail_url:
            for n in number_list:
                temp_n = re.sub(r"[\W_]", "", n).upper()
                temp_title = re.sub(r"[\W_]", "", title).upper()
                if temp_n in temp_title:
                    return True, n, title, detail_url, cover_url
    return False, "", "", "", ""


@dataclass
class MadouquContext(Context):
    number_candidates: list[str] = field(default_factory=list)
    matched_number: str = ""
    search_cover_url: str = ""


class MadouquCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.MADOUQU

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://madouqu.com"

    @override
    def new_context(self, input: CrawlerInput) -> MadouquContext:
        return MadouquContext(input=input)

    @override
    async def _generate_search_url(self, ctx: MadouquContext) -> list[str] | str | None:
        file_path = str(ctx.input.file_path or "")
        number_list, filename_list = get_number_list(ctx.input.number, ctx.input.appoint_number, file_path)
        ctx.number_candidates = number_list[:1] + filename_list
        return [f"{self.base_url}/?s={each}" for each in ctx.number_candidates]

    @override
    async def _parse_search_page(self, ctx: MadouquContext, html: Selector, search_url: str) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        result, number, _title, detail_url, cover_url = get_real_url(search_page, ctx.number_candidates)
        if not result:
            ctx.debug("Madouqu 搜索页没有匹配结果")
            return None
        ctx.matched_number = number
        ctx.search_cover_url = cover_url
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: MadouquContext, html: Selector, detail_url: str) -> CrawlerData | None:
        detail_page = etree.fromstring(html.get(), etree.HTMLParser())
        file_path = str(ctx.input.file_path or "")
        number = ctx.matched_number or ctx.input.number
        number, title, actor, detail_cover_url, studio, release, year = get_detail_info(detail_page, number, file_path)
        if not title:
            raise CralwerException("数据获取失败: 未获取到标题")
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            release=release,
            year=year,
            studio=studio,
            publisher=studio,
            thumb=detail_cover_url or ctx.search_cover_url,
            poster="",
            extrafanart=[],
            image_download=False,
            image_cut="no",
            mosaic="国产",
            external_id=detail_url,
        )
