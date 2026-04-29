import pytest

from mdcx.config.enums import Language, Website
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.official import OfficialCrawler
from mdcx.models.types import CrawlerInput


class FakeOfficialClient:
    async def get_text(self, url, **kwargs):
        if url == "https://s1s1s1.com/search/list?keyword=SSIS001":
            return (
                """
                <html><body>
                  <a class="img hover" href="https://s1s1s1.com/works/detail/ssis001">
                    <img data-src="https://example.test/poster.jpg" />
                  </a>
                </body></html>
                """,
                "",
            )
        if url == "https://s1s1s1.com/works/detail/ssis001":
            return _detail_html(), ""
        return None, f"unexpected url: {url}"


def _detail_html() -> str:
    return """
    <html>
      <head><meta name="description" content="【公式】Publisher A(Studio A)" /></head>
      <body>
        <h2 class="p-workPage__title">Official Title</h2>
        <a class="c-tag c-main-bg-hover c-main-font c-main-bd" href="/actress/a">Actor A</a>
        <p class="p-workPage__text">Official outline</p>
        <div class="th">収録時間</div><div><div><p>120分</p></div></div>
        <div class="th">シリーズ</div><div><a>Series A</a></div>
        <div class="th">レーベル</div><div><a>Label A</a></div>
        <div class="th">監督</div><div><div><p>Director A</p></div></div>
        <div>発売日</div><div><div><a>2026年04月03日</a></div></div>
        <div>ジャンル</div><div><div><a>Genre A</a><a>Blu-ray（ブルーレイ）</a></div></div>
        <img class="swiper-lazy" data-src="https://example.test/cover.jpg" />
        <img class="swiper-lazy" data-src="https://example.test/extra.jpg" />
        <div class="video"><video src="https://example.test/trailer.mp4"></video></div>
      </body>
    </html>
    """


@pytest.mark.asyncio
async def test_official_crawler_uses_prefix_mapping_and_dynamic_source():
    crawler = OfficialCrawler(client=FakeOfficialClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="SSIS-001",
            short_number="SSIS-001",
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "s1s1s1"
    assert res.data.number == "SSIS-001"
    assert res.data.title == "Official Title"
    assert res.data.actors == ["Actor A"]
    assert res.data.outline == "Official outline"
    assert res.data.release == "2026-04-03"
    assert res.data.year == "2026"
    assert res.data.runtime == "120"
    assert res.data.series == "Series A"
    assert res.data.directors == ["Director A"]
    assert res.data.tags == ["Genre A"]
    assert res.data.publisher == "Label A"
    assert res.data.studio == "Studio A"
    assert res.data.thumb == "https://example.test/cover.jpg"
    assert res.data.poster == "https://example.test/poster.jpg"
    assert res.data.extrafanart == ["https://example.test/extra.jpg"]
    assert res.data.trailer == "https://example.test/trailer.mp4"


def test_official_crawler_is_registered():
    assert get_crawler(Website.OFFICIAL) is OfficialCrawler
