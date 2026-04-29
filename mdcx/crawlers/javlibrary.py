#!/usr/bin/env python3
import re
import urllib.parse
from typing import override

from lxml import etree

from ..config.enums import Language, Website
from ..config.manager import manager
from ..gen.field_enums import CrawlerResultFields
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def get_real_url(html, number, domain_2):
    real_url = ""
    origin = urllib.parse.urlsplit(domain_2)._replace(path="", query="", fragment="").geturl()
    new_number = number.strip().replace("-", "").upper() + " "
    result = html.xpath('//div[@id="video_title"]/h3/a/text()')

    for each in result:
        if new_number in each.replace("-", "").upper():
            real_url = html.xpath('//div[@id="video_title"]/h3/a[contains(text(), $title)]/@href', title=each)[0]
            return urllib.parse.urljoin(origin, real_url)
    result = html.xpath('//a[contains(@href, "/?v=jav")]/@title')

    for each in result:
        if new_number in each.replace("-", "").upper():
            real_url = html.xpath("//a[@title=$title]/@href", title=each)[0]
            real_url = urllib.parse.urljoin(domain_2 + "/", real_url)
            if "ブルーレイディスク" not in each:
                return real_url
    if real_url:
        return real_url
    return ""


def get_title(html):
    result = html.xpath('//div[@id="video_title"]/h3/a/text()')
    return result[0].strip() if result else ""


def get_number(html, number):
    result = html.xpath('//div[@id="video_id"]/table/tr/td[@class="text"]/text()')
    return result[0] if result else number


def get_actor(html):
    result = html.xpath('//div[@id="video_cast"]/table/tr/td[@class="text"]/span/span[@class="star"]/a/text()')
    return str(result).strip(" []").replace("'", "").replace(", ", ",") if result else ""


def get_cover(html):
    result = html.xpath("//img[@id='video_jacket_img']/@src")
    return ("https:" + result[0] if "http" not in result[0] else result[0]) if result else ""


def get_tag(html):
    result = html.xpath('//div[@id="video_genres"]/table/tr/td[@class="text"]/span/a/text()')
    return str(result).strip(" []").replace("'", "").replace(", ", ",") if result else ""


def get_release(html):
    result = html.xpath('//div[@id="video_date"]/table/tr/td[@class="text"]/text()')
    return str(result).strip(" []").replace("'", "").replace(", ", ",") if result else ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release[:4]


def get_studio(html):
    result = html.xpath('//div[@id="video_maker"]/table/tr/td[@class="text"]/span/a/text()')
    return result[0] if result else ""


def get_publisher(html):
    result = html.xpath('//div[@id="video_label"]/table/tr/td[@class="text"]/span/a/text()')
    return result[0] if result else ""


def get_runtime(html):
    result = html.xpath('//div[@id="video_length"]/table/tr/td/span[@class="text"]/text()')
    return result[0] if result else ""


def get_score(html):
    result = html.xpath('//div[@id="video_review"]/table/tr/td/span[@class="score"]/text()')
    return result[0].strip("()") if result else ""


def get_director(html):
    result = html.xpath('//div[@id="video_director"]/table/tr/td[@class="text"]/span/a/text()')
    return result[0] if result else ""


def get_wanted(html):
    result = html.xpath('//a[contains(@href, "userswanted.php?")]/text()')
    return str(result[0]) if result else ""


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_language(language: Language | str) -> Language:
    if isinstance(language, Language):
        return language
    try:
        return Language(language)
    except ValueError:
        return Language.ZH_CN


def language_path(language: Language) -> str:
    if language == Language.ZH_CN:
        return "cn"
    if language == Language.ZH_TW:
        return "tw"
    return "ja"


class JavlibraryCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVLIBRARY

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.JAVLIBRARY, "https://www.javlibrary.com")

    @property
    def use_proxy(self) -> bool:
        return not manager.config.get_site_config(Website.JAVLIBRARY).custom_url

    def _needs_localized_language(self) -> Language | None:
        field_languages = [
            manager.config.get_field_config(field).language
            for field in (
                CrawlerResultFields.TITLE,
                CrawlerResultFields.OUTLINE,
                CrawlerResultFields.ACTORS,
                CrawlerResultFields.TAGS,
                CrawlerResultFields.SERIES,
                CrawlerResultFields.STUDIO,
            )
        ]
        if Language.ZH_CN in field_languages:
            return Language.ZH_CN
        if Language.ZH_TW in field_languages:
            return Language.ZH_TW
        return None

    @override
    async def _run(self, ctx: Context):
        requested_language = normalize_language(ctx.input.language)
        jp_url = ctx.input.appoint_url.replace("/cn/", "/ja/").replace("/tw/", "/ja/")
        jp_data = await self._scrape_language(ctx, Language.JP, jp_url)
        target_language = requested_language if requested_language in {Language.ZH_CN, Language.ZH_TW} else None
        target_language = target_language or self._needs_localized_language()
        if not target_language:
            result = jp_data.to_result()
            result.source = self.site().value
            ctx.debug("数据获取成功！")
            return result

        localized_url = ""
        if isinstance(jp_data.external_id, str) and jp_data.external_id:
            localized_url = jp_data.external_id.replace("/ja/", f"/{language_path(target_language)}/")
        localized_data = await self._scrape_language(ctx, target_language, localized_url)
        localized_data.originaltitle = jp_data.originaltitle or jp_data.title
        localized_data.originalplot = jp_data.originalplot or jp_data.outline
        result = localized_data.to_result()
        result.source = self.site().value
        ctx.debug("数据获取成功！")
        return result

    async def _scrape_language(self, ctx: Context, language: Language, appoint_url: str = "") -> CrawlerData:
        number = ctx.input.number
        lang_path = language_path(language)
        domain_2 = f"{self.base_url}/{lang_path}"
        real_url = appoint_url
        if not real_url:
            search_url = f"{domain_2}/vl_searchbyid.php?keyword={number}"
            ctx.debug(f"搜索地址[{language.value}]: {search_url}")
            ctx.debug_info.search_urls = [*(ctx.debug_info.search_urls or []), search_url]
            html_search, error = await self.async_client.get_text(search_url, use_proxy=self.use_proxy)
            if html_search is None:
                raise CralwerException(f"请求错误: {error}")
            if "Cloudflare" in html_search:
                raise CralwerException("搜索结果: 被 Cloudflare 5 秒盾拦截！")
            html = etree.fromstring(html_search, etree.HTMLParser())
            real_url = get_real_url(html, number, domain_2)
            if not real_url:
                raise CralwerException("搜索结果: 未匹配到番号！")

        ctx.debug(f"番号地址[{language.value}]: {real_url}")
        ctx.debug_info.detail_urls = [*(ctx.debug_info.detail_urls or []), real_url]
        html_info, error = await self.async_client.get_text(real_url, use_proxy=self.use_proxy)
        if html_info is None:
            raise CralwerException(f"请求错误: {error}")
        if "Cloudflare" in html_info:
            raise CralwerException("搜索结果: 被 Cloudflare 5 秒盾拦截！")

        html_detail = etree.fromstring(html_info, etree.HTMLParser())
        title = get_title(html_detail)
        if not title:
            raise CralwerException("数据获取失败: 未获取到标题！")
        web_number = get_number(html_detail, number)
        title = title.replace(web_number + " ", "")
        release = get_release(html_detail)
        return CrawlerData(
            number=web_number,
            title=title,
            originaltitle=title,
            actors=split_csv(get_actor(html_detail)),
            outline="",
            originalplot="",
            tags=split_csv(get_tag(html_detail)),
            release=release,
            year=get_year(release),
            runtime=get_runtime(html_detail),
            score=get_score(html_detail),
            series="",
            directors=split_csv(get_director(html_detail)),
            studio=get_studio(html_detail),
            publisher=get_publisher(html_detail),
            thumb=get_cover(html_detail),
            poster="",
            extrafanart=[],
            trailer="",
            image_download=False,
            image_cut="right",
            mosaic="有码",
            external_id=real_url,
            wanted=get_wanted(html_detail),
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
