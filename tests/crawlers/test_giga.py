import pytest

from mdcx.config.enums import Language
from mdcx.crawlers.giga import GigaCrawler
from mdcx.models.types import CrawlerInput


class FakeGigaClient:
    def __init__(self):
        self.search_count = 0
        self.cookie_requested = False

    async def get_text(self, url, **kwargs):
        if url == "https://www.giga-web.jp/search/?keyword=SPSE-88":
            self.search_count += 1
            if self.search_count == 1:
                return '<a href="/cookie_set.php" />', ""
            return (
                """
                <div class="search_sam_box">
                    <a href="/product/index.php?product_id=7666"></a>
                    戦え！スペースウーマン（SPSE-88）
                </div>
                """,
                "",
            )
        if url == "https://www.giga-web.jp/product/index.php?product_id=7666":
            return (
                """
                <div id="works_pic"><ul><li><h5>戦え！スペースウーマン</h5></li></ul></div>
                <dt>作品番号</dt><dd>SPSE-88</dd>
                <dt>リリース</dt><dd>2026/04/10</dd>
                <dt>収録時間</dt><dd>70min</dd>
                <span class="yaku"><a>サンプル女優</a></span>
                <dt>監督</dt><dd>サンプル監督</dd>
                <div class="smh"><li><ul><li>
                    <a href="http://www.giga-web.jp/db_titles/spse/spse88/pac_l.jpg">
                        <img src="https://www.giga-web.jp/db_titles/spse/spse88/pac_s.jpg" />
                    </a>
                </li></ul></li></div>
                <div id="story_list2"><ul><li class="story_window">あらすじ</li></ul></div>
                <div id="tag_main"><a>特撮</a></div>
                """,
                "",
            )
        if url == "https://www.giga-web.jp/product/player_sample.php?id=7666&q=h":
            return '<source src="https://example.test/spse88.mp4"', ""
        return None, f"unexpected url: {url}"

    async def request(self, method, url, **kwargs):
        if method == "GET" and url == "https://www.giga-web.jp/cookie_set.php":
            self.cookie_requested = True
            return None, "GET https://www.giga-web.jp/cookie_set.php 失败: HTTP 302"
        return None, f"unexpected request: {method} {url}"


@pytest.mark.asyncio
async def test_giga_retries_search_after_cookie_gate():
    client = FakeGigaClient()
    crawler = GigaCrawler(client=client)
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="SPSE-88",
            short_number="SPSE-88",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert client.cookie_requested is True
    assert client.search_count == 2
    assert res.debug_info.detail_urls == ["https://www.giga-web.jp/product/index.php?product_id=7666"]
    assert res.data.number == "SPSE-88"
    assert res.data.trailer == "https://example.test/spse88.mp4"
