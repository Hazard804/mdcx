#!/usr/bin/env python3
import re
import time
from datetime import date

from lxml import etree

from ..config.enums import Website
from ..config.manager import manager
from ..models.log_buffer import LogBuffer


def get_title(html):
    result = html.xpath("//h3/text()")
    result = result[0].strip() if result else ""
    return result


def getWebNumber(html, number):
    result = html.xpath('//span[@class="header"][contains(text(), "識別碼:")]/../span[2]/text()')
    return result[0] if result else number


def getActor(html):
    try:
        result = (
            str(html.xpath('//div[@class="star-name"]/a/text()')).strip(" ['']").replace("'", "").replace(", ", ",")
        )
    except Exception:
        result = ""
    return result


def getActorPhoto(html, url):
    actor = html.xpath('//div[@class="star-name"]/../a/img/@title')
    photo = html.xpath('//div[@class="star-name"]/../a/img/@src')
    data = {}
    if len(actor) == len(photo):
        for i in range(len(actor)):
            if "http" not in photo[i]:
                data[actor[i]] = url + photo[i]
            else:
                data[actor[i]] = photo[i]
    else:
        for each in actor:
            data[each] = ""
    return data


def getCover(html, url):  # 获取封面链接
    result = html.xpath('//a[@class="bigImage"]/@href')
    cover_url = (url + result[0] if "http" not in result[0] else result[0]) if result else ""
    return cover_url


def get_poster_url(cover_url):  # 获取小封面链接
    poster_url = ""
    if "/pics/" in cover_url:
        poster_url = cover_url.replace("/cover/", "/thumb/").replace("_b.jpg", ".jpg")
    elif "/imgs/" in cover_url:
        poster_url = cover_url.replace("/cover/", "/thumbs/").replace("_b.jpg", ".jpg")
    return poster_url


def getRelease(html):  # 获取发行日期
    result = html.xpath('//span[@class="header"][contains(text(), "發行日期:")]/../text()')
    result = result[0].strip() if result else ""
    return result


def getValidRelease(release):
    release = release.replace("/", "-").replace(".", "-").strip()
    if not release:
        return ""
    if not (match := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", release)):
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def getYear(release):
    release = getValidRelease(release)
    return release[:4] if release else ""


def getMosaic(html):
    select_tab = str(html.xpath('//li[@class="active"]/a/text()'))
    mosaic = "有码" if "有碼" in select_tab else "无码"
    return mosaic


def getRuntime(html):
    result = html.xpath('//span[@class="header"][contains(text(), "長度:")]/../text()')
    if result:
        result = result[0].strip()
        result = re.findall(r"\d+", result)
        result = result[0] if result else ""
    else:
        result = ""
    return result


def getStudio(html):
    result = html.xpath('//a[contains(@href, "/studio/")]/text()')
    result = result[0].strip() if result else ""
    return result


def getPublisher(html, studio):  # 获取发行商
    result = html.xpath('//a[contains(@href, "/label/")]/text()')
    result = result[0].strip() if result else studio
    return result


def getDirector(html):  # 获取导演
    result = html.xpath('//a[contains(@href, "/director/")]/text()')
    result = result[0].strip() if result else ""
    return result


def getSeries(html):
    result = html.xpath('//a[contains(@href, "/series/")]/text()')
    result = result[0].strip() if result else ""
    return result


def getExtraFanart(html, url):  # 获取封面链接
    result = html.xpath("//div[@id='sample-waterfall']/a/@href")
    if result:
        new_list = []
        for each in result:
            if "http" not in each:
                each = url + each
            new_list.append(each)
    else:
        new_list = ""
    return new_list


def getTag(html):  # 获取标签
    result = html.xpath('//span[@class="genre"]/label/a[contains(@href, "/genre/")]/text()')
    result = str(result).strip(" ['']").replace("'", "").replace(", ", ",") if result else ""
    return result


async def get_real_url(number, url_type, javbus_url, headers):  # 获取详情页链接
    if url_type == "us":  # 欧美
        url_search = "https://www.javbus.hair/search/" + number
    elif url_type == "censored":  # 有码
        url_search = javbus_url + "/search/" + number + "&type=&parent=ce"
    else:  # 无码
        url_search = javbus_url + "/uncensored/search/" + number + "&type=0&parent=uc"

    debug_info = f"搜索地址: {url_search} "
    LogBuffer.info().write(debug_info)
    # ========================================================================搜索番号
    html_search, error = await manager.computed.async_client.get_text(url_search, headers=headers)
    # 判断是否需要登录
    if html_search is None:
        debug_info = f"网络请求错误: {error} "
        LogBuffer.info().write(debug_info)
        raise Exception(debug_info)
    if "lostpasswd" in html_search:
        raise Exception("Cookie 无效！请重新填写 Cookie 或更新节点！")

    html = etree.fromstring(html_search, etree.HTMLParser())
    url_list = html.xpath("//a[@class='movie-box']/@href")
    for each in url_list:
        each_url = each.upper().replace("-", "")
        number_1 = "/" + number.upper().replace(".", "").replace("-", "")
        number_2 = number_1 + "_"
        if each_url.endswith(number_1) or number_2 in each_url:
            debug_info = f"番号地址: {each} "
            LogBuffer.info().write(debug_info)
            return each
    debug_info = "搜索结果: 未匹配到番号！"
    LogBuffer.info().write(debug_info)
    raise Exception(debug_info)


async def main(
    number,
    appoint_url="",
    mosaic="",
    **kwargs,
):
    start_time = time.time()
    website_name = "javbus"
    LogBuffer.req().write(f"-> {website_name}")
    real_url = appoint_url
    javbus_url = manager.config.get_site_url(Website.JAVBUS, "https://www.javbus.com")
    headers = {
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "cookie": manager.config.javbus,
    }

    title = ""
    cover_url = ""
    poster_url = ""
    image_download = False
    image_cut = "right"
    dic = {}
    debug_info = ""
    LogBuffer.info().write(" \n    🌐 javbus")

    try:
        if not real_url:
            # 欧美去搜索，其他尝试直接拼接地址，没有结果时再搜索
            if "." in number or re.search(r"[-_]\d{2}[-_]\d{2}[-_]\d{2}", number):  # 欧美影片
                number = number.replace("-", ".").replace("_", ".")
                real_url = await get_real_url(number, "us", javbus_url, headers)
            else:
                real_url = javbus_url + "/" + number
                if number.upper().startswith("CWP") or number.upper().startswith("LAF"):
                    temp_number = number.replace("-0", "-")
                    if temp_number[-2] == "-":
                        temp_number = temp_number.replace("-", "-0")
                    real_url = javbus_url + "/" + temp_number

        debug_info = f"番号地址: {real_url} "
        LogBuffer.info().write(debug_info)
        htmlcode, error = await manager.computed.async_client.get_text(real_url, headers=headers)

        # 判断是否需要登录
        if htmlcode is None:
            debug_info = f"网络请求错误: {error} "
            LogBuffer.info().write(debug_info)
            raise Exception(debug_info)
        if "lostpasswd" in htmlcode:
            raise Exception("Cookie 无效！请重新填写 Cookie 或更新节点！")

        if htmlcode is None:
            # 有404时尝试再次搜索 DV-1175
            if "404" not in error:
                debug_info = f"番号地址:{real_url} \n       网络请求错误: {error} "
                LogBuffer.info().write(debug_info)
                raise Exception(debug_info)

            # 欧美的不再搜索
            if "." in number:
                debug_info = "未匹配到番号！"
                LogBuffer.info().write(debug_info)
                raise Exception(debug_info)

            # 无码搜索结果
            elif mosaic == "无码" or mosaic == "無碼":
                real_url = await get_real_url(number, "uncensored", javbus_url, headers)

            # 有码搜索结果
            else:
                real_url = await get_real_url(number, "censored", javbus_url, headers)

            htmlcode, error = await manager.computed.async_client.get_text(real_url, headers=headers)
            if htmlcode is None:
                debug_info = "未匹配到番号！"
                LogBuffer.info().write(debug_info)
                raise Exception(debug_info)

        # 获取详情页内容
        html_info = etree.fromstring(htmlcode, etree.HTMLParser())
        title = get_title(html_info)
        if not title:
            debug_info = "数据获取失败: 未获取到title"
            LogBuffer.info().write(debug_info)
            raise Exception(debug_info)
        number = getWebNumber(html_info, number)  # 获取番号，用来替换标题里的番号
        title = title.replace(number, "").strip()
        actor = getActor(html_info)  # 获取actor
        actor_photo = getActorPhoto(html_info, javbus_url)
        cover_url = getCover(html_info, javbus_url)  # 获取cover
        poster_url = get_poster_url(cover_url)
        release_raw = getRelease(html_info)
        release = getValidRelease(release_raw)
        if release_raw and not release:
            debug_info = f"发行日期无效，已忽略: {release_raw}"
            LogBuffer.info().write(debug_info)
        year = getYear(release)
        tag = getTag(html_info)
        mosaic = getMosaic(html_info)
        if mosaic == "无码":
            image_cut = "center"
            if (
                "_" in number
                and poster_url
                or "HEYZO" in number
                and len(poster_url.replace(javbus_url + "/imgs/thumbs/", "")) == 7
            ):  # 一本道，并且有小图时，下载poster
                image_download = True
            else:
                poster_url = ""  # 非一本道的无码/欧美影片，清空小图地址，因为小图都是未裁剪的低分辨率图片
        runtime = getRuntime(html_info)
        studio = getStudio(html_info)
        publisher = getPublisher(html_info, studio)
        director = getDirector(html_info)
        series = getSeries(html_info)
        extrafanart = getExtraFanart(html_info, javbus_url)
        if "KMHRS" in number:  # 剧照第一张是高清图
            image_download = True
            if extrafanart:
                poster_url = extrafanart[0]
        try:
            dic = {
                "number": number,
                "title": title,
                "originaltitle": title,
                "actor": actor,
                "outline": "",
                "originalplot": "",
                "tag": tag,
                "release": release,
                "year": year,
                "runtime": runtime,
                "score": "",
                "series": series,
                "director": director,
                "studio": studio,
                "publisher": publisher,
                "source": "javbus",
                "website": real_url,
                "actor_photo": actor_photo,
                "thumb": cover_url,
                "poster": poster_url,
                "extrafanart": extrafanart,
                "trailer": "",
                "image_download": image_download,
                "image_cut": image_cut,
                "mosaic": mosaic,
                "wanted": "",
            }
            debug_info = "数据获取成功！"
            LogBuffer.info().write(debug_info)
        except Exception as e:
            debug_info = f"数据生成出错: {str(e)}"
            LogBuffer.info().write(debug_info)
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
    # print(main('LAFBD-034'))    # cwp,cwpbd 数字为2位时不带0
    print(main('PMAXVR-008'))  # print(main('cwpbd-034'))    # cwp,cwpbd 数字为2位时不带0  # print(main('FC2-1262472'))    # 无结果  # print(main('STARS-199'))    # 禁止  # print(main('EDVR-043'))    # 无结果  # print(main('SSIS-243'))  # print(main('ABW-015'))  # print(main('DASD-972'))  # print(main('ss-036'))    # 无结果  # print(main('KMHRS-050'))  # print(main('KV-115'))    # 无结果  # print(main('070621_001'))  # print(main('heyzo-1031'))  # print(main('heyzo-0811'))  # print(main('heyzo-1673'))  # print(main('dv-1175'))    # 无结果，通过搜索有结果  # print(main('dv1175'))  # print(main('ssni-644'))  # print(main('010115-001'))  # print(main('ssni644'))  # print(main('BigTitsatWork-17-09-26'))  # print(main('BrazzersExxtra.21.02.01'))  # print(main('KA-001'))   # 无结果  # print(main('012715-793'))  # print(main('ssni-644', "https://www.javbus.com/SSNI-644"))  # print(main('ssni-802', ""))  # print(main('DirtyMasseur.20.07.26', "https://www.javbus.hair/DirtyMasseur-21-01-31"))
