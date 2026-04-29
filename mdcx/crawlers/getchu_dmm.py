#!/usr/bin/env python3

from typing import override

from ..config.enums import Website
from .base import BaseCrawler, Context, CrawlerData
from .getchu import GetchuCrawler


class GetchuDmmCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.GETCHU_DMM

    @classmethod
    @override
    def base_url_(cls) -> str:
        return GetchuCrawler.base_url_()

    @override
    async def _run(self, ctx: Context):
        data = await GetchuCrawler(client=self.async_client, base_url=self.base_url)._scrape(ctx)
        result = data.to_result()
        if result.number.startswith("DLID") or "dl.getchu" in ctx.input.appoint_url:
            result.source = data.source if isinstance(data.source, str) else Website.GETCHU.value
        else:
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
