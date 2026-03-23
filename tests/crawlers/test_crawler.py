import pytest

from mdcx.config.enums import Website
from mdcx.config.models import Config, SiteConfig
from mdcx.crawler import CrawlerProvider
from mdcx.crawlers.base import crawler_registry, get_crawler
from mdcx.web_async import AsyncWebClient


def test_crawler_classes():
    """测试所有注册的爬虫类可正常初始化."""
    async_client = AsyncWebClient(timeout=1)
    for site in crawler_registry:
        crawler_class = get_crawler(site)
        assert crawler_class is not None, f"未找到 {site} 的爬虫"
        # assert crawler_class.site() == site, f"{crawler_class} 的 site 方法返回值不正确"
        crawler_class(client=async_client)


@pytest.mark.asyncio
async def test_crawler_provider_always_uses_http_only():
    config = Config()
    config.site_configs[Website.DMM] = SiteConfig()
    provider = CrawlerProvider(config=config, client=AsyncWebClient(timeout=1))

    crawler = await provider.get(Website.DMM)

    assert crawler is not None
    assert crawler.browser is None
    await provider.close()
