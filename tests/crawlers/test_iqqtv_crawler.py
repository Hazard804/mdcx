import pytest

from mdcx.config.enums import Language
from mdcx.crawlers.iqqtv import IqqtvCrawler
from mdcx.models.types import CrawlerInput


class FakeIqqtvClient:
    async def get_text(self, url, **kwargs):
        if url == "https://iqq5.xyz/jp/search.php?kw=SSIS-001":
            return (
                """
                <html><body>
                  <a class="ga_click" href="/jp/player/SSIS-001"></a>
                  <span class="title"><a href="/jp/player/SSIS-001" title="SSIS-001 JP Title"></a></span>
                </body></html>
                """,
                "",
            )
        if url == "https://iqq5.xyz/jp/player/SSIS-001":
            return _detail_html("JP Title SSIS-001", "JP Outline"), ""
        if url == "https://iqq5.xyz/cn/player/SSIS-001":
            return _detail_html("中文标题 SSIS-001", "中文简介"), ""
        return None, f"unexpected url: {url}"


def _detail_html(title: str, outline: str) -> str:
    return f"""
    <html>
      <head><meta property="og:image" content="https://example.test/cover.jpg" /></head>
      <body>
        <h1 class="h4 b">{title}</h1>
        <a href="/actor/a"><span>演员A</span></a>
        <div class="intro"><p>简介：{outline}</p></div>
        <div class="date">2026/04/03</div>
        <div class="tag-info"><a href="/tag/a">剧情</a></div>
        <a href="/fac/a"><div itemprop="name">制作商</div></a>
        <a href="/series/a">系列</a>
        <div class="cover"><img data-src="https://example.test/extra.jpg" /></div>
      </body>
    </html>
    """


@pytest.mark.asyncio
async def test_iqqtv_crawler_keeps_jp_original_fields_for_zh_cn():
    crawler = IqqtvCrawler(client=FakeIqqtvClient(), base_url="https://iqq5.xyz")
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="SSIS-001",
            short_number="SSIS-001",
            language=Language.ZH_CN,
            org_language=Language.ZH_CN,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.number == "SSIS-001"
    assert res.data.title == "中文标题"
    assert res.data.originaltitle == "JP Title"
    assert res.data.outline == "中文简介"
    assert res.data.originalplot == "JP Outline"
    assert res.data.actors == ["演员A"]
    assert res.data.tags == ["剧情"]
    assert res.data.release == "2026-04-03"
    assert res.data.source == "iqqtv"
