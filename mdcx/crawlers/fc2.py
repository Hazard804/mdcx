#!/usr/bin/env python3
import json
import re
import time

from lxml import etree

from ..config.enums import FieldRule
from ..config.manager import manager
from ..models.log_buffer import LogBuffer
from ..signals import signal


def getTitle(html):  # 获取标题
    result = html.xpath('//div[@data-section="userInfo"]//h3/span/../text()')
    result = " ".join(result) if result else ""
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


async def getTrailer(number):  # 获取预告片
    # FC2 sample 接口返回的是带 mid 参数的临时直链，适合立即下载，不适合长期固化。
    # 注意 path 上的 mid 参数不能丢，否则直链会返回 403。
    req_url = f"https://adult.contents.fc2.com/api/v2/videos/{number}/sample"
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


def getMosaic(tag, title):  # 获取马赛克
    result = "无码" if "無修正" in tag or "無修正" in title else "有码"
    return result


async def main(
    number,
    appoint_url="",
    **kwargs,
):
    start_time = time.time()
    website_name = "fc2"
    LogBuffer.req().write(f"-> {website_name}")
    real_url = appoint_url
    title = ""
    cover_url = ""
    poster_url = ""
    image_download = False
    image_cut = "center"
    number = number.upper().replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()
    dic = {}
    web_info = "\n       "
    LogBuffer.info().write(" \n    🌐 fc2")
    debug_info = ""

    try:  # 捕获主动抛出的异常
        if not real_url:
            real_url = f"https://adult.contents.fc2.com/article/{number}/"

        debug_info = f"番号地址: {real_url}"
        LogBuffer.info().write(web_info + debug_info)

        # ========================================================================番号详情页
        html_content, error = await manager.computed.async_client.get_text(real_url)
        if html_content is None:
            debug_info = f"网络请求错误: {error}"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)
        html_info = etree.fromstring(html_content, etree.HTMLParser())

        if isNotFoundPage(html_info):
            debug_info = "搜索结果: 未匹配到番号！"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

        if not isDetailPage(html_info):
            debug_info = "数据获取失败: 未进入影片详情页！"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

        title = getTitle(html_info)  # 获取标题
        if not title:
            debug_info = "数据获取失败: 未获取到title！"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

        cover_url, extrafanart = getCover(html_info)  # 获取cover,extrafanart
        if "http" not in cover_url:
            debug_info = "数据获取失败: 未获取到cover！"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

        poster_url = getCoverSmall(html_info)
        outline = getOutline(html_info)
        tag = getTag(html_info)
        release = getRelease(html_info)
        runtime = getRuntime(html_info)
        score = getScore(html_info)
        trailer = await getTrailer(number)
        debug_info = (
            "预告片: 已获取到带时效参数的临时链接，仅适合立即下载" if trailer else "预告片: 未获取到临时下载链接"
        )
        LogBuffer.info().write(web_info + debug_info)
        if trailer:
            signal.add_log("🟡 FC2 预告片链接带时效参数，仅适合立即下载，不建议长期复用远程链接。")
        studio = getStudio(html_info)  # 使用卖家作为厂商
        mosaic = getMosaic(tag, title)
        tag = tag.replace("無修正,", "").replace("無修正", "").strip(",")
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
                "release": release,
                "year": release[:4],
                "runtime": runtime,
                "score": score,
                "series": "FC2系列",
                "director": "",
                "studio": studio,
                "publisher": studio,
                "source": "fc2",
                "website": real_url,
                "actor_photo": {actor: ""},
                "thumb": cover_url,
                "poster": poster_url,
                "extrafanart": extrafanart,
                "trailer": trailer,
                "image_download": image_download,
                "image_cut": image_cut,
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
    print(main('1723984',
               ''))  # 有码  # print(main('1924776', ''))  # print(main('1860858', ''))  # print(main('1599412', ''))    # fc2hub有，fc2/fc2club没有  # print(main('1131214', ''))    # fc2club有，fc2/fc2hub没有  # print(main('1837553', ''))  # 无码  # print(main('1613618', ''))  # print(main('1837553', ''))  # print(main('1837589', ""))  # print(main('1760182', ''))  # print(main('1251689', ''))  # print(main('674239', ""))  # print(main('674239', "))
