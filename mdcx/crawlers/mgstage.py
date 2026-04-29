#!/usr/bin/env python3
import re
from typing import override

from lxml import etree
from parsel import Selector

from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def getTitle(html):
    try:
        result = str(html.xpath('//*[@id="center_column"]/div[1]/h1/text()')).strip(" ['']")
        return result.replace("/", ",")
    except Exception:
        return ""


def getActor(html):
    result = (
        str(html.xpath('//th[contains(text(),"出演")]/../td/a/text()'))
        .replace("\\n", "")
        .strip(" ['']")
        .replace("/", ",")
        .replace("'", "")
        .replace(" ", "")
    )
    if not result:
        result = (
            str(html.xpath('//th[contains(text(),"出演")]/../td/text()'))
            .replace("\\n", "")
            .strip(" ['']")
            .replace("/", ",")
            .replace("'", "")
            .replace(" ", "")
        )
    return result


def getStudio(html):
    result1 = str(html.xpath('//th[contains(text(),"メーカー：")]/../td/a/text()')).strip(" ['']")
    result2 = str(html.xpath('//th[contains(text(),"メーカー：")]/../td/text()')).strip(" ['']")
    return str(result1 + result2).replace("'", "").replace(" ", "").replace("\\n", "")


def getPublisher(html):
    result1 = str(html.xpath('//th[contains(text(),"レーベル：")]/../td/a/text()')).strip(" ['']")
    result2 = str(html.xpath('//th[contains(text(),"レーベル：")]/../td/text()')).strip(" ['']")
    return str(result1 + result2).replace("'", "").replace(" ", "").replace("\\n", "")


def getRuntime(html):
    result1 = str(html.xpath('//th[contains(text(),"収録時間：")]/../td/a/text()')).strip(" ['']")
    result2 = str(html.xpath('//th[contains(text(),"収録時間：")]/../td/text()')).strip(" ['']")
    return str(result1 + result2).rstrip("min").replace("'", "").replace(" ", "").replace("\\n", "")


def getSeries(html):
    result1 = str(html.xpath('//th[contains(text(),"シリーズ：")]/../td/a/text()')).strip(" ['']")
    result2 = str(html.xpath('//th[contains(text(),"シリーズ：")]/../td/text()')).strip(" ['']")
    return str(result1 + result2).replace("'", "").replace(" ", "").replace("\\n", "")


def getNum(html):
    result1 = str(html.xpath('//th[contains(text(),"品番：")]/../td/a/text()')).strip(" ['']")
    result2 = str(html.xpath('//th[contains(text(),"品番：")]/../td/text()')).strip(" ['']")
    return str(result1 + result2).replace("'", "").replace(" ", "").replace("\\n", "")


def getYear(getRelease):
    try:
        result = str(re.search(r"\d{4}", getRelease).group())
        return result
    except Exception:
        return getRelease


def getRelease(html):
    result1 = str(html.xpath('//th[contains(text(),"配信開始日：")]/../td/a/text()')).strip(" ['']")
    result2 = str(html.xpath('//th[contains(text(),"配信開始日：")]/../td/text()')).strip(" ['']")
    return str(result1 + result2).replace("'", "").replace(" ", "").replace("\\n", "")


def getTag(html):
    result1 = str(html.xpath('//th[contains(text(),"ジャンル：")]/../td/a/text()')).strip(" ['']")
    result2 = str(html.xpath('//th[contains(text(),"ジャンル：")]/../td/text()')).strip(" ['']")
    return str(result1 + result2).replace("'", "").replace(" ", "").replace("\\n", "")


def getCoverSmall(cover_url):
    result = cover_url.replace("/pb_", "/pf_")
    return result


def getCover(html):
    result = str(html.xpath('//a[@id="EnlargeImage"]/@href')).strip(" ['']")
    return result


def getExtraFanart(html):
    extrafanart_list = html.xpath("//dl[@id='sample-photo']/dd/ul/li/a[@class='sample_image']/@href")
    return extrafanart_list


async def get_trailer(client, html):
    trailer = ""
    play_url = html.xpath("//a[@class='review-btn']/@href")
    if play_url:
        play_url = play_url[0].replace("/mypage/review.php", "/sampleplayer/sampleRespons.php")
        htmlcode, error = await client.get_json(play_url, cookies={"adc": "1"})
        if htmlcode is not None:
            url_str = htmlcode.get("url")
            if url_str:
                url_temp = re.search(r"(https.+)ism/request", str(url_str))
                if url_temp:
                    trailer = url_temp.group(1) + "mp4"
    return trailer


def getOutline(html):
    result = str(html.xpath('//*[@id="introduction"]/dd/p[1]/text()')).strip(" ['']")
    if not result:
        temp = html.xpath('//*[@id="introduction"]/dd')
        result = temp[0].xpath("string(.)").replace(" ", "").strip() if temp else ""
    return result


def getScore(html):
    result = html.xpath('//td[@class="review"]/span/@class')
    if result:
        result = f"{int(result[0].replace('star_', '')[:2]) / 10:.1f}"
    return str(result)


def remove_number_leading_zero(number: str) -> str:
    if not number:
        return ""
    normalized = number.upper().strip()
    if not (matched := re.fullmatch(r"([A-Z0-9]+)-0+(\d+)", normalized)):
        return normalized
    return f"{matched[1]}-{matched[2]}"


def build_candidate_numbers(number: str, short_number: str) -> list[str]:
    candidates = []
    for each in [
        remove_number_leading_zero(number),
        remove_number_leading_zero(short_number),
        (number or "").upper().strip(),
        (short_number or "").upper().strip(),
    ]:
        if each and each not in candidates:
            candidates.append(each)
    return candidates


class MgstageCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.MGSTAGE

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.mgstage.com"

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        candidate_numbers = build_candidate_numbers(ctx.input.number.upper(), ctx.input.short_number.upper())
        if len(candidate_numbers) > 1:
            ctx.debug(f"候选番号: {', '.join(candidate_numbers)}")
        return [f"{self.base_url}/product/product_detail/{each}/" for each in candidate_numbers]

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        htmlcode = etree.fromstring(html.get(), etree.HTMLParser())
        web_number = getNum(htmlcode).strip(",")
        title = getTitle(htmlcode).replace("\\n", "").replace("        ", "").strip(",").strip()
        if title and web_number:
            return [search_url]
        ctx.debug("MGStage 候选详情页未获取到 title 或番号")
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        htmlcode = etree.fromstring(html.get(), etree.HTMLParser())
        number = getNum(htmlcode).strip(",") or ctx.input.number
        actor = getActor(htmlcode).replace(" ", "").strip(",")
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        title = getTitle(htmlcode).replace("\\n", "").replace("        ", "").strip(",").strip()
        if not title or not number:
            raise CralwerException("数据获取失败: 未获取到title或番号！")
        cover_url = getCover(htmlcode)
        release = getRelease(htmlcode).strip(",").replace("/", "-")
        tag = getTag(htmlcode).strip(",")
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=getOutline(htmlcode).replace("\n", "").strip(","),
            originalplot=getOutline(htmlcode).replace("\n", "").strip(","),
            tags=[item.strip() for item in tag.split(",") if item.strip()],
            release=release,
            year=getYear(release).strip(","),
            runtime=getRuntime(htmlcode).strip(","),
            score=getScore(htmlcode).strip(","),
            series=getSeries(htmlcode).strip(","),
            studio=getStudio(htmlcode).strip(","),
            publisher=getPublisher(htmlcode).strip(","),
            thumb=cover_url,
            poster=getCoverSmall(cover_url),
            extrafanart=getExtraFanart(htmlcode),
            trailer=await get_trailer(self.async_client, htmlcode),
            image_download=True,
            image_cut="right",
            mosaic="有码",
            external_id=detail_url,
        )

    @override
    async def _fetch_search(self, ctx: Context, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        return await self.async_client.get_text(url, cookies={"adc": "1"})

    @override
    async def _fetch_detail(self, ctx: Context, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        return await self.async_client.get_text(url, cookies={"adc": "1"})
