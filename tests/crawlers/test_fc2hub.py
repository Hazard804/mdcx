import pytest

from mdcx.config.enums import Language
from mdcx.config.manager import manager
from mdcx.crawlers.fc2hub import Fc2hubCrawler
from mdcx.models.types import CrawlerInput


class FakeFc2hubClient:
    async def get_text(self, url, **kwargs):
        if url == "https://javten.com/search?kw=1940476":
            return '<html><head><link href="https://javten.com/id1940476/" /></head></html>', ""
        if url == "https://javten.com/id1940476/":
            return (
                """
                <html>
                  <body>
                    <h1>FC2-1940476</h1><h1>Hub Sample Title</h1>
                    <a data-fancybox="gallery" href="//example.test/cover.jpg"></a>
                    <div style="padding: 0"><a href="//example.test/extra.jpg"></a></div>
                    <div class="col-8">seller</div>
                    <p class="card-text"><a href="/tag/a">tag-a</a><a href="/tag/b">tag-b</a></p>
                    <div class="col des">outline text</div>
                    <div class="player-api" data-id="4866909"></div>
                  </body>
                </html>
                """,
                "",
            )
        if url == "https://adult.contents.fc2.com/api/v2/videos/4866909/sample":
            return '{"path":"https://example.test/hub.mp4?mid=token"}', ""
        return None, f"unexpected url: {url}"


@pytest.mark.asyncio
async def test_fc2hub_crawler_searches_detail_and_sample_api(monkeypatch):
    monkeypatch.setattr(manager.config, "fields_rule", "")
    crawler = Fc2hubCrawler(client=FakeFc2hubClient(), base_url="https://javten.com")
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="FC2-1940476",
            short_number="FC2-1940476",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.number == "FC2-1940476"
    assert res.data.title == "Hub Sample Title"
    assert res.data.tags == ["tag-a", "tag-b"]
    assert res.data.studio == "seller"
    assert res.data.thumb == "https://example.test/cover.jpg"
    assert res.data.extrafanart == ["https://example.test/extra.jpg"]
    assert res.data.trailer == "https://example.test/hub.mp4?mid=token"
    assert res.data.source == "fc2hub"
