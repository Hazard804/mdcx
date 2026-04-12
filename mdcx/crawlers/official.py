#!/usr/bin/env python3
import re
import time

from lxml import etree

from ..config.manager import manager
from ..crawlers import prestige
from ..models.log_buffer import LogBuffer
from ..number import get_number_letters

DIRECTOR_PLACEHOLDER_CHARS = frozenset("-—－ー―‐~～·•. ")


def get_title(html):
    result = html.xpath('//h2[@class="p-workPage__title"]/text()')
    return result[0].strip() if result else ""


def get_actor(html):
    actor_list = html.xpath(
        '//a[@class="c-tag c-main-bg-hover c-main-font c-main-bd" and contains(@href, "/actress/")]/text()'
    )
    new_list = [each.strip() for each in actor_list]
    return ",".join(new_list)


def get_actor_photo(actor):
    actor = actor.split(",")
    data = {}
    for i in actor:
        actor_photo = {i: ""}
        data.update(actor_photo)
    return data


def get_outline(html):
    return html.xpath('string(//p[@class="p-workPage__text"])')


def get_studio(html):
    result = html.xpath('string(//div[contains(text(), "製作商")]/following-sibling::div)')
    return result.strip()


def get_runtime(html):
    result = html.xpath('//div[@class="th" and text()="収録時間"]/following-sibling::div/div/p/text()')
    return result[0].replace("分", "").strip() if result else ""


def get_series(html):
    result = html.xpath('//div[@class="th" and contains(text(), "シリーズ")]/following-sibling::div/a/text()')
    return result[0].strip() if result else ""


def get_publisher(html):
    publisher = ""
    studio = ""
    result_1 = html.xpath('//meta[@name="description"]/@content')
    if result_1:
        result_2 = re.findall(r"【公式】([^(]+)\(([^\)]+)", result_1[0])
        publisher, studio = result_2[0] if result_2 else ("", "")
    result = html.xpath('//div[@class="th" and contains(text(), "レーベル")]/following-sibling::div/a/text()')
    publisher = result[0].strip() if result else publisher
    return publisher.replace("　", " "), studio


def get_director(html):
    result = html.xpath('//div[@class="th" and contains(text(), "監督")]/following-sibling::div/div/p/text()')
    if not result:
        return ""
    director = result[0].strip()
    if not director or director == "N/A" or all(char in DIRECTOR_PLACEHOLDER_CHARS for char in director):
        return ""
    return director


def get_trailer(html):
    result = html.xpath('//div[@class="video"]/video/@src')
    return result[0] if result else ""


def get_release(html):
    result = html.xpath('//div[contains(text(), "発売日")]/following-sibling::div/div/a/text()')
    return result[0].replace("年", "-").replace("月", "-").replace("日", "") if result else ""


def get_year(release):
    if r := re.search(r"\d{4}", release):
        result = r.group()
        return result
    return release


def get_tag(html):
    result = html.xpath('//div[contains(text(), "ジャンル")]/following-sibling::div/div/a/text()')
    return ",".join(result).replace(",Blu-ray（ブルーレイ）", "")


def get_real_url(html, number):
    result = html.xpath('//a[@class="img hover"]')
    for each in result:
        href = each.get("href")
        poster = each.xpath("img/@data-src")[0]
        if href.upper().endswith(number.upper().replace("-", "")):
            return href, poster
    return "", ""


def get_cover(html):
    result = html.xpath('//img[@class="swiper-lazy"]/@data-src')
    return (result.pop(0), result) if result else ("", [])


async def main(
    number,
    appoint_url="",
    **kwargs,
):
    start_time = time.time()

    website_name = "offical_failed"

    try:  # 捕获主动抛出的异常
        official_url = manager.computed.official_websites.get(get_number_letters(number))
        if not official_url:
            raise Exception("不在官网番号前缀列表中")
        elif official_url == "https://www.prestige-av.com":
            return await prestige.main(number, appoint_url)
        website_name = official_url.split(".")[-2].replace("https://", "")
        LogBuffer.req().write(f"-> {website_name}")
        real_url = appoint_url
        image_cut = ""
        mosaic = "有码"
        web_info = "\n       "
        LogBuffer.info().write(f" \n    🌐 {website_name}")
        debug_info = ""

        url_search = official_url + "/search/list?keyword=" + number.replace("-", "")
        debug_info = f"搜索地址: {url_search} "
        LogBuffer.info().write(web_info + debug_info)

        # ========================================================================搜索番号
        html_search, error = await manager.computed.async_client.get_text(url_search)
        if html_search is None:
            debug_info = f"网络请求错误: {error} "
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

        html = etree.fromstring(html_search, etree.HTMLParser())
        real_url, poster = get_real_url(html, number)
        if not real_url:
            debug_info = "搜索结果: 未匹配到番号！"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)
        else:
            debug_info = f"番号地址: {real_url} "
            LogBuffer.info().write(web_info + debug_info)

            html_content, error = await manager.computed.async_client.get_text(real_url)
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
            cover_url, extrafanart = get_cover(html_info)
            outline = get_outline(html_info)
            actor = get_actor(html_info)
            actor_photo = get_actor_photo(actor)
            release = get_release(html_info)
            year = get_year(release)
            series = get_series(html_info)
            publisher, studio = get_publisher(html_info)
            tag = get_tag(html_info)
            director = get_director(html_info)
            runtime = get_runtime(html_info)
            trailer = get_trailer(html_info)
            score = ""
            image_download = False
            if "VR" in number.upper():
                image_download = True
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
                    "source": website_name,
                    "actor_photo": actor_photo,
                    "thumb": cover_url,
                    "poster": poster,
                    "extrafanart": extrafanart,
                    "trailer": trailer,
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
    dic = {
        "official": {"zh_cn": dic, "zh_tw": dic, "jp": dic},
        website_name: {"zh_cn": dic, "zh_tw": dic, "jp": dic},
    }
    LogBuffer.req().write(f"({round(time.time() - start_time)}s) ")
    return dic


if __name__ == "__main__":
    # print(main('ssni-871'))
    # print(main('stko-003'))
    # print(main('abw-123'))
    # print(main('EVA-088'))
    # print(main('SNIS-216'))
    # print(main('aa-173'))
    # print(main('ALDN-107'))
    # print(main('ten-024'))
    # print(main('459ten-024'))
    # print(main('IPX-729'))
    # print(main('STARS-199'))    # 无结果
    # print(main('SIVR-160'))
    # print(main('ssni-700'))
    # print(main('ssis-200'))
    # print(main('heyzo-2026'))
    # print(main('110219-001'))
    # print(main('abw-157'))
    # print(main('010520-001'))
    # print(main('abs-141'))
    # print(main('HYSD-00083'))
    # print(main('IESP-660'))
    # print(main('LUXU-1217'))
    # print(main('OFJE-318'))
    # print(main('abs-001'))
    # print(main('SSIS-623', ''))
    # print(main('MIDV-002', ''))
    # print(main('MIDV256', ''))
    print(main("SSNI-531"))  # print(main('SSIS-090', ''))  # print(main('SNIS-016', ''))
