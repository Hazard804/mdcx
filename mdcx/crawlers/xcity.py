#!/usr/bin/python
import re
from typing import override

from lxml import etree
from parsel import Selector

from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def getTitle(html):
    result = html.xpath('//span[@id="program_detail_title"]/text()')
    result = result[0] if result else ""
    return result


def getWebNumber(html, number):
    result = html.xpath('//span[@id="hinban"]/text()')
    return result[0] if result else number


def getActor(html):
    try:
        result = str(html.xpath('//li[@class="credit-links"]/a/text()')).strip("['']").replace("'", "")
    except Exception:
        result = ""
    return result


def getCover(html):
    result = html.xpath('//div[@class="photo"]/p/a/@href')
    result = "https:" + result[0] if result else ""
    return result


def getOutline(html):
    result = html.xpath('//p[@class="lead"]/text()')
    result = result[0].strip().replace('"', "") if result else ""
    return result


def getRelease(html):
    result = html.xpath('//li/span[@class="koumoku" and (contains(text(), "発売日"))]/../text()')
    result = re.findall(r"[\d]+/[\d]+/[\d]+", str(result))
    result = result[0].replace("/", "-") if result else ""
    return result


def getYear(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release[:4]


def getTag(html):
    result = html.xpath('//a[@class="genre"]/text()')
    if result:
        result = str(result).strip(" ['']").replace("'", "").replace(", ", ",").replace("\\n", "").replace("\\t", "")
    else:
        result = ""
    return result


def getStudio(html):
    result = html.xpath('//span[@id="program_detail_maker_name"]/text()')
    result = result[0].strip() if result else ""
    return result


def getPublisher(html):
    result = html.xpath('//span[@id="program_detail_label_name"]/text()')
    result = result[0].strip() if result else ""
    return result


def getRuntime(html):
    result = str(html.xpath('//span[@class="koumoku"][contains(text(), "収録時間")]/../text()'))
    result = re.findall(r"[\d]+", result)
    result = result[0].strip() if result else ""
    return result


def getDirector(html):
    result = html.xpath('//span[@id="program_detail_director"]/text()')
    result = result[0].replace("\\n", "").replace("\\t", "").strip() if result else ""
    return result


def getExtrafanart(html):
    result = html.xpath('//a[contains(@class, "thumb")]/@href')
    if result:
        result = (
            str(result)
            .replace("//faws.xcity.jp/scene/small/", "https://faws.xcity.jp/")
            .strip(" []")
            .replace("'", "")
            .replace(", ", ",")
        )
        result = result.split(",")
    else:
        result = ""
    return result


def getCoverSmall(html):
    result = html.xpath('//img[@class="packageThumb"]/@src')
    result = "https:" + result[0] if result else ""
    return result.replace("package/medium/", "")


def getSeries(html):
    result = html.xpath('//a[contains(@href, "series")]/span/text()')
    result = result[0] if result else ""
    return result


class XcityCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.XCITY

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://xcity.jp"

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return f"{self.base_url}/result_published/?q={ctx.input.number.replace('-', '')}"

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        html_search = html.get()
        if "該当する作品はみつかりませんでした" in html_search:
            ctx.debug("xcity 搜索页没有匹配结果")
            return None
        search_page = etree.fromstring(html_search, etree.HTMLParser())
        detail_urls = search_page.xpath("//table[@class='resultList']/tr/td/a/@href")
        if not detail_urls:
            ctx.debug("xcity 搜索页没有匹配结果")
            return None
        return [self.base_url + detail_urls[0]]

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        detail_page = etree.fromstring(html.get(), etree.HTMLParser())
        title = getTitle(detail_page)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        web_number = getWebNumber(detail_page, ctx.input.number)
        title = title.replace(f" {web_number}", "").strip()
        actor = getActor(detail_page)
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        tag = getTag(detail_page)
        director = getDirector(detail_page)
        directors = [item.strip() for item in director.split(",") if item.strip()]
        release = getRelease(detail_page)
        extrafanart = getExtrafanart(detail_page)
        return CrawlerData(
            number=ctx.input.number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            directors=directors,
            outline=getOutline(detail_page),
            originalplot=getOutline(detail_page),
            tags=[item.strip() for item in tag.split(",") if item.strip()],
            release=release,
            year=getYear(release),
            runtime=getRuntime(detail_page),
            series=getSeries(detail_page),
            studio=getStudio(detail_page),
            publisher=getPublisher(detail_page),
            thumb=getCover(detail_page),
            poster=getCoverSmall(detail_page),
            extrafanart=extrafanart if isinstance(extrafanart, list) else [],
            trailer="",
            image_download=False,
            image_cut="right",
            mosaic="有码",
            external_id=detail_url,
        )
