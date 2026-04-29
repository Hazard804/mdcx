import pytest

import mdcx.crawlers.dmm_new as dmm_module
from mdcx.config.enums import DownloadableFile
from mdcx.config.manager import manager
from mdcx.config.models import Website
from mdcx.crawlers.javdbapi import JavdbApiCrawler, JavdbApiMovie
from mdcx.models.types import CrawlerInput


def test_to_crawler_data_maps_api_response():
    crawler = JavdbApiCrawler(client=None)
    data = crawler._to_crawler_data(
        JavdbApiMovie.model_validate(
            {
                "universal_id": "SSIS-001",
                "title": "Title",
                "description": "Line 1<br>Line 2",
                "fullcover_url": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001pl.jpg",
                "frontcover_url": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001ps.jpg",
                "sample_movie_url": "https://cc3001.dmm.co.jp/pv/TOKEN/ssis00001_mhb_w.mp4",
                "release_date": "2021-02-18",
                "duration": 147,
                "source_url": "https://video.dmm.co.jp/av/content/?id=ssis00001",
                "maker": "エスワン ナンバーワンスタイル",
                "label": "S1 NO.1 STYLE",
                "series": None,
                "actresses": ["葵つかさ", "葵つかさ", "乙白さやか"],
                "directors": ["苺原"],
                "genres": ["ドラマ", "ギリモザ"],
                "samples": ["https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001jp-1.jpg"],
            }
        ),
        fallback_number="SSIS-001",
    )

    assert data.number == "SSIS-001"
    assert data.title == "Title"
    assert data.outline == "Line 1\nLine 2"
    assert data.runtime == "147"
    assert data.actors == ["葵つかさ", "乙白さやか"]
    assert data.all_actors == ["葵つかさ", "乙白さやか"]
    assert data.directors == ["苺原"]
    assert data.tags == ["ドラマ", "ギリモザ"]
    assert data.studio == "エスワン ナンバーワンスタイル"
    assert data.publisher == "S1 NO.1 STYLE"
    assert data.image_cut == "right"
    assert data.mosaic == "有码"
    assert data.external_id == "https://video.dmm.co.jp/av/content/?id=ssis00001"


@pytest.mark.asyncio
async def test_run_calls_api_and_reuses_dmm_image_processing(monkeypatch: pytest.MonkeyPatch):
    class FakeClient:
        async def get_json(self, url: str, **kwargs):
            assert url == "https://api.thejavdb.net/v1/movies?q=SSIS-001"
            assert kwargs == {"headers": {"Accept": "application/json"}}
            return (
                {
                    "universal_id": "SSIS-001",
                    "title": "Title",
                    "description": "Outline",
                    "fullcover_url": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001pl.jpg",
                    "frontcover_url": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001ps.jpg",
                    "sample_movie_url": "https://cc3001.dmm.co.jp/pv/TOKEN/ssis00001_mhb_w.mp4",
                    "release_date": "2021-02-18",
                    "duration": 147,
                    "source_url": "https://video.dmm.co.jp/av/content/?id=ssis00001",
                    "maker": "Maker",
                    "label": "Label",
                    "actresses": ["Actor"],
                    "samples": ["https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001jp-1.jpg"],
                },
                "",
            )

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        return url

    monkeypatch.setattr(dmm_module, "check_url", fake_check_url)
    monkeypatch.setattr(
        manager.config,
        "download_files",
        [DownloadableFile.POSTER, DownloadableFile.THUMB, DownloadableFile.EXTRAFANART],
    )

    crawler = JavdbApiCrawler(client=FakeClient())
    input_data = CrawlerInput.empty()
    input_data.number = "SSIS-001"

    response = await crawler.run(input_data)

    assert response.data is not None
    assert response.data.source == Website.JAVDBAPI.value
    assert response.data.number == "SSIS-001"
    assert response.data.title == "Title"
    assert response.data.release == "2021-02-18"
    assert response.data.year == "2021"
    assert response.data.thumb == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001pl.jpg"
    assert response.data.poster == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001ps.jpg"
    assert response.data.extrafanart == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001jp-1.jpg"
    ]
