import pytest

from mdcx.config.enums import Language, Website
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.mywife import MywifeCrawler
from mdcx.models.types import CrawlerInput


class FakeMywifeClient:
    async def get_text(self, url, **kwargs):
        if url == "https://mywife.cc/teigaku/model/no/1500":
            return (
                """
                <html>
                  <head><title>No.1500 Sample Title</title></head>
                  <body>
                    <video id="video" poster="//img.example.test/topview.jpg" src="https://example.test/trailer.mp4"></video>
                    <div class="modelsamplephototop">Sample outline</div>
                    <div class="modelwaku0"><img alt="Actor A" /></div>
                    <div class="modelsample_photowaku"><img src="https://example.test/extra1.jpg" /></div>
                  </body>
                </html>
                """,
                "",
            )
        if url == "https://seesaawiki.jp/av_neme/d/%C9%F1%A5%EF%A5%A4%A5%D5":
            return None, "skip wiki"
        return None, f"unexpected url: {url}"


@pytest.mark.asyncio
async def test_mywife_crawler_uses_direct_new_number_url():
    crawler = MywifeCrawler(client=FakeMywifeClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="mywife-1500",
            short_number="mywife-1500",
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "mywife"
    assert res.data.number == "Mywife No.1500"
    assert res.data.title == "Sample Title"
    assert res.data.actors == ["Actor A"]
    assert res.data.outline == "Sample outline"
    assert res.data.thumb == "https://img.example.test/topview.jpg"
    assert res.data.poster == "https://img.example.test/thumb.jpg"
    assert res.data.trailer == "https://example.test/trailer.mp4"
    assert res.data.extrafanart == ["https://example.test/extra1.jpg"]


def test_mywife_crawler_is_registered():
    assert get_crawler(Website.MYWIFE) is MywifeCrawler
