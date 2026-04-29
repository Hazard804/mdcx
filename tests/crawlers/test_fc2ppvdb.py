import pytest

from mdcx.config.enums import Language
from mdcx.config.manager import manager
from mdcx.crawlers.fc2ppvdb import Fc2ppvdbCrawler
from mdcx.models.types import CrawlerInput


class FakeFc2ppvdbClient:
    def __init__(self):
        self.article_requested = False

    async def request(self, method, url, **kwargs):
        assert method == "GET"
        assert url == "https://fc2ppvdb.com/articles/3259498"
        self.article_requested = True

        class Response:
            status_code = 200

        return Response(), ""

    async def get_json(self, url, **kwargs):
        assert self.article_requested is True
        assert url == "https://fc2ppvdb.com/articles/article-info?videoid=3259498"
        return (
            {
                "article": {
                    "title": "FC2 Sample",
                    "image_url": "https://example.test/cover.jpg",
                    "release_date": "2026-04-02",
                    "actresses": [{"name": "演员A"}],
                    "tags": [{"name": "無修正"}, {"name": "素人"}],
                    "writer": {"name": "卖家"},
                    "censored": "無",
                    "duration": "01:05:30",
                }
            },
            "",
        )


@pytest.mark.asyncio
async def test_fc2ppvdb_crawler_uses_article_then_xhr(monkeypatch):
    monkeypatch.setattr(manager.config, "fields_rule", "")
    client = FakeFc2ppvdbClient()
    crawler = Fc2ppvdbCrawler(client=client)
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="FC2-PPV-3259498",
            short_number="FC2-PPV-3259498",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.number == "FC2-3259498"
    assert res.data.title == "FC2 Sample"
    assert res.data.actors == ["演员A"]
    assert res.data.tags == ["素人"]
    assert res.data.runtime == "65"
    assert res.data.mosaic == "无码"
    assert res.data.external_id == "https://fc2ppvdb.com/articles/3259498"
