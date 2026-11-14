#!/usr/bin/env python3
import re
from typing import override

from lxml import etree
from parsel import Selector

from ..config.models import Website
from ..models.types import CrawlerResult
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def get_web_number(html, number):
    result = html.xpath("//dt[contains(text(),'作品番号')]/following-sibling::dd/text()")
    return result[0].strip() if result else number


def get_title(html):
    result = html.xpath('//div[@id="works_pic"]/ul/li/h5/text()')
    return result[0].strip() if result else ""


def get_actor(html):
    try:
        actor_list = html.xpath('//span[@class="yaku"]/a/text()')
        result = ",".join(actor_list)
    except Exception:
        result = ""
    return result


def get_director(html):
    result = html.xpath("string(//dt[contains(text(),'監督')]/following-sibling::dd)")
    return result


def get_extrafanart(html):
    result = html.xpath('//div[@class="gasatsu_images_pc"]/div/div/a/@href')
    for i in range(len(result)):
        result[i] = "https://www.giga-web.jp" + result[i]
    return result


def get_release(html):
    result = html.xpath("//dt[contains(text(),'リリース')]/following-sibling::dd/text()")
    return result[0].replace("/", "-") if result else ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_runtime(html):
    result = html.xpath("//dt[contains(text(),'収録時間')]/following-sibling::dd/text()")
    if result:
        result = re.findall(r"\d+", result[0])
    return result[0] if result else ""


def get_score(html):
    result = re.findall(r"5点満点中 <b>(.+)<", html)
    return result[0] if result else ""


def get_tag(html):
    result = html.xpath('//div[@id="tag_main"]/a/text()')
    return ",".join(result) if result else ""


async def get_trailer(client, real_url):
    # https://www.giga-web.jp/product/index.php?product_id=6841
    # https://www.giga-web.jp/product/player_sample.php?id=6841&q=h
    url = real_url.replace("index.php?product_id=", "player_sample.php?id=") + "&q=h"
    html, error = await client.get_text(url)
    result = []
    if html is not None:
        # <source src="https://cdn-dl.webstream.ne.jp/gigadlcdn/dl/X4baSNNrcDfRdCiSN4we_s_sample/ghov28_6000.mp4" type='video/mp4'>
        result = re.findall(r'<source src="([^"]+)', html)
    return result[0] if result else ""


def get_cover(html):
    result = html.xpath('//div[@class="smh"]/li/ul/li/a/@href')
    cover = result[0].replace("http://", "https://") if result else ""
    result = html.xpath('//div[@class="smh"]/li/ul/li/a/img/@src')
    poster = result[0] if result else cover.replace("pac_l", "pac_s")
    if not poster:  # tre-82
        result = html.xpath('//div[@class="smh"]/li/img/@src')
        poster = result[0] if result else ""
        cover = poster.replace("pac_s", "pac_l")
    return poster, cover


def get_outline(html):
    a = html.xpath('//div[@id="story_list2"]/ul/li[@class="story_window"]/text()')
    a = a[0].replace("[BAD END]", "").strip() if a else ""
    b = html.xpath('//div[@id="eye_list2"]/ul/li[@class="story_window"]/text()')
    b = b[0].replace("[BAD END]", "").strip() if b else ""
    return (a + "\n" + b).strip()


def get_real_url(html, number):
    result = html.xpath('//div[@class="search_sam_box"]')
    for each in result:
        href = each.xpath("a/@href")
        title = each.xpath("string()")
        if f"（{number.upper()}）" in title and href:
            return "https://www.giga-web.jp" + href[0]
    return ""


class GigaCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.GIGA

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.giga-web.jp"

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return f"{self.base_url}/search/?keyword={ctx.input.number}"

    async def _get_with_cookie(self, url: str) -> tuple[str | None, str]:
        """
        请求页面并处理站点的 cookie 门禁.

        站点首次访问会返回年龄确认页(内含 /cookie_set.php), 需要先访问该地址写入 cookie 再重试;
        搜索页与详情页都可能遇到, 因此统一在此处理, 避免「指定网址」直刮详情页时拿不到数据.
        """
        html, error = await self.async_client.get_text(url)
        if html is None:
            return None, error
        if "/cookie_set.php" in html:
            # 该地址返回 302 并下发 cookie, 不需要跟随跳转
            await self.async_client.request("GET", f"{self.base_url}/cookie_set.php", allow_redirects=False)
            html, error = await self.async_client.get_text(url)
        return html, error

    @override
    async def _fetch(self, ctx: Context, url: str, use_browser: bool | None) -> tuple[str | None, str]:
        if use_browser is True:
            return None, "当前版本已移除浏览器请求模式"
        return await self._get_with_cookie(url)

    @override
    async def _fetch_search(self, ctx: Context, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        return await self._fetch(ctx, url, use_browser)

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        detail_url = get_real_url(search_page, ctx.input.number)
        if not detail_url:
            ctx.debug("giga 搜索页没有匹配结果")
            return None
        return [detail_url]

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        html_content = html.get()
        detail_page = etree.fromstring(html_content, etree.HTMLParser())
        title = get_title(detail_page)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        number = get_web_number(detail_page, ctx.input.number)
        actor = get_actor(detail_page)
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        tag = get_tag(detail_page)
        director = get_director(detail_page)
        directors = [item.strip() for item in director.split(",") if item.strip()]
        release = get_release(detail_page)
        poster, cover_url = get_cover(detail_page)
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            directors=directors,
            outline=get_outline(detail_page),
            originalplot=get_outline(detail_page),
            tags=[item.strip() for item in tag.split(",") if item.strip()],
            release=release,
            year=get_year(release),
            runtime=get_runtime(detail_page),
            score=get_score(html_content),
            series="",
            studio="GIGA",
            publisher="GIGA",
            thumb=cover_url,
            poster=poster,
            extrafanart=get_extrafanart(detail_page),
            trailer=await get_trailer(self.async_client, detail_url),
            image_download=True,
            mosaic="有码",
            external_id=detail_url,
        )

    @override
    async def post_process(self, ctx: Context, res: CrawlerResult) -> CrawlerResult:
        """
        封面大图兜底.

        站点部分作品只提供 pac_s 小图, 由小图推导出的 pac_l 大图会返回 404;
        直接使用会导致缩略图下载失败(整条任务被标记失败), 因此探活后回退到小图.
        """
        cover = str(res.thumb or "").strip()
        if cover and cover != res.poster:
            response, error = await self.async_client.request("HEAD", cover)
            content_type = str(response.headers.get("Content-Type", "")).lower() if response is not None else ""
            if response is None or response.status_code != 200 or not content_type.startswith("image/"):
                ctx.debug(f"封面大图不可用, 回退小图: {cover} ({error or response.status_code})")
                res.thumb = res.poster or ""
        return res
