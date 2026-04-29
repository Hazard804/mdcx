#!/usr/bin/env python3
import re
from typing import override

from lxml import etree
from parsel import Selector

from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData

seesaawiki_request_fail_flag = False


def get_title(html):
    result = html.xpath('//p[contains(@class, "sub_title")]/text()')
    if result:
        return result[0]
    result = html.xpath('//*[contains(@class, "Movie_Detail_title-img")]//img/@alt')
    if result:
        return result[0].strip()
    result = html.xpath("//meta[@property='og:title']/@content")
    if result:
        return result[0].split("|", 1)[0].strip()
    result = html.xpath("//title/text()")
    return result[0].split("|", 1)[0].strip() if result else ""


def get_cover(key):
    return (
        f"https://www.kin8tengoku.com/{key}/pht/1.jpg",
        f"https://smovie.kin8tengoku.com/sample_mobile_template/{key}/hls-1800k.mp4",
    )


def get_outline(html):
    result = html.xpath('normalize-space(string(//div[@id="comment"]))')
    if result.strip():
        return result.strip()
    result = html.xpath('normalize-space(string(//*[contains(@class, "Movie_Detail_memo")]))')
    if result.strip():
        return result.strip()
    result = html.xpath("//meta[@name='description']/@content")
    return result[0].strip() if result else ""


def get_actor(html):
    result = html.xpath('//div[@class="icon"]/a[contains(@href, "listpages/actor")]/text()')
    if not result:
        result = html.xpath('//a[contains(@href, "listpages/actor")]/text()')
    return ",".join(result)


def get_tag(html):
    result = html.xpath(
        '//td[@class="movie_table_td" and contains(text(), "カテゴリー")]/following-sibling::td/div/a/text()'
    )
    if not result:
        result = html.xpath('//*[contains(@class, "Movie_Detail_actor-type")]//a/text()')
    return ",".join(result)


def get_release(html):
    result = html.xpath('string(//td[@class="movie_table_td" and contains(text(), "更新日")]/following-sibling::td)')
    if result.strip():
        return result.strip()
    result = html.xpath('//*[contains(@class, "Movie_Detail_date-movie")]//span/text()')
    return result[0].replace("/", "-").strip() if result else ""


def get_year(release):
    result = re.search(r"\d{4}", release)
    return result[0] if result else release


def get_runtime(html):
    s = html.xpath('string(//td[@class="movie_table_td" and contains(text(), "再生時間")]/following-sibling::td)')
    runtime = ""
    if ":" in s:
        temp_list = s.split(":")
        if len(temp_list) == 3:
            runtime = int(temp_list[0]) * 60 + int(temp_list[1])
        elif len(temp_list) <= 2:
            runtime = int(temp_list[0])
    return str(runtime)


def get_extrafanart(html):
    result = html.xpath("//img[@class='white_gallery ']/@src")
    new_result = []
    for i in result:
        if i:
            if "http" not in i:
                i = f"https:{i}"
            new_result.append(
                i.replace("/2.jpg", "/2_lg.jpg").replace("/3.jpg", "/3_lg.jpg").replace("/4.jpg", "/4_lg.jpg")
            )
    return new_result


def get_cover_from_detail(html, key):
    cover_url, trailer = get_cover(key)
    result = html.xpath("//video/@poster")
    if result:
        cover_url = result[0]
    else:
        result = html.xpath("//meta[@property='og:image']/@content")
        if result:
            cover_url = result[0]

    result = html.xpath("//video/@src")
    if result:
        trailer = result[0]
    else:
        result = html.xpath("//meta[@property='og:video']/@content")
        if result:
            trailer = result[0]
    return cover_url, trailer


class Kin8Crawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.KIN8

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.kin8tengoku.com"

    @override
    async def _run(self, ctx: Context):
        number = ctx.input.number
        detail_url = ctx.input.appoint_url
        if detail_url:
            key = re.findall(r"\d{3,}", detail_url)
            key = key[0] if key else ""
            number = f"KIN8-{key}" if key else number
        else:
            key = re.findall(r"KIN8(TENGOKU)?-?(\d{3,})", number.upper())
            key = key[0][1] if key else ""
            if not key:
                raise CralwerException(f"番号中未识别到 KIN8 番号: {number}")
            number = f"KIN8-{key}"
            detail_url = f"{self.base_url}/moviepages/{key}/index.html"

        ctx.debug_info.detail_urls = [detail_url]
        html_content, error = await self.async_client.get_text(detail_url)
        if html_content is None:
            raise CralwerException(f"网络请求错误: {error}")

        data = await self._parse_detail_page(ctx, Selector(text=html_content), detail_url)
        if not data:
            raise CralwerException("获取详情页数据失败")
        data.number = number
        data.source = self.site().value
        return await self.post_process(ctx, data.to_result())

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        html_info = etree.fromstring(html.get(), etree.HTMLParser())
        title = get_title(html_info)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        actor = get_actor(html_info)
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        release = get_release(html_info)
        key = re.findall(r"\d{3,}", detail_url)
        cover_url, trailer = get_cover_from_detail(html_info, key[0] if key else "")
        tag = get_tag(html_info)
        tags = [item.strip() for item in tag.split(",") if item.strip()]
        outline = get_outline(html_info)
        return CrawlerData(
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=outline,
            originalplot=outline,
            tags=tags,
            release=release,
            year=get_year(release),
            runtime=get_runtime(html_info),
            studio="kin8tengoku",
            publisher="kin8tengoku",
            thumb=cover_url,
            poster=cover_url,
            extrafanart=get_extrafanart(html_info),
            trailer=trailer,
            image_download=False,
            image_cut="",
            mosaic="无码",
            external_id=detail_url,
        )
