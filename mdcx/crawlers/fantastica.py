#!/usr/bin/env python3
import re
from dataclasses import dataclass
from typing import override

from lxml import etree
from parsel import Selector

from ..base.web import get_imgsize
from ..config.models import Website
from ..models.types import CrawlerInput
from .base import Context, CralwerException, CrawlerData, GenericBaseCrawler


def get_web_number(html, number):
    result = html.xpath("//dt[contains(text(),'作品番号')]/following-sibling::dd/text()")
    return result[0].strip() if result else number


def get_title(html):
    result = html.xpath('//div[@class="title-area"]/h2/text()')
    return result[0] if result else ""


def get_actor(html):
    result = html.xpath("//th[contains(text(),'出演者')]/following-sibling::td//text()")
    actor_new_list = []
    for a in result:
        if a.strip():
            actor_new_list.append(a.strip())
    return ",".join(actor_new_list) if actor_new_list else ""


def get_extrafanart(html):
    return html.xpath('//div[@class="vr_images clearfix"]/div[@class="vr_image"]/a/@href')


def get_release(html):
    result = html.xpath("//th[contains(text(),'発売日')]/following-sibling::td//text()")
    return result[0].replace("年", "-").replace("月", "-").replace("日", "").strip() if result else ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_runtime(html):
    result = html.xpath("//th[contains(text(),'収録時間')]/following-sibling::td//text()")
    return result[0].replace("分", "").strip() if result else ""


def get_tag(html):
    result = html.xpath("//th[contains(text(),'ジャンル')]/following-sibling::td/a/text()")
    new_list = []
    for a in result:
        new_list.append(a.strip())
    return ",".join(new_list)


def get_series(html):
    result = html.xpath("//th[contains(text(),'シリーズ')]/following-sibling::td//text()")
    return result[0].strip() if result else ""


def get_cover(html):
    result = html.xpath('//div[@class="vr_wrapper clearfix"]/div[@class="img"]/img/@src')
    cover = result[0] if result else ""
    if cover == "https://assets.fantastica-vr.com/assets/common/img/dummy_large_white.jpg":
        cover = ""
    return cover


def get_outline(html):
    return html.xpath('string(//p[@class="explain"])')


def get_real_url(html, number):
    result = html.xpath('//section[@class="item_search item_list clearfix"]/div/ul/li/a')
    for each in result:
        href = each.get("href")
        poster = each.xpath("img/@src")
        if number.lower().replace("-", "") in href.lower().replace("-", ""):
            poster = poster[0] if poster else ""
            if poster == "https://assets.fantastica-vr.com/assets/common/img/dummy_white.jpg":
                poster = ""
            real_url = "http://fantastica-vr.com" + href if "http" not in href else href
            return real_url, poster
    return "", ""


@dataclass
class FantasticaContext(Context):
    search_poster: str = ""


class FantasticaCrawler(GenericBaseCrawler[FantasticaContext]):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.FANTASTICA

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "http://fantastica-vr.com"

    @override
    def new_context(self, input: CrawlerInput) -> FantasticaContext:
        return FantasticaContext(input=input)

    @override
    async def _generate_search_url(self, ctx: FantasticaContext) -> list[str] | str | None:
        return f"{self.base_url}/items/search?q={ctx.input.number}"

    @override
    async def _parse_search_page(
        self, ctx: FantasticaContext, html: Selector, search_url: str
    ) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        detail_url, poster = get_real_url(search_page, ctx.input.number)
        if not detail_url:
            raise CralwerException("搜索结果: 未匹配到番号")
        ctx.search_poster = poster
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: FantasticaContext, html: Selector, detail_url: str) -> CrawlerData | None:
        html_info = etree.fromstring(html.get(), etree.HTMLParser())
        title = get_title(html_info)
        if not title:
            raise CralwerException("数据获取失败: 未获取到 title")

        actor = get_actor(html_info)
        release = get_release(html_info)
        extrafanart = get_extrafanart(html_info)
        poster = ctx.search_poster
        image_download = bool(poster)
        if not poster and extrafanart:
            w, h = await get_imgsize(extrafanart[0])
            if w > h:
                poster = extrafanart[0]
                image_download = True

        actors = [item.strip() for item in actor.split(",") if item.strip()]
        tags = [item.strip() for item in get_tag(html_info).split(",") if item.strip()]
        return CrawlerData(
            number=ctx.input.number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=get_outline(html_info),
            originalplot=get_outline(html_info),
            tags=tags,
            release=release,
            year=get_year(release),
            runtime=get_runtime(html_info),
            series=get_series(html_info),
            studio="ファンタスティカ",
            publisher="ファンタスティカ",
            thumb=get_cover(html_info),
            poster=poster,
            extrafanart=extrafanart,
            trailer="",
            image_download=image_download,
            image_cut="right",
            mosaic="有码",
            external_id=detail_url,
        )
