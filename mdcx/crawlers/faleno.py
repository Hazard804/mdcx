#!/usr/bin/env python3

import re
from dataclasses import dataclass, field
from typing import override
from urllib.parse import urljoin

from parsel import Selector

from ..config.models import Website
from ..models.types import CrawlerInput
from .base import (
    Context,
    CralwerException,
    CrawlerData,
    DetailPageParser,
    GenericBaseCrawler,
    extract_all_texts,
    extract_text,
)


@dataclass
class FalenoContext(Context):
    search_posters: dict[str, str] = field(default_factory=dict)


def get_detail_value(html, *labels):
    for label in labels:
        result = html.xpath(
            f'//div[contains(@class, "box_works01_list")]//li[contains(@class, "clearfix")][span[normalize-space()="{label}"]]/p//text()'
        )
        text = "".join(part.strip() for part in result if part.strip())
        if text:
            return text
    return ""


def normalize_date(date_text):
    if not date_text:
        return ""
    if match := re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", date_text):
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return date_text.replace("/", "-").strip()


def get_timer_date(html, keyword):
    for timer in html.xpath('//div[contains(@class, "view_timer")]'):
        text = "".join(part.strip() for part in timer.xpath(".//text()") if part.strip())
        if keyword in text and (match := re.search(r"(\d{4}/\d{1,2}/\d{1,2})", text)):
            return normalize_date(match.group(1))
    return ""


def get_title(html):
    result = html.xpath("//h1/text()")
    return result[0] if result else ""


def get_actor(html):
    return get_detail_value(html, "出演女優")


def get_outline(html):
    return html.xpath("string(//div[@class='box_works01_text']/p)")


def get_runtime(html):
    result = re.findall(r"\d+", get_detail_value(html, "収録時間"))
    return result[0] if result else ""


def get_series(html):
    return get_detail_value(html, "系列", "シリーズ")


def get_director(html):
    return get_detail_value(html, "导演", "導演", "監督")


def get_publisher(html):
    result = get_detail_value(html, "メーカー", "レーベル")
    return result if result else "FALENO"


def get_release(html):
    release = get_detail_value(html, "発売日")
    if release:
        return normalize_date(release)

    # 部分旧页面没有详情列表日期，保留按钮区日期作为兜底。
    release = get_timer_date(html, "発売")
    if release:
        return release

    release = get_detail_value(html, "配信日", "配信開始日")
    if release:
        return normalize_date(release)

    return get_timer_date(html, "配信")


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


def get_real_url(html):
    href_result = html.xpath('//div[@class="text_name"]/a/@href')
    poster_result = html.xpath('//div[@class="text_name"]/../a/img/@src')
    if href_result and poster_result:
        return href_result[0], poster_result[0]
    return "", ""


class FalenoParser(DetailPageParser[FalenoContext]):
    @staticmethod
    def _detail_value(html: Selector, *labels: str) -> str:
        for label in labels:
            result = html.xpath(
                f'//div[contains(@class, "box_works01_list")]//li[contains(@class, "clearfix")][span[normalize-space()="{label}"]]/p//text()'
            ).getall()
            text = "".join(part.strip() for part in result if part.strip())
            if text:
                return text
        return ""

    @staticmethod
    def _timer_date(html: Selector, keyword: str) -> str:
        for timer in html.xpath('//div[contains(@class, "view_timer")]'):
            text = "".join(part.strip() for part in timer.xpath(".//text()").getall() if part.strip())
            if keyword in text and (match := re.search(r"(\d{4}/\d{1,2}/\d{1,2})", text)):
                return normalize_date(match.group(1))
        return ""

    @staticmethod
    def _split_csv(value: str) -> list[str]:
        return [item.strip() for item in re.split(r"[,，、/／]", value) if item.strip()]

    async def number(self, ctx: FalenoContext, html: Selector) -> str:
        return ctx.input.number

    async def title(self, ctx: FalenoContext, html: Selector) -> str:
        title = extract_text(html, "normalize-space(//h1)")
        for actor in await self.actors(ctx, html):
            title = title.replace(" " + actor, "")
        return title

    async def originaltitle(self, ctx: FalenoContext, html: Selector) -> str:
        return await self.title(ctx, html)

    async def actors(self, ctx: FalenoContext, html: Selector) -> list[str]:
        return self._split_csv(self._detail_value(html, "出演女優"))

    async def all_actors(self, ctx: FalenoContext, html: Selector) -> list[str]:
        return await self.actors(ctx, html)

    async def outline(self, ctx: FalenoContext, html: Selector) -> str:
        return extract_text(html, "string(//div[@class='box_works01_text']/p)")

    async def originalplot(self, ctx: FalenoContext, html: Selector) -> str:
        return await self.outline(ctx, html)

    async def release(self, ctx: FalenoContext, html: Selector) -> str:
        release = self._detail_value(html, "発売日")
        if release:
            return normalize_date(release)

        release = self._timer_date(html, "発売")
        if release:
            return release

        release = self._detail_value(html, "配信日", "配信開始日")
        if release:
            return normalize_date(release)

        return self._timer_date(html, "配信")

    async def year(self, ctx: FalenoContext, html: Selector) -> str:
        release = await self.release(ctx, html)
        result = re.findall(r"\d{4}", release)
        return result[0] if result else ""

    async def runtime(self, ctx: FalenoContext, html: Selector) -> str:
        result = re.findall(r"\d+", self._detail_value(html, "収録時間"))
        return result[0] if result else ""

    async def series(self, ctx: FalenoContext, html: Selector) -> str:
        return self._detail_value(html, "系列", "シリーズ")

    async def directors(self, ctx: FalenoContext, html: Selector) -> list[str]:
        return self._split_csv(self._detail_value(html, "导演", "導演", "監督"))

    async def studio(self, ctx: FalenoContext, html: Selector) -> str:
        return self._detail_value(html, "メーカー", "レーベル") or "FALENO"

    async def publisher(self, ctx: FalenoContext, html: Selector) -> str:
        return await self.studio(ctx, html)

    async def tags(self, ctx: FalenoContext, html: Selector) -> list[str]:
        return [tag.strip().replace("，", "") for tag in extract_all_texts(html, '//a[@class="genre"]//text()')]

    async def thumb(self, ctx: FalenoContext, html: Selector) -> str:
        return extract_text(html, "//a[@class='pop_sample']/img/@src").replace("?output-quality=60", "")

    async def poster(self, ctx: FalenoContext, html: Selector) -> str:
        thumb = await self.thumb(ctx, html)
        return (
            thumb.replace("_1200.jpg", "_2125.jpg")
            .replace("_tsp.jpg", "_actor.jpg")
            .replace("1200_re", "2125")
            .replace("_1200-1", "_2125-1")
        )

    async def extrafanart(self, ctx: FalenoContext, html: Selector) -> list[str]:
        return extract_all_texts(html, "//a[@class='pop_img']/@href")

    async def trailer(self, ctx: FalenoContext, html: Selector) -> str:
        return extract_text(html, "//a[@class='pop_sample']/@href")

    async def image_download(self, ctx: FalenoContext, html: Selector) -> bool:
        return True

    async def image_cut(self, ctx: FalenoContext, html: Selector) -> str:
        return "right"

    async def mosaic(self, ctx: FalenoContext, html: Selector) -> str:
        return "有码"


class FalenoCrawler(GenericBaseCrawler[FalenoContext]):
    parser = FalenoParser()

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.FALENO

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://faleno.jp"

    @override
    def new_context(self, input: CrawlerInput) -> FalenoContext:
        return FalenoContext(input=input)

    @override
    async def _generate_search_url(self, ctx: FalenoContext) -> list[str] | str | None:
        number_lo = ctx.input.number.lower()
        number_lo_noline = number_lo.replace("-", "")
        number_lo_space = number_lo.replace("-", " ")
        if ctx.input.number.upper().startswith("FLN"):
            return [
                f"https://faleno.jp/top/works/{number_lo_noline}/",
                f"https://faleno.jp/top/works/{number_lo}/",
                f"https://falenogroup.com/works/{number_lo}/",
                f"https://falenogroup.com/works/{number_lo_noline}/",
            ]
        return [
            f"https://faleno.jp/top/?s={number_lo_space}",
            f"https://falenogroup.com/top/?s={number_lo_space}",
        ]

    @staticmethod
    def _is_detail_url(url: str) -> bool:
        return "/works/" in url

    @override
    async def _parse_search_page(self, ctx: FalenoContext, html: Selector, search_url: str) -> list[str] | str | None:
        if self._is_detail_url(search_url):
            return [search_url]

        href = extract_text(html, '//div[@class="text_name"]/a/@href')
        poster = extract_text(html, '//div[@class="text_name"]/../a/img/@src')
        if not href:
            ctx.debug("Faleno 搜索页未找到结果")
            return None

        detail_url = urljoin(search_url, href)
        if poster:
            ctx.search_posters[detail_url] = urljoin(search_url, poster)
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: FalenoContext, html: Selector, detail_url: str) -> CrawlerData | None:
        data = await self.parser.parse(ctx, html, external_id=detail_url)
        if not data.title:
            raise CralwerException("数据获取失败: 番号标题不存在")
        if search_poster := ctx.search_posters.get(detail_url):
            data.poster = search_poster
        return data
