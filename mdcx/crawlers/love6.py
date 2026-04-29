#!/usr/bin/env python3
import re
from dataclasses import dataclass

from lxml import etree
from parsel import Selector

from ..config.models import Website
from ..models.types import CrawlerInput
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def get_web_number(html, number):
    result = html.xpath("//dt[contains(text(),'作品番号')]/following-sibling::dd/text()")
    return result[0].strip() if result else number


def get_title(
    html,
    title,
    number,
    actors,
):
    if not title:
        result = html.xpath("//title/text()")
        if result:
            title = result[0].replace(number, "")
            for actor in actors:
                title = title.replace(actor, "")
            number_123 = re.findall(r"\d+", number)
            for each in number_123:
                title = title.replace(each, "")
    return title.strip()


def get_actor(html):
    actor_list = html.xpath('//div[@class="video_description"]/a[contains(@href, "performer/")]/text()')
    actor_new_list = []
    for a in actor_list:
        if a.strip():
            actor_new_list.append(a.strip())
    return ",".join(actor_new_list)


def get_studio(html):
    result = html.xpath("string(//div[@class='tag_box d-flex flex-wrap p-1 col-12 mb-1']/a[@title='片商'])")
    return result.strip()


def get_extrafanart(html):
    result = html.xpath('//div[@id="stills"]/div/img/@src')
    for i in range(len(result)):
        result[i] = "https://lulubar.net" + result[i]
    return result


def get_release(html):
    result = html.xpath('//div[@class="video_description"]/span[contains(text(), "發行時間")]/text()')
    return result[0].replace("發行時間: ", "").strip() if result else ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_mosaic(html):
    result = html.xpath('//div[@class="tag_box d-flex flex-wrap p-1 col-12 mb-1"]/a[@class="tag"]/text()')
    total = ",".join(result)
    mosaic = ""
    if "有码" in total:
        mosaic = "有码"
    elif "国产" in total:
        mosaic = "国产"
    elif "无码" in total:
        mosaic = "无码"
    return mosaic


def get_tag(html):
    result = html.xpath('//div[@class="kv_tag"]/a/text()')
    new_list = []
    for a in result:
        new_list.append(a.strip())
    return ",".join(new_list)


def get_cover(html_content):
    result = re.findall(r"background-image: url\('([^']+)", html_content)
    cover = result[0] if result else ""
    return cover


def get_outline(html):
    a = html.xpath('//div[@class="kv_description"]/text()')
    return a[0].strip() if a else ""


def get_real_url(html):
    title = ""
    real_url = ""
    poster_url = ""
    result = html.xpath('//div[@class="col-sm-2 search_item"]')
    for each in result:
        each_title = each.xpath('a/div[@class="album_text"]/text()')
        each_href = each.xpath("a/@href")
        each_poster = each.xpath('a/div[@class="search_img"]/img/@src')
        if each_title and each_href:
            title = each_title[0]
            real_url = "https://love6.tv" + each_href[0]
            poster_url = each_poster[0] if each_poster else ""
        break
    return title, real_url, poster_url


def get_webnumber(html, number):
    number_list = html.xpath('//div[@class="video_description"]/span[contains(text(), "番號")]/text()')
    return number_list[0].replace("番號 : ", "").strip() if number_list else number


@dataclass
class Love6Context(Context):
    search_title: str = ""
    search_poster: str = ""


class Love6Crawler(BaseCrawler):
    @classmethod
    def site(cls) -> Website:
        return Website.LOVE6

    @classmethod
    def base_url_(cls) -> str:
        return "https://love6.tv"

    def new_context(self, input: CrawlerInput) -> Love6Context:
        return Love6Context(input=input)

    async def _generate_search_url(self, ctx: Love6Context) -> list[str] | str | None:
        return f"{self.base_url}/search/all/?search_text={ctx.input.number}"

    async def _parse_search_page(self, ctx: Love6Context, html: Selector, search_url: str) -> list[str] | str | None:
        search_page = etree.fromstring(html.get(), etree.HTMLParser())
        title, detail_url, poster = get_real_url(search_page)
        if not detail_url:
            ctx.debug("love6 搜索页没有匹配结果")
            return None
        ctx.search_title = title
        ctx.search_poster = poster
        return [detail_url]

    async def _parse_detail_page(self, ctx: Love6Context, html: Selector, detail_url: str) -> CrawlerData | None:
        html_content = html.get()
        html_info = etree.fromstring(html_content, etree.HTMLParser())
        number = get_webnumber(html_info, ctx.input.number)
        actor = get_actor(html_info)
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        title = get_title(html_info, ctx.search_title, number, actors)
        if not title:
            raise CralwerException("数据获取失败: 未获取到标题")
        tag = get_tag(html_info)
        release = get_release(html_info)
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=get_outline(html_info),
            originalplot="",
            tags=[item.strip() for item in tag.split(",") if item.strip()],
            release=release,
            year=get_year(release),
            thumb=get_cover(html_content),
            poster=ctx.search_poster,
            extrafanart=[],
            trailer="",
            image_download=False,
            image_cut="",
            mosaic="",
            external_id=detail_url,
        )
