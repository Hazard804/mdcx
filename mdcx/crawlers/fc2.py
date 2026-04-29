#!/usr/bin/env python3
import json
import re
from typing import override

from lxml import etree

from ..config.enums import FieldRule, Website
from ..config.manager import manager
from ..signals import signal
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def getTitle(html):  # 获取标题
    result = html.xpath('//div[@data-section="userInfo"]//h3/span/../text()')
    result = " ".join(result).strip() if result else ""
    return result


def getPageTitle(html):  # 获取页面标题
    result = html.xpath("string(//title)")
    result = re.sub(r"\s+", " ", result).strip()
    return result


def isNotFoundPage(html):  # 判断是否为无结果页
    page_title = getPageTitle(html)
    if "お探しの商品が見つかりませんでした" in page_title:
        return True
    if html.xpath('//div[contains(@class, "items_notfound_header")]'):
        return True
    result = html.xpath('string(//div[contains(@class, "items_notfound_header")])')
    result = re.sub(r"\s+", " ", result).strip()
    return "お探しの商品が見つかりませんでした" in result


def isDetailPage(html):  # 判断是否成功进入详情页
    return bool(
        html.xpath('//section[contains(@class, "items_article_wrapper")]')
        and html.xpath('//div[@data-section="userInfo"]')
    )


def getCover(html):  # 获取封面
    extrafanart = html.xpath('//ul[@class="items_article_SampleImagesArea"]/li/a/@href')
    if extrafanart:
        extrafanart = [f"https:{x}" for x in extrafanart]
        result = extrafanart[0]
    else:
        result = ""
    return result, extrafanart


def getCoverSmall(html):  # 获取小图
    result = html.xpath('//div[@class="items_article_MainitemThumb"]/span/img/@src')
    result = "https:" + result[0] if result else ""
    return result


def getRelease(html):
    result = html.xpath('//div[@class="items_article_Releasedate"]/p/text()')
    if not result:
        result = html.xpath('//div[contains(@class, "items_article_softDevice")]/p/text()')
    result = re.findall(r"\d+/\d+/\d+", str(result))
    result = result[0].replace("/", "-") if result else ""
    return result


def getStudio(html):  # 使用卖家作为厂家
    result = html.xpath('//div[@class="items_article_headerInfo"]/ul/li[last()]/a/text()')
    result = result[0].strip() if result else ""
    return result


def getTag(html):  # 获取标签
    result = html.xpath('//a[@class="tag tagTag"]/text()')
    result = str(result).strip(" ['']").replace("', '", ",")
    return result


def getOutline(html):  # 获取简介
    result = html.xpath(
        '//section[contains(@class, "items_article_Contents")]//text()[not(ancestor::script) and not(ancestor::iframe)]'
    )
    result = [re.sub(r"\s+", " ", x).strip() for x in result if x and x.strip()]
    result = [
        x
        for x in result
        if x
        not in {
            "商品説明",
            "商品说明",
            "商品說明",
            "Product description",
            "Description",
            "もっとみる",
            "See more",
            "查看更多",
            "查看更多內容",
        }
    ]
    outline = "\n".join(dict.fromkeys(result)).strip()
    if not outline:
        return ""
    if outline.startswith(("FC2-PPV-", "FC2 PPV ", "FC2-")):
        return ""
    if any(x in outline for x in ("本作品はFC2", "18歳未満", "出演承諾書類", "年齢確認書類")):
        return ""
    return outline


def getRuntime(html):  # 获取时长（分钟）
    result = html.xpath('string(//p[@class="items_article_info"])').strip()
    if not result or ":" not in result:
        return ""
    temp_list = result.split(":")
    runtime = ""
    if len(temp_list) == 3:
        runtime = int(temp_list[0]) * 60 + int(temp_list[1])
    elif len(temp_list) <= 2:
        runtime = int(temp_list[0])
    return str(runtime)


def getScore(html):  # 获取评分
    result = html.xpath('//script[@type="application/ld+json"]/text()')
    for each in result:
        each = each.strip()
        if not each:
            continue
        try:
            data = json.loads(each)
        except Exception:
            continue
        if isinstance(data, dict):
            data_list = [data]
        elif isinstance(data, list):
            data_list = data
        else:
            continue
        for item in data_list:
            if not isinstance(item, dict):
                continue
            aggregate_rating = item.get("aggregateRating")
            if not isinstance(aggregate_rating, dict):
                continue
            score = aggregate_rating.get("ratingValue")
            if score not in [None, ""]:
                return str(score)
    return ""


async def getTrailer(client, number):  # 获取预告片
    # FC2 sample 接口返回的是带 mid 参数的临时直链，适合立即下载，不适合长期固化。
    # 注意 path 上的 mid 参数不能丢，否则直链会返回 403。
    req_url = f"https://adult.contents.fc2.com/api/v2/videos/{number}/sample"
    response, error = await client.get_text(req_url)
    if response is None:
        return ""
    try:
        data = json.loads(response)
    except Exception:
        return ""

    trailer_url = data.get("path")
    if isinstance(trailer_url, str) and trailer_url.startswith("http"):
        return trailer_url
    return ""


def getMosaic(tag, title):  # 获取马赛克
    result = "无码" if "無修正" in tag or "無修正" in title else "有码"
    return result


def normalize_fc2_number(number: str) -> str:
    return number.upper().replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Fc2Crawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.FC2

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://adult.contents.fc2.com"

    @override
    async def _run(self, ctx: Context):
        number = normalize_fc2_number(ctx.input.number)
        real_url = ctx.input.appoint_url or f"{self.base_url}/article/{number}/"
        ctx.debug(f"番号地址: {real_url}")
        ctx.debug_info.detail_urls = [real_url]

        html_content, error = await self.async_client.get_text(real_url)
        if html_content is None:
            raise CralwerException(f"网络请求错误: {error}")
        html_info = etree.fromstring(html_content, etree.HTMLParser())

        if isNotFoundPage(html_info):
            raise CralwerException("搜索结果: 未匹配到番号！")
        if not isDetailPage(html_info):
            raise CralwerException("数据获取失败: 未进入影片详情页！")

        title = getTitle(html_info)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")

        cover_url, extrafanart = getCover(html_info)
        if "http" not in cover_url:
            raise CralwerException("数据获取失败: 未获取到cover！")

        tag = getTag(html_info)
        release = getRelease(html_info)
        trailer = await getTrailer(self.async_client, number)
        ctx.debug("预告片: 已获取到带时效参数的临时链接" if trailer else "预告片: 未获取到临时下载链接")
        if trailer:
            signal.add_log("🟡 FC2 预告片链接带时效参数，仅适合立即下载，不建议长期复用远程链接。")

        studio = getStudio(html_info)
        actor = studio if FieldRule.FC2_SELLER in manager.config.fields_rule else ""
        tag = tag.replace("無修正,", "").replace("無修正", "").strip(",")
        data = CrawlerData(
            number="FC2-" + str(number),
            title=title,
            originaltitle=title,
            actors=split_csv(actor),
            outline=getOutline(html_info),
            originalplot=getOutline(html_info),
            tags=split_csv(tag),
            release=release,
            year=release[:4],
            runtime=getRuntime(html_info),
            score=getScore(html_info),
            series="FC2系列",
            directors=[],
            studio=studio,
            publisher=studio,
            thumb=cover_url,
            poster=getCoverSmall(html_info),
            extrafanart=extrafanart,
            trailer=trailer,
            image_download=False,
            image_cut="center",
            mosaic=getMosaic(tag, title),
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
