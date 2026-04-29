#!/usr/bin/env python3
import re
from datetime import date
from typing import override

from lxml import etree

from ..config.enums import Website
from ..config.manager import manager
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def get_title(html):
    result = html.xpath("//h3/text()")
    return result[0].strip() if result else ""


def getWebNumber(html, number):
    result = html.xpath('//span[@class="header"][contains(text(), "識別碼:")]/../span[2]/text()')
    return result[0] if result else number


def getActor(html):
    try:
        return str(html.xpath('//div[@class="star-name"]/a/text()')).strip(" ['']").replace("'", "").replace(", ", ",")
    except Exception:
        return ""


def getCover(html, url):  # 获取封面链接
    result = html.xpath('//a[@class="bigImage"]/@href')
    return (url + result[0] if "http" not in result[0] else result[0]) if result else ""


def get_poster_url(cover_url):  # 获取小封面链接
    if "/pics/" in cover_url:
        return cover_url.replace("/cover/", "/thumb/").replace("_b.jpg", ".jpg")
    if "/imgs/" in cover_url:
        return cover_url.replace("/cover/", "/thumbs/").replace("_b.jpg", ".jpg")
    return ""


def getRelease(html):  # 获取发行日期
    result = html.xpath('//span[@class="header"][contains(text(), "發行日期:")]/../text()')
    return result[0].strip() if result else ""


def getValidRelease(release):
    release = release.replace("/", "-").replace(".", "-").strip()
    if not release:
        return ""
    if not (match := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", release)):
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def getYear(release):
    release = getValidRelease(release)
    return release[:4] if release else ""


def getMosaic(html):
    select_tab = str(html.xpath('//li[@class="active"]/a/text()'))
    return "有码" if "有碼" in select_tab else "无码"


def getRuntime(html):
    result = html.xpath('//span[@class="header"][contains(text(), "長度:")]/../text()')
    if result:
        result = re.findall(r"\d+", result[0].strip())
        return result[0] if result else ""
    return ""


def getStudio(html):
    result = html.xpath('//a[contains(@href, "/studio/")]/text()')
    return result[0].strip() if result else ""


def getPublisher(html, studio):  # 获取发行商
    result = html.xpath('//a[contains(@href, "/label/")]/text()')
    return result[0].strip() if result else studio


def getDirector(html):  # 获取导演
    result = html.xpath('//a[contains(@href, "/director/")]/text()')
    return result[0].strip() if result else ""


def getSeries(html):
    result = html.xpath('//a[contains(@href, "/series/")]/text()')
    return result[0].strip() if result else ""


def getExtraFanart(html, url):  # 获取封面链接
    result = html.xpath("//div[@id='sample-waterfall']/a/@href")
    if not result:
        return []
    new_list = []
    for each in result:
        if "http" not in each:
            each = url + each
        new_list.append(each)
    return new_list


def getTag(html):  # 获取标签
    result = html.xpath('//span[@class="genre"]/label/a[contains(@href, "/genre/")]/text()')
    return str(result).strip(" ['']").replace("'", "").replace(", ", ",") if result else ""


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def get_real_url(client, ctx: Context, number, url_type, javbus_url, headers):  # 获取详情页链接
    if url_type == "us":  # 欧美
        url_search = "https://www.javbus.hair/search/" + number
    elif url_type == "censored":  # 有码
        url_search = javbus_url + "/search/" + number + "&type=&parent=ce"
    else:  # 无码
        url_search = javbus_url + "/uncensored/search/" + number + "&type=0&parent=uc"

    ctx.debug(f"搜索地址: {url_search}")
    ctx.debug_info.search_urls.append(url_search)
    html_search, error = await client.get_text(url_search, headers=headers)
    if html_search is None:
        raise CralwerException(f"网络请求错误: {error}")
    if "lostpasswd" in html_search:
        raise CralwerException("Cookie 无效！请重新填写 Cookie 或更新节点！")

    html = etree.fromstring(html_search, etree.HTMLParser())
    url_list = html.xpath("//a[@class='movie-box']/@href")
    for each in url_list:
        each_url = each.upper().replace("-", "")
        number_1 = "/" + number.upper().replace(".", "").replace("-", "")
        number_2 = number_1 + "_"
        if each_url.endswith(number_1) or number_2 in each_url:
            ctx.debug(f"番号地址: {each}")
            return each
    raise CralwerException("搜索结果: 未匹配到番号！")


class JavbusCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVBUS

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.JAVBUS, "https://www.javbus.com")

    @override
    async def _run(self, ctx: Context):
        number = ctx.input.number
        mosaic = ctx.input.mosaic
        real_url = ctx.input.appoint_url
        headers = {
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
            "cookie": manager.config.javbus,
        }
        image_download = False
        image_cut = "right"

        if not real_url:
            if "." in number or re.search(r"[-_]\d{2}[-_]\d{2}[-_]\d{2}", number):
                number = number.replace("-", ".").replace("_", ".")
                real_url = await get_real_url(self.async_client, ctx, number, "us", self.base_url, headers)
            else:
                real_url = self.base_url + "/" + number
                if number.upper().startswith(("CWP", "LAF")):
                    temp_number = number.replace("-0", "-")
                    if temp_number[-2] == "-":
                        temp_number = temp_number.replace("-", "-0")
                    real_url = self.base_url + "/" + temp_number

        ctx.debug(f"番号地址: {real_url}")
        htmlcode, error = await self.async_client.get_text(real_url, headers=headers)
        if htmlcode is None:
            if "404" not in str(error) or "." in number:
                raise CralwerException(f"网络请求错误: {error}")
            if mosaic in {"无码", "無碼"}:
                real_url = await get_real_url(self.async_client, ctx, number, "uncensored", self.base_url, headers)
            else:
                real_url = await get_real_url(self.async_client, ctx, number, "censored", self.base_url, headers)
            htmlcode, error = await self.async_client.get_text(real_url, headers=headers)
            if htmlcode is None:
                raise CralwerException("未匹配到番号！")
        if "lostpasswd" in htmlcode:
            raise CralwerException("Cookie 无效！请重新填写 Cookie 或更新节点！")

        ctx.debug_info.detail_urls = [real_url]
        html_info = etree.fromstring(htmlcode, etree.HTMLParser())
        title = get_title(html_info)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title")

        number = getWebNumber(html_info, number)
        title = title.replace(number, "").strip()
        actor = getActor(html_info)
        cover_url = getCover(html_info, self.base_url)
        poster_url = get_poster_url(cover_url)
        release_raw = getRelease(html_info)
        release = getValidRelease(release_raw)
        if release_raw and not release:
            ctx.debug(f"发行日期无效，已忽略: {release_raw}")
        tag = getTag(html_info)
        mosaic = getMosaic(html_info)
        if mosaic == "无码":
            image_cut = "center"
            if (
                "_" in number
                and poster_url
                or "HEYZO" in number
                and len(poster_url.replace(self.base_url + "/imgs/thumbs/", "")) == 7
            ):
                image_download = True
            else:
                poster_url = ""
        studio = getStudio(html_info)
        extrafanart = getExtraFanart(html_info, self.base_url)
        if "KMHRS" in number:
            image_download = True
            if extrafanart:
                poster_url = extrafanart[0]

        data = CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=split_csv(actor),
            outline="",
            originalplot="",
            tags=split_csv(tag),
            release=release,
            year=getYear(release),
            runtime=getRuntime(html_info),
            score="",
            series=getSeries(html_info),
            directors=split_csv(getDirector(html_info)),
            studio=studio,
            publisher=getPublisher(html_info, studio),
            thumb=cover_url,
            poster=poster_url,
            extrafanart=extrafanart,
            trailer="",
            image_download=image_download,
            image_cut=image_cut,
            mosaic=mosaic,
            external_id=real_url,
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
