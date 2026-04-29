#!/usr/bin/env python3
import re
from typing import override

from lxml import etree

from ..base.web import check_url
from ..config.enums import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData

seesaawiki_request_fail_flag = False


def get_title(html):
    result = html.xpath("//head/title/text()")
    if result:
        number, title = re.findall(r"(No\.\d*)(.*)", result[0])[0]
        return number, title.strip()
    return "", ""


def get_first_url(html, key):
    result = html.xpath('//h2[@class="heading heading-secondary"]/a/@href')
    temp_key = f"no{key}"
    for each in result:
        if temp_key in each:
            return each
    return ""


def get_second_url(html):
    result = html.xpath(
        '//a[@class="wp-block-button__link has-luminous-vivid-amber-to-luminous-vivid-orange-gradient-background has-background"]/@href'
    )
    return result[0] if result else ""


def get_cover(html):
    result = html.xpath('//video[@id="video"]')
    if result:
        cover_url = result[0].get("poster")
        if not cover_url.startswith("http"):
            cover_url = "https:" + cover_url
        trailer = result[0].get("src")
        return cover_url, trailer
    return "", ""


def get_outline(html):
    result = html.xpath('normalize-space(string(//div[@class="modelsamplephototop"]))')
    return result.strip()


def get_actor(html):
    result = html.xpath('//div[@class="modelwaku0"]/img/@alt')
    return result[0] if result else ""


def get_extrafanart(html):
    return html.xpath("//div[@class='modelsample_photowaku']/img/@src")


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class MywifeCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.MYWIFE

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://mywife.cc"

    async def get_wiki_data(self):
        url = "https://seesaawiki.jp/av_neme/d/%C9%F1%A5%EF%A5%A4%A5%D5"
        html_search, error = await self.async_client.get_text(url, encoding="euc-jp")
        if html_search is None:
            return False
        try:
            html = etree.fromstring(html_search, etree.HTMLParser())
            mywife_data = html.xpath("//div[@class='wiki-section-3']")
            mywife_dic = {}
            for each in mywife_data:
                number_id = each.xpath("div/h5/text()")
                if not number_id or "No." not in number_id[0]:
                    continue
                number_id = number_id[0].replace("No.", "").strip()
                href = each.xpath("div[@class='wiki-section-body-3']/a/@href")
                if not href or len(href) < 2:
                    continue
                poster, website = href[0], href[1]
                actor = each.xpath("div[@class='wiki-section-body-3']/span/a/text()")
                if not actor:
                    actor = each.xpath("div[@class='wiki-section-body-3']/a[@rel='nofollow']/text()")
                if actor:
                    actor = actor[0]
                mywife_dic[number_id] = {
                    "number": number_id,
                    "actor": actor,
                    "poster": poster,
                    "website": website,
                }
            return mywife_dic
        except Exception:
            return False

    async def get_number_data(self, number):
        global seesaawiki_request_fail_flag
        mywife_data = await self.get_wiki_data()
        if not mywife_data:
            seesaawiki_request_fail_flag = True
            return False
        return mywife_data.get(str(number))

    @override
    async def _run(self, ctx: Context):
        global seesaawiki_request_fail_flag
        number = ctx.input.number
        real_url = ctx.input.appoint_url
        key = re.findall(r"NO\.(\d*)", number.upper())
        key = key[0] if key else ""
        if not key:
            key_match = re.findall(r"\d{3,}", number)
            if key_match:
                key = key_match[0]
                if int(key) >= 1450:
                    real_url = f"{self.base_url}/teigaku/model/no/{key}"
        if not key:
            raise CralwerException(f"番号中未识别到三位及以上数字: {number}")

        actor = ""
        poster = ""
        req_wiki_data = False
        number_data = None

        if not real_url:
            req_wiki_data = True
            ctx.debug("请求 seesaawiki.jp 数据...")
            number_data = await self.get_number_data(key)
            if number_data:
                number = number_data["number"]
                actor = number_data["actor"]
                poster = number_data["poster"]
                real_url = number_data["website"]
                if "mywife.cc" not in real_url:
                    web_url = await check_url(real_url, real_url=True)
                    real_url = re.sub(r"\?.*$", "", web_url) if web_url else ""

        if not real_url:
            if not number_data:
                debug_info = "seesaawiki.jp 暂未收录该番号！当前尝试使用官网搜索查询..."
                if seesaawiki_request_fail_flag:
                    debug_info = (
                        "seesaawiki.jp 获取数据失败！无法获取真实演员名字！建议更换代理！当前尝试使用官网搜索查询..."
                    )
            else:
                debug_info = "track.bannerbridge.net 无法访问！无法快速获取官网详情页地址！建议更换代理！当前尝试使用官网搜索查询..."
            ctx.debug(debug_info)

            search_url = f"https://mywife.jp/?s={key}"
            ctx.debug(f"搜索页地址: {search_url}")
            ctx.debug_info.search_urls = [search_url]
            html_content, error = await self.async_client.get_text(search_url)
            if html_content is None:
                raise CralwerException(f"网络请求错误: {error}")
            html_info = etree.fromstring(html_content, etree.HTMLParser())
            first_url = get_first_url(html_info, key)

            if first_url:
                ctx.debug(f"中间页地址: {first_url}")
                html_content, error = await self.async_client.get_text(first_url)
                if html_content is None:
                    raise CralwerException(f"网络请求错误: {error}")
                html_info = etree.fromstring(html_content, etree.HTMLParser())
                real_url = get_second_url(html_info)
                if not real_url:
                    raise CralwerException(f"中间页未获取到详情页地址！ {first_url}")
            else:
                ctx.debug(f"搜索页未获取到匹配数据！ {search_url}")
                ctx.debug("尝试拼接番号地址")
                real_url = f"{self.base_url}/teigaku/model/no/{key}"

        ctx.debug(f"番号地址: {real_url}")
        ctx.debug_info.detail_urls = [real_url]
        html_content, error = await self.async_client.get_text(real_url)
        if html_content is None:
            raise CralwerException(f"网络请求错误: {error}")
        html_info = etree.fromstring(html_content, etree.HTMLParser())
        number, title = get_title(html_info)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        if not actor:
            actor = get_actor(html_info)
        cover_url, trailer = get_cover(html_info)
        if not poster:
            poster = cover_url.replace("topview.jpg", "thumb.jpg")

        if not req_wiki_data:
            ctx.debug("请求 seesaawiki.jp 获取真实演员...")
            key = number.replace("No.", "")
            number_data = await self.get_number_data(key)
            if number_data:
                actor = number_data["actor"]
                poster = number_data["poster"]

        data = CrawlerData(
            number=f"Mywife {number}",
            title=title,
            originaltitle=title,
            actors=split_csv(actor),
            outline=get_outline(html_info),
            originalplot=get_outline(html_info),
            tags=[],
            release="",
            year="",
            runtime="",
            score="",
            series="",
            directors=[],
            studio="舞ワイフ",
            publisher="舞ワイフ",
            thumb=cover_url,
            poster=poster,
            extrafanart=get_extrafanart(html_info),
            trailer=trailer,
            image_download=True,
            image_cut="",
            mosaic="有码",
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
