#!/usr/bin/env python3
import re
import time

from lxml import etree

from ..config.enums import Website
from ..config.manager import manager
from ..models.log_buffer import LogBuffer

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


def getActorPhoto(actor):
    actor = actor.split(",")
    data = {}
    for i in actor:
        actor_photo = {i: ""}
        data.update(actor_photo)
    return data


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


async def _main_single_language(
    number,
    appoint_url="",
    language="zh_cn",
    **kwargs,
):
    language = _normalize_language(language)
    start_time = time.time()
    website_name = "iqqtv"
    LogBuffer.req().write(f"-> {website_name}[{language}]")

    if not re.match(r"n\d{4}", number):
        number = number.upper()
    real_url = appoint_url or ""
    iqqtv_url = manager.config.get_site_url(Website.IQQTV, "https://iqq5.xyz")
    cover_url = ""
    image_cut = "right"
    image_download = False
    mosaic = ""
    url_search = ""
    if language == "zh_cn":
        iqqtv_url = iqqtv_url + "/cn/"
    elif language == "zh_tw":
        iqqtv_url = iqqtv_url + "/"
    else:
        iqqtv_url = iqqtv_url + "/jp/"
    # web_info = ' \n    >>> ' + "%-10s" % '[iqqtv] '
    web_info = "\n       "
    LogBuffer.info().write(f" \n    🌐 iqqtv[{language}]")
    debug_info = ""

    try:  # 捕获主动抛出的异常
        if not real_url:
            # 通过搜索获取real_url
            url_search = iqqtv_url + "search.php?kw=" + number
            debug_info = f"搜索地址: {url_search} "
            LogBuffer.info().write(web_info + debug_info)

            # ========================================================================搜索番号
            html_search, error = await manager.computed.async_client.get_text(url_search)
            if html_search is None:
                debug_info = f"网络请求错误: {error}"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
            html = etree.fromstring(html_search, etree.HTMLParser())
            real_url = html.xpath('//a[@class="ga_click"]/@href')
            if real_url:
                real_url_tmp = get_real_url(html, number)
                real_url = iqqtv_url + real_url_tmp.replace("/cn/", "").replace("/jp/", "").replace("&cat=19", "")
            else:
                debug_info = "搜索结果: 未匹配到番号！"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
        else:
            real_url = iqqtv_url + re.sub(r".*player", "player", appoint_url)

        debug_info = f"番号地址: {real_url} "
        LogBuffer.info().write(web_info + debug_info)
        html_content, error = await manager.computed.async_client.get_text(real_url)
        if html_content is None:
            debug_info = f"网络请求错误: {error}"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)
        html_info = etree.fromstring(html_content, etree.HTMLParser())

        title = get_title(html_info)  # 获取标题
        if not title:
            debug_info = "数据获取失败: 未获取到title！"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)
        web_number = getWebNumber(title, number)  # 获取番号，用来替换标题里的番号
        title = title.replace(f" {web_number}", "").strip()
        actor = getActor(html_info)  # 获取actor
        actor_photo = getActorPhoto(actor)
        title = get_real_title(title)
        cover_url = getCover(html_info)  # 获取cover
        outline = getOutline(html_info)
        release = getRelease(html_info)
        year = getYear(release)
        tag = getTag(html_info)
        mosaic = getMosaic(tag)
        if mosaic == "无码":
            image_cut = "center"
        studio = getStudio(html_info)
        runtime = ""
        score = ""
        series = get_series(html_info)
        director = ""
        publisher = studio
        extrafanart = get_extrafanart(html_info)
        tag = tag.replace("无码片", "").replace("無碼片", "").replace("無修正", "")
        try:
            dic = {
                "number": web_number,
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
                "source": "iqqtv",
                "website": real_url,
                "actor_photo": actor_photo,
                "thumb": cover_url,
                "poster": "",
                "extrafanart": extrafanart,
                "trailer": "",
                "image_download": image_download,
                "image_cut": image_cut,
                "mosaic": mosaic,
                "wanted": "",
            }

            debug_info = "数据获取成功！"
            LogBuffer.info().write(web_info + debug_info)

        except Exception as e:
            debug_info = "数据生成出错: " + str(e)
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)

    except Exception as e:
        LogBuffer.error().write(str(e))
        dic = {
            "title": "",
            "thumb": "",
            "website": "",
        }
    dic = {website_name: {language: dic}}
    LogBuffer.req().write(f"({round(time.time() - start_time)}s) ")
    return dic


async def main(
    number,
    appoint_url="",
    language="zh_cn",
    **kwargs,
):
    language = _normalize_language(language)
    appoint_url = appoint_url.replace("/cn/", "/jp/").replace("iqqtv.cloud/player", "iqqtv.cloud/jp/player")
    json_data = await _main_single_language(number, appoint_url, "jp", **kwargs)
    if not json_data["iqqtv"]["jp"]["title"] or language == "jp":
        json_data["iqqtv"]["zh_cn"] = json_data["iqqtv"]["jp"]
        json_data["iqqtv"]["zh_tw"] = json_data["iqqtv"]["jp"]
        return json_data

    if language == "zh_cn":
        appoint_url = json_data["iqqtv"]["jp"]["website"].replace("/jp/", "/cn/")
    else:
        appoint_url = json_data["iqqtv"]["jp"]["website"].replace("/jp/", "/")

    json_data_zh = await _main_single_language(number, appoint_url, language, **kwargs)
    dic = json_data_zh["iqqtv"][language]
    dic["originaltitle"] = json_data["iqqtv"]["jp"]["originaltitle"]
    dic["originalplot"] = json_data["iqqtv"]["jp"]["originalplot"]
    json_data["iqqtv"].update({language: dic})

    return json_data


if __name__ == "__main__":
    # yapf: disable
    # print(main('mimk-095'))
    # print(main('abp-554'))
    # print(main('gs-067'))
    # print(main('110912-179'))
    # print(main('abs-141'))
    # print(main('FC2-906625'))
    # print(main('HYSD-00083'))
    # print(main('IESP-660'))
    # print(main('n1403'))
    # print(main('GANA-1910'))
    # print(main('heyzo-1031'))
    # print(main('x-art.19.11.03'))
    # print(main('032020-001'))
    # print(main('S2M-055'))
    # print(main('LUXU-1217'))
    # print(main('1101132', ''))
    # print(main('OFJE-318'))
    # print(main('110119-001'))
    # print(main('abs-001'))
    # print(main('SSIS-090', ''))
    # print(main('SSIS-090', ''))
    # print(main('SNIS-016', ''))
    # print(main('HYSD-00083', ''))
    # print(main('IESP-660', ''))
    # print(main('n1403', ''))
    # print(main('GANA-1910', ''))
    # print(main('heyzo-1031', ''))
    # print(main_us('x-art.19.11.03'))
    # print(main('032020-001', ''))
    # print(main('S2M-055', ''))
    # print(main('LUXU-1217', ''))
    # print(main('aldn-334', ''))           # 存在系列字段
    # print(main('ssni-200', ''))           # 存在多个搜索结果
    # print(main('START-104', language='zh_tw'))      # 简介存在无效信息  "*根据分发方式,内容可能会有所不同"
    print(main('abs-141'))  # 一个搜索结果
    print(main('MIAB-204'))  # 多个搜索结果
    print(main('ABF-131', ''))  # 无码破解
