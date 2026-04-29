#!/usr/bin/env python3

import contextlib
import re
import unicodedata
import urllib.parse
from typing import override

from lxml import etree

from ..config.enums import Website
from . import getchu_dl
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def normalize_detail_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"(?:soft\.phtml\?id=|/item/)(\d+)", url)
    if not match:
        return url
    item_id = match.group(1)
    return f"https://www.getchu.com/item/{item_id}/?gc=gc"


def get_attestation_continue_url(html) -> str:
    result = html.xpath("//h1[contains(., '年齢認証ページ')]/following::a[contains(., 'すすむ')][1]/@href")
    return normalize_detail_url(result[0].strip()) if result else ""


def get_web_number(html, number):
    result = html.xpath('//td[contains(text(), "品番：")]/following-sibling::td/text()')
    return result[0].strip().upper() if result else number


def get_title(html):
    result = html.xpath('//h1[@id="soft-title"]/text()')
    if result:
        return result[0].strip()

    result = html.xpath('//meta[@property="og:title"]/@content')
    if result:
        title = re.sub(r"\s*\|\s*.*$", "", result[0]).strip()
        if title:
            return title

    result = html.xpath("//title/text()")
    if result:
        title = re.sub(r"\s+", " ", result[0]).strip()
        title = re.sub(r"\s*\|.*$", "", title).strip()
        title = re.sub(r"\s*\(.*?\)$", "", title).strip()
        return title
    return ""


def get_studio(html):
    result = html.xpath('//a[@class="glance"]/text()')
    return result[0] if result else ""


def get_release(html):
    result = html.xpath("//td[contains(text(),'発売日：')]/following-sibling::td/a/text()")
    return result[0].replace("/", "-") if result and re.search(r"\d+", result[0]) else ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_director(html):
    result = html.xpath("//td[contains(text(),'監督：')]/following-sibling::td/text()")
    if not result:
        result = html.xpath("//a[contains(@href,'person=')]/text()")
    if not result:
        result = html.xpath("//td[contains(text(),'キャラデザイン：')]/following-sibling::td/text()")
    return result[0] if result else ""


def get_runtime(html):
    result = html.xpath("//td[contains(text(),'時間：')]/following-sibling::td/text()")
    if result:
        result = re.findall(r"\d*", result[0])
    return result[0] if result else ""


def get_tag(html):
    result = html.xpath(
        "//td[contains(text(), 'サブジャンル：') or contains(text(), 'カテゴリ：')]/following-sibling::td/a/text()"
    )
    return ",".join(result).replace(",[一覧]", "") if result else ""


def get_cover(html):
    result = html.xpath('//meta[@property="og:image"]/@content')
    if result:
        return "http://www.getchu.com" + result[0] if "http" not in result[0] else result[0]
    return ""


def get_outline(html):
    all_info = html.xpath('//div[@class="tablebody"]')
    result = ""
    for each in all_info:
        info = each.xpath("normalize-space(string())")
        result += "\n" + info
    return result.strip()


def get_mosaic(html, mosaic):
    result = html.xpath('//li[@class="genretab current"]/text()')
    if result:
        r = result[0]
        if r == "アダルトアニメ":
            mosaic = "里番"
        elif r == "書籍・雑誌":
            mosaic = "书籍"
        elif r == "アニメ":
            mosaic = "动漫"

    return mosaic


def get_extrafanart(html):
    result_list = html.xpath("//div[contains(text(),'サンプル画像')]/following-sibling::div[1]/a/@href")
    if not result_list:
        result_list = html.xpath("//div[contains(@class,'item-Samplecard')]//a[contains(@class,'highslide')]/@href")
    result = []
    for each in result_list:
        each = each.replace("./", "https://www.getchu.com/")
        if each.startswith("/"):
            each = "https://www.getchu.com" + each
        result.append(each)
    return result


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class GetchuCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.GETCHU

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "http://www.getchu.com"

    @override
    async def _run(self, ctx: Context):
        data = await self._scrape(ctx)
        result = data.to_result()
        result.source = data.source if isinstance(data.source, str) else self.site().value
        ctx.debug("数据获取成功！")
        return result

    async def _scrape(self, ctx: Context) -> CrawlerData:
        number = ctx.input.number
        appoint_url = ctx.input.appoint_url
        if (
            "DLID" in number.upper()
            or "ITEM" in number.upper()
            or "GETCHU" in number.upper()
            or "dl.getchu" in appoint_url
        ):
            return await getchu_dl.scrape_dl_getchu(self.async_client, number, appoint_url, ctx)

        real_url = appoint_url.replace("&gc=gc", "") + "&gc=gc" if appoint_url else ""
        image_cut = ""
        image_download = True

        if not real_url:
            number = number.replace("10bit", "").replace("裕未", "祐未").replace("“", "”").replace("·", "・")
            keyword = unicodedata.normalize("NFC", number)
            with contextlib.suppress(Exception):
                keyword = keyword.encode("cp932").decode("shift_jis")
            keyword2 = urllib.parse.quote_plus(keyword, encoding="EUC-JP")
            search_url = f"{self.base_url}/php/search.phtml?genre=all&search_keyword={keyword2}&gc=gc"
            ctx.debug(f"搜索地址: {search_url}")
            ctx.debug_info.search_urls = [search_url]

            html_search, error = await self.async_client.get_text(search_url, encoding="euc-jp")
            if html_search is None:
                raise CralwerException(f"网络请求错误: {error}")
            html = etree.fromstring(html_search, etree.HTMLParser())
            url_list = html.xpath("//a[@class='blueb']/@href")
            title_list = html.xpath("//a[@class='blueb']/text()")
            if not url_list:
                ctx.debug("getchu 未匹配到结果，尝试 DL Getchu")
                return await getchu_dl.scrape_dl_getchu(self.async_client, number, appoint_url, ctx)

            real_url = normalize_detail_url(self.base_url + url_list[0].replace("../", "/") + "&gc=gc")
            keyword_temp = re.sub(r"[ \[\]\［\］]+", "", keyword)
            for i, url in enumerate(url_list):
                title_temp = re.sub(r"[ \[\]\［\］]+", "", title_list[i])
                if keyword_temp in title_temp:
                    real_url = normalize_detail_url(self.base_url + url.replace("../", "/") + "&gc=gc")
                    break

        real_url = normalize_detail_url(real_url)
        ctx.debug(f"番号地址: {real_url}")
        ctx.debug_info.detail_urls = [real_url]
        html_content, error = await self.async_client.get_text(real_url, encoding="euc-jp")
        if html_content is None:
            raise CralwerException(f"网络请求错误: {error}")
        html_info = etree.fromstring(html_content, etree.HTMLParser())
        continue_url = get_attestation_continue_url(html_info)
        if continue_url:
            ctx.debug(f"检测到年龄确认页，继续访问: {continue_url}")
            real_url = continue_url
            ctx.debug_info.detail_urls.append(real_url)
            html_content, error = await self.async_client.get_text(real_url, encoding="euc-jp")
            if html_content is None:
                raise CralwerException(f"网络请求错误: {error}")
            html_info = etree.fromstring(html_content, etree.HTMLParser())

        title = get_title(html_info)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        release = get_release(html_info)
        mosaic = "里番" if "18禁" in html_content else "动漫"
        mosaic = get_mosaic(html_info, mosaic)
        cover_url = get_cover(html_info)
        outline = get_outline(html_info)
        return CrawlerData(
            number=get_web_number(html_info, number),
            title=title,
            originaltitle=title,
            actors=[],
            outline=outline,
            originalplot=outline,
            tags=split_csv(get_tag(html_info)),
            release=release,
            year=get_year(release),
            runtime=get_runtime(html_info),
            score="",
            series="",
            directors=split_csv(get_director(html_info)),
            studio=get_studio(html_info),
            publisher="",
            thumb=cover_url,
            poster=cover_url,
            extrafanart=get_extrafanart(html_info),
            trailer="",
            image_download=image_download,
            image_cut=image_cut,
            mosaic=mosaic,
            external_id=real_url,
            wanted="",
            source=self.site().value,
        )

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str) -> CrawlerData | None:
        return None
