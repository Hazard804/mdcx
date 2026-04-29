#!/usr/bin/env python3
import re
from typing import override

from lxml import etree

from ..config.enums import Website
from ..config.manager import manager
from .base import BaseCrawler, Context, CralwerException, CrawlerData

_SUPPORTED_LANGUAGES = {"zh_cn", "zh_tw", "jp"}
_OUTLINE_PREFIX_PATTERN = re.compile(r"^(?:简介|簡介|介绍|介紹|紹介)\s*[:：]?\s*")


def get_title(html):
    result = html.xpath('//h1[@class="h4 b"]/text()')
    result = str(result[0]).strip() if result else ""
    # 去掉无意义的简介(马赛克破坏版)，'克破'两字简繁同形
    if not result or "克破" in result:
        return ""
    return result


def get_real_title(title):
    temp_t = title.strip(" ").split(" ")
    if len(temp_t) > 1 and len(temp_t[-1]) < 5:
        temp_t.pop()
    return " ".join(temp_t).strip()


def getWebNumber(title, number):
    result = title.split(" ")
    result = result[-1] if len(result) > 1 else number.upper()
    return (
        result.replace("_1pondo_", "")
        .replace("1pondo_", "")
        .replace("caribbeancom-", "")
        .replace("caribbeancom", "")
        .replace("-PPV", "")
        .strip(" _-")
    )


def getActor(html):
    actor_list = html.xpath('//a[contains(@href, "actor")]/span/text()')
    result = ",".join(actor_list) if actor_list else ""
    return result


def getCover(html):
    result = html.xpath('//meta[@property="og:image"]/@content')
    result = result[0] if result else ""
    return result


def getOutline(html):
    result = "".join(html.xpath('//div[contains(@class, "intro")]//p//text()')).strip()
    if not result:
        result = html.xpath(
            'string(//p[contains(., "简介") or contains(., "簡介") or contains(., "介绍")'
            ' or contains(., "介紹") or contains(., "紹介")])'
        )
    result = str(result).strip() if result else ""
    # 去掉无意义的简介(马赛克破坏版)，'克破'两字简繁同形
    if not result or "克破" in result:
        return ""
    else:
        # 去除简介中的无意义信息，中间和首尾的空白字符、简介两字、*根据分发等
        result = re.sub(r"[\r\n\t]", "", result)
        result = _OUTLINE_PREFIX_PATTERN.sub("", result)
        result = result.split("*根据分发", 1)[0].strip()
    return result


def getRelease(html):
    result = html.xpath('//div[@class="date"]/text()')
    result = result[0].replace("/", "-").strip() if result else ""
    return result


def getYear(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release[:4]


def getTag(html):
    tag_list = html.xpath('//div[contains(@class,"tag-info")]//a[contains(@href, "tag")]/text()')
    result = (",".join(tag_list) if tag_list else "") if tag_list else ""
    return result


def getMosaic(tag):
    mosaic = "无码" if "无码" in tag or "無碼" in tag or "無修正" in tag else "有码"
    return mosaic


def getStudio(html):
    result = html.xpath('//a[contains(@href, "fac")]/div[@itemprop]/text()')
    result = result[0].strip() if result else ""
    return result


def getRuntime(html):
    result = html.xpath('//meta[@itemprop="duration"]/@content')
    if result:
        result = result[0].strip().split(":")
        if len(result) == 3:
            result = int(int(result[0]) * 60 + int(result[1]) + int(result[2]) / 60)
    else:
        result = ""
    return str(result)


def get_series(html):
    result = html.xpath('//a[contains(@href, "series")]/text()')
    result = result[0] if result else ""
    return result


def get_extrafanart(html):
    extrafanart_list = html.xpath('//div[@class="cover"]//img[@src]/@data-src')
    return extrafanart_list


def get_real_url(html, number):
    number = number.replace("FC2", "").replace("-PPV", "")
    # 非 fc2 影片前面加入空格，可能会导致识别率降低
    # if not re.search(r'\d+[-_]\d+', number):
    #     number1 = ' ' + number.replace('FC2', '').replace('-PPV', '')
    item_list = html.xpath('//span[@class="title"]')
    for each in item_list:
        detail_url = each.xpath("./a/@href")[0]
        title = each.xpath("./a/@title")[0]
        # 注意去除马赛克破坏版等几乎没有有效字段的条目
        if number.upper() in title and all(
            keyword not in title for keyword in ["克破", "无码破解", "無碼破解", "无码流出", "無碼流出"]
        ):
            return detail_url
    return ""


def _normalize_language(language: str) -> str:
    return language if language in _SUPPORTED_LANGUAGES else "zh_cn"


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class IqqtvCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.IQQTV

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.IQQTV, "https://iqq5.xyz")

    def _language_base_url(self, language: str) -> str:
        if language == "zh_cn":
            return self.base_url + "/cn/"
        if language == "zh_tw":
            return self.base_url + "/"
        return self.base_url + "/jp/"

    async def _fetch_language(self, ctx: Context, number: str, appoint_url: str, language: str) -> CrawlerData:
        language = _normalize_language(language)
        if not re.match(r"n\d{4}", number):
            number = number.upper()
        real_url = appoint_url or ""
        iqqtv_url = self._language_base_url(language)
        image_cut = "right"
        image_download = False
        if not real_url:
            url_search = iqqtv_url + "search.php?kw=" + number
            ctx.debug(f"搜索地址: {url_search}")
            if ctx.debug_info.search_urls is None:
                ctx.debug_info.search_urls = []
            ctx.debug_info.search_urls.append(url_search)
            html_search, error = await self.async_client.get_text(url_search)
            if html_search is None:
                raise CralwerException(f"网络请求错误: {error}")
            html = etree.fromstring(html_search, etree.HTMLParser())
            real_url = html.xpath('//a[@class="ga_click"]/@href')
            if real_url:
                real_url_tmp = get_real_url(html, number)
                real_url = iqqtv_url + real_url_tmp.replace("/cn/", "").replace("/jp/", "").replace("&cat=19", "")
            else:
                raise CralwerException("搜索结果: 未匹配到番号！")
        else:
            real_url = iqqtv_url + re.sub(r".*player", "player", appoint_url)

        ctx.debug(f"番号地址: {real_url}")
        html_content, error = await self.async_client.get_text(real_url)
        if html_content is None:
            raise CralwerException(f"网络请求错误: {error}")
        html_info = etree.fromstring(html_content, etree.HTMLParser())

        title = get_title(html_info)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        web_number = getWebNumber(title, number)
        title = title.replace(f" {web_number}", "").strip()
        actor = getActor(html_info)
        title = get_real_title(title)
        cover_url = getCover(html_info)
        outline = getOutline(html_info)
        release = getRelease(html_info)
        tag = getTag(html_info)
        mosaic = getMosaic(tag)
        if mosaic == "无码":
            image_cut = "center"
        studio = getStudio(html_info)
        tag = tag.replace("无码片", "").replace("無碼片", "").replace("無修正", "")
        return CrawlerData(
            number=web_number,
            title=title,
            originaltitle=title,
            actors=split_csv(actor),
            outline=outline,
            originalplot=outline,
            tags=split_csv(tag),
            release=release,
            year=getYear(release),
            runtime="",
            score="",
            series=get_series(html_info),
            directors=[],
            studio=studio,
            publisher=studio,
            thumb=cover_url,
            poster="",
            extrafanart=get_extrafanart(html_info),
            trailer="",
            image_download=image_download,
            image_cut=image_cut,
            mosaic=mosaic,
            external_id=real_url,
            wanted="",
        )

    @override
    async def _run(self, ctx: Context):
        language = _normalize_language(getattr(ctx.input.language, "value", str(ctx.input.language)))
        appoint_url = ctx.input.appoint_url.replace("/cn/", "/jp/").replace(
            "iqqtv.cloud/player", "iqqtv.cloud/jp/player"
        )
        jp_data = await self._fetch_language(ctx, ctx.input.number, appoint_url, "jp")
        if language == "jp":
            data = jp_data
        else:
            zh_url = jp_data.external_id.replace("/jp/", "/cn/" if language == "zh_cn" else "/")
            data = await self._fetch_language(ctx, ctx.input.number, zh_url, language)
            data.originaltitle = jp_data.originaltitle
            data.originalplot = jp_data.originalplot

        result = data.to_result()
        result.source = self.site().value
        ctx.debug_info.detail_urls = [data.external_id]
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
