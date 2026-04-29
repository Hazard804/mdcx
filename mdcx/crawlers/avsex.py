#!/usr/bin/env python3
import re
from dataclasses import dataclass
from typing import override

from lxml import etree
from parsel import Selector

from ..config.manager import manager
from ..config.models import Website
from ..models.types import CrawlerInput
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def get_web_number(html, number):
    result = html.xpath('//h2[@class]//span[@class="truncate"]/text()')
    return result[0].strip() if result else number


def get_title(html):
    result = html.xpath('//span[@class="truncate p-2 text-primary font-bold dark:text-primary-200"]/text()')
    title = result[0] if result else ""
    rep_char_list = ["[VIP会员点播] ", "[VIP會員點播] ", "[VIP] ", "★ (请到免费赠片区观赏)", "(破解版獨家中文)"]
    for rep_char in rep_char_list:
        title = title.replace(rep_char, "")
    return title.strip()


def get_actor(html):
    actor_list = html.xpath('//dd[@class="flex gap-2 flex-wrap"]/a[contains(@href, "actor")]/text()')
    new_list = [each.strip() for each in actor_list]
    return ",".join(new_list)


def get_outline(html):
    result = html.xpath('string(//h2[contains(text(), "劇情簡介")]/following-sibling::p)')
    rep_list = [
        "(中文字幕1280x720)",
        "(日本同步最新‧中文字幕1280x720)",
        "(日本同步最新‧中文字幕)",
        "(日本同步最新‧完整激薄版‧中文字幕1280x720)",
        "＊日本女優＊ 劇情做愛影片 ＊完整日本版＊",
        "＊日本女優＊ 剧情做爱影片 ＊完整日本版＊",
        "&nbsp;",
        "<br/>",
        "<p>",
        "</p>",
        '<style type="text/css"><!--td {border: 1px solid #ccc;}br {mso-data-placement:same-cell;}-->\n</style>\n',
        '<table style="border-collapse:collapse; width:54pt; border:none" width="72">\n\t<colgroup>\n\t\t<col style="width:54pt" width="72" />\n\t</colgroup>\n\t<tbody>\n\t\t<tr height="22" style="height:16.5pt">\n\t\t\t<td height="22" style="border:none; height:16.5pt; width:54pt; padding-top:1px; padding-right:1px; padding-left:1px; vertical-align:middle; white-space:nowrap" width="72"><span style="font-size:12pt"><span style="color:black"><span style="font-weight:400"><span style="font-style:normal"><span style="text-decoration:none"><span style="font-family:新細明體,serif">',
        "</span></span></span></span></span></span></td>\n\t\t</tr>\n\t</tbody>\n</table>",
        "★ (请到免费赠片区观赏)",
    ]
    for each in rep_list:
        result = result.replace(each, "").strip()
    return result


def get_studio(html):
    result = html.xpath('string(//dt[contains(text(), "製作商")]/following-sibling::dd)')
    return result.strip()


def get_runtime(html):
    runtime = ""
    result = html.xpath('string(//dt[contains(text(), "片長")]/following-sibling::dd)').strip()
    result = re.findall(r"\d+", result)
    if len(result) == 3:
        runtime = int(result[0]) * 60 + int(result[1])
    return runtime


def get_series(html):
    result = html.xpath('//span[contains(text(), "系列：")]/following-sibling::span/text()')
    return result[0].strip() if result else ""


def get_director(html):
    result = html.xpath('//span[contains(text(), "导演：")]/following-sibling::span/a/text()')
    return result[0].strip() if result else ""


def get_release(html):
    result = html.xpath('//div/dt[contains(text(), "上架日")]/../dd/text()')
    return result[0].replace("/", "-").strip() if result else ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_tag(html):
    result = html.xpath('//dt[contains(text(), "類別")]/following-sibling::dd/a/@title')
    return ",".join(result)


def get_cover(html):
    result = html.xpath('//div[@class="relative overflow-hidden rounded-md"]/img/@src')
    return result[0] if result else ""


def get_extrafanart(html):
    ex_list = html.xpath(
        '//h2[contains(text(), "精彩劇照")]/following-sibling::ul/li/div[@class="relative overflow-hidden rounded-md"]/img/@src'
    )
    return ex_list


def get_mosaic(html, studio):
    result = html.xpath('string(//h1[@class="vv_title col-12"])')
    mosaic = "无码" if "無碼" in result and "破解版" not in result else "有码"
    return "国产" if "國產" in studio else mosaic


def get_poster(html):
    result = html.xpath('//div[@class="img_box col-4 col-sm-3 col-md-3 d-lg-none"]/img/@src')
    if result:
        return "https://9sex.tv/cn" + result[0] if "http" not in result[0] else result[0]


def get_real_url(html, number):
    res_list = html.xpath("//ul[@class]/li/a")
    for each in res_list:
        temp_title = each.xpath('div/h4[contains(@class,"truncate")]/text()')
        temp_url = each.get("href")
        temp_poster = each.xpath('div[@class="relative overflow-hidden rounded-t-md"]/img/@src')
        if temp_title:
            temp_title = temp_title[0]
            if temp_title.upper().startswith(number.upper()) or (
                f"{number.upper()}-" in temp_title.upper() and temp_title[:1].isdigit()
            ):
                # https://9sex.tv/web/video?id=317900
                # https://9sex.tv/#/home/video/340496
                real_url = temp_url
                poster_url = temp_poster[0] if temp_poster else ""
                return real_url, poster_url
    return "", ""


@dataclass
class AvsexContext(Context):
    number: str = ""
    site_url: str = ""
    detail_url: str = ""
    poster_url: str = ""


class AvsexCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AVSEX

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.AVSEX, "https://gg5.co")

    @override
    def new_context(self, input: CrawlerInput) -> AvsexContext:
        number = input.number if re.match(r"n\d{4}", input.number) else input.number.upper()
        site_url = self.base_url_()
        detail_url = input.appoint_url
        if detail_url:
            if "http" in detail_url:
                site_url = re.findall(r"(.*//[^/]*)/", detail_url)[0]
            else:
                site_url = "https://" + re.findall(r"([^/]*)/", detail_url)[0]
                detail_url = "https://" + detail_url
        return AvsexContext(input=input, number=number, site_url=site_url, detail_url=detail_url)

    @override
    async def _run(self, ctx: AvsexContext):
        if ctx.detail_url:
            ctx.debug_info.detail_urls = [ctx.detail_url]
            data = await self._detail(ctx, [ctx.detail_url])
            if not data:
                raise CralwerException("获取详情页数据失败")
            data.source = self.site().value
            return await self.post_process(ctx, data.to_result())
        return await super()._run(ctx)

    @override
    async def _generate_search_url(self, ctx: AvsexContext) -> list[str] | str | None:
        return f"{ctx.site_url}/tw/search?query={ctx.number.lower()}"

    @override
    async def _parse_search_page(self, ctx: AvsexContext, html: Selector, search_url: str) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        detail_url, poster_url = get_real_url(search_page, ctx.number)
        if not detail_url:
            ctx.debug("avsex 搜索页没有匹配结果")
            return None
        ctx.poster_url = poster_url
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: AvsexContext, html: Selector, detail_url: str) -> CrawlerData | None:
        detail_page = etree.fromstring(html.get(), etree.HTMLParser())
        title = get_title(detail_page)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        number = get_web_number(detail_page, ctx.number)
        release = get_release(detail_page)
        studio = get_studio(detail_page).replace("N/A", "")
        runtime = str(get_runtime(detail_page)).replace("N/A", "")
        outline = get_outline(detail_page)
        actor = get_actor(detail_page)
        tag = get_tag(detail_page)
        external_id = re.sub(r"http[s]?://[^/]+", ctx.site_url, detail_url)
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=[item.strip() for item in actor.split(",") if item.strip()],
            all_actors=[item.strip() for item in actor.split(",") if item.strip()],
            outline=outline,
            originalplot=outline,
            tags=[item.strip() for item in tag.split(",") if item.strip()],
            release=release.replace("N/A", ""),
            year=get_year(release),
            runtime=runtime,
            score="",
            series="",
            directors=[],
            studio=studio,
            publisher="",
            thumb=get_cover(detail_page),
            poster=ctx.poster_url,
            extrafanart=get_extrafanart(detail_page),
            trailer="",
            image_download=False,
            image_cut="right",
            mosaic=get_mosaic(detail_page, studio),
            external_id=external_id,
        )
