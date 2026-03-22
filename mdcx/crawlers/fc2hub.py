#!/usr/bin/env python3
import json
import re
import time

from lxml import etree

from ..config.enums import FieldRule, Website
from ..config.manager import manager
from ..models.log_buffer import LogBuffer
from ..signals import signal


def getTitle(html):  # 获取标题
    result = html.xpath("//h1/text()")
    result = result[1] if result else ""
    return result


def getNum(html):  # 获取番号
    result = html.xpath("//h1/text()")
    result = result[0] if result else ""
    return result


def getCover(html):  # 获取封面
    result = html.xpath('//a[@data-fancybox="gallery"]/@href')
    result = result[0] if result else ""
    result = "https:" + result if result.startswith("//") else result
    return result


def getExtraFanart(html):  # 获取剧照
    result = html.xpath('//div[@style="padding: 0"]/a/@href')
    result = ["https:" + u if u.startswith("//") else u for u in result]
    return result


def getStudio(html):  # 使用卖家作为厂家
    result = html.xpath('//div[@class="col-8"]/text()')
    if result:
        result = result[0].strip()
    return result


def getTag(html):  # 获取标签
    result = html.xpath('//p[@class="card-text"]/a[contains(@href, "/tag/")]/text()')
    result = str(result).strip(" []").replace(", ", ",").replace("'", "").strip() if result else ""
    return result


def getOutline(html):  # 获取简介
    result = (
        "".join(html.xpath('//div[@class="col des"]//text()'))
        .strip("[]")
        .replace("',", "")
        .replace("\\n", "")
        .replace("'", "")
        .replace("・", "")
        .strip()
    )
    return result


def getMosaic(tag, title):  # 获取马赛克
    result = "无码" if "無修正" in tag or "無修正" in title else "有码"
    return result


def getTrailerVideoId(html, number):  # 获取 FC2 视频 ID
    result = html.xpath(
        '//div[contains(@class, "player-api")]/@data-id'
        ' | //iframe[contains(@data-src, "/embed/")]/@data-src'
        ' | //iframe[contains(@src, "/embed/")]/@src'
    )
    for item in result:
        item = str(item).strip()
        if not item:
            continue
        if item.isdigit():
            return item
        matched = re.search(r"/embed/(\d+)", item)
        if matched:
            return matched.group(1)
    return number


async def getTrailer(html, number):  # 获取预告片
    fc2_video_id = getTrailerVideoId(html, number)
    # FC2 sample 接口返回的是带 mid 参数的临时直链，适合立即下载，不适合长期固化。
    # 注意 path 上的 mid 参数不能丢，否则直链会返回 403。
    req_url = f"https://adult.contents.fc2.com/api/v2/videos/{fc2_video_id}/sample"
    response, error = await manager.computed.async_client.get_text(req_url)
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


async def main(
    number,
    appoint_url="",
    **kwargs,
):
    start_time = time.time()
    website_name = "fc2hub"
    LogBuffer.req().write(f"-> {website_name}")
    real_url = appoint_url
    root_url = manager.config.get_site_url(Website.FC2HUB, "https://javten.com")

    number = number.upper().replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()
    dic = {}
    web_info = "\n       "
    LogBuffer.info().write(" \n    🌐 fc2hub")

    try:  # 捕获主动抛出的异常
        if not real_url:
            # 通过搜索获取real_url
            url_search = root_url + "/search?kw=" + number
            debug_info = f"搜索地址: {url_search} "
            LogBuffer.info().write(web_info + debug_info)

            # ========================================================================搜索番号
            html_search, error = await manager.computed.async_client.get_text(url_search)
            if html_search is None:
                debug_info = f"网络请求错误: {error}"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
            html = etree.fromstring(html_search, etree.HTMLParser())
            real_urls = html.xpath("//link[contains(@href, $number)]/@href", number="id" + number)

            if not real_urls:
                debug_info = "搜索结果: 未匹配到番号！"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
            else:
                language_not_jp = ["/tw/", "/ko/", "/en/"]
                for url in real_urls:
                    if all(la not in url for la in language_not_jp):
                        real_url = url
                        break

        if real_url:
            debug_info = f"番号地址: {real_url} "
            LogBuffer.info().write(web_info + debug_info)
            html_content, error = await manager.computed.async_client.get_text(real_url)
            if html_content is None:
                debug_info = f"网络请求错误: {error}"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
            html_info = etree.fromstring(html_content, etree.HTMLParser())

            title = getTitle(html_info)  # 获取标题
            if not title:
                debug_info = "数据获取失败: 未获取到title！"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
            cover_url = getCover(html_info)  # 获取cover
            outline = getOutline(html_info)
            tag = getTag(html_info)
            studio = getStudio(html_info)  # 获取厂商
            extrafanart = getExtraFanart(html_info)
            trailer = await getTrailer(html_info, number)
            debug_info = (
                "预告片: 已获取到带时效参数的临时链接，仅适合立即下载" if trailer else "预告片: 未获取到临时下载链接"
            )
            LogBuffer.info().write(web_info + debug_info)
            if trailer:
                signal.add_log("🟡 FC2Hub 预告片链接带时效参数，仅适合立即下载，不建议长期复用远程链接。")
            mosaic = getMosaic(tag, title)
            actor = studio if FieldRule.FC2_SELLER in manager.config.fields_rule else ""

            try:
                dic = {
                    "number": "FC2-" + str(number),
                    "title": title,
                    "originaltitle": title,
                    "actor": actor,
                    "outline": outline,
                    "originalplot": outline,
                    "tag": tag,
                    "release": "",
                    "year": "",
                    "runtime": "",
                    "score": "",
                    "series": "FC2系列",
                    "director": "",
                    "studio": studio,
                    "publisher": studio,
                    "source": "fc2hub",
                    "website": str(real_url).strip("[]"),
                    "actor_photo": {actor: ""},
                    "thumb": str(cover_url),
                    "poster": "",
                    "extrafanart": extrafanart,
                    "trailer": trailer,
                    "image_download": False,
                    "image_cut": "center",
                    "mosaic": mosaic,
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
    # print(main('FC2-424646'))
    print(main('1940476'))  # 无码  # print(main('1860858', ''))  #有码  # print(main('1599412', ''))  # print(main('1131214', ''))  # 未找到  # print(main('1837553', ''))  # print(main('1613618', ''))  # print(main('1837553', ''))  # print(main('1837589', ""))  # print(main('1760182', ''))  # print(main('1251689', ''))  # print(main('674239', ""))  # print(main('674239', "))  # print(main('1924003', ''))   # 无图
