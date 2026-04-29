import pytest

from mdcx.config.enums import Language
from mdcx.crawlers.prestige import PrestigeCrawler
from mdcx.models.types import CrawlerInput


class FakePrestigeClient:
    async def get_json(self, url, **kwargs):
        if url.startswith("https://www.prestige-av.com/api/search"):
            return (
                {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "productUuid": "uuid-001",
                                    "deliveryItemId": "ABW-130",
                                }
                            }
                        ]
                    }
                },
                "",
            )
        if url == "https://www.prestige-av.com/api/product/uuid-001":
            return (
                {
                    "title": "サンプルタイトル",
                    "body": "あらすじ",
                    "actress": [{"name": "演员 A"}],
                    "genre": [{"name": "企画"}],
                    "media": [{"path": "sample/001.jpg"}],
                    "thumbnail": {"path": "goods/prestige/abw/130/pf_abw-130.jpg"},
                    "packageImage": {"path": "goods/prestige/abw/130/pb_abw-130.jpg"},
                    "sku": [{"salesStartAt": "2026-04-01T00:00:00"}],
                    "playTime": 120,
                    "series": {"name": "系列"},
                    "directors": [{"name": "导演"}],
                    "maker": {"name": "制作商"},
                    "label": {"name": "发行"},
                    "movie": {"path": "movie/sample.mp4"},
                },
                "",
            )
        return None, f"unexpected url: {url}"


@pytest.mark.asyncio
async def test_prestige_crawler_maps_api_response():
    crawler = PrestigeCrawler(client=FakePrestigeClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="ABW-130",
            short_number="ABW-130",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "サンプルタイトル"
    assert res.data.actors == ["演员A"]
    assert res.data.directors == ["导演"]
    assert res.data.tags == ["企画"]
    assert res.data.release == "2026-04-01"
    assert res.data.runtime == "120"
    assert res.data.source == "prestige"
    assert res.data.external_id == "https://www.prestige-av.com/goods/uuid-001"
