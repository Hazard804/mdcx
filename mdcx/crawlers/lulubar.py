#!/usr/bin/env python3
import re
from dataclasses import dataclass
from typing import override

from lxml import etree
from parsel import Selector

from ..config.models import Website
from ..models.types import CrawlerInput
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def get_web_number(html, number):
    result = html.xpath("//dt[contains(text(),'作品番号')]/following-sibling::dd/text()")
    return result[0].strip() if result else number


def get_title(html):
    try:
        result = html.xpath("//title/text()")[0].split("|")
        number = result[0].strip()
        title = result[1].replace(number, "").strip()
        if not title or "撸撸吧" in title:
            title = number
        return title, number
    except Exception:
        return "", ""


def get_actor(html):
    actor_list = html.xpath('//a[@title="女优"]/text()')
    actor_new_list = []
    for a in actor_list:
        if a.strip():
            actor_new_list.append(a.strip())
    return ",".join(actor_new_list) if actor_new_list else ""


def get_studio(html):
    result = html.xpath("string(//div[@class='tag_box d-flex flex-wrap p-1 col-12 mb-1']/a[@title='片商'])")
    return result.strip()


def get_extrafanart(html):
    result = html.xpath('//div[@id="stills"]/div/img/@src')
    for i in range(len(result)):
        result[i] = "https://lulubar.co" + result[i]
    return result


def get_release(html):
    result = html.xpath("//a[contains(@title,'上架日')]/@title")
    return result[0].replace("上架日", "").strip() if result else ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_mosaic(html):
    result = html.xpath('//div[@class="tag_box d-flex flex-wrap p-1 col-12 mb-1"]/a[@class="tag"]/text()')
    total = ",".join(result)
    mosaic = ""
    if "有码" in total:
        mosaic = "有码"
    elif "国产" in total:
        mosaic = "国产"
    elif "无码" in total:
        mosaic = "无码"
    return mosaic


def get_tag(html):
    result = html.xpath(
        '//div[@class="tag_box d-flex flex-wrap p-1 col-12 mb-1"]/a[@class="tag" and contains(@href,"bytagdetail")]/text()'
    )
    new_list = []
    for a in result:
        new_list.append(a.strip())
    return ",".join(new_list)


def get_cover(html):
    result = html.xpath('//a[@class="notVipAd imgBoxW position-relative d-block"]/img/@src')
    cover = result[0] if result else ""
    return f"https://lulubar.co{cover}" if cover and "http" not in cover else cover


def get_outline(html):
    a = html.xpath('//p[@class="video_container_info"]/text()')
    return a[0] if a else ""


def get_real_url(html, number):
    result = html.xpath('//a[@class="imgBoxW"]')
    for each in result:
        href = each.get("href")
        title = each.xpath("img/@alt")
        poster = each.xpath("img/@src")
        if title and title[0].startswith(number.lower()) and href:
            poster = f"https://lulubar.co{poster[0]}" if poster else ""
            return (
                "https://lulubar.co" + href,
                f"https://lulubar.co{poster}" if poster and "http" not in poster else poster,
            )
    return "", ""


@dataclass
class LulubarContext(Context):
    search_poster: str = ""


class LulubarCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.LULUBAR

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://lulubar.co"

    @override
    def new_context(self, input: CrawlerInput) -> LulubarContext:
        return LulubarContext(input=input)

    @override
    async def _generate_search_url(self, ctx: LulubarContext) -> list[str] | str | None:
        return f"{self.base_url}/video/bysearch?search={ctx.input.number}&page=1"

    @override
    async def _parse_search_page(self, ctx: LulubarContext, html: Selector, search_url: str) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        detail_url, poster = get_real_url(search_page, ctx.input.number)
        if not detail_url:
            ctx.debug("lulubar 搜索页没有匹配结果")
            return None
        ctx.search_poster = poster
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: LulubarContext, html: Selector, detail_url: str) -> CrawlerData | None:
        detail_page = etree.fromstring(html.get(), etree.HTMLParser())
        title, number = get_title(detail_page)
        if not title:
            raise CralwerException("数据获取失败: 未获取到 title！")
        actor = get_actor(detail_page)
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        tag = get_tag(detail_page)
        release = get_release(detail_page)
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=get_outline(detail_page),
            originalplot="",
            tags=[item.strip() for item in tag.split(",") if item.strip()],
            release=release,
            year=get_year(release),
            studio=get_studio(detail_page),
            thumb=get_cover(detail_page),
            poster=ctx.search_poster,
            extrafanart=get_extrafanart(detail_page),
            trailer="",
            image_download=False,
            image_cut="right",
            mosaic=get_mosaic(detail_page),
            external_id=detail_url,
        )
