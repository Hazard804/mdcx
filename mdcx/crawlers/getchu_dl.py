#!/usr/bin/env python3
import contextlib
import re
import unicodedata
import urllib.parse

from lxml import etree

from .base import Context, CralwerException, CrawlerData


def get_title(html):
    result = html.xpath('//meta[@property="og:title"]/@content')
    return result[0].strip() if result else ""


def get_studio(html):
    return html.xpath("string(//td[text()='サークル']/following-sibling::td)")


def get_release(html):
    result = html.xpath("//td[contains(text(),'配信開始日')]/following-sibling::td/text()")
    return result[0].replace("/", "-") if result and re.search(r"\d+", result[0]) else ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_director(html):
    return html.xpath('string(//td[text()="作者"]/following-sibling::td)').strip()


def get_runtime(html):
    result = html.xpath("//td[contains(text(),'画像数&ページ数')]/following-sibling::td/text()")
    if result:
        result = re.findall(r"\d*", result[0])
    return result[0] if result else ""


def get_tag(html):
    result = html.xpath('//td[text()="趣向"]/following-sibling::td/a/text()')
    return ",".join(result) if result else ""


def get_cover(html):
    result = html.xpath('//meta[@property="og:image"]/@content')
    return result[0] if result else ""


def get_outline(html):
    return html.xpath('string(//td[text()="作品内容"]/following-sibling::td)').strip()


def get_extrafanart(html):
    result_list = html.xpath("//a[contains(@href,'/data/item_img/') and @class='highslide']/@href")
    result = []
    for each in result_list:
        result.append(f"https://dl.getchu.com{each}")
    return result


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def scrape_dl_getchu(client, number: str, appoint_url: str = "", ctx: Context | None = None) -> CrawlerData:
    real_url = appoint_url
    image_cut = ""
    image_download = True
    cookies = {"adult_check_flag": "1"}
    if not real_url and ("DLID" in number.upper() or "ITEM" in number.upper() or "GETCHU" in number.upper()):
        id = re.findall(r"\d+", number)[0]
        real_url = f"https://dl.getchu.com/i/item{id}"  # real_url = 'https://dl.getchu.com/i/item4024984'

    if not real_url:
        keyword = unicodedata.normalize("NFC", number.replace("●", " "))
        with contextlib.suppress(Exception):
            keyword = keyword.encode("cp932").decode("shift_jis")
        keyword2 = urllib.parse.quote_plus(keyword, encoding="EUC-JP")
        search_url = f"https://dl.getchu.com/search/search_list.php?dojin=1&search_category_id=&search_keyword={keyword2}&btnWordSearch=%B8%A1%BA%F7&action=search&set_category_flag=1"
        if ctx:
            ctx.debug(f"DL Getchu 搜索地址: {search_url}")
            ctx.debug_info.search_urls.append(search_url)

        html_search, error = await client.get_text(search_url, cookies=cookies, encoding="euc-jp")
        if html_search is None:
            raise CralwerException(f"网络请求错误: {error}")
        html = etree.fromstring(html_search, etree.HTMLParser())
        res_list = html.xpath("//table/tr/td[@valign='top' and not (@align)]/div/a")
        for each in res_list:
            temp_url = each.get("href")
            temp_title = each.xpath("string(.)")
            if temp_url and "/item" in temp_url and temp_title and temp_title.startswith(number):
                real_url = temp_url
                break
        else:
            raise CralwerException("搜索结果: 未匹配到番号！")

    if ctx:
        ctx.debug(f"DL Getchu 番号地址: {real_url}")
        ctx.debug_info.detail_urls.append(real_url)
    html_content, error = await client.get_text(real_url, cookies=cookies, encoding="euc-jp")
    if html_content is None:
        raise CralwerException(f"网络请求错误: {error}")
    html_info = etree.fromstring(html_content, etree.HTMLParser())
    number = "DLID-" + re.findall(r"\d+", real_url)[0]
    title = get_title(html_info)
    if not title:
        raise CralwerException("数据获取失败: 未获取到title！")
    release = get_release(html_info)
    cover_url = get_cover(html_info)
    return CrawlerData(
        number=number,
        title=title,
        originaltitle=title,
        actors=[],
        outline=get_outline(html_info),
        originalplot=get_outline(html_info),
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
        mosaic="同人",
        external_id=real_url,
        wanted="",
        source="dl_getchu",
    )
