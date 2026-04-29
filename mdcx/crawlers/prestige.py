#!/usr/bin/env python3
import re
from typing import override

from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def get_actor(page_data):
    actor_new_list = []
    for each in page_data["actress"]:
        actor_new_list.append(each["name"].replace(" ", ""))
    return actor_new_list


def get_extrafanart(page_data):
    result = []
    for each in page_data["media"]:
        result.append("https://www.prestige-av.com/api/media/" + each["path"])
    return result


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_tag(page_data):
    new_list = []
    for each in page_data["genre"]:
        new_list.append(each["name"])
    return new_list


def get_real_url(html_search, number):
    result = html_search["hits"]["hits"]
    for each in result:
        productUuid = each["_source"]["productUuid"]
        deliveryItemId = each["_source"]["deliveryItemId"]
        if deliveryItemId.endswith(number.upper()):
            return "https://www.prestige-av.com/api/product/" + productUuid
    return ""


def get_media_path(page_data, key):
    try:
        path = page_data[key]["path"]
        if path:
            media_url = "https://www.prestige-av.com/api/media/" + path
            return "" if "noimage" in media_url else media_url
    except Exception:
        return ""
    return ""


class PrestigeCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.PRESTIGE

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.prestige-av.com"

    @override
    async def _run(self, ctx: Context):
        real_url = ctx.input.appoint_url.replace("goods", "api/product")
        if not real_url:
            search_url = (
                f"{self.base_url}/api/search?isEnabledQuery=true&searchText={ctx.input.number}"
                "&isEnableAggregation=false&release=false&reservation=false&soldOut=false"
                "&from=0&aggregationTermsSize=0&size=20"
            )
            ctx.debug(f"搜索地址: {search_url}")
            ctx.debug_info.search_urls = [search_url]
            html_search, error = await self.async_client.get_json(search_url)
            if html_search is None:
                raise CralwerException(f"网络请求错误: {error}")
            real_url = get_real_url(html_search, ctx.input.number)
            if not real_url:
                raise CralwerException("搜索结果: 未匹配到番号！")

        detail_url = real_url.replace("api/product", "goods")
        ctx.debug(f"番号地址: {detail_url}")
        ctx.debug_info.detail_urls = [detail_url]
        page_data, error = await self.async_client.get_json(real_url)
        if page_data is None:
            raise CralwerException(f"网络请求错误: {error}")

        title = page_data["title"].replace("【配信専用】", "")
        if not title:
            raise CralwerException("数据获取失败: 未获取到 title！")
        release = ""
        try:
            release = page_data["sku"][0]["salesStartAt"][:10]
        except Exception:
            pass
        try:
            director = page_data["directors"][0]["name"]
        except Exception:
            director = ""
        try:
            series = page_data["series"]["name"]
        except Exception:
            series = ""
        try:
            studio = page_data["maker"]["name"]
        except Exception:
            studio = ""
        try:
            publisher = page_data["label"]["name"]
        except Exception:
            publisher = ""
        try:
            trailer = "https://www.prestige-av.com/api/media/" + page_data["movie"]["path"]
        except Exception:
            trailer = ""

        data = CrawlerData(
            number=ctx.input.number,
            title=title,
            originaltitle=title,
            actors=get_actor(page_data),
            outline=page_data["body"],
            originalplot=page_data["body"],
            tags=get_tag(page_data),
            release=release,
            year=get_year(release),
            runtime=str(page_data["playTime"]),
            score="",
            series=series,
            directors=[director] if director else [],
            studio=studio,
            publisher=publisher,
            thumb=get_media_path(page_data, "packageImage"),
            poster=get_media_path(page_data, "thumbnail"),
            extrafanart=get_extrafanart(page_data),
            trailer=trailer,
            image_download=True,
            image_cut="right",
            mosaic="有码",
            external_id=detail_url,
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
