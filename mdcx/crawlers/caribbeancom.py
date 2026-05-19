import json
import re
from typing import Any, override
from urllib.parse import quote, urljoin, urlparse

from parsel import Selector

from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData, DetailPageParser, extract_all_texts, extract_text


class BaseCaribbeanParser(DetailPageParser):
    crawler_cls: type["BaseCaribbeanCrawler"]
    studio_name = "Caribbeancom"

    @staticmethod
    def _clean_items(items: list[str]) -> list[str]:
        return list(dict.fromkeys([item.strip() for item in items if item and item.strip()]))

    @staticmethod
    def _movie_data(html: Selector) -> dict[str, Any]:
        html_content = html.get() or ""
        if not (matched := re.search(r"var\s+Movie\s*=\s*(\{.*?\});", html_content, re.S)):
            return {}
        try:
            return json.loads(matched.group(1).replace("\\/", "/"))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _spec_by_label(html: Selector, label: str) -> Selector | None:
        for row in html.xpath("//li[contains(@class,'movie-spec')]"):
            row_label = extract_text(row, "normalize-space(.//*[contains(@class,'spec-title')])")
            if row_label == label:
                return row
        return None

    @classmethod
    def _spec_text(cls, html: Selector, label: str) -> str:
        row = cls._spec_by_label(html, label)
        if row is None:
            return ""
        return " ".join(extract_all_texts(row, ".//*[contains(@class,'spec-content')]//text()"))

    @classmethod
    def _spec_links(cls, html: Selector, label: str) -> list[str]:
        row = cls._spec_by_label(html, label)
        if row is None:
            return []
        return cls._clean_items(extract_all_texts(row, ".//*[contains(@class,'spec-content')]//a//text()"))

    @staticmethod
    def _format_release(value: str) -> str:
        return (value or "").strip().replace("/", "-")

    @staticmethod
    def _runtime_to_minutes(value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        parts = [int(part) for part in re.findall(r"\d+", value)]
        if len(parts) >= 3:
            return str(parts[0] * 60 + parts[1])
        if len(parts) == 2:
            return str(parts[0])
        if len(parts) == 1:
            return str(parts[0])
        return ""

    async def number(self, ctx: Context, html: Selector) -> str:
        movie_id = str(self._movie_data(html).get("movie_id") or "").strip()
        return movie_id or ctx.input.number

    async def title(self, ctx: Context, html: Selector) -> str:
        return extract_text(html, "normalize-space(//h1[@itemprop='name'])", "normalize-space(//h1)")

    async def originaltitle(self, ctx: Context, html: Selector) -> str:
        return await self.title(ctx, html)

    async def actors(self, ctx: Context, html: Selector) -> list[str]:
        return self._spec_links(html, "出演")

    async def all_actors(self, ctx: Context, html: Selector) -> list[str]:
        return await self.actors(ctx, html)

    async def outline(self, ctx: Context, html: Selector) -> str:
        return extract_text(
            html,
            "normalize-space(//*[@itemprop='description'])",
            "normalize-space(//div[contains(@class,'movie-info')]//div[contains(@class,'heading')]/following-sibling::p[1])",
        )

    async def originalplot(self, ctx: Context, html: Selector) -> str:
        return await self.outline(ctx, html)

    async def release(self, ctx: Context, html: Selector) -> str:
        return self._format_release(self._spec_text(html, "配信日"))

    async def year(self, ctx: Context, html: Selector) -> str:
        release = await self.release(ctx, html)
        return match.group() if (match := re.search(r"\d{4}", release)) else ""

    async def runtime(self, ctx: Context, html: Selector) -> str:
        return self._runtime_to_minutes(self._spec_text(html, "再生時間"))

    async def series(self, ctx: Context, html: Selector) -> str:
        links = self._spec_links(html, "シリーズ")
        return links[0] if links else self._spec_text(html, "シリーズ")

    async def tags(self, ctx: Context, html: Selector) -> list[str]:
        return self._spec_links(html, "タグ")

    async def score(self, ctx: Context, html: Selector) -> str:
        score_text = self._spec_text(html, "ユーザー評価")
        stars = score_text.count("★")
        return f"{stars}.0" if stars else ""

    async def thumb(self, ctx: Context, html: Selector) -> str:
        movie = self._movie_data(html)
        site_name = str(movie.get("site_name") or "").strip()
        image_name = str(movie.get("image_name") or "").strip()
        movie_id = str(movie.get("movie_id") or "").strip()
        if site_name and image_name and movie_id:
            return f"https://www.{site_name}/assets/sample/{movie_id}/{image_name}"

        image = html.xpath("//script/text()").re_first(r"emimg\s*=\s*['\"]([^'\"]+)['\"]")
        if image and not image.endswith("."):
            return urljoin(self.crawler_cls.base_url_(), image)
        number = await self.number(ctx, html)
        return urljoin(self.crawler_cls.base_url_(), f"/moviepages/{number}/images/l_l.jpg") if number else ""

    async def poster(self, ctx: Context, html: Selector) -> str:
        return ""

    async def extrafanart(self, ctx: Context, html: Selector) -> list[str]:
        images = []
        for href in html.xpath("//a[contains(@class,'fancy-gallery')]/@href").getall():
            if "/member/" in urlparse(href).path or href.startswith("/member/"):
                continue
            images.append(urljoin(self.crawler_cls.base_url_(), href))
        return self._clean_items(images)

    async def trailer(self, ctx: Context, html: Selector) -> str:
        movie = self._movie_data(html)
        return str(
            movie.get("sample_m_flash_url") or movie.get("sample_aff_flash_url") or movie.get("sample_flash_url") or ""
        )

    async def studio(self, ctx: Context, html: Selector) -> str:
        links = self._spec_links(html, "スタジオ")
        return links[0] if links else self.studio_name

    async def publisher(self, ctx: Context, html: Selector) -> str:
        return await self.studio(ctx, html)

    async def mosaic(self, ctx: Context, html: Selector) -> str:
        return "无码"


class CaribbeancomParser(BaseCaribbeanParser):
    crawler_cls: type["BaseCaribbeanCrawler"]
    studio_name = "Caribbeancom"


class CaribbeancomprParser(BaseCaribbeanParser):
    crawler_cls: type["BaseCaribbeanCrawler"]
    studio_name = "CaribbeancomPR"


class BaseCaribbeanCrawler(BaseCrawler):
    parser: BaseCaribbeanParser
    NUMBER_PATTERN = re.compile(r"(\d{6}[-_]\d{3})")

    @classmethod
    @override
    def site(cls) -> Website:
        raise NotImplementedError

    @classmethod
    @override
    def base_url_(cls) -> str:
        raise NotImplementedError

    @classmethod
    def _normalize_number(cls, number: str) -> str:
        number = (number or "").strip()
        if matched := cls.NUMBER_PATTERN.search(number):
            return matched.group(1)
        return number

    @classmethod
    def _number_from_url(cls, detail_url: str) -> str:
        path = urlparse(detail_url).path
        if matched := cls.NUMBER_PATTERN.search(path):
            return matched.group(1)
        return ""

    def _build_detail_url(self, number: str) -> str:
        return f"{self.base_url}/moviepages/{quote(self._normalize_number(number))}/index.html"

    @override
    async def _fetch_detail(self, ctx: Context, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        _ = use_browser
        return await self.async_client.get_text(
            url, headers=self._get_headers(ctx), cookies=self._get_cookies(ctx), encoding="euc-jp"
        )

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        number = self._normalize_number(ctx.input.number)
        if not number:
            raise CralwerException("番号为空")
        return self._build_detail_url(number)

    @override
    async def _search(self, ctx: Context, search_urls: list[str]) -> list[str] | None:
        ctx.debug(f"{self.site().value} 跳过搜索页，直接使用详情页 URL: {search_urls}")
        return search_urls

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        return [search_url]

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        title = extract_text(html, "normalize-space(//h1[@itemprop='name'])", "normalize-space(//h1)")
        if not title:
            raise CralwerException(f"{self.site().value} 详情页不存在或页面结构异常: {detail_url}")

        url_number = self._number_from_url(detail_url)
        if not url_number:
            raise CralwerException(f"{self.site().value} 详情页 URL 未包含有效番号: {detail_url}")

        movie_id = str(self.parser._movie_data(html).get("movie_id") or "").strip()
        if not movie_id:
            raise CralwerException(f"{self.site().value} 详情页缺少影片标识: {detail_url}")
        if movie_id != url_number:
            raise CralwerException(f"{self.site().value} 详情页影片标识不一致: url={url_number}, page={movie_id}")

        data = await self.parser.parse(ctx, html, external_id=detail_url)
        input_number = self._normalize_number(ctx.input.number)
        if input_number and url_number and input_number != url_number:
            raise CralwerException(f"详情页番号与输入不一致: input={ctx.input.number}, detail={detail_url}")
        data.number = url_number
        return data


class CaribbeancomCrawler(BaseCaribbeanCrawler):
    parser = CaribbeancomParser()
    parser.crawler_cls = None  # type: ignore[assignment]

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.CARIBBEANCOM

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.caribbeancom.com"


CaribbeancomCrawler.parser.crawler_cls = CaribbeancomCrawler


class CaribbeancomprCrawler(BaseCaribbeanCrawler):
    parser = CaribbeancomprParser()
    parser.crawler_cls = None  # type: ignore[assignment]

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.CARIBBEANCOMPR

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.caribbeancompr.com"


CaribbeancomprCrawler.parser.crawler_cls = CaribbeancomprCrawler
