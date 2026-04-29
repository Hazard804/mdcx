import pytest

from mdcx.config.enums import Language
from mdcx.crawlers.freejavbt import FreejavbtCrawler
from mdcx.models.types import CrawlerInput


class FakeFreejavbtClient:
    async def get_text(self, url, **kwargs):
        assert url == "https://freejavbt.com/SSNI-531"
        return (
            """
            <html>
              <head><title>SSNI-531 Sample Title | FREE JAV BT</title></head>
              <head><meta property="og:image" content="https://example.test/cover.jpg" /></head>
              <body>
                <div class="single-video-info col-12"></div>
                <a class="btn actress active">演员A</a>
                <a class="btn actress active">森林原人</a>
                <div><span>日期</span><b>2026-04-03</b></div>
                <div><span>时长</span><b>120分钟</b></div>
                <div><span>系列</span><b>系列名</b></div>
                <div><span>导演</span><b>导演名</b></div>
                <div><span>制作</span><b>制作商</b></div>
                <div><span>发行</span><b>发行商</b></div>
                <a href="/genre/drama">#剧情</a><a href="/genre/sub">#中文字幕</a>
                <a class="tile-item" href="https://example.test/extra.jpg"></a>
              </body>
            </html>
            """,
            "",
        )


@pytest.mark.asyncio
async def test_freejavbt_crawler_maps_detail_page():
    crawler = FreejavbtCrawler(client=FakeFreejavbtClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="SSNI-531",
            short_number="SSNI-531",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.number == "SSNI-531"
    assert res.data.title == "Sample Title"
    assert res.data.actors == ["演员A"]
    assert res.data.all_actors == ["演员A", "森林原人"]
    assert res.data.tags == ["剧情", "中文字幕"]
    assert res.data.release == "2026-04-03"
    assert res.data.year == "2026"
    assert res.data.runtime == "120"
    assert res.data.series == "系列名"
    assert res.data.directors == ["导演名"]
    assert res.data.studio == "制作商"
    assert res.data.publisher == "发行商"
    assert res.data.thumb == "https://example.test/cover.jpg"
    assert res.data.extrafanart == ["https://example.test/extra.jpg"]
    assert res.data.source == "freejavbt"
