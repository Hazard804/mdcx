import asyncio
from typing import TYPE_CHECKING, Never, Protocol

from .config.enums import Website
from .crawlers.base import GenericBaseCrawler, get_crawler

if TYPE_CHECKING:
    from .config.models import Config
    from .web_async import AsyncWebClient


class CrawlerProviderProtocol(Protocol):
    async def get(self, site: Website) -> "GenericBaseCrawler[Never]": ...
    async def close(self) -> None: ...


class CrawlerProvider:
    def __init__(self, config: "Config", client: "AsyncWebClient"):
        self.instances: dict[Website, GenericBaseCrawler[Never]] = {}
        self.config = config
        self.client = client
        self.lock = asyncio.Lock()

    async def get(self, site: Website):
        if r := self.instances.get(site):
            return r
        async with self.lock:
            if site not in self.instances:
                crawler_cls = get_crawler(site)
                if crawler_cls is None:
                    raise ValueError(f"未找到 {site} 的刮削器")
                self.instances[site] = crawler_cls(
                    client=self.client,
                    base_url=self.config.get_site_url(site),
                    browser=None,
                )
        return self.instances[site]

    async def close(self):
        for instance in self.instances.values():
            await instance.close()
        self.instances.clear()
