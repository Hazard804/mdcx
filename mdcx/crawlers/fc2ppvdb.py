#!/usr/bin/env python3
from typing import override

from ..config.manager import manager
from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def get_title(data):  # 获取标题
    return data.get("article", {}).get("title", "")


def get_cover(data):  # 获取封面URL
    image_url = data.get("article", {}).get("image_url", "")
    if image_url and "no-image" not in image_url:
        return image_url
    return ""


def get_release_date(data):  # 获取发行日期
    return data.get("article", {}).get("release_date", "")


def get_actors(data):  # 获取演员
    actresses = data.get("article", {}).get("actresses", [])
    return [actress.get("name", "") for actress in actresses if actress.get("name")] if actresses else []


def get_tags(data):  # 获取标签
    tags = data.get("article", {}).get("tags", [])
    return [tag.get("name", "") for tag in tags if tag.get("name")] if tags else []


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


def normalize_fc2_number(number: str) -> str:
    return number.upper().replace("FC2PPV", "").replace("FC2-PPV-", "").replace("FC2-", "").replace("-", "").strip()


class Fc2ppvdbCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.FC2PPVDB

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://fc2ppvdb.com"

    @override
    async def _run(self, ctx: Context):
        number = normalize_fc2_number(ctx.input.number)
        article_url = f"{self.base_url}/articles/{number}"
        xhr_url = f"{self.base_url}/articles/article-info?videoid={number}"
        ctx.debug(f"番号地址: {article_url}")
        ctx.debug_info.detail_urls = [article_url]

        cookies = cookie_str_to_dict(manager.config.fc2ppvdb)
        use_proxy = manager.config.use_proxy
        response_article, error = await self.async_client.request(
            "GET",
            article_url,
            cookies=cookies,
            use_proxy=use_proxy,
        )
        if response_article is None:
            raise CralwerException(f"详情页请求失败: {error}")
        if response_article.status_code != 200:
            raise CralwerException(f"详情页请求失败: {response_article.status_code}")

        ctx.debug(f"XHR 地址: {xhr_url}")
        html_info, error = await self.async_client.get_json(
            xhr_url,
            cookies=cookies,
            use_proxy=use_proxy,
        )
        if html_info is None:
            raise CralwerException(f"XHR 请求失败: {error}")

        title = get_title(html_info)
        if not title:
            raise CralwerException("数据获取失败: 未获取到title！")
        cover_url = get_cover(html_info)
        if "http" not in cover_url:
            ctx.debug("数据获取失败: 未获取到cover！")
        release_date = get_release_date(html_info)
        actors = get_actors(html_info)
        tags = [tag for tag in get_tags(html_info) if tag != "無修正"]
        studio = get_studio(html_info)  # 使用卖家作为厂商
        if "fc2_seller" in manager.config.fields_rule and studio:
            actors = [studio]
        video_type = get_video_type(html_info)

        data = CrawlerData(
            number="FC2-" + str(number),
            title=title,
            originaltitle=title,
            outline="",
            actors=actors,
            originalplot="",
            tags=tags,
            release=release_date,
            year=release_date[:4] if release_date else "",
            runtime=get_video_time(html_info),
            score="",
            series="FC2系列",
            directors=[],
            studio=studio,
            publisher=studio,
            thumb=cover_url,
            poster=cover_url,
            extrafanart=[],
            trailer=get_video_url(html_info),
            image_download=False,
            image_cut="center",
            mosaic="无码" if video_type == "無碼" else "有码",
            external_id=article_url,
            wanted="",
        )
        result = data.to_result()
        result.source = self.site().value
        ctx.debug("数据获取成功！")
        return result

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str) -> CrawlerData | None:
        return None
