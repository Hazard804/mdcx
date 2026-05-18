import asyncio
import json
import re
from typing import Any, override
from urllib.parse import quote, urljoin, urlparse

from parsel import Selector

from mdcx.base.web import check_url

from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData, DetailPageParser, extract_all_texts, extract_text

PLACEHOLDER_VALUES = {"", "-", "--", "---", "-----", "N/A", "n/a"}
GALLERY_PROBE_BATCH_SIZE = 3
GALLERY_PROBE_MAX_INDEX = 300


class Parser(DetailPageParser):
    @staticmethod
    def _clean_items(items: list[str]) -> list[str]:
        return list(dict.fromkeys([item.strip() for item in items if item and item.strip()]))

    @staticmethod
    def _json_ld(html: Selector) -> dict[str, Any]:
        for script in html.xpath('//script[@type="application/ld+json"]/text()').getall():
            script = script.strip()
            if not script:
                continue
            try:
                data = json.loads(script)
            except json.JSONDecodeError:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("@type") == "Movie":
                    return item
        return {}

    @classmethod
    def _json_video(cls, html: Selector) -> dict[str, Any]:
        video = cls._json_ld(html).get("video")
        return video if isinstance(video, dict) else {}

    @staticmethod
    def _full_url(value: str) -> str:
        return urljoin(HeyzoCrawler.base_url_(), value)

    @staticmethod
    def _clean_placeholder(value: str) -> str:
        value = (value or "").strip()
        return "" if value in PLACEHOLDER_VALUES else value

    @staticmethod
    def _iso_duration_to_minutes(value: str) -> str:
        if not value:
            return ""
        matched = re.search(r"P(?:T)?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
        if not matched:
            return ""
        hours = int(matched.group(1) or 0)
        minutes = int(matched.group(2) or 0)
        seconds = int(matched.group(3) or 0)
        total = hours * 60 + minutes
        if seconds and not total:
            total = 1
        return str(total)

    @classmethod
    def _actor_names(cls, html: Selector) -> list[str]:
        actor = cls._json_ld(html).get("actor")
        actors = actor if isinstance(actor, list) else [actor]
        names: list[str] = []
        for item in actors:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
            else:
                name = str(item or "").strip()
            if name:
                names.append(name)
        if names:
            return cls._clean_items(names)
        return cls._clean_items(extract_all_texts(html, '//tr[contains(@class,"table-actor")]//a//text()'))

    async def number(self, ctx: Context, html: Selector) -> str:
        movie_id = HeyzoCrawler._page_movie_id(html)
        return f"HEYZO-{movie_id}" if movie_id else ctx.input.number

    async def title(self, ctx: Context, html: Selector) -> str:
        title = str(self._json_ld(html).get("name") or "").strip()
        return title or extract_text(html, "normalize-space(//h1)")

    async def originaltitle(self, ctx: Context, html: Selector) -> str:
        return await self.title(ctx, html)

    async def actors(self, ctx: Context, html: Selector) -> list[str]:
        return self._actor_names(html)

    async def all_actors(self, ctx: Context, html: Selector) -> list[str]:
        return await self.actors(ctx, html)

    async def outline(self, ctx: Context, html: Selector) -> str:
        outline = str(self._json_ld(html).get("description") or "").strip()
        return outline or extract_text(
            html, "//meta[@property='og:description']/@content", "//meta[@name='description']/@content"
        )

    async def originalplot(self, ctx: Context, html: Selector) -> str:
        return await self.outline(ctx, html)

    async def release(self, ctx: Context, html: Selector) -> str:
        release = str(self._json_ld(html).get("dateCreated") or "").strip()
        if release:
            return release.split("T", 1)[0].replace("/", "-")
        return extract_text(html, 'normalize-space(//tr[contains(@class,"table-release-day")]/td[2])').replace("/", "-")

    async def year(self, ctx: Context, html: Selector) -> str:
        release = await self.release(ctx, html)
        return matched.group() if (matched := re.search(r"\d{4}", release)) else ""

    async def runtime(self, ctx: Context, html: Selector) -> str:
        runtime = str(self._json_ld(html).get("duration") or self._json_video(html).get("duration") or "")
        return self._iso_duration_to_minutes(runtime)

    async def score(self, ctx: Context, html: Selector) -> str:
        score = extract_text(html, 'normalize-space(//span[@itemprop="ratingValue"])')
        return score if score else ""

    async def series(self, ctx: Context, html: Selector) -> str:
        series = extract_text(html, 'normalize-space(//tr[contains(@class,"table-series")]/td[2])')
        return self._clean_placeholder(series)

    async def tags(self, ctx: Context, html: Selector) -> list[str]:
        actor_types = extract_all_texts(html, '//tr[contains(@class,"table-actor-type")]//a/text()')
        keywords = extract_all_texts(html, '//ul[contains(@class,"tag-keyword-list")]//a/text()')
        return self._clean_items(actor_types + keywords)

    async def thumb(self, ctx: Context, html: Selector) -> str:
        image = str(self._json_ld(html).get("image") or "").strip()
        return self._full_url(image) if image else extract_text(html, "//meta[@property='og:image']/@content")

    async def poster(self, ctx: Context, html: Selector) -> str:
        return ""

    async def extrafanart(self, ctx: Context, html: Selector) -> list[str]:
        images: list[str] = []
        for script in html.xpath("//script/text()").getall():
            for image in re.findall(r'["\']([^"\']*/contents/3000/\d+/gallery/\d+\.jpg)["\']', script):
                if "/member/" not in image:
                    images.append(self._full_url(image))
        return self._clean_items(images)

    async def trailer(self, ctx: Context, html: Selector) -> str:
        # sample.mp4 是页面可见候选中更高清的版本，sample_low.mp4 仅作为兜底。
        video_url = str(self._json_video(html).get("contentUrl") or "").strip()
        if video_url:
            return self._full_url(video_url)
        sample = html.xpath("//script/text()").re_first(r'["\']([^"\']*/contents/3000/\d+/sample\.mp4)["\']')
        if sample:
            return self._full_url(sample)
        sample_low = html.xpath("//script/text()").re_first(r'["\']([^"\']*/contents/3000/\d+/sample_low\.mp4)["\']')
        return self._full_url(sample_low) if sample_low else ""

    async def studio(self, ctx: Context, html: Selector) -> str:
        return "HEYZO"

    async def publisher(self, ctx: Context, html: Selector) -> str:
        return "HEYZO"

    async def mosaic(self, ctx: Context, html: Selector) -> str:
        return "无码"


class HeyzoCrawler(BaseCrawler):
    parser = Parser()
    NUMBER_PATTERN = re.compile(r"(?i)\bHEYZO[-_ ]?(\d{3,})\b")
    URL_ID_PATTERN = re.compile(r"/moviepages/(\d+)/")

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.HEYZO

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.heyzo.com"

    @classmethod
    def _normalize_number(cls, number: str) -> str:
        if matched := cls.NUMBER_PATTERN.search(number or ""):
            return matched.group(1)
        return ""

    @classmethod
    def _number_from_url(cls, detail_url: str) -> str:
        if matched := cls.URL_ID_PATTERN.search(urlparse(detail_url).path):
            return matched.group(1)
        return ""

    @staticmethod
    def _page_movie_id(html: Selector) -> str:
        for pattern in [r"var\s+movieId\s*=\s*'(\d+)'", r"var\s+emid\s*=\s*'(\d+)'"]:
            if movie_id := html.xpath("//script/text()").re_first(pattern):
                return movie_id
        return ""

    def _build_detail_url(self, number: str) -> str:
        return f"{self.base_url}/moviepages/{quote(number)}/index.html"

    async def _check_image_url(self, ctx: Context, url: str) -> str:
        _ = ctx
        return str(await check_url(url) or "")

    @staticmethod
    def _gallery_index(url: str) -> int:
        if matched := re.search(r"/gallery/(\d+)\.jpg(?:[?#].*)?$", url):
            return int(matched.group(1))
        return 0

    def _build_gallery_url(self, movie_id: str, index: int) -> str:
        return f"{self.base_url}/contents/3000/{movie_id}/gallery/{index:03d}.jpg"

    async def _probe_gallery_extrafanart(self, ctx: Context, movie_id: str, existing_urls: list[str]) -> list[str]:
        images = list(dict.fromkeys(existing_urls))
        seen = set(images)
        start_index = max([self._gallery_index(url) for url in images] or [0]) + 1
        if start_index < 1:
            start_index = 1

        for batch_start in range(start_index, GALLERY_PROBE_MAX_INDEX + 1, GALLERY_PROBE_BATCH_SIZE):
            indexes = range(batch_start, min(batch_start + GALLERY_PROBE_BATCH_SIZE, GALLERY_PROBE_MAX_INDEX + 1))
            candidates = [(index, self._build_gallery_url(movie_id, index)) for index in indexes]
            checked_urls = await asyncio.gather(*[self._check_image_url(ctx, url) for _, url in candidates])

            should_stop = False
            for (index, _), valid_url in zip(candidates, checked_urls, strict=True):
                if not valid_url:
                    ctx.debug(f"HEYZO gallery 探测停止: index={index}")
                    should_stop = True
                    break
                ctx.debug(f"HEYZO gallery 探测通过: index={index}, url={valid_url}")
                if valid_url not in seen:
                    seen.add(valid_url)
                    images.append(valid_url)
            if should_stop:
                break

        return images

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        number = self._normalize_number(ctx.input.number)
        if not number:
            raise CralwerException("非 HEYZO 番号")
        return self._build_detail_url(number)

    @override
    async def _search(self, ctx: Context, search_urls: list[str]) -> list[str] | None:
        ctx.debug(f"HEYZO 跳过搜索页，直接使用详情页 URL: {search_urls}")
        return search_urls

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        return [search_url]

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        url_number = self._number_from_url(detail_url)
        if not url_number:
            raise CralwerException(f"HEYZO 详情页 URL 未包含有效番号: {detail_url}")

        page_movie_id = self._page_movie_id(html)
        if not page_movie_id:
            raise CralwerException(f"HEYZO 详情页缺少影片标识: {detail_url}")
        if page_movie_id != url_number:
            raise CralwerException(f"HEYZO 详情页影片标识不一致: url={url_number}, page={page_movie_id}")

        data = await self.parser.parse(ctx, html, external_id=detail_url)
        if not data.title:
            raise CralwerException(f"HEYZO 详情页未获取到标题: {detail_url}")

        input_number = self._normalize_number(ctx.input.number)
        if input_number and input_number != url_number:
            raise CralwerException(f"详情页番号与输入不一致: input={ctx.input.number}, detail={detail_url}")
        data.number = f"HEYZO-{url_number}"
        return data

    @override
    async def post_process(self, ctx: Context, res):
        movie_id = self._normalize_number(res.number or ctx.input.number)
        if movie_id:
            res.extrafanart = await self._probe_gallery_extrafanart(ctx, movie_id, list(res.extrafanart or []))
        return res
