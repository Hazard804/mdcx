import pytest

from mdcx.config.enums import Language
from mdcx.config.manager import manager
from mdcx.crawlers.fc2club import Fc2clubCrawler
from mdcx.models.types import CrawlerInput


class FakeFc2clubClient:
    async def get_text(self, url, **kwargs):
        assert url == "https://fc2club.top/html/FC2-743423.html"
        return (
            """
            <html>
              <body>
                <h3>FC2-743423 サンプルタイトル</h3>
                <img class="responsive" src="../uploadfile/sample.jpg" />
                <p><strong>卖家信息</strong><a>seller</a></p>
                <p><strong>影片评分</strong> 88分</p>
                <p><strong>女优名字</strong><a>actor-a</a><a>actor-b</a></p>
                <p><strong>影片标签</strong><a>tag-a</a><a>tag-b</a></p>
                <h5><strong>资源参数</strong> 无码</h5>
              </body>
            </html>
            """,
            "",
        )


@pytest.mark.asyncio
async def test_fc2club_crawler_maps_detail_page(monkeypatch):
    monkeypatch.setattr(manager.config, "fields_rule", "")
    crawler = Fc2clubCrawler(client=FakeFc2clubClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="FC2-743423",
            short_number="FC2-743423",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.number == "FC2-743423"
    assert res.data.title == "サンプルタイトル"
    assert res.data.actors == ["actor-a", "actor-b"]
    assert res.data.tags == ["tag-a", "tag-b"]
    assert res.data.score == "88"
    assert res.data.studio == "seller"
    assert res.data.thumb == "https://fc2club.top/uploadfile/sample.jpg"
    assert res.data.mosaic == "无码"
    assert res.data.source == "fc2club"
