#!/usr/bin/env python3
import re
from typing import override

from lxml import etree

from ..config.enums import Website
from ..config.manager import manager
from ..number import get_number_letters
from .base import BaseCrawler, Context, CralwerException, CrawlerData
from .prestige import PrestigeCrawler

DIRECTOR_PLACEHOLDER_CHARS = frozenset("-—－ー―‐~～·•. ")


def get_title(html):
    result = html.xpath('//h2[@class="p-workPage__title"]/text()')
    return result[0].strip() if result else ""


def get_actor(html):
    actor_list = html.xpath(
        '//a[@class="c-tag c-main-bg-hover c-main-font c-main-bd" and contains(@href, "/actress/")]/text()'
    )
    return ",".join(each.strip() for each in actor_list)


def get_outline(html):
    return html.xpath('string(//p[@class="p-workPage__text"])')


def get_studio(html):
    result = html.xpath('string(//div[contains(text(), "製作商")]/following-sibling::div)')
    return result.strip()


def get_runtime(html):
    result = html.xpath('//div[@class="th" and text()="収録時間"]/following-sibling::div/div/p/text()')
    return result[0].replace("分", "").strip() if result else ""


def get_series(html):
    result = html.xpath('//div[@class="th" and contains(text(), "シリーズ")]/following-sibling::div/a/text()')
    return result[0].strip() if result else ""


def get_publisher(html):
    publisher = ""
    studio = ""
    result_1 = html.xpath('//meta[@name="description"]/@content')
    if result_1:
        result_2 = re.findall(r"【公式】([^(]+)\(([^\)]+)", result_1[0])
        publisher, studio = result_2[0] if result_2 else ("", "")
    result = html.xpath('//div[@class="th" and contains(text(), "レーベル")]/following-sibling::div/a/text()')
    publisher = result[0].strip() if result else publisher
    return publisher.replace("　", " "), studio


def get_director(html):
    result = html.xpath('//div[@class="th" and contains(text(), "監督")]/following-sibling::div/div/p/text()')
    if not result:
        return ""
    director = result[0].strip()
    if not director or director == "N/A" or all(char in DIRECTOR_PLACEHOLDER_CHARS for char in director):
        return ""
    return director


def get_trailer(html):
    result = html.xpath('//div[@class="video"]/video/@src')
    return result[0] if result else ""


def get_release(html):
    result = html.xpath('//div[contains(text(), "発売日")]/following-sibling::div/div/a/text()')
    return result[0].replace("年", "-").replace("月", "-").replace("日", "") if result else ""


def get_year(release):
    if r := re.search(r"\d{4}", release):
        return r.group()
    return release


def get_tag(html):
    result = html.xpath('//div[contains(text(), "ジャンル")]/following-sibling::div/div/a/text()')
    return ",".join(result).replace(",Blu-ray（ブルーレイ）", "")


def get_real_url(html, number):
    result = html.xpath('//a[@class="img hover"]')
    for each in result:
        href = each.get("href")
        poster = each.xpath("img/@data-src")[0]
        if href.upper().endswith(number.upper().replace("-", "")):
            return href, poster
    return "", ""


def get_cover(html):
    result = html.xpath('//img[@class="swiper-lazy"]/@data-src')
    return (result.pop(0), result) if result else ("", [])


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class OfficialCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.OFFICIAL

    @classmethod
    @override
    def base_url_(cls) -> str:
        return ""

    @override
    async def _run(self, ctx: Context):
        number = ctx.input.number
        official_url = manager.computed.official_websites.get(get_number_letters(number))
        if not official_url:
            raise CralwerException("不在官网番号前缀列表中")
        if official_url == "https://www.prestige-av.com":
            return await PrestigeCrawler(client=self.async_client, base_url=official_url)._run(ctx)

        website_name = official_url.split(".")[-2].replace("https://", "")
        real_url = ctx.input.appoint_url
        poster = ""

        if not real_url:
            search_url = official_url + "/search/list?keyword=" + number.replace("-", "")
            ctx.debug(f"搜索地址: {search_url}")
            ctx.debug_info.search_urls = [search_url]
            html_search, error = await self.async_client.get_text(search_url)
            if html_search is None:
                raise CralwerException(f"网络请求错误: {error}")

            html = etree.fromstring(html_search, etree.HTMLParser())
            real_url, poster = get_real_url(html, number)
            if not real_url:
                raise CralwerException("搜索结果: 未匹配到番号！")

        ctx.debug(f"番号地址: {real_url}")
        ctx.debug_info.detail_urls = [real_url]
        html_content, error = await self.async_client.get_text(real_url)
        if html_content is None:
            raise CralwerException(f"网络请求错误: {error}")

        html_info = etree.fromstring(html_content, etree.HTMLParser())
        title = get_title(html_info)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        cover_url, extrafanart = get_cover(html_info)
        outline = get_outline(html_info)
        actor = get_actor(html_info)
        release = get_release(html_info)
        publisher, studio = get_publisher(html_info)
        if not studio:
            studio = get_studio(html_info)
        data = CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=split_csv(actor),
            outline=outline,
            originalplot=outline,
            tags=split_csv(get_tag(html_info)),
            release=release,
            year=get_year(release),
            runtime=get_runtime(html_info),
            score="",
            series=get_series(html_info),
            directors=split_csv(get_director(html_info)),
            studio=studio,
            publisher=publisher,
            thumb=cover_url,
            poster=poster,
            extrafanart=extrafanart,
            trailer=get_trailer(html_info),
            image_download="VR" in number.upper(),
            image_cut="",
            mosaic="有码",
            external_id=real_url,
            wanted="",
            source=website_name,
        )
        result = data.to_result()
        result.source = website_name
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
