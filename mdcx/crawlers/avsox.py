#!/usr/bin/env python3
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, override

from pydantic import BaseModel, ConfigDict, Field

from ..base.web import get_avsox_domain
from ..config.models import Website
from ..models.types import CrawlerInput, CrawlerResult
from ..signals import signal
from .base import Context, CralwerException, CrawlerData, GenericBaseCrawler

# 站点前端已改造为 SPA, HTML 不再直出业务数据.
# 所有页面(含详情页)都只返回一个空壳, 真实数据统一由以下 JSON 接口提供:
#   POST {域名}/{SITE_APP}/data/api/{方法}
# 接口请求体为参数数组, 例如 search 接口: [{search, lang}, 每页条数, 页码]
SITE_APP = "javu"
INDEX_LANG = "cn"
PAGE_SIZE = 60

# 详情页路由格式: /{lang}/movies/{movieId}
MOVIE_ID_PATTERN = re.compile(r"/(?:movies|movie)/([^/?#]+)", re.IGNORECASE)


def normalize_number(value: str) -> str:
    """
    番号归一化, 用于比对输入番号与站点番号.

    规则与旧版页面解析保持一致: 仅忽略大小写与 -PPV 后缀, 番号必须严格一致.
    下划线(100326_001)与短横线(100326-001)属于不同写法, 不视为同一番号.
    """
    return value.upper().replace("-PPV", "").strip()


def extract_movie_id(url: str) -> str:
    """从详情页 URL 中解析影片 ID, 用于支持用户指定 URL 刮削."""
    value = (url or "").strip()
    if not value:
        return ""
    if matched := MOVIE_ID_PATTERN.search(value):
        return matched.group(1)
    # 允许直接填写影片 ID
    if "/" not in value:
        return value
    return ""


class AvsoxNamedEntity(BaseModel):
    """接口返回的命名实体, 系列/厂牌/标签/演员共用此结构."""

    model_config = ConfigDict(extra="ignore")

    series_name: str | None = Field(default=None, alias="seriesName")
    studio_name: str | None = Field(default=None, alias="studioName")
    genre_name: str | None = Field(default=None, alias="genreName")
    star_name: str | None = Field(default=None, alias="starName")

    @property
    def name(self) -> str:
        """取该实体在当前语言下的名称."""
        for value in (self.series_name, self.studio_name, self.genre_name, self.star_name):
            if value and value.strip():
                return value.strip()
        return ""


class AvsoxMovie(BaseModel):
    """接口返回的影片数据, 搜索接口与详情接口使用同一结构."""

    model_config = ConfigDict(extra="ignore")

    movie_id: str | None = Field(default=None, alias="movieId")
    movie_fan_hao: str | None = Field(default=None, alias="movieFanHao")
    title: str | None = None
    release_date: str | None = Field(default=None, alias="releaseDate")
    length: int | str | None = None
    poster_small: str | None = Field(default=None, alias="posterSmall")
    poster_large: str | None = Field(default=None, alias="posterLarge")
    sample_large: list[str] | None = Field(default=None, alias="sampleLarge")
    series: AvsoxNamedEntity | None = None
    studio: AvsoxNamedEntity | None = None
    genre: list[AvsoxNamedEntity] | None = None
    star: list[AvsoxNamedEntity] | None = None


@dataclass
class AvsoxContext(Context):
    domain: str = ""  # 站点域名, 每次刮削动态解析
    csrf_token: str = ""  # 前端页面 meta 中的 CSRF token
    movie_id: str = ""  # 当前影片在站点内的 ID

    @property
    def api_base(self) -> str:
        """接口基础地址."""
        return f"{self.domain}/{SITE_APP}/data/api"

    @property
    def movie_url(self) -> str:
        """当前影片的详情页地址."""
        return f"{self.domain}/{INDEX_LANG}/movies/{self.movie_id}"


class AvsoxCrawler(GenericBaseCrawler[AvsoxContext]):
    # 站点域名与 CSRF token 在同一批刮削内复用, 避免每个文件都重复请求一次页面
    _auth_cache: tuple[str, str] | None = None

    @staticmethod
    def _log(message: str) -> None:
        signal.add_log(f"🌐 [AVSOX] {message}")

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AVSOX

    @classmethod
    @override
    def base_url_(cls) -> str:
        return ""

    @override
    def new_context(self, input: CrawlerInput) -> AvsoxContext:
        return AvsoxContext(input=input)

    @override
    async def _run(self, ctx: AvsoxContext) -> CrawlerResult:
        await self._prepare(ctx)

        if ctx.input.appoint_url:
            ctx.movie_id = extract_movie_id(ctx.input.appoint_url)
            if not ctx.movie_id:
                raise CralwerException(f"无法从指定 URL 解析影片 ID: {ctx.input.appoint_url}")
            ctx.debug(f"使用指定详情页 URL: {ctx.input.appoint_url}")
        else:
            if not ctx.input.number:
                raise CralwerException("番号为空")
            ctx.movie_id = await self._search_movie_id(ctx, ctx.input.number)

        movie = await self._get_movie(ctx)
        data = self._to_crawler_data(ctx, movie)
        data.source = self.site().value
        result = data.to_result()
        return await self.post_process(ctx, result)

    async def _prepare(self, ctx: AvsoxContext) -> None:
        """解析站点域名并获取前端 CSRF token, 写入 Context 供本次刮削使用."""
        ctx.domain, ctx.csrf_token = await self._load_auth(ctx)

    async def _load_auth(self, ctx: AvsoxContext) -> tuple[str, str]:
        """
        获取站点域名与前端 CSRF token.

        页面请求仅用于获取 token 与 cookie, 使接口调用与浏览器行为保持一致;
        接口本身不校验 token, 因此获取失败时降级为不带 token 请求, 且不写入缓存以便下次重试.
        """
        if self._auth_cache is not None:
            return self._auth_cache

        domain = await get_avsox_domain()
        ctx.debug(f"站点域名: {domain}")

        html, error = await self.async_client.get_text(f"{domain}/{INDEX_LANG}")
        if html is None:
            ctx.debug(f"获取 CSRF token 失败, 将不带 token 调用接口: {error}")
            self._log(f"⚠️ 获取 CSRF token 失败, 已降级: {error}")
            return domain, ""

        matched = re.search(r'name="csrf-token" content="([^"]+)"', html)
        csrf_token = matched.group(1) if matched else ""
        ctx.debug(f"CSRF token: {'已获取' if csrf_token else '未获取'}")

        self._auth_cache = (domain, csrf_token)
        return self._auth_cache

    def _api_headers(self, ctx: AvsoxContext) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }
        if ctx.csrf_token:
            headers["X-CSRF-Token"] = ctx.csrf_token
        return headers

    async def _call_api(self, ctx: AvsoxContext, method: str, args: list[Any]) -> Any:
        """调用站点数据接口, 返回响应体中的 data 字段."""
        url = f"{ctx.api_base}/{method}"
        body = json.dumps(args, ensure_ascii=False)
        ctx.debug(f"接口请求: {url} {body}")

        text, error = await self.async_client.post_text(url, data=body, headers=self._api_headers(ctx))
        if text is None:
            raise CralwerException(f"接口请求失败: {error}")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as parse_error:
            ctx.debug(f"接口响应解析失败: {text[:200]}")
            raise CralwerException(f"接口响应解析失败: {parse_error}") from parse_error

        if payload.get("code") != 200:
            raise CralwerException(f"接口返回异常: code={payload.get('code')} message={payload.get('message')}")
        return payload.get("data")

    async def _search_movie_id(self, ctx: AvsoxContext, number: str) -> str:
        """按番号搜索影片, 返回影片 ID."""
        ctx.debug_info.search_urls = [f"{ctx.api_base}/search"]
        movies = self._validate_movies(
            await self._call_api(ctx, "search", [{"search": number, "lang": INDEX_LANG}, PAGE_SIZE, 1])
        )

        # 站点搜索为模糊匹配, 因此必须按番号严格筛选, 无法精确匹配时一律视为未找到
        target = normalize_number(number)
        movie = next((each for each in movies if normalize_number(each.movie_fan_hao or "") == target), None)
        if movie is None:
            ctx.debug(f"搜索结果: 未匹配到番号, 候选: {[each.movie_fan_hao for each in movies]}")
            raise CralwerException("搜索结果: 未匹配到番号")

        if not movie.movie_id:
            raise CralwerException("搜索结果缺少影片 ID")
        self._log(f"搜索命中: {movie.movie_fan_hao}")
        return movie.movie_id

    async def _get_movie(self, ctx: AvsoxContext) -> AvsoxMovie:
        """按影片 ID 获取详情数据."""
        data = await self._call_api(ctx, "getMovie", [ctx.movie_id, INDEX_LANG])
        if not isinstance(data, dict):
            raise CralwerException("详情数据格式异常")

        movie = AvsoxMovie.model_validate(data)
        ctx.debug(f"详情页数据获取成功: {ctx.movie_url}")
        ctx.debug_info.detail_urls = [ctx.movie_url]
        return movie

    @staticmethod
    def _validate_movies(data: Any) -> list[AvsoxMovie]:
        if not isinstance(data, list):
            raise CralwerException("搜索结果格式异常")
        return [AvsoxMovie.model_validate(each) for each in data if isinstance(each, dict)]

    @staticmethod
    def _unique(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(each for each in values if each))

    @staticmethod
    def _runtime(length: int | str | None) -> str:
        if length is None:
            return ""
        if isinstance(length, int):
            return str(length) if length > 0 else ""
        matched = re.search(r"\d+", str(length))
        return matched.group() if matched else ""

    def _to_crawler_data(self, ctx: AvsoxContext, movie: AvsoxMovie) -> CrawlerData:
        title = (movie.title or "").strip()
        if not title:
            raise CralwerException("数据获取失败: 未获取到title")

        release = (movie.release_date or "").strip()
        studio = movie.studio.name if movie.studio else ""
        # 详情接口同时给出大图与列表小图, 与旧版页面的大封面/列表封面保持一致
        thumb = (movie.poster_large or movie.poster_small or "").strip()
        poster = (movie.poster_small or movie.poster_large or "").strip()
        actors = self._unique(each.name for each in (movie.star or []))
        tags = self._unique(each.name for each in (movie.genre or []))
        extrafanart = self._unique(movie.sample_large or [])

        return CrawlerData(
            number=ctx.input.number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            tags=tags,
            release=release,
            year=release[:4],
            runtime=self._runtime(movie.length),
            series=movie.series.name if movie.series else "",
            studio=studio,
            publisher=studio,
            thumb=thumb,
            poster=poster,
            extrafanart=extrafanart,
            trailer="",
            image_download=bool(poster or thumb),
            mosaic="无码",
            external_id=ctx.movie_url,
        )

    # 站点已全面改为接口取数, 以下 HTML 解析入口不再使用, 保留空实现以复用 `_run` 之外的公共流程
    @override
    async def _generate_search_url(self, ctx: AvsoxContext) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: AvsoxContext, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: AvsoxContext, html, detail_url: str) -> CrawlerData | None:
        return None
