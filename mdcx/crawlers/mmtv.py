#!/usr/bin/env python3
import re
from typing import override

from lxml import etree
from parsel import Selector

from ..config.models import Website
from ..number import is_uncensored
from .base import BaseCrawler, CralwerException, CrawlerData
from .guochan import get_extra_info


def get_title(html, web_number):
    result = html.xpath('string(//h1[contains(@class, "fullvideo-title")])')
    title = re.sub(r"\s+", " ", result).strip()
    if not title:
        return ""
    if web_number:
        title = re.sub(rf"^{re.escape(web_number)}\s*", "", title, count=1, flags=re.IGNORECASE).strip()
    return title


def get_actor(html, title, file_path):
    actor_list = html.xpath('//div[@class="fullvideo-idol"]/span/a/text()')
    actor = ""
    if actor_list:
        for each in actor_list:
            """愛澄玲花,日高ゆりあ（青山ひより） 菜津子 32歳 デザイナー"""
            actor += re.sub(r"（.+）", "", each).split(" ")[0] + ","
    else:
        actor = get_extra_info(title, file_path, info_type="actor")
    return actor.strip(",")


def get_real_url(html, number):
    result = html.xpath('//figure[@class="video-preview"]/a')
    url = ""
    cap_number = number.upper()
    for each in result:
        temp_url = each.get("href")
        temp_title = each.xpath("img/@alt")
        if temp_title and temp_url:
            temp_title = temp_title[0]
            temp_number = temp_title.split(" ")[0]
            if cap_number.startswith("FC2"):
                temp_number_head = cap_number.replace("FC2-", "FC2-PPV ")
                if temp_title.upper().startswith(temp_number_head):
                    return temp_url
            elif (
                temp_number.upper().startswith(cap_number)
                or temp_number.upper().endswith(cap_number)
                and temp_number.upper().replace(cap_number, "").isdigit()
            ):
                return temp_url
    return url


def get_cover(html):
    result = re.findall(r'class="player-cover" ><a><img src="([^"]+)', html)
    if result:
        result = result[0]
        if "http" not in result:
            result = "https://7mmtv.tv" + result
    return result if result else ""


def get_outline(html):
    outline = ""
    result = html.xpath('//div[contains(@class, "video-introduction-images-text")]')
    if result:
        parts = [re.sub(r"\s+", " ", text).strip() for text in result[0].xpath(".//text()")]
        parts = [text for text in parts if text]
        if parts:
            outline = "\n".join(parts)
    return outline, outline


def get_year(release):
    result = re.search(r"\d{4}", release)
    return result[0] if result else release


def get_release(res):
    release = re.search(r"\d{4}-\d{2}-\d{2}", res)
    return release[0] if release else ""


def get_runtime(s):
    runtime = ""
    if ":" in s:
        temp_list = s.split(":")
        if len(temp_list) == 3:
            runtime = int(temp_list[0]) * 60 + int(temp_list[1])
        elif len(temp_list) <= 2:
            runtime = int(temp_list[0])
    elif "分" in s or "min" in s:
        a = re.findall(r"(\d+)(分|min)", s)
        if a:
            runtime = a[0][0]
    return str(runtime)


def get_director(html):
    director = ""
    result = html.xpath('//div[@class="col-auto flex-shrink-1 flex-grow-1"]/a[contains(@href,"director")]/text()')
    if result and result[0] != "N/A" and result[0] != "----":
        director = result[0]
    return director


def get_studio(html):
    studio = ""
    result = html.xpath('//div[@class="col-auto flex-shrink-1 flex-grow-1"]/a[contains(@href,"makersr")]/text()')
    if result and result[0] != "N/A" and result[0] != "----":
        studio = result[0]
    return studio


def get_publisher(html):
    publisher = ""
    result = html.xpath('//div[@class="col-auto flex-shrink-1 flex-grow-1"]/a[contains(@href,"issuer")]/text()')
    if result and result[0] != "N/A" and result[0] != "----":
        publisher = result[0]
    return publisher


def get_tag(html):
    result = html.xpath('//div[@class="d-flex flex-wrap categories"]/a/text()')
    return ",".join(result)


def get_extrafanart(html):
    # 前几张
    result1 = html.xpath('//span/img[contains(@class, "lazyload")]/@data-src')
    # 其他隐藏需点击的
    if result2 := html.xpath('//div[contains(@class, "fullvideo")]/script[@language="javascript"]/text()'):
        result2 = re.findall(r"https?://.+?\.jpe?g", str(result2))
    result = result1 + result2
    return result if result else ""


def get_mosaic(html, number):
    try:
        mosaic = ""
        result = html.xpath('//ol[@class="breadcrumb"]')[0].xpath("string(.)")
        if "無碼AV" in result or "國產影片" in result:
            mosaic = "无码"
        elif "有碼AV" in result or "素人AV" in result:
            mosaic = "有码"
    except Exception:
        pass
    if not mosaic:
        mosaic = "无码" if number.upper().startswith("FC2") or is_uncensored(number) else "有码"
    return mosaic


def get_number(html, number):
    result = html.xpath('//div[@class="d-flex mb-4"]/span/text()')
    number = result[0] if result else number
    release = get_release(result[1]) if len(result) >= 2 else ""
    runtime = get_runtime(result[2]) if len(result) >= 3 else ""
    return number.replace("FC2-PPV ", "FC2-"), release, runtime, number


class MmtvCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.MMTV

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.7mmtv.sx"

    @override
    async def _generate_search_url(self, ctx) -> list[str] | str | None:
        search_keyword = ctx.input.number
        if ctx.input.number.upper().startswith("FC2"):
            search_keyword = re.findall(r"\d{3,}", ctx.input.number)[0]
        return f"{self.base_url}/zh/searchform_search/all/index.html?search_keyword={search_keyword}&search_type=searchall&op=search"

    @override
    async def _parse_search_page(self, ctx, html: Selector, search_url: str) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        detail_url = get_real_url(search_page, ctx.input.number)
        if not detail_url:
            raise CralwerException("搜索结果: 未匹配到番号")
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        html_content = html.get()
        html_info = etree.fromstring(html_content, etree.HTMLParser())
        number, release, runtime, web_number = get_number(html_info, ctx.input.number)
        title = get_title(html_info, web_number)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title")

        actor = get_actor(html_info, title, str(ctx.input.file_path or ""))
        outline, originalplot = get_outline(html_info)
        extrafanart = get_extrafanart(html_info)
        if not isinstance(extrafanart, list):
            extrafanart = []
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        directors = [item.strip() for item in get_director(html_info).split(",") if item.strip()]
        tags = [item.strip() for item in get_tag(html_info).split(",") if item.strip()]
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=outline,
            originalplot=originalplot,
            tags=tags,
            release=release,
            year=get_year(release),
            runtime=runtime,
            directors=directors,
            studio=get_studio(html_info),
            publisher=get_publisher(html_info),
            thumb=get_cover(html_content),
            poster="",
            extrafanart=extrafanart,
            trailer="",
            image_download=False,
            image_cut="",
            mosaic=get_mosaic(html_info, number),
            external_id=detail_url,
        )
