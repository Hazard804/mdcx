import pytest

from mdcx.config.enums import Language
from mdcx.config.manager import manager
from mdcx.crawlers.fc2ppvdb import Fc2ppvdbCrawler, cookie_str_to_dict
from mdcx.models.types import CrawlerInput


class FakeFc2ppvdbClient:
    def __init__(self):
        self.article_requested = False

    async def request(self, method, url, **kwargs):
        assert method == "GET"
        if url == "https://fc2ppvdb.com/articles/3259498":
            self.article_requested = True

            class ArticleResponse:
                status_code = 200

            return ArticleResponse(), ""

        assert self.article_requested is True
        assert url == "https://fc2ppvdb.com/articles/article-info?videoid=3259498"

        class XhrResponse:
            status_code = 200
            headers = {"content-type": "application/json"}

            def json(self):
                return {
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
                }

        return XhrResponse(), ""


class FakeFc2ppvdbHtmlClient:
    async def request(self, method, url, **kwargs):
        assert method == "GET"

        if url == "https://fc2ppvdb.com/articles/3259498":

            class ArticleResponse:
                status_code = 200

            return ArticleResponse(), ""

        class XhrResponse:
            status_code = 200
            headers = {"content-type": "text/html; charset=UTF-8"}
            text = "<!DOCTYPE html><html><title>FC2PPVDB</title><body>ログイン</body></html>"

            def json(self):
                raise ValueError("Expecting value: line 1 column 1 (char 0)")

        return XhrResponse(), ""


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


def test_fc2ppvdb_cookie_parser_accepts_cookie_without_spaces():
    assert cookie_str_to_dict("foo=bar;fc2ppvdb_session=abc; theme=dark") == {
        "foo": "bar",
        "fc2ppvdb_session": "abc",
        "theme": "dark",
    }


@pytest.mark.asyncio
async def test_fc2ppvdb_crawler_reports_login_page_xhr(monkeypatch):
    monkeypatch.setattr(manager.config, "fields_rule", "")
    crawler = Fc2ppvdbCrawler(client=FakeFc2ppvdbHtmlClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="FC2-3259498",
            short_number="FC2-3259498",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
    )

    assert res.data is None
    assert res.debug_info.error is not None
    assert "fc2ppvdb Cookie 可能无效或已过期" in str(res.debug_info.error)
