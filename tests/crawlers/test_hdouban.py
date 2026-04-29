import pytest

from mdcx.config.enums import Language
from mdcx.crawlers.hdouban import HdoubanCrawler
from mdcx.models.types import CrawlerInput


class FakeHdoubanClient:
    async def get_json(self, url, **kwargs):
        assert url == "https://api.6dccbca.com/api/search?ty=movie&search=SSIS-334&page=1&pageSize=12"
        return (
            {
                "data": {
                    "list": [
                        {
                            "id": 2202,
                            "number": "SSIS-334",
                            "name": "SSIS-334 示例标题",
                        }
                    ]
                }
            },
            "",
        )

    async def post_json(self, url, data=None, **kwargs):
        assert url == "https://api.6dccbca.com/api/movie/detail"
        assert data == {"id": "2202"}
        return (
            {
                "data": {
                    "number": "SSIS-334",
                    "name": "SSIS-334 示例标题",
                    "big_cove": "https://example.test/big.jpg",
                    "small_cover": "https://example.test/small.jpg",
                    "actors": [{"sex": "♀", "name": "演员A♀"}, {"sex": "♂", "name": "男演员"}],
                    "labels": [{"name": "国产"}, {"name": "剧情"}],
                    "director": [{"name": "导演"}],
                    "company": [{"name": "制作商"}],
                    "series": [{"name": "系列"}],
                    "release_time": "2026-04-03 00:00:00",
                    "time": "7200",
                    "score": "8.1",
                    "trailer": "https://example.test/trailer.mp4",
                    "map": [{"big_img": "https://example.test/extra.jpg"}],
                }
            },
            "",
        )


@pytest.mark.asyncio
async def test_hdouban_crawler_searches_and_maps_detail_api():
    crawler = HdoubanCrawler(client=FakeHdoubanClient(), base_url="https://ormtgu.com")
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="SSIS-334",
            short_number="SSIS-334",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.number == "SSIS-334"
    assert res.data.title == "示例标题"
    assert res.data.actors == ["演员A"]
    assert res.data.tags == ["国产", "剧情"]
    assert res.data.release == "2026-04-03"
    assert res.data.runtime == "2"
    assert res.data.score == "8.1"
    assert res.data.mosaic == "国产"
    assert res.data.external_id == "https://ormtgu.com/moviedetail/2202"
    assert res.data.source == "hdouban"
