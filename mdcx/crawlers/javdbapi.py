import html as html_utils
import re
from typing import override
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict

from mdcx.config.enums import DownloadableFile
from mdcx.config.manager import manager
from mdcx.config.models import Website
from mdcx.models.types import CrawlerResult
from mdcx.signals import signal

from .base import CralwerException, CrawlerData
from .dmm_new import DMMContext, DmmCrawler


class JavdbApiMovie(BaseModel):
    model_config = ConfigDict(extra="ignore")

    universal_id: str | None = None
    title: str | None = None
    description: str | None = None
    fullcover_url: str | None = None
    frontcover_url: str | None = None
    sample_movie_url: str | None = None
    release_date: str | None = None
    duration: int | str | None = None
    source_url: str | None = None
    maker: str | None = None
    label: str | None = None
    series: str | None = None
    actresses: list[str | None] | None = None
    directors: list[str | None] | None = None
    genres: list[str | None] | None = None
    samples: list[str | None] | None = None


class JavdbApiCrawler(DmmCrawler):
    @staticmethod
    def _log(message: str) -> None:
        signal.add_log(f"🎬 [JavdbApi] {message}")

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVDBAPI

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://api.thejavdb.net/v1"

    @staticmethod
    def _clean_text(value: object) -> str:
        text = html_utils.unescape(str(value or "").strip())
        if not text:
            return ""
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p\s*>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def _clean_list(cls, values: list[str | None] | None) -> list[str]:
        return list(dict.fromkeys(item for value in (values or []) if (item := cls._clean_text(value))))

    @staticmethod
    def _runtime(value: int | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, int):
            return str(value) if value > 0 else ""
        if matched := re.search(r"\d+", str(value)):
            return matched.group()
        return ""

    def _api_url(self, number: str) -> str:
        return f"{self.base_url}/movies?{urlencode({'q': number})}"

    @override
    async def _run(self, ctx: DMMContext) -> CrawlerResult:
        number = ctx.input.number.strip()
        if not number:
            raise CralwerException("番号为空")

        api_url = self._api_url(number)
        ctx.debug(f"API URL: {api_url}")
        ctx.debug_info.search_urls = [api_url]

        response, error = await self.async_client.get_json(api_url, headers={"Accept": "application/json"})
        if response is None:
            raise CralwerException(f"API 请求失败: {error}")

        try:
            movie = JavdbApiMovie.model_validate(response)
        except Exception as e:
            ctx.debug(f"API 响应解析失败: {e} {response=}")
            raise CralwerException("API 响应解析失败") from e

        data = self._to_crawler_data(movie, fallback_number=number)
        if not data.title and not data.thumb:
            ctx.debug(f"API 返回空内容: {response=}")
            raise CralwerException("API 返回空内容")

        if data.external_id:
            ctx.debug_info.detail_urls = [str(data.external_id)]

        data.source = self.site().value
        result = data.to_result()
        return await self.post_process(ctx, result)

    def _to_crawler_data(self, movie: JavdbApiMovie, *, fallback_number: str) -> CrawlerData:
        title = self._clean_text(movie.title)
        outline = self._clean_text(movie.description)
        source_url = self._clean_text(movie.source_url)
        number = self._clean_text(movie.universal_id) or fallback_number
        thumb = self._with_https(str(movie.fullcover_url or "").strip())
        poster = self._with_https(str(movie.frontcover_url or "").strip())

        return CrawlerData(
            title=title,
            originaltitle=title,
            outline=outline,
            originalplot=outline,
            number=number,
            thumb=thumb,
            poster=poster,
            trailer=self._with_https(str(movie.sample_movie_url or "").strip()),
            release=self._clean_text(movie.release_date),
            runtime=self._runtime(movie.duration),
            studio=self._clean_text(movie.maker),
            publisher=self._clean_text(movie.label),
            series=self._clean_text(movie.series),
            actors=self._clean_list(movie.actresses),
            all_actors=self._clean_list(movie.actresses),
            directors=self._clean_list(movie.directors),
            tags=self._clean_list(movie.genres),
            extrafanart=[self._with_https(str(url or "").strip()) for url in (movie.samples or []) if url],
            external_id=source_url or number,
            image_cut="right",
            mosaic="有码",
        )

    @override
    async def post_process(self, ctx: DMMContext, res: CrawlerResult) -> CrawlerResult:
        if res.trailer:
            res.trailer = self._pick_best_unvalidated_trailer("", [res.trailer])
        if not res.publisher:
            res.publisher = res.studio
        if res.extrafanart and DownloadableFile.EXTRAFANART not in manager.config.download_files:
            res.extrafanart = self._dedupe_urls(res.extrafanart)
        return await super().post_process(ctx, res)
