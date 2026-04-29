import oshash
import pytest

from mdcx.config.enums import Language, Switch, Website
from mdcx.config.manager import manager
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.theporndb import TheporndbCrawler
from mdcx.models.types import CrawlerInput


class FakeTheporndbClient:
    async def get_json(self, url, **kwargs):
        if url == "https://api.theporndb.net/scenes/test-scene":
            return {"data": _api_data("test-scene", "scenes")}, ""
        if url == "https://api.theporndb.net/scenes/test-movie":
            return {"data": None}, ""
        if url == "https://api.theporndb.net/movies/test-movie":
            return {"data": _api_data("test-movie", "movies")}, ""
        return None, f"unexpected url: {url}"


class FakeTheporndbSearchClient:
    async def get_json(self, url, **kwargs):
        if url == "https://api.theporndb.net/scenes/hash/fakehash":
            return None, "HTTP 404"
        if url == "https://api.theporndb.net/scenes?parse=nurumassage 2026-02-23&per_page=100":
            return {"data": [_api_data("nurumassage-ellie-nova", "scenes", title="Ellie Nova", date="2026-02-23")]}, ""
        if url == "https://api.theporndb.net/scenes/nurumassage-ellie-nova":
            return {"data": _api_data("nurumassage-ellie-nova", "scenes", title="Ellie Nova", date="2026-02-23")}, ""
        return None, f"unexpected url: {url}"


def _api_data(slug: str, kind: str, title: str | None = None, date: str = "2026-04-03") -> dict:
    return {
        "slug": slug,
        "title": title or f"{kind} title",
        "description": "Outline",
        "date": date,
        "trailer": "https://example.test/trailer.mp4",
        "background": {"large": "https://example.test/cover.jpg"},
        "posters": {"large": "https://example.test/poster.jpg"},
        "duration": 7200,
        "site": {"name": "Series A", "short_name": "seriesa", "network": {"name": "Network A"}},
        "director": {"name": "Director A"},
        "tags": [{"name": "Tag A"}],
        "performers": [
            {"name": "Actor A", "parent": {"extras": {"gender": "Female"}}},
            {"name": "Actor B", "parent": {"extras": {"gender": "Male"}}},
        ],
    }


def _input(appoint_url: str) -> CrawlerInput:
    return CrawlerInput(
        appoint_number="",
        appoint_url=appoint_url,
        file_path=None,
        mosaic="",
        number="SceneTest",
        short_number="SceneTest",
        language=Language.JP,
        org_language=Language.JP,
    )


def _file_input() -> CrawlerInput:
    data = _input("")
    data.number = "Nurumassage.26.02.23"
    data.short_number = "Nurumassage.26.02.23"
    data.file_path = "D:/Code/Personal/daiguaxiao/nurumassage.26.02.23.ellie.nova.mp4"
    return data


@pytest.mark.asyncio
async def test_theporndb_crawler_reads_scene_detail_url():
    old_token = manager.config.theporndb_api_token
    manager.config.theporndb_api_token = "token"
    try:
        crawler = TheporndbCrawler(client=FakeTheporndbClient())
        res = await crawler.run(_input("https://theporndb.net/scenes/test-scene"))
    finally:
        manager.config.theporndb_api_token = old_token

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "theporndb"
    assert res.data.number == "SeriesA.26.04.03"
    assert res.data.title == "scenes title"
    assert res.data.actors == ["Actor A"]
    assert res.data.all_actors == ["Actor A", "Actor B"]
    assert res.data.directors == ["Director A"]
    assert res.data.tags == ["Tag A"]
    assert res.data.runtime == "120"
    assert res.data.thumb == "https://example.test/cover.jpg"
    assert res.data.poster == "https://example.test/poster.jpg"
    assert res.data.external_id == "https://api.theporndb.net/scenes/test-scene"


@pytest.mark.asyncio
async def test_theporndb_crawler_falls_back_to_movies():
    old_token = manager.config.theporndb_api_token
    manager.config.theporndb_api_token = "token"
    try:
        crawler = TheporndbCrawler(client=FakeTheporndbClient())
        res = await crawler.run(_input("https://theporndb.net/movies/test-movie"))
    finally:
        manager.config.theporndb_api_token = old_token

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "movies title"
    assert res.data.external_id == "https://api.theporndb.net/movies/test-movie"


@pytest.mark.asyncio
async def test_theporndb_crawler_continues_search_when_hash_misses(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(oshash, "oshash", lambda file_path: "fakehash")
    old_token = manager.config.theporndb_api_token
    old_switch_on = list(manager.config.switch_on)
    manager.config.theporndb_api_token = "token"
    manager.config.switch_on = [switch for switch in manager.config.switch_on if switch != Switch.THEPORNDB_NO_HASH]
    try:
        crawler = TheporndbCrawler(client=FakeTheporndbSearchClient())
        res = await crawler.run(_file_input())
    finally:
        manager.config.theporndb_api_token = old_token
        manager.config.switch_on = old_switch_on

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "Ellie Nova"
    assert res.debug_info.search_urls == [
        "https://api.theporndb.net/scenes/hash/fakehash",
        "https://api.theporndb.net/scenes?parse=nurumassage 2026-02-23&per_page=100",
    ]


def test_theporndb_crawler_is_registered():
    assert get_crawler(Website.THEPORNDB) is TheporndbCrawler
