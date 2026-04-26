#!/usr/bin/env python3
import time

from ..config.manager import manager
from ..models.log_buffer import LogBuffer


def get_title(data):  # 获取标题
    return data.get("article", {}).get("title", "")


def get_cover(data, number):  # 获取封面URL
    image_url = data.get("article", {}).get("image_url", "")
    if image_url and "no-image" not in image_url:
        return image_url
    return ""


def get_release_date(data):  # 获取发行日期
    return data.get("article", {}).get("release_date", "")


def get_actors(data):  # 获取演员
    actresses = data.get("article", {}).get("actresses", [])
    return ",".join([actress.get("name", "") for actress in actresses]) if actresses else ""


def get_tags(data):  # 获取标签
    tags = data.get("article", {}).get("tags", [])
    return ",".join([tag.get("name", "") for tag in tags]) if tags else ""


def get_studio(data):  # 获取厂家
    writer = data.get("article", {}).get("writer", {})
    return writer.get("name", "")


def get_video_type(data):  # 获取视频类型
    censored = data.get("article", {}).get("censored")
    if censored == "無":
        return "無碼"
    elif censored == "有":
        return "有碼"
    else:
        return ""


def get_video_url(data):  # 获取视频URL
    # video_id = data.get("article", {}).get("video_id")
    # if video_id:
    #     return f"https://example.com/videos/{video_id}.mp4"
    return ""


def get_video_time(data):  # 获取视频时长
    duration = str(data.get("article", {}).get("duration", "")).strip()
    if not duration:
        return ""

    temp_list = duration.split(":")
    if len(temp_list) == 3:
        hours, minutes, seconds = temp_list
        try:
            total_minutes = int(hours) * 60 + int(minutes)
            if total_minutes == 0 and int(seconds) > 0:
                return "1"
            return str(total_minutes)
        except ValueError:
            return duration
    if len(temp_list) <= 2 and temp_list[0].isdigit():
        return str(int(temp_list[0]))
    return duration


def cookie_str_to_dict(cookie_str: str) -> dict:  # cookie 转为字典
    cookies = {}
    for item in cookie_str.split("; "):
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key] = value
    return cookies


async def main(
    number,
    appoint_url="",
    **kwargs,
):
    """
    主函数，获取FC2视频信息
    :param number: 番号
    :param appoint_url: 指定的URL
    :param language: 语言
    :return: JSON格式的影片信息
    """
    start_time = time.time()
    website_name = "fc2ppvdb"
    LogBuffer.req().write(f"-> {website_name}")
    real_url = appoint_url
    number = number.upper().replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()
    dic = {}
    web_info = "\n       "

    try:
        debug_info = f"番号地址: {real_url}"
        LogBuffer.info().write(web_info + debug_info)
        # ========================================================================番号详情页
        cookies = cookie_str_to_dict(manager.config.fc2ppvdb)
        use_proxy = manager.config.use_proxy

        # 先访问详情页，让站点接受配置中的独立 cookie。
        url_article = f"https://fc2ppvdb.com/articles/{number}"
        response_article, error = await manager.computed.async_client.request(
            "GET",
            url_article,
            cookies=cookies,
            use_proxy=use_proxy,
        )
        if response_article is None:
            raise Exception(f"详情页请求失败: {error}")
        if response_article.status_code != 200:
            raise Exception(f"详情页请求失败: {response_article.status_code}")

        # 再访问 XHR 接口获取 JSON 数据。
        xhr_url = f"https://fc2ppvdb.com/articles/article-info?videoid={number}"
        html_info, error = await manager.computed.async_client.get_json(
            xhr_url,
            cookies=cookies,
            use_proxy=use_proxy,
        )
        if html_info is None:
            raise Exception(f"XHR 请求失败: {error}")

        title = get_title(html_info)
        if not title:
            debug_info = "数据获取失败: 未获取到title！"
            LogBuffer.info().write(web_info + debug_info)
            raise Exception(debug_info)
        cover_url = get_cover(html_info, number)
        if "http" not in cover_url:
            debug_info = "数据获取失败: 未获取到cover！"
            LogBuffer.info().write(web_info + debug_info)
        release_date = get_release_date(html_info)
        year = release_date[:4] if release_date else ""
        actor = get_actors(html_info)
        tag = get_tags(html_info)
        studio = get_studio(html_info)  # 使用卖家作为厂商
        video_type = get_video_type(html_info)
        video_url = get_video_url(html_info)
        video_time = get_video_time(html_info)
        tag = tag.replace("無修正,", "").replace("無修正", "").strip(",")
        if "fc2_seller" in manager.config.fields_rule:
            actor = studio

        try:
            dic = {
                "number": "FC2-" + str(number),
                "title": title,
                "originaltitle": title,
                "outline": "",
                "actor": actor,
                "originalplot": "",
                "tag": tag,
                "release": release_date,
                "year": year,
                "runtime": video_time,
                "score": "",
                "series": "FC2系列",
                "director": "",
                "studio": studio,
                "publisher": studio,
                "source": "fc2",
                "website": real_url,
                "actor_photo": {actor: ""},
                "thumb": cover_url,
                "poster": cover_url,
                "extrafanart": [],
                "trailer": video_url,
                "image_download": False,
                "image_cut": "center",
                "mosaic": "无码" if video_type == "無碼" else "有码",
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
    print(main("FC2-3259498"))
