#!/usr/bin/env python3

import re
import time

from lxml import etree

from ..config.manager import manager
from ..models.log_buffer import LogBuffer


def get_detail_value(html, *labels):
    for label in labels:
        result = html.xpath(
            f'//div[contains(@class, "box_works01_list")]//li[contains(@class, "clearfix")][span[normalize-space()="{label}"]]/p//text()'
        )
        text = "".join(part.strip() for part in result if part.strip())
        if text:
            return text
    return ""


def normalize_date(date_text):
    if not date_text:
        return ""
    if match := re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", date_text):
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return date_text.replace("/", "-").strip()


def get_timer_date(html, keyword):
    for timer in html.xpath('//div[contains(@class, "view_timer")]'):
        text = "".join(part.strip() for part in timer.xpath(".//text()") if part.strip())
        if keyword in text and (match := re.search(r"(\d{4}/\d{1,2}/\d{1,2})", text)):
            return normalize_date(match.group(1))
    return ""


def get_title(html):
    result = html.xpath("//h1/text()")
    return result[0] if result else ""


def get_actor(html):
    return get_detail_value(html, "出演女優")


def get_actor_photo(actor):
    actor = actor.split(",")
    data = {}
    for i in actor:
        actor_photo = {i: ""}
        data.update(actor_photo)
    return data


def get_outline(html):
    return html.xpath("string(//div[@class='box_works01_text']/p)")


def get_runtime(html):
    result = re.findall(r"\d+", get_detail_value(html, "収録時間"))
    return result[0] if result else ""


def get_series(html):
    return get_detail_value(html, "系列", "シリーズ")


def get_director(html):
    return get_detail_value(html, "导演", "導演", "監督")


def get_publisher(html):
    result = get_detail_value(html, "メーカー", "レーベル")
    return result if result else "FALENO"


def get_release(html):
    release = get_detail_value(html, "発売日")
    if release:
        return normalize_date(release)

    # 部分旧页面没有详情列表日期，保留按钮区日期作为兜底。
    release = get_timer_date(html, "発売")
    if release:
        return release

    release = get_detail_value(html, "配信日", "配信開始日")
    if release:
        return normalize_date(release)

    return get_timer_date(html, "配信")


def get_year(release):
    result = re.findall(r"\d{4}", release)
    return result[0] if result else ""


def get_tag(html):
    result = html.xpath('//a[@class="genre"]//text()')
    tag = ""
    for each in result:
        tag += each.strip().replace("，", "") + ","
    return tag.strip(",")


def get_cover(html):
    result = html.xpath("//a[@class='pop_sample']/img/@src")
    return result[0].replace("?output-quality=60", "") if result else ""


def get_extrafanart(html):  # 获取封面链接
    extrafanart_list = html.xpath("//a[@class='pop_img']/@href")
    return extrafanart_list


def get_trailer(html):  # 获取预览片
    result = html.xpath("//a[@class='pop_sample']/@href")
    return result[0] if result else ""


def get_real_url(html):
    href_result = html.xpath('//div[@class="text_name"]/a/@href')
    poster_result = html.xpath('//div[@class="text_name"]/../a/img/@src')
    if href_result and poster_result:
        return href_result[0], poster_result[0]
    return "", ""


async def main(
    number,
    appoint_url="",
    **kwargs,
):
    # https://faleno.jp/top/works/fsdss564/
    # https://falenogroup.com/works/votan-034/
    start_time = time.time()
    website_name = "faleno"
    LogBuffer.req().write(f"-> {website_name}")
    real_url = appoint_url
    title = ""
    cover_url = ""
    poster_url = ""
    image_download = True
    image_cut = "right"
    web_info = "\n       "
    debug_info = ""
    number_lo = number.lower()
    number_lo_noline = number_lo.replace("-", "")
    number_lo_space = number_lo.replace("-", " ")
    search_url_list = [
        f"https://faleno.jp/top/?s={number_lo_space}",
        f"https://falenogroup.com/top/?s={number_lo_space}",
    ]
    real_url_list = []
    if real_url:
        real_url_list = [real_url]
    elif number.upper().startswith("FLN"):
        real_url_list = [
            f"https://faleno.jp/top/works/{number_lo_noline}/",
            f"https://faleno.jp/top/works/{number_lo}/",
            f"https://falenogroup.com/works/{number_lo}/",
            f"https://falenogroup.com/works/{number_lo_noline}/",
        ]
    LogBuffer.info().write("\n    🌐 faleno")
    mosaic = "有码"
    try:  # 捕获主动抛出的异常
        if not real_url_list:
            for search_url in search_url_list:
                debug_info = f"请求地址: {search_url} "
                LogBuffer.info().write(web_info + debug_info)

                html_info, error = await manager.computed.async_client.get_text(search_url)
                if html_info is None:
                    debug_info = f"请求错误: {error} "
                    LogBuffer.info().write(web_info + debug_info)
                    continue

                html_detail = etree.fromstring(html_info, etree.HTMLParser())
                real_url, poster_url = get_real_url(html_detail)
                if real_url:
                    real_url_list = [real_url]
                    break
                else:
                    debug_info = "未找到搜索结果"
                    LogBuffer.info().write(web_info + debug_info)
            else:
                raise Exception(debug_info)

        for real_url in real_url_list:
            debug_info = f"番号地址: {real_url} "
            LogBuffer.info().write(web_info + debug_info)

            html_info, error = await manager.computed.async_client.get_text(real_url)
            if html_info is None:
                debug_info = f"请求错误: {error} "
                LogBuffer.info().write(web_info + debug_info)
                continue

            html_detail = etree.fromstring(html_info, etree.HTMLParser())
            title = get_title(html_detail)
            if not title:
                debug_info = "数据获取失败: 番号标题不存在！"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)

            actor = get_actor(html_detail)  # 获取actor
            actor_photo = get_actor_photo(actor)
            for each in actor_photo:
                title = title.replace(" " + each, "")
            cover_url = get_cover(html_detail)  # 获取cover
            if not poster_url:
                poster_url = (
                    cover_url.replace("_1200.jpg", "_2125.jpg")
                    .replace("_tsp.jpg", "_actor.jpg")
                    .replace("1200_re", "2125")
                    .replace("_1200-1", "_2125-1")
                )
            outline = get_outline(html_detail)
            tag = ""
            release = get_release(html_detail)
            year = get_year(release)
            runtime = get_runtime(html_detail)
            score = ""
            series = get_series(html_detail)
            director = get_director(html_detail)
            studio = get_publisher(html_detail)
            publisher = studio
            extrafanart = get_extrafanart(html_detail)
            trailer = get_trailer(html_detail)
            website = real_url
            break
        else:
            raise Exception(debug_info)
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
                "source": "faleno",
                "actor_photo": actor_photo,
                "thumb": cover_url,
                "poster": poster_url,
                "extrafanart": extrafanart,
                "trailer": trailer,
                "image_download": image_download,
                "image_cut": image_cut,
                "mosaic": mosaic,
                "website": website,
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
    print(main('fsdss-564'))  # print(main('mgold-017'))    # 地址带 -  # print(main('votan-034'))    # falenogroup.com 番号和数字加空格才能搜到  # print(main('fcdss-001'))    # 页面地址 flnc001  # print(main('FSDSS-037'))    # poster .replace('_1200-1', '_2125-1')  # print(main('flns-072'))       # outline 换行
