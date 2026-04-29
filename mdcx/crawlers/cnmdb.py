#!/usr/bin/env python3
import re
from typing import override
from urllib.parse import unquote

from lxml import etree

from ..config.models import Website
from ..models.types import CrawlerResult
from .base import BaseCrawler, CralwerException, CrawlerData
from .guochan import get_number_list


def get_detail_info(html, real_url):
    number = unquote(real_url.split("/")[-1])
    item_list = html.xpath('//ol[@class="breadcrumb"]//text()')
    new_item_list = []
    [new_item_list.append(i) for i in item_list if i.strip()]
    if new_item_list:
        title = new_item_list[-1].strip()
        studio = "麻豆" if "麻豆" in new_item_list[1] else new_item_list[-2].strip()
        title, number, actor, series = get_actor_title(title, number, studio)
        if "系列" in new_item_list[-2]:
            series = new_item_list[-2].strip()
        cover = html.xpath('//div[@class="post-image-inner"]/img/@src')
        cover = cover[0] if cover else ""
        return True, number, title, actor, real_url, cover, studio, series
    return False, "", "", "", "", "", "", ""


def get_search_info(html, number_list):
    item_list = html.xpath('//div[@class="post-item"]')
    for each in item_list:
        title = each.xpath("h3/a/text()")
        if title:
            for n in number_list:
                if n.upper() in title[0].upper():
                    number = n
                    real_url = each.xpath("h3/a/@href")
                    real_url = real_url[0] if real_url else ""
                    cover = each.xpath('div[@class="post-item-image"]/a/div/img/@src')
                    cover = cover[0] if cover else ""
                    studio_url = each.xpath("a/@href")
                    studio_url = studio_url[0] if studio_url else ""
                    studio = each.xpath("a/span/text()")
                    studio = studio[0] if studio else ""
                    if "麻豆" in studio_url:
                        studio = "麻豆"
                    title, number, actor, series = get_actor_title(title[0], number, studio)
                    return True, number, title, actor, real_url, cover, studio, series
    return False, "", "", "", "", "", "", ""


def get_actor_title(title, number, studio):
    temp_list = re.split(r"[\., ]", title.replace("/", "."))
    actor_list = []
    new_title = ""
    series = ""
    for i in range(len(temp_list)):
        if number.upper() in temp_list[i].upper():
            number = temp_list[i]
            continue
        if "系列" in temp_list[i]:
            series = temp_list[i]
            continue
        if i < 2 and ("传媒" in temp_list[i] or studio in temp_list[i]):
            continue
        if i > 2 and (
            studio == temp_list[i] or "麻豆" in temp_list[i] or "出品" in temp_list[i] or "传媒" in temp_list[i]
        ):
            break
        if i < 3 and len(temp_list[i]) <= 4 and len(actor_list) < 1:
            actor_list.append(temp_list[i])
            continue
        if len(temp_list[i]) <= 3 and len(temp_list[i]) > 1:
            actor_list.append(temp_list[i])
            continue
        new_title += "." + temp_list[i]
    title = new_title if new_title else title
    return title.strip("."), number, ",".join(actor_list), series


class CnmdbCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.CNMDB

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://cnmdb.net"

    @override
    async def _run(self, ctx) -> CrawlerResult:
        data = await self._crawl_cnmdb(ctx)
        data.source = self.site().value
        return data.to_result()

    async def _crawl_cnmdb(self, ctx) -> CrawlerData:
        file_path = str(ctx.input.file_path or "")
        if ctx.input.appoint_url:
            detail_url = ctx.input.appoint_url
            ctx.debug(f"番号地址: {detail_url}")
            ctx.debug_info.detail_urls = [detail_url]
            return await self._fetch_and_parse_detail(ctx, detail_url)

        number_list, _filename_list = get_number_list(ctx.input.number, ctx.input.appoint_number, file_path)
        detail_urls = [f"{self.base_url}/{number}" for number in number_list]
        ctx.debug_info.detail_urls = detail_urls
        for detail_url in detail_urls:
            ctx.debug(f"请求地址: {detail_url}")
            data = await self._fetch_and_parse_detail(ctx, detail_url, ignore_empty=True)
            if data:
                return data

        search_urls = []
        for each in re.split(r"[\.,，]", file_path):
            if len(each) < 5 or "传媒" in each or "麻豆" in each:
                continue
            search_urls.append(f"{self.base_url}/s0?q={each}")
        ctx.debug_info.search_urls = search_urls

        for search_url in search_urls:
            ctx.debug(f"请求地址: {search_url}")
            response, error = await self.async_client.get_text(search_url)
            if response is None:
                ctx.debug(f"搜索页请求失败: {error=}")
                continue
            search_page = etree.fromstring(response, etree.HTMLParser())
            result, number, title, actor, real_url, cover_url, studio, series = get_search_info(
                search_page, number_list
            )
            if result:
                return self._to_data(number, title, actor, real_url, cover_url, studio, series)

        raise CralwerException("没有匹配的搜索结果")

    async def _fetch_and_parse_detail(self, ctx, detail_url: str, *, ignore_empty: bool = False) -> CrawlerData | None:
        response, error = await self.async_client.get_text(detail_url)
        if response is None:
            ctx.debug(f"详情页请求失败: {error=}")
            if ignore_empty:
                return None
            raise CralwerException("没有找到数据")

        detail_page = etree.fromstring(response, etree.HTMLParser())
        result, number, title, actor, real_url, cover_url, studio, series = get_detail_info(detail_page, detail_url)
        if not result:
            if ignore_empty:
                return None
            raise CralwerException("详情页解析失败")
        return self._to_data(number, title, actor, real_url, cover_url, studio, series)

    @staticmethod
    def _to_data(
        number: str,
        title: str,
        actor: str,
        real_url: str,
        cover_url: str,
        studio: str,
        series: str,
    ) -> CrawlerData:
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            tags=[],
            series=series,
            studio=studio,
            publisher=studio,
            thumb=cover_url,
            poster="",
            extrafanart=[],
            trailer="",
            image_download=False,
            image_cut="no",
            mosaic="国产",
            external_id=real_url,
        )

    @override
    async def _generate_search_url(self, ctx) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx, html, detail_url: str) -> CrawlerData | None:
        return None
