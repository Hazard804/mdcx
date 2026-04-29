import pytest

from mdcx.config.enums import Language, Website
from mdcx.crawlers.airav_cc import AiravCcCrawler
from mdcx.crawlers.base import get_crawler
from mdcx.models.types import CrawlerInput


class FakeAiravCcClient:
    async def get_text(self, url, **kwargs):
        if url == "https://airav.io/cn/search_result?kw=JUQ-888":
            return (
                """
                <html><body>
                  <div class="col oneVideo">
                    <a href="/cn/video?hid=QC-BT-4177567"></a>
                    <h5>JUQ-888 中文标题</h5>
                  </div>
                </body></html>
                """,
                "",
            )
        if url == "https://airav.io/cn/video?hid=QC-BT-4177567":
            return _detail_html(), ""
        return None, f"unexpected url: {url}"


def _detail_html() -> str:
    return """
    <html>
      <head>
        <script type="application/ld+json">
          {"thumbnailUrl": ["https://example.test/big_pic/cover.jpg"]}
        </script>
      </head>
      <body>
        <div class="video-title my-3"><h1>JUQ-888 中文标题</h1></div>
        <div>番号<span>JUQ-888</span></div>
        <div>女优<a>演员A</a></div>
        <div>厂商<a>制作商</a></div>
        <div><i class="fa fa-clock me-2"></i>2026-04-03</div>
        <div>标籤<a>剧情</a><a>无码</a></div>
        <div class="video-info"><p>中文简介 *根据分发信息</p></div>
        <div>系列<a>系列A</a></div>
      </body>
    </html>
    """


@pytest.mark.asyncio
async def test_airav_cc_crawler_uses_airav_io_and_language_path():
    crawler = AiravCcCrawler(client=FakeAiravCcClient(), base_url="https://airav.io")
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="JUQ-888",
            short_number="JUQ-888",
            language=Language.ZH_CN,
            org_language=Language.ZH_CN,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.debug_info.search_urls == ["https://airav.io/cn/search_result?kw=JUQ-888"]
    assert res.data.number == "JUQ-888"
    assert res.data.title == "中文标题"
    assert res.data.actors == ["演员A"]
    assert res.data.tags == ["剧情", "无码"]
    assert res.data.release == "2026-04-03"
    assert res.data.year == "2026"
    assert res.data.series == "系列A"
    assert res.data.studio == "制作商"
    assert res.data.outline == "中文简介"
    assert res.data.thumb == "https://example.test/big_pic/cover.jpg"
    assert res.data.poster == "https://example.test/small_pic/cover.jpg"
    assert res.data.mosaic == "无码"
    assert res.data.source == "airav_cc"


def test_airav_is_no_longer_registered():
    assert get_crawler(Website.AIRAV_CC) is AiravCcCrawler
    assert get_crawler(Website.AIRAV) is None
