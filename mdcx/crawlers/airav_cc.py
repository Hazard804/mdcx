#!/usr/bin/env python3
import json
import re
import urllib.parse
from typing import override

from lxml import etree

from ..config.enums import Website
from ..config.manager import manager
from ..signals import signal
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def get_web_number(html):
    result = html.xpath('//*[contains(text(), "番號") or contains(text(), "番号")]//span/text()')
    return result[0].strip() if result else ""


def get_number(html, number):
    result = html.xpath('//*[contains(text(), "番號") or contains(text(), "番号")]//span/text()')
    num = result[0].strip() if result else ""
    return number if number else num


def get_title(html):
    result = html.xpath('//div[@class="video-title my-3"]/h1/text()')
    result = str(result[0]).strip() if result else ""
    # 去掉无意义的简介(马赛克破坏版)，'克破'两字简繁同形
    if not result or "克破" in result:
        return ""
    return result


def get_actor(html):
    try:
        actor_list = html.xpath('//*[contains(text(), "女優") or contains(text(), "女优")]//a/text()')
        result = ",".join(actor_list)
    except Exception:
        result = ""
    return result


def get_studio(html):
    result = html.xpath('//*[contains(text(), "廠商") or contains(text(), "厂商")]//a/text()')
    return result[0] if result else ""


def get_release(html):
    result = html.xpath('//i[@class="fa fa-clock me-2"]/../text()')
    if result:
        s = re.search(r"\d{4}-\d{2}-\d{2}", result[0]).group()
        return s if s else ""
    return ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_tag(html):
    result = html.xpath('//*[contains(text(), "標籤") or contains(text(), "标籤")]//a/text()')
    return ",".join(result) if result else ""


def get_cover(html):
    result = html.xpath('//script[@type="application/ld+json"]/text()')[0]
    if result:
        data_dict = json.loads(result)
        result = data_dict.get("thumbnailUrl", "")[0]
    return result if result else ""


def get_outline(html):
    result = html.xpath('//div[@class="video-info"]/p/text()')
    result = str(result[0]).strip() if result else ""
    # 去掉无意义的简介(马赛克破坏版)，'克破'两字简繁同形
    if not result or "克破" in result:
        return ""
    else:
        # 去除简介中的无意义信息，中间和首尾的空白字符、*根据分发等
        result = re.sub(r"[\n\t]", "", result).split("*根据分发", 1)[0].strip()
    return result


def get_series(html):
    result = html.xpath('//*[contains(text(), "系列")]//a/text()')
    result = result[0] if result else ""
    return result


async def retry_request(client, real_url):
    html_content, error = await client.get_text(real_url)
    if html_content is None:
        raise CralwerException(f"网络请求错误: {error}")
    html_info = etree.fromstring(html_content, etree.HTMLParser())
    title = get_title(html_info)
    if not title:
        raise CralwerException("数据获取失败: 未获取到title！")
    web_number = get_web_number(html_info)
    for prefix in (f"[{web_number}]", web_number):
        if prefix:
            title = title.replace(prefix, "", 1).strip()
    outline = get_outline(html_info)
    actor = get_actor(html_info)
    cover_url = get_cover(html_info)
    tag = get_tag(html_info)
    studio = get_studio(html_info)
    return html_info, title, outline, actor, cover_url, tag, studio


def get_real_url(html, number):
    item_list = html.xpath('//div[@class="col oneVideo"]')
    for each in item_list:
        # href="/video?hid=99-21-39624"
        detail_url = each.xpath(".//a/@href")[0]
        title = each.xpath(".//h5/text()")[0]
        # 注意去除马赛克破坏版这种几乎没有有效字段的条目
        if number.upper() in title and all(keyword not in title for keyword in ["克破", "无码破解", "無碼破解"]):
            return detail_url
    return ""


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_language(language: str) -> str:
    return language if language in {"zh_cn", "zh_tw", "jp"} else "zh_cn"


class AiravCcCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AIRAV_CC

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.AIRAV_CC, "https://airav.io")

    def _language_base_url(self, language: str) -> str:
        base_url = self.base_url
        return base_url + "/cn" if language == "zh_cn" else base_url

    @override
    async def _run(self, ctx: Context):
        language = normalize_language(getattr(ctx.input.language, "value", str(ctx.input.language)))
        number = ctx.input.number.upper()
        if re.match(r"N\d{4}", number):
            number = number.lower()
        real_url = ctx.input.appoint_url
        airav_url = self._language_base_url(language)
        image_cut = "right"
        image_download = False
        mosaic = "有码"

        if not real_url:
            search_url = airav_url + f"/search_result?kw={number}"
            ctx.debug(f"搜索地址: {search_url}")
            ctx.debug_info.search_urls = [search_url]
            html_search, error = await self.async_client.get_text(search_url)
            if html_search is None:
                raise CralwerException(f"网络请求错误: {error}")
            html = etree.fromstring(html_search, etree.HTMLParser())
            real_urls = html.xpath('//div[@class="col oneVideo"]//a[@href]/@href')
            if not real_urls:
                raise CralwerException("搜索结果: 未匹配到番号！")
            real_url = real_urls[0] if len(real_urls) == 1 else get_real_url(html, number)
            if not real_url:
                raise CralwerException("搜索结果: 未匹配到番号！")

        real_url = urllib.parse.urljoin(airav_url, real_url) if real_url.startswith("/") else real_url
        ctx.debug(f"番号地址: {real_url}")
        ctx.debug_info.detail_urls = [real_url]
        html_info, title, outline, actor, cover_url, tag, studio = await retry_request(self.async_client, real_url)

        if cover_url.startswith("/"):
            cover_url = urllib.parse.urljoin(airav_url, cover_url)

        temp_str = title + outline + actor + tag + studio
        if "�" in temp_str:
            debug_info = f"{number} 请求 airav_cc 返回内容存在乱码 �"
            signal.add_log(debug_info)
            ctx.debug(debug_info)
            raise CralwerException(debug_info)

        number = get_number(html_info, number)
        release = get_release(html_info)
        series = get_series(html_info)
        if "无码" in tag or "無修正" in tag or "無码" in tag or "uncensored" in tag.lower():
            mosaic = "无码"
        title_rep = ["第一集", "第二集", " - 上", " - 下", " 上集", " 下集", " -上", " -下"]
        for each in title_rep:
            title = title.replace(each, "").strip()

        data = CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=split_csv(actor),
            outline=outline,
            originalplot=outline,
            tags=split_csv(tag),
            release=release,
            year=get_year(release),
            runtime="",
            score="",
            series=series,
            directors=[],
            studio=studio,
            publisher="",
            thumb=cover_url,
            poster=cover_url.replace("big_pic", "small_pic"),
            extrafanart=[],
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
