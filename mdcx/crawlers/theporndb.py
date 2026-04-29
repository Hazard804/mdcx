#!/usr/bin/env python3
import os.path
import re
from difflib import SequenceMatcher
from typing import Literal, override

import oshash

from ..base.number import remove_escape_string
from ..config.enums import Switch, Website
from ..config.manager import manager
from ..number import long_name
from .base import BaseCrawler, Context, CralwerException, CrawlerData

TheporndbKind = Literal["scenes", "movies"]


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def get_year(release):
    try:
        return re.findall(r"\d{4}", release)[0]
    except Exception:
        return ""


def get_number(series, release, title):
    try:
        if series and release:
            return series.replace(" ", "") + "." + re.findall(r"\d{2}-\d{2}-\d{2}", release)[0].replace("-", ".")
    except Exception:
        pass
    return title


def read_data(data, kind: TheporndbKind):
    title = data.get("title") or ""
    outline = data.get("description")
    outline = "" if not outline else outline.replace("＜p＞", "").replace("＜/p＞", "")
    release = data.get("date") or ""
    trailer = data.get("trailer") or ""
    try:
        cover = data["background"]["large"]
    except Exception:
        cover = data.get("image")
    cover = cover or ""
    try:
        poster = data["posters"]["large"]
    except Exception:
        poster = data.get("poster")
    poster = poster or ""
    try:
        runtime = str(int(int(data.get("duration")) / 60))
    except Exception:
        runtime = ""
    try:
        series = data["site"]["name"]
    except Exception:
        series = ""
    try:
        studio = data["site"]["network"]["name"]
    except Exception:
        studio = ""
    publisher = studio
    try:
        director = data["director"]["name"]
    except Exception:
        director = ""
    tag_list = []
    try:
        for each in data["tags"]:
            tag_list.append(each["name"])
    except Exception:
        pass
    slug = data.get("slug") or ""
    real_url = f"https://api.theporndb.net/{kind}/{slug}" if slug else ""
    all_actor_list = []
    actor_list = []
    try:
        for each in data["performers"]:
            all_actor_list.append(each["name"])
            if each["parent"]["extras"]["gender"] != "Male":
                actor_list.append(each["name"])
    except Exception:
        pass
    number = get_number(series, release, title)
    return CrawlerData(
        number=number,
        title=title,
        originaltitle=title,
        actors=actor_list,
        all_actors=all_actor_list,
        outline=outline,
        originalplot=outline,
        tags=tag_list,
        release=release,
        year=get_year(release),
        runtime=runtime,
        score="",
        series=series,
        directors=[director] if director else [],
        studio=studio,
        publisher=publisher,
        thumb=cover,
        poster=poster,
        extrafanart=[],
        trailer=trailer,
        image_download=False,
        image_cut="",
        mosaic="无码",
        external_id=real_url,
        wanted="",
    )


def get_real_url(res_search, file_path, series_ex, date, kind: TheporndbKind):
    search_data = res_search.get("data")
    file_name = os.path.split(file_path)[1].lower()
    new_file_name = re.findall(r"[\.-_]\d{2}\.\d{2}\.\d{2}(.+)", file_name)
    new_file_name = new_file_name[0] if new_file_name else file_name
    actor_number = len(new_file_name.replace(".and.", "&").split("&"))
    temp_file_path_space = re.sub(r"[\W_]", " ", file_path.lower()).replace("  ", " ").replace("  ", " ")
    temp_file_path_nospace = temp_file_path_space.replace(" ", "")
    try:
        if search_data:
            res_date_list = []
            res_title_list = []
            res_actor_list = []
            for each in search_data:
                res_id_url = f"https://api.theporndb.net/{kind}/{each['slug']}"
                try:
                    res_series = each["site"]["short_name"]
                except Exception:
                    res_series = ""
                try:
                    res_url = each["site"]["url"].replace("-", "")
                except Exception:
                    res_url = ""
                res_date = each["date"]
                res_title_space = re.sub(r"[\W_]", " ", each["title"].lower())
                res_title_nospace = res_title_space.replace(" ", "")
                actor_list_space = []
                actor_list_nospace = []
                for a in each["performers"]:
                    ac = re.sub(r"[\W_]", " ", a["name"].lower())
                    actor_list_space.append(ac)
                    actor_list_nospace.append(ac.replace(" ", ""))
                res_actor_title_space = (" ".join(actor_list_space) + " " + res_title_space).replace("  ", " ")

                if series_ex:
                    if series_ex == res_series or series_ex in res_url:
                        if date and res_date == date:
                            res_date_list.append([res_id_url, res_actor_title_space])
                        elif res_title_nospace in temp_file_path_nospace:
                            res_title_list.append([res_id_url, res_actor_title_space])
                        elif actor_list_nospace and len(actor_list_nospace) >= actor_number:
                            for a in actor_list_nospace:
                                if a not in temp_file_path_nospace:
                                    break
                            else:
                                res_actor_list.append([res_id_url, res_actor_title_space])
                    elif date and res_date == date and res_title_nospace in temp_file_path_nospace:
                        res_title_list.append([res_id_url, res_actor_title_space])
                elif kind == "scenes" or res_title_nospace in temp_file_path_nospace:
                    res_title_list.append([res_id_url, res_actor_title_space])

            for candidate_list in (res_date_list, res_title_list, res_actor_list):
                if len(candidate_list) == 1:
                    return candidate_list[0][0]
                if len(candidate_list):
                    return max(candidate_list, key=lambda each: similarity(each[1], temp_file_path_space))[0]
    except Exception:
        return False
    return False


def get_search_keyword(file_path):
    file_path = remove_escape_string(file_path)
    file_name = os.path.basename(file_path.replace("\\", "/")).replace(",", ".")
    file_name = os.path.splitext(file_name)[0]

    temp_number = re.findall(r"(([A-Z0-9-\.]{2,})[-_\. ]{1}2?0?(\d{2}[-\.]\d{2}[-\.]\d{2}))", file_path)
    keyword_list = []
    series_ex = ""
    date = ""
    if temp_number:
        full_number, series_ex, date = temp_number[0]
        series_ex = long_name(series_ex.lower().replace("-", "").replace(".", ""))
        date = "20" + date.replace(".", "-")
        keyword_list.append(series_ex + " " + date)
        temp_title = re.sub(r"[-_&\.]", " ", file_name.replace(full_number, "")).strip()
        temp_title_list = []
        [temp_title_list.append(i) for i in temp_title.split(" ") if i and i != series_ex]
        keyword_list.append(series_ex + " " + " ".join(temp_title_list[:2]))
    else:
        keyword_list.append(" ".join(file_name.split(".")[:2]).replace("-", " "))
    return keyword_list, series_ex, date


class TheporndbCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.THEPORNDB

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://api.theporndb.net"

    def _headers(self):
        api_token = manager.config.theporndb_api_token
        if not api_token:
            raise CralwerException("请添加 API Token 后刮削！（「设置」-「网络」-「API Token」）")
        return {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.202 Safari/537.36",
        }

    @override
    async def _run(self, ctx: Context):
        errors = []
        for kind in ("scenes", "movies"):
            try:
                data = await self._scrape_kind(ctx, kind)
                result = data.to_result()
                result.source = self.site().value
                ctx.debug("数据获取成功！")
                return result
            except Exception as e:
                errors.append(f"{kind}: {e}")
                ctx.debug(f"{kind} 获取失败，尝试下一类型: {e}")
        raise CralwerException("；".join(errors))

    async def _scrape_kind(self, ctx: Context, kind: TheporndbKind) -> CrawlerData:
        headers = self._headers()
        file_path = str(ctx.input.file_path or f"{ctx.input.number}.mp4")
        real_url = ctx.input.appoint_url.replace("//theporndb", "//api.theporndb")
        real_url = real_url.replace("/scenes/", f"/{kind}/").replace("/movies/", f"/{kind}/") if real_url else ""
        hash_data = None

        if not real_url:
            use_hash = kind == "movies" or Switch.THEPORNDB_NO_HASH not in manager.config.switch_on
            if use_hash:
                try:
                    file_hash = oshash.oshash(file_path)
                    hash_url = f"{self.base_url}/{kind}/hash/{file_hash}"
                    ctx.debug(f"请求地址: {hash_url}")
                    ctx.debug_info.search_urls = [*(ctx.debug_info.search_urls or []), hash_url]
                    hash_search, error = await self.async_client.get_json(hash_url, headers=headers)
                    if hash_search is None:
                        if "HTTP 401" in str(error):
                            raise CralwerException(f"请检查 API Token 是否正确: {manager.config.theporndb_api_token}")
                        ctx.debug(f"Hash 请求失败，继续文件名搜索: {error}")
                        hash_search = {}
                    hash_data = hash_search.get("data")
                    if hash_data:
                        return read_data(hash_data, kind)
                except CralwerException:
                    raise
                except Exception:
                    pass

            search_keyword_list, series_ex, date = get_search_keyword(file_path)
            last_search_url = ""
            for search_keyword in search_keyword_list:
                query = "parse" if kind == "scenes" else "q"
                last_search_url = f"{self.base_url}/{kind}?{query}={search_keyword}&per_page=100"
                ctx.debug(f"请求地址: {last_search_url}")
                ctx.debug_info.search_urls = [*(ctx.debug_info.search_urls or []), last_search_url]
                res_search, error = await self.async_client.get_json(last_search_url, headers=headers)
                if res_search is None:
                    if "HTTP 401" in str(error):
                        raise CralwerException(f"请检查 API Token 是否正确: {manager.config.theporndb_api_token}")
                    raise CralwerException(f"请求错误: {error}")

                real_url = get_real_url(res_search, file_path, series_ex, date, kind)
                if real_url:
                    break
            else:
                raise CralwerException(f"未找到匹配的内容: {last_search_url}")

        ctx.debug(f"番号地址: {real_url}")
        ctx.debug_info.detail_urls = [*(ctx.debug_info.detail_urls or []), real_url]
        res_real, error = await self.async_client.get_json(real_url, headers=headers)
        if res_real is None:
            if "HTTP 401" in str(error):
                raise CralwerException(f"请检查 API Token 是否正确: {manager.config.theporndb_api_token}")
            raise CralwerException(f"请求错误: {error}")

        real_data = res_real.get("data")
        if not real_data:
            raise CralwerException(f"未获取正确数据: {real_url}")
        return read_data(real_data, kind)

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str) -> CrawlerData | None:
        return None
