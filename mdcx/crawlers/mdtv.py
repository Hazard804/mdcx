#!/usr/bin/env python3
import re
from dataclasses import dataclass, field
from typing import override

from lxml import etree
from parsel import Selector

from ..config.manager import manager
from ..config.models import Website
from ..models.types import CrawlerInput
from .base import BaseCrawler, Context, CralwerException, CrawlerData
from .guochan import get_actor_list, get_lable_list, get_number_list


def get_title(html):
    result = html.xpath('//div[@class="blog-single"]/div/a/@title')
    return result[0].replace("\t", "").strip(" .") if result else ""


def get_some_info(html, title, file_path):
    series_list = html.xpath('(//div[@class="category"])[1]/text()')
    tag_list = html.xpath('(//div[@class="category"])[2]/a/text()')
    actor_list = html.xpath('(//div[@class="category"])[3]/a/text()')

    series = series_list[0] if series_list else ""
    tag = ",".join(tag_list)
    actor_fake_name = any("未知" in item for item in actor_list)
    actor_list = [] if actor_fake_name else actor_list
    if not actor_list:
        all_info = title + series + tag + file_path
        all_actor = get_actor_list()
        for each in all_actor:
            if each in all_info:
                actor_list.append(each)
    new_actor_list = []
    [new_actor_list.append(i) for i in actor_list if i and i not in new_actor_list]

    for each in actor_list:
        if each in tag_list:
            tag_list.remove(each)
    new_tag_list = []
    [new_tag_list.append(i) for i in tag_list if i and i not in new_tag_list]

    return series, ",".join(new_tag_list), ",".join(new_actor_list)


def get_studio(series, tag, lable_list):
    word_list = [series]
    word_list.extend(tag.split(","))
    for word in word_list:
        if word in lable_list:
            return word
    return ""


def get_real_url(html, number, mdtv_url, file_path):
    real_url = ""
    a = re.search(r"(\d*[A-Z]{2,})\s*(\d{3,})", number)
    real_number = number
    if a:
        real_number = a[1] + "-" + a[2]
    result = html.xpath('//h4[@class="post-title"]')
    cd = re.findall(r"((AV|EP)\d{1})", file_path.upper())
    for each in result:
        title = each.xpath("a/@title")[0].upper()
        href = each.xpath("a/@href")[0]
        title_1 = title.replace(".", "").replace("-", "").replace(" ", "")
        number_1 = number.replace(".", "").replace("-", "").replace(" ", "")
        if number in title or real_number in title or number_1 in title_1:
            real_url = mdtv_url + href
            if cd:
                if cd[0][0] in title_1.upper():
                    break
            else:
                break
    return real_url


def get_cover(html, mdtv_url):
    result = html.xpath('//div[@class="blog-single"]/div/a/img/@src')
    if result:
        result = result[0]
        if "http" not in result:
            result = mdtv_url + result
    return result if result else ""


def get_year(release):
    result = re.search(r"\d{4}", release)
    return result[0] if result else release


def get_release(cover_url):
    a = re.search(r"/(\d{4})(\d{2})(\d{2})-", cover_url)
    return f"{a[1]}-{a[2]}-{a[3]}" if a else ""


def get_tag(html):
    result = html.xpath('//div[@class="category"]/a[contains(@href, "/class/")]/text()')
    return ",".join(result)


def get_real_number_title(number, title, number_list, appoint_number, appoint_url, lable_list, tag, actor, series):
    if appoint_number:
        number = appoint_number
        temp_title = title.replace(number, "")
        if len(temp_title) > 4:
            title = temp_title
    else:
        if number not in number_list or appoint_url:
            title_number_list, filename_list = get_number_list(number, appoint_number, title)
            if title_number_list:
                number = title_number_list[0]
                number_list = title_number_list

        if number in number_list:
            if number != title:
                title = title.replace(number, "").replace(number.lower(), "")
            if "-" not in number:
                if re.search(r"[A-Z]{4,}\d{2,}", number):
                    result = re.search(r"([A-Z]{4,})(\d{2,})", number)
                    number = result[1] + "-" + result[2]
                else:
                    result = re.search(r"\d{3,}", number)
                    if result:
                        number = number.replace(result[0], "-" + result[0])
            if number != title:
                title = title.replace(number, "")
        else:
            number = title
    temp_title = get_real_title(title, number_list, lable_list, tag, actor, series)
    if number == title:
        number = temp_title

    cd = re.findall(r"((AV|EP)\d{1})", title.upper())
    if cd and cd[0][0] not in number:
        number = number + " " + cd[0][0]

    return number, temp_title


def get_real_title(title, number_list, lable_list, tag, actor, series):
    for number in number_list:
        title = title.replace(number, "")

    title_list = re.split("[. ]", title)
    if len(title_list) > 1:
        for key in lable_list:
            for each in title_list:
                if key in each:
                    title_list.remove(each)
        if title_list[-1].lower() == "x":
            title_list.pop()
        title = " ".join(title_list)
    for each in tag.split(","):
        if each:
            title = title.replace("" + each, "")
    for each in actor.split(","):
        if each:
            title = title.replace(" " + each, "")
    title = title.lstrip(series + " ").replace("..", ".").replace("  ", " ")

    return title.replace(" x ", "").replace(" X ", "").strip(" -.")


@dataclass
class MdtvContext(Context):
    label_list: list[str] = field(default_factory=list)
    number_list: list[str] = field(default_factory=list)
    search_number: str = ""
    file_path_text: str = ""


class MdtvCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.MDTV

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.MDTV, "https://www.mdpjzip.xyz")

    @override
    def new_context(self, input: CrawlerInput) -> MdtvContext:
        file_path = str(input.file_path or "")
        number_list, filename_list = get_number_list(input.number, input.appoint_number, file_path)
        total_number_list = number_list + filename_list
        number_candidates = list(set(total_number_list))
        number_candidates.sort(key=total_number_list.index)
        return MdtvContext(
            input=input,
            label_list=get_lable_list(),
            number_list=number_list,
            file_path_text=file_path,
            search_number=number_candidates[0] if number_candidates else input.number,
        )

    @override
    async def _generate_search_url(self, ctx: MdtvContext) -> list[str] | str | None:
        return f"{self.base_url}/index.php/vodsearch/-------------.html"

    @override
    async def _search(self, ctx: MdtvContext, search_urls: list[str]) -> list[str] | None:
        search_url = search_urls[0]
        file_path = ctx.file_path_text
        number_list, filename_list = get_number_list(ctx.input.number, ctx.input.appoint_number, file_path)
        total_number_list = number_list + filename_list
        number_candidates = list(set(total_number_list))
        number_candidates.sort(key=total_number_list.index)
        for number in number_candidates:
            ctx.search_number = number
            ctx.debug(f'MDTV 搜索地址: {search_url} {{"wd": {number}}}')
            response, error = await self.async_client.post_text(search_url, data={"wd": number})
            if response is None:
                raise CralwerException(f"网络请求错误: {error}")
            if "没有找到匹配数据" in response:
                ctx.debug("MDTV 搜索结果: 没有搜索内容")
                continue
            search_page = Selector(text=response)
            detail_urls = await self._parse_search_page(ctx, search_page, search_url)
            if detail_urls:
                return detail_urls if isinstance(detail_urls, list) else [detail_urls]
        return None

    @override
    async def _parse_search_page(self, ctx: MdtvContext, html: Selector, search_url: str) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        detail_url = get_real_url(search_page, ctx.search_number, self.base_url, ctx.file_path_text)
        if not detail_url:
            ctx.debug("mdtv 搜索页没有匹配结果")
            return None
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: MdtvContext, html: Selector, detail_url: str) -> CrawlerData | None:
        detail_page = etree.fromstring(html.get(), etree.HTMLParser())
        title = get_title(detail_page)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        series, tag, actor = get_some_info(detail_page, title, ctx.file_path_text)
        cover_url = get_cover(detail_page, self.base_url)
        release = get_release(cover_url)
        studio = get_studio(series, tag, ctx.label_list)
        number, title = get_real_number_title(
            ctx.input.number,
            title,
            ctx.number_list,
            ctx.input.appoint_number,
            ctx.input.appoint_url,
            ctx.label_list,
            tag,
            actor,
            series,
        )
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            tags=[item.strip() for item in tag.split(",") if item.strip()],
            release=release,
            year=get_year(release),
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
            external_id=detail_url,
        )
