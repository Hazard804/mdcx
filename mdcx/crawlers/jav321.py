#!/usr/bin/env python3
import asyncio
import random
import re
import time
from urllib.parse import urlsplit

from lxml import etree

from ..base.web import check_url, is_dmm_image_url, normalize_media_url
from ..config.enums import DownloadableFile
from ..config.manager import manager
from ..models.log_buffer import LogBuffer


def getActorPhoto(actor):
    actor = actor.split(",")
    data = {}
    for i in actor:
        actor_photo = {i: ""}
        data.update(actor_photo)
    return data


def getTitle(response):
    return str(re.findall(r"<h3>(.+) <small>", response)).strip(" ['']")


def getActor(response):
    if re.search(r'<a href="/star/\S+">(\S+)</a> &nbsp;', response):
        return str(re.findall(r'<a href="/star/\S+">(\S+)</a> &nbsp;', response)).strip(" [',']").replace("'", "")
    elif re.search(r'<a href="/heyzo_star/\S+">(\S+)</a> &nbsp;', response):
        return str(re.findall(r'<a href="/heyzo_star/\S+">(\S+)</a> &nbsp;', response)).strip(" [',']").replace("'", "")
    else:
        return str(re.findall(r"<b>出演者</b>: ([^<]+) &nbsp; <br>", response)).strip(" [',']").replace("'", "")


def getStudio(html):
    result = str(html.xpath('//div[@class="col-md-9"]/a[contains(@href,"/company/")]/text()')).strip(" ['']")
    return result


def getRuntime(response):
    return str(re.findall(r"<b>収録時間</b>: (\d+) \S+<br>", response)).strip(" ['']")


def getSeries(html):
    result = str(html.xpath('//div[@class="col-md-9"]/a[contains(@href,"/series/")]/text()')).strip(" ['']")
    return result


def getWebsite(detail_page):
    return "https:" + detail_page.xpath('//a[contains(text(),"简体中文")]/@href')[0]


def getNum(response, number):
    result = re.findall(r"<b>品番</b>: (\S+)<br>", response)
    return result[0].strip().upper() if result else number


def getScore(response):
    if re.search(r'<b>平均評価</b>: <img data-original="/img/(\d+).gif" />', response):
        score = re.findall(r'<b>平均評価</b>: <img data-original="/img/(\d+).gif" />', response)[0]
        return str(float(score) / 10.0)
    else:
        return str(re.findall(r"<b>平均評価</b>: ([^<]+)<br>", response)).strip(" [',']").replace("'", "")


def getYear(release):
    try:
        result = str(re.search(r"\d{4}", release).group())
        return result
    except Exception:
        return release


def getRelease(response):
    return str(re.findall(r"<b>配信開始日</b>: (\d+-\d+-\d+)<br>", response)).strip(" ['']").replace("0000-00-00", "")


def getCover(detail_page):
    cover_url = str(
        detail_page.xpath(
            "/html/body/div[@class='row'][2]/div[@class='col-md-3']/div[@class='col-xs-12 col-md-12'][1]/p/a/img[@class='img-responsive']/@src"
        )
    ).strip(" ['']")
    if cover_url == "":
        cover_url = str(detail_page.xpath("//*[@id='vjs_sample_player']/@poster")).strip(" ['']")
    return cover_url


def getExtraFanart(htmlcode):
    extrafanart_list = htmlcode.xpath(
        "/html/body/div[@class='row'][2]/div[@class='col-md-3']/div[@class='col-xs-12 col-md-12']/p/a/img[@class='img-responsive']/@src"
    )
    return extrafanart_list


def getCoverSmall(detail_page):
    return str(detail_page.xpath('//img[@class="img-responsive"]/@src')[0])


def _prefer_dmm_aws_url(url: str) -> str:
    normalized = normalize_media_url(str(url or "").strip())
    if not normalized:
        return ""
    if "pics.dmm.co.jp" in normalized:
        return normalized.replace("pics.dmm.co.jp", "awsimgsrc.dmm.co.jp/pics_dig").replace("/adult/", "/")
    return normalized


def _iter_dmm_image_candidates(url: str) -> list[str]:
    normalized = normalize_media_url(str(url or "").strip())
    if not normalized:
        return []

    seen: set[str] = set()
    candidates: list[str] = []
    for candidate in (_prefer_dmm_aws_url(normalized), normalized):
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
    return candidates


def _to_poster_url(thumb_url: str) -> str:
    normalized = normalize_media_url(str(thumb_url or "").strip())
    if normalized.endswith("pl.jpg"):
        return normalized[:-6] + "ps.jpg"
    return normalized


def _normalize_thumb_poster(thumb_url: str, poster_url: str) -> tuple[str, str]:
    normalized_thumb = normalize_media_url(str(thumb_url or "").strip())
    normalized_poster = normalize_media_url(str(poster_url or "").strip())

    for candidate in (normalized_thumb, normalized_poster):
        if candidate.endswith("pl.jpg") or candidate.endswith("ps.jpg"):
            base_url = candidate[:-6]
            return base_url + "pl.jpg", base_url + "ps.jpg"

    if normalized_thumb and not normalized_poster:
        return normalized_thumb, normalized_thumb
    if normalized_poster and not normalized_thumb:
        return normalized_poster, normalized_poster
    return normalized_thumb, normalized_poster


def _image_match_key(url: str) -> str:
    normalized = normalize_media_url(str(url or "").strip())
    if not normalized:
        return ""
    if not is_dmm_image_url(normalized):
        return normalized

    split_result = urlsplit(normalized)
    path = split_result.path
    if split_result.netloc.lower() == "awsimgsrc.dmm.co.jp" and path.startswith("/pics_dig/"):
        path = path[len("/pics_dig") :]
    return path.replace("/adult/", "/")


def _remove_cover_from_extrafanart(cover_url: str, image_urls: list[str]) -> list[str]:
    cover_key = _image_match_key(cover_url)
    if not cover_key:
        return image_urls
    return [image_url for image_url in image_urls if _image_match_key(image_url) != cover_key]


def getTag(response):  # 获取演员
    return re.findall(r'<a href="/genre/\S+">(\S+)</a>', response)


def getOutline(detail_page):
    # 修复路径，避免简介含有垃圾信息 "*根据分发方式，内容可能会有所不同"
    return detail_page.xpath("string(/html/body/div[2]/div[1]/div[1]/div[2]/div[3]/div/text())")


async def _validate_dmm_image_if_needed(url: str, label: str) -> str:
    normalized = normalize_media_url(str(url or "").strip())
    if not normalized:
        return ""

    if not is_dmm_image_url(normalized):
        return normalized

    for index, candidate in enumerate(_iter_dmm_image_candidates(normalized)):
        validated = await check_url(candidate)
        if not validated:
            continue

        validated_url = normalize_media_url(str(validated).strip())
        if index == 0 and candidate != normalized:
            LogBuffer.info().write(f"\n       图片高清图命中: {label} {normalized} -> {validated_url}")
        elif validated_url != normalized:
            LogBuffer.info().write(f"\n       图片校验重定向: {label} {normalized} -> {validated_url}")
        return validated_url

    LogBuffer.info().write(f"\n       图片校验失败: {label} {normalized}")
    return ""


async def _validate_preferred_dmm_image_if_needed(url: str, label: str) -> str:
    normalized = normalize_media_url(str(url or "").strip())
    if not normalized:
        return ""

    preferred = _prefer_dmm_aws_url(normalized)
    if not is_dmm_image_url(preferred):
        return preferred

    validated = await check_url(preferred)
    if not validated:
        LogBuffer.info().write(f"\n       图片抽检失败: {label} {preferred}")
        return ""

    validated_url = normalize_media_url(str(validated).strip())
    if preferred != normalized and validated_url == preferred:
        LogBuffer.info().write(f"\n       图片高清图命中: {label} {normalized} -> {validated_url}")
    elif validated_url != preferred:
        LogBuffer.info().write(f"\n       图片校验重定向: {label} {preferred} -> {validated_url}")
    return validated_url


async def _filter_dmm_extrafanart(image_urls: list[str]) -> list[str]:
    candidates = _normalize_extrafanart_urls(image_urls)
    if not candidates:
        return []

    sample_indexes = list(range(len(candidates)))
    if len(candidates) > 3:
        sample_indexes = sorted(random.sample(range(len(candidates)), 3))

    sampled_candidates = [(index, candidates[index]) for index in sample_indexes]
    sampled_results = await asyncio.gather(
        *[
            _validate_preferred_dmm_image_if_needed(image_url, f"extrafanart[{index + 1}]")
            for index, image_url in sampled_candidates
        ]
    )
    validated_by_index = {
        index: validated for (index, _), validated in zip(sampled_candidates, sampled_results, strict=True)
    }

    if all(sampled_results):
        LogBuffer.info().write(
            f"\n       剧照抽检通过: 随机抽检 {len(sampled_candidates)}/{len(candidates)}，整批升级 AWS"
        )
        valid_urls: list[str] = []
        for index, image_url in enumerate(candidates):
            resolved_url = validated_by_index.get(index) or _prefer_dmm_aws_url(image_url) or image_url
            if resolved_url not in valid_urls:
                valid_urls.append(resolved_url)
        return valid_urls

    passed_count = sum(1 for image_url in sampled_results if image_url)
    LogBuffer.info().write(
        f"\n       剧照抽检失败: 随机抽检 {passed_count}/{len(sampled_candidates)} 通过，回退全量校验"
    )

    remaining_candidates = [
        (index, image_url) for index, image_url in enumerate(candidates) if not validated_by_index.get(index)
    ]
    if remaining_candidates:
        remaining_results = await asyncio.gather(
            *[
                _validate_dmm_image_if_needed(image_url, f"extrafanart[{index + 1}]")
                for index, image_url in remaining_candidates
            ]
        )
        for (index, _), validated in zip(remaining_candidates, remaining_results, strict=True):
            validated_by_index[index] = validated

    valid_urls: list[str] = []
    for index in range(len(candidates)):
        validated_url = validated_by_index.get(index, "")
        if validated_url and validated_url not in valid_urls:
            valid_urls.append(validated_url)
    return valid_urls


async def _resolve_dmm_poster_url(thumb_url: str, poster_url: str) -> str:
    candidates = _normalize_extrafanart_urls([poster_url, _to_poster_url(thumb_url)])
    for candidate in candidates:
        validated_url = await _validate_dmm_image_if_needed(candidate, "poster")
        if validated_url:
            return validated_url
    return ""


def _normalize_extrafanart_urls(image_urls: list[str]) -> list[str]:
    valid_urls: list[str] = []
    for image_url in image_urls:
        normalized = normalize_media_url(str(image_url or "").strip())
        if normalized and normalized not in valid_urls:
            valid_urls.append(normalized)
    return valid_urls


async def main(
    number,
    appoint_url="",
    **kwargs,
):
    start_time = time.time()
    website_name = "jav321"
    LogBuffer.req().write(f"-> {website_name}")
    title = ""
    cover_url = ""
    poster_url = ""
    image_download = False
    image_cut = "right"
    mosaic = "有码"
    web_info = "\n       "
    LogBuffer.info().write(" \n    🌐 jav321")
    debug_info = ""

    try:
        result_url = "https://www.jav321.com/search"
        if appoint_url != "":
            result_url = appoint_url
            debug_info = f"番号地址: {result_url}"
            LogBuffer.info().write(web_info + debug_info)
        else:
            debug_info = f'搜索地址: {result_url} {{"sn": {number}}}'
            LogBuffer.info().write(web_info + debug_info)
        response, error = await manager.computed.async_client.post_text(result_url, data={"sn": number})
        if response is None:
            debug_info = f"网络请求错误: {error}"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)
        if "AVが見つかりませんでした" in response:
            debug_info = "搜索结果: 未匹配到番号！"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)
        detail_page = etree.fromstring(response, etree.HTMLParser())
        website = getWebsite(detail_page)
        if website:
            debug_info = f"番号地址: {website} "
            LogBuffer.info().write(web_info + debug_info)
        actor = getActor(response)
        actor_photo = getActorPhoto(actor)
        title = getTitle(response).strip()  # 获取标题
        if not title:
            debug_info = "数据获取失败: 未获取到标题！"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)
        cover_url = getCover(detail_page)  # 获取cover
        poster_url = getCoverSmall(detail_page)
        if not cover_url:
            cover_url = poster_url
        release = getRelease(response)
        year = getYear(release)
        runtime = getRuntime(response)
        number = getNum(response, number)
        outline = getOutline(detail_page)
        tag = getTag(response)
        score = getScore(response)
        studio = getStudio(detail_page)
        series = getSeries(detail_page)
        extrafanart = getExtraFanart(detail_page)
        cover_url, poster_url = _normalize_thumb_poster(cover_url, poster_url)
        extrafanart = _remove_cover_from_extrafanart(cover_url, extrafanart)
        cover_url = await _validate_dmm_image_if_needed(cover_url, "thumb")
        poster_url = await _resolve_dmm_poster_url(cover_url, poster_url)
        if DownloadableFile.EXTRAFANART in manager.config.download_files:
            extrafanart = await _filter_dmm_extrafanart(extrafanart)
        else:
            extrafanart = _normalize_extrafanart_urls(extrafanart)
        # 判断无码
        uncensorted_list = [
            "一本道",
            "HEYZO",
            "サムライポルノ",
            "キャットウォーク",
            "サイクロン",
            "ルチャリブレ",
            "スーパーモデルメディア",
            "スタジオテリヤキ",
            "レッドホットコレクション",
            "スカイハイエンターテインメント",
            "小天狗",
            "オリエンタルドリーム",
            "Climax Zipang",
            "CATCHEYE",
            "ファイブスター",
            "アジアンアイズ",
            "ゴリラ",
            "ラフォーレ ガール",
            "MIKADO",
            "ムゲンエンターテインメント",
            "ツバキハウス",
            "ザーメン二郎",
            "トラトラトラ",
            "メルシーボークー",
            "神風",
            "Queen 8",
            "SASUKE",
            "ファンタドリーム",
            "マツエンターテインメント",
            "ピンクパンチャー",
            "ワンピース",
            "ゴールデンドラゴン",
            "Tokyo Hot",
            "Caribbean",
        ]
        for each in uncensorted_list:
            if each == studio:
                mosaic = "无码"
                break
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
                "director": "",
                "studio": studio,
                "publisher": studio,
                "source": "jav321",
                "website": website,
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
    # print(main('blk-495'))
    # print(main('hkgl-004'))
    # print(main('snis-333'))
    # print(main('GERK-326'))
    # print(main('msfh-010'))
    # print(main('msfh-010'))
    # print(main('kavr-065'))
    # print(main('ssni-645'))
    # print(main('sivr-038'))
    # print(main('ara-415'))
    # print(main('luxu-1257'))
    # print(main('heyzo-1031'))
    # print(main('ABP-905'))
    # print(main('heyzo-1031', ''))
    # print(main('ymdd-173', 'https://www.jav321.com/video/ymdd00173'))
    print(main("MIST-409"))
