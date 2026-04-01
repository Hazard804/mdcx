#!/usr/bin/env python3

import contextlib
import re
import time
import unicodedata
import urllib.parse

from lxml import etree

from ..config.manager import manager
from ..crawlers import getchu_dl
from ..models.log_buffer import LogBuffer


def normalize_detail_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"(?:soft\.phtml\?id=|/item/)(\d+)", url)
    if not match:
        return url
    item_id = match.group(1)
    return f"https://www.getchu.com/item/{item_id}/?gc=gc"


def get_attestation_continue_url(html) -> str:
    result = html.xpath("//h1[contains(., '年齢認証ページ')]/following::a[contains(., 'すすむ')][1]/@href")
    return normalize_detail_url(result[0].strip()) if result else ""


def get_web_number(html, number):
    result = html.xpath('//td[contains(text(), "品番：")]/following-sibling::td/text()')
    return result[0].strip().upper() if result else number


def get_title(html):
    result = html.xpath('//h1[@id="soft-title"]/text()')
    if result:
        return result[0].strip()

    result = html.xpath('//meta[@property="og:title"]/@content')
    if result:
        title = re.sub(r"\s*\|\s*.*$", "", result[0]).strip()
        if title:
            return title

    result = html.xpath("//title/text()")
    if result:
        title = re.sub(r"\s+", " ", result[0]).strip()
        title = re.sub(r"\s*\|.*$", "", title).strip()
        title = re.sub(r"\s*\(.*?\)$", "", title).strip()
        return title
    return ""


def get_studio(html):
    result = html.xpath('//a[@class="glance"]/text()')
    return result[0] if result else ""


def get_release(html):
    result = html.xpath("//td[contains(text(),'発売日：')]/following-sibling::td/a/text()")
    return result[0].replace("/", "-") if result and re.search(r"\d+", result[0]) else ""


def get_year(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def get_director(html):
    result = html.xpath("//td[contains(text(),'監督：')]/following-sibling::td/text()")
    if not result:
        result = html.xpath("//a[contains(@href,'person=')]/text()")
    if not result:
        result = html.xpath("//td[contains(text(),'キャラデザイン：')]/following-sibling::td/text()")
    return result[0] if result else ""


def get_runtime(html):
    result = html.xpath("//td[contains(text(),'時間：')]/following-sibling::td/text()")
    if result:
        result = re.findall(r"\d*", result[0])
    return result[0] if result else ""


def get_tag(html):
    result = html.xpath(
        "//td[contains(text(), 'サブジャンル：') or contains(text(), 'カテゴリ：')]/following-sibling::td/a/text()"
    )
    return ",".join(result).replace(",[一覧]", "") if result else ""


def get_cover(html):
    result = html.xpath('//meta[@property="og:image"]/@content')
    if result:
        return "http://www.getchu.com" + result[0] if "http" not in result[0] else result[0]
    return ""


def get_outline(html):
    all_info = html.xpath('//div[@class="tablebody"]')
    result = ""
    for each in all_info:
        info = each.xpath("normalize-space(string())")
        result += "\n" + info
    return result.strip()


def get_mosaic(html, mosaic):
    result = html.xpath('//li[@class="genretab current"]/text()')
    if result:
        r = result[0]
        if r == "アダルトアニメ":
            mosaic = "里番"
        elif r == "書籍・雑誌":
            mosaic = "书籍"
        elif r == "アニメ":
            mosaic = "动漫"

    return mosaic


def get_extrafanart(html):
    result_list = html.xpath("//div[contains(text(),'サンプル画像')]/following-sibling::div[1]/a/@href")
    if not result_list:
        result_list = html.xpath("//div[contains(@class,'item-Samplecard')]//a[contains(@class,'highslide')]/@href")
    result = []
    for each in result_list:
        each = each.replace("./", "https://www.getchu.com/")
        if each.startswith("/"):
            each = "https://www.getchu.com" + each
        result.append(each)
    return result


async def main(
    number,
    appoint_url="",
    **kwargs,
):
    if "DLID" in number.upper() or "ITEM" in number.upper() or "GETCHU" in number.upper() or "dl.getchu" in appoint_url:
        return await getchu_dl.main(number, appoint_url)
    start_time = time.time()
    website_name = "getchu"
    getchu_url = "http://www.getchu.com"
    LogBuffer.req().write(f"-> {website_name}")
    real_url = appoint_url.replace("&gc=gc", "") + "&gc=gc" if appoint_url else ""
    cover_url = ""
    image_cut = ""
    image_download = True
    url_search = ""
    web_info = "\n       "
    LogBuffer.info().write(" \n    🌐 getchu")
    debug_info = ""

    # real_url = 'http://www.getchu.com/soft.phtml?id=1141110&gc=gc'
    # real_url = 'http://www.getchu.com/soft.phtml?id=1178713&gc=gc'
    # real_url = 'http://www.getchu.com/soft.phtml?id=1007200&gc=gc'

    try:  # 捕获主动抛出的异常
        if not real_url:
            number = number.replace("10bit", "").replace("裕未", "祐未").replace("“", "”").replace("·", "・")

            keyword = unicodedata.normalize("NFC", number)  # Mac 会拆成两个字符，即 NFD，而网页请求使用的是 NFC
            with contextlib.suppress(Exception):  # 转换为常见日文，比如～ 转换成 〜
                keyword = keyword.encode("cp932").decode("shift_jis")
            keyword2 = urllib.parse.quote_plus(
                keyword, encoding="EUC-JP"
            )  # quote() 不编码斜线，空格‘ ’编码为‘%20’；quote_plus() 会编码斜线为‘%2F’; 空格‘ ’编码为‘+’
            url_search = f"http://www.getchu.com/php/search.phtml?genre=all&search_keyword={keyword2}&gc=gc"
            # http://www.getchu.com/php/search.phtml?genre=anime_dvd&search_keyword=_WORD_&check_key_dtl=1&submit=&genre=anime_dvd&gc=gc
            debug_info = f"搜索地址: {url_search} "
            LogBuffer.info().write(web_info + debug_info)

            # ========================================================================搜索番号
            html_search, error = await manager.computed.async_client.get_text(url_search, encoding="euc-jp")
            if html_search is None:
                debug_info = f"网络请求错误: {error} "
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
            html = etree.fromstring(html_search, etree.HTMLParser())
            url_list = html.xpath("//a[@class='blueb']/@href")
            title_list = html.xpath("//a[@class='blueb']/text()")

            if url_list:
                real_url = normalize_detail_url(getchu_url + url_list[0].replace("../", "/") + "&gc=gc")
                keyword_temp = re.sub(r"[ \[\]\［\］]+", "", keyword)
                for i in range(len(url_list)):
                    title_temp = re.sub(r"[ \[\]\［\］]+", "", title_list[i])
                    if keyword_temp in title_temp:  # 有多个分集时，用标题符合的
                        real_url = normalize_detail_url(getchu_url + url_list[i].replace("../", "/") + "&gc=gc")
                        break
            else:
                debug_info = "搜索结果: 未匹配到番号！"
                LogBuffer.info().write(web_info + debug_info)
                return await getchu_dl.main(number, appoint_url)

        if real_url:
            real_url = normalize_detail_url(real_url)
            debug_info = f"番号地址: {real_url} "
            LogBuffer.info().write(web_info + debug_info)

            html_content, error = await manager.computed.async_client.get_text(real_url, encoding="euc-jp")
            if html_content is None:
                debug_info = f"网络请求错误: {error} "
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
            html_info = etree.fromstring(html_content, etree.HTMLParser())
            continue_url = get_attestation_continue_url(html_info)
            if continue_url:
                debug_info = f"检测到年龄确认页，继续访问: {continue_url} "
                LogBuffer.info().write(web_info + debug_info)
                real_url = continue_url
                html_content, error = await manager.computed.async_client.get_text(real_url, encoding="euc-jp")
                if html_content is None:
                    debug_info = f"网络请求错误: {error} "
                    LogBuffer.info().write(web_info + debug_info)
                    raise Exception(debug_info)
                html_info = etree.fromstring(html_content, etree.HTMLParser())
            title = get_title(html_info)
            if not title:
                debug_info = "数据获取失败: 未获取到title！"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
            outline = get_outline(html_info)
            actor = ""
            actor_photo = {"": ""}
            cover_url = get_cover(html_info)
            number = get_web_number(html_info, number)
            tag = get_tag(html_info)
            studio = get_studio(html_info)
            release = get_release(html_info)
            year = get_year(release)
            runtime = get_runtime(html_info)
            score = ""
            series = ""
            director = get_director(html_info)
            publisher = ""
            extrafanart = get_extrafanart(html_info)
            mosaic = "动漫"
            if "18禁" in html_content:
                mosaic = "里番"
            mosaic = get_mosaic(html_info, mosaic)
            try:
                dic = {
                    "number": number,
                    "title": title,
                    "originaltitle": title,
                    "actor": actor,
                    "outline": outline,
                    "originalplot": outline,
                    "tag": tag,
                    "release": release,
                    "year": year,
                    "runtime": runtime,
                    "score": score,
                    "series": series,
                    "director": director,
                    "studio": studio,
                    "publisher": publisher,
                    "source": "getchu",
                    "actor_photo": actor_photo,
                    "thumb": cover_url,
                    "poster": cover_url,
                    "extrafanart": extrafanart,
                    "trailer": "",
                    "image_download": image_download,
                    "image_cut": image_cut,
                    "mosaic": mosaic,
                    "website": real_url,
                    "wanted": "",
                }
                debug_info = "数据获取成功！"
                LogBuffer.info().write(web_info + debug_info)

            except Exception as e:
                debug_info = f"数据生成出错: {str(e)}"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
    except Exception as e:
        # print(traceback.format_exc())
        LogBuffer.error().write(str(e))
        dic = {
            "title": "",
            "thumb": "",
            "website": "",
        }
    dic = {website_name: {"zh_cn": dic, "zh_tw": dic, "jp": dic}}
    LogBuffer.req().write(f"({round(time.time() - start_time)}s) ")
    return dic


if __name__ == "__main__":
    # yapf: disable
    # print(main('コンビニ○○Z 第三話 あなた、ヤンクレママですよね。旦那に万引きがバレていいんですか？'))
    # print(main('dokidokiりとる大家さん お家賃6突き目 妖しい踊りで悪霊祓い！『婦警』さんのきわどいオシオキ'))
    # print(main('[PoRO]エロコンビニ店長 泣きべそ蓮っ葉・栞～お仕置きじぇらしぃナマ逸機～'))
    print(main('4562215333534'))  # print(main('人妻、蜜と肉 第二巻［月野定規］'))  # print(main('ACHDL-1159'))  # print(main('好きにしやがれ GOTcomics'))    # 書籍，没有番号  # print(main('あまあまロ●ータ女装男子レズ キス・フェラ・69からの3P介入'))  # print(main('DLID4033023'))  # print(main('', appoint_url='https://dl.getchu.com/i/item4033023'))  # print(main('ACMDP-1005')) # 有时间、导演，上下集ACMDP-1005B  # print(main('ISTU-5391'))  # print(main('INH-392'))  # print(main('ISTU-5391', appoint_url='http://www.getchu.com/soft.phtml?id=1180483'))  # print(main('SPY×FAMILY Vol.1 Blu-ray Disc＜初回生産限定版＞'))    # dmm 没有
