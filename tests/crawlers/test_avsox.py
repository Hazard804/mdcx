import json

import pytest

import mdcx.crawlers.avsox as avsox_module
from mdcx.config.models import Website
from mdcx.crawlers.avsox import (
    AvsoxCrawler,
    AvsoxMovie,
    extract_movie_id,
    normalize_digit_number,
    normalize_number,
)
from mdcx.models.types import CrawlerInput

DOMAIN = "https://avsox.click"

MOVIE_DATA = {
    "movieId": "kravlwn",
    "movieFanHao": "010414-516",
    "title": "010414-516 サンプルタイトル",
    "releaseDate": "2014-01-04",
    "length": 61,
    "posterSmall": "https://file.example.test/small.jpg",
    "posterLarge": "https://file.example.test/large.jpg",
    "sampleLarge": ["https://file.example.test/sample-1.jpg", "https://file.example.test/sample-1.jpg"],
    "series": {"seriesName": "Caribbeancom"},
    "studio": {"studioName": "Caribbeancom"},
    "genre": [{"genreName": "タグA"}, {"genreName": "タグB"}, {"genreName": "タグA"}],
    "star": [{"starName": "藤原ひとみ"}, {"starName": "藤原ひとみ"}],
}


class FakeAvsoxClient:
    """模拟站点请求: 页面请求返回含 CSRF token 的空壳, 接口请求返回 JSON."""

    def __init__(self, search_data=None, movie_data=None, page_unavailable=False):
        self.search_data = search_data if search_data is not None else [MOVIE_DATA]
        self.movie_data = movie_data if movie_data is not None else MOVIE_DATA
        self.page_unavailable = page_unavailable
        self.requests: list[dict] = []

    async def get_text(self, url: str, **kwargs):
        self.requests.append({"method": "GET", "url": url, "headers": kwargs.get("headers")})
        if self.page_unavailable:
            return None, "HTTP 500"
        return '<html><head><meta name="csrf-token" content="TOKEN"></head></html>', ""

    async def post_text(self, url: str, **kwargs):
        self.requests.append(
            {"method": "POST", "url": url, "body": kwargs.get("data"), "headers": kwargs.get("headers")}
        )
        method = url.rsplit("/", 1)[-1]
        if method == "search":
            return json.dumps({"code": 200, "data": self.search_data}), ""
        if method == "getMovie":
            return json.dumps({"code": 200, "data": self.movie_data}), ""
        return json.dumps({"code": 400, "message": "unknown method"}), ""


def make_input(number: str = "", appoint_url: str = "") -> CrawlerInput:
    input_data = CrawlerInput.empty()
    input_data.number = number
    input_data.short_number = number
    input_data.appoint_url = appoint_url
    return input_data


@pytest.fixture(autouse=True)
def fake_domain(monkeypatch: pytest.MonkeyPatch):
    async def fake_get_avsox_domain() -> str:
        return DOMAIN

    monkeypatch.setattr(avsox_module, "get_avsox_domain", fake_get_avsox_domain)


def test_normalize_number_and_extract_movie_id():
    # 严格规则与旧版页面解析一致: 仅忽略大小写与 -PPV 后缀
    assert normalize_number("ssis-001-ppv") == "SSIS-001"
    assert normalize_number("SSIS-001") == normalize_number("ssis-001")
    # 严格规则下下划线与短横线是不同写法
    assert normalize_number("100326_001") != normalize_number("100326-001")
    # 纯数字番号的兜底规则会忽略分隔符差异
    assert normalize_digit_number("100326_001") == normalize_digit_number("100326-001")
    assert normalize_digit_number("021517_374") == "021517374"
    assert extract_movie_id(f"{DOMAIN}/cn/movies/kravlwn") == "kravlwn"
    assert extract_movie_id(f"{DOMAIN}/cn/movie/kravlwn") == "kravlwn"
    assert extract_movie_id("kravlwn") == "kravlwn"
    assert extract_movie_id(f"{DOMAIN}/cn/search/010414-516") == ""


def test_to_crawler_data_maps_api_response():
    crawler = AvsoxCrawler(client=None)
    ctx = crawler.new_context(make_input("010414-516"))
    ctx.domain = DOMAIN
    ctx.movie_id = "kravlwn"

    data = crawler._to_crawler_data(ctx, AvsoxMovie.model_validate(MOVIE_DATA))

    assert data.number == "010414-516"
    assert data.title == "010414-516 サンプルタイトル"
    assert data.originaltitle == data.title
    assert data.actors == ["藤原ひとみ"]
    assert data.all_actors == ["藤原ひとみ"]
    assert data.tags == ["タグA", "タグB"]
    assert data.release == "2014-01-04"
    assert data.year == "2014"
    assert data.runtime == "61"
    assert data.series == "Caribbeancom"
    assert data.studio == "Caribbeancom"
    assert data.publisher == "Caribbeancom"
    assert data.thumb == "https://file.example.test/large.jpg"
    assert data.poster == "https://file.example.test/small.jpg"
    assert data.extrafanart == ["https://file.example.test/sample-1.jpg"]
    assert data.image_download is True
    assert data.mosaic == "无码"
    assert data.external_id == f"{DOMAIN}/cn/movies/kravlwn"


@pytest.mark.asyncio
async def test_run_searches_and_fetches_movie_detail():
    client = FakeAvsoxClient()
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("010414-516"))

    assert response.debug_info.error is None
    assert response.data is not None
    assert response.data.source == Website.AVSOX.value
    assert response.data.title == "010414-516 サンプルタイトル"
    assert response.data.mosaic == "无码"
    assert response.debug_info.search_urls == [f"{DOMAIN}/javu/data/api/search"]
    assert response.debug_info.detail_urls == [f"{DOMAIN}/cn/movies/kravlwn"]

    # 首次页面请求用于获取 CSRF token, 之后两次为接口调用
    assert [each["method"] for each in client.requests] == ["GET", "POST", "POST"]
    search_request = client.requests[1]
    assert search_request["url"] == f"{DOMAIN}/javu/data/api/search"
    assert json.loads(search_request["body"]) == [{"search": "010414-516", "lang": "cn"}, 60, 1]
    assert search_request["headers"]["X-CSRF-Token"] == "TOKEN"

    movie_request = client.requests[2]
    assert movie_request["url"] == f"{DOMAIN}/javu/data/api/getMovie"
    assert json.loads(movie_request["body"]) == ["kravlwn", "cn"]


@pytest.mark.asyncio
async def test_run_matches_number_with_ppv_suffix():
    client = FakeAvsoxClient(search_data=[{**MOVIE_DATA, "movieFanHao": "010414-516", "movieId": "kravlwn"}])
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("010414-516-PPV"))

    assert response.debug_info.error is None
    assert response.data is not None
    assert response.debug_info.detail_urls == [f"{DOMAIN}/cn/movies/kravlwn"]


@pytest.mark.asyncio
async def test_run_matches_digit_number_ignoring_separator():
    """纯数字番号: 严格比对失败时, 允许忽略 - 与 _ 的写法差异."""
    client = FakeAvsoxClient(search_data=[{**MOVIE_DATA, "movieFanHao": "021517-374", "movieId": "nvjyzbn"}])
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("021517_374"))

    assert response.debug_info.error is None
    assert response.data is not None
    assert response.debug_info.detail_urls == [f"{DOMAIN}/cn/movies/nvjyzbn"]


@pytest.mark.asyncio
async def test_run_prefers_exact_match_over_separator_variant():
    """多个结果时, 完全等同的候选优先于仅分隔符不同的候选."""
    client = FakeAvsoxClient(
        search_data=[
            {**MOVIE_DATA, "movieFanHao": "021517_374", "movieId": "looseid"},
            {**MOVIE_DATA, "movieFanHao": "021517-374", "movieId": "exactid"},
        ]
    )
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("021517-374"))

    assert response.debug_info.error is None
    assert response.debug_info.detail_urls == [f"{DOMAIN}/cn/movies/exactid"]


@pytest.mark.asyncio
async def test_run_does_not_ignore_separator_for_non_digit_number():
    """非纯数字番号不适用分隔符兜底, 避免 ABC_123 与 ABC-123 被当成同一番号."""
    client = FakeAvsoxClient(search_data=[{**MOVIE_DATA, "movieFanHao": "ABC-123", "movieId": "abcid"}])
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("ABC_123"))

    assert response.data is None
    assert "未匹配到番号" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_raises_when_digit_number_has_no_separator_variant_match():
    client = FakeAvsoxClient(search_data=[{**MOVIE_DATA, "movieFanHao": "021517-375", "movieId": "otherid"}])
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("021517_374"))

    assert response.data is None
    assert "未匹配到番号" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_raises_when_number_not_matched():
    client = FakeAvsoxClient(search_data=[])
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("ZZZZ-9999"))

    assert response.data is None
    assert "未匹配到番号" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_raises_when_only_candidate_is_not_exact_match():
    """站点搜索为模糊匹配, 唯一的候选若不精确匹配也不能采用."""
    client = FakeAvsoxClient(search_data=[{**MOVIE_DATA, "movieFanHao": "010414-517", "movieId": "aaaaaaa"}])
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("010414-516"))

    assert response.data is None
    assert "未匹配到番号" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_raises_when_multiple_candidates_without_exact_match():
    client = FakeAvsoxClient(
        search_data=[
            {**MOVIE_DATA, "movieFanHao": "010414-517", "movieId": "aaaaaaa"},
            {**MOVIE_DATA, "movieFanHao": "010414-518", "movieId": "bbbbbbb"},
        ]
    )
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("010414-516"))

    assert response.data is None
    assert "未匹配到番号" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_uses_appoint_url():
    client = FakeAvsoxClient()
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("010414-516", appoint_url=f"{DOMAIN}/cn/movies/kravlwn"))

    assert response.debug_info.error is None
    assert response.data is not None
    assert response.data.number == "010414-516"
    # 指定 URL 时跳过搜索, 只请求详情接口
    assert [each["method"] for each in client.requests].count("POST") == 1
    assert client.requests[-1]["url"] == f"{DOMAIN}/javu/data/api/getMovie"


@pytest.mark.asyncio
async def test_auth_is_cached_across_files_in_same_task():
    client = FakeAvsoxClient()
    crawler = AvsoxCrawler(client=client)

    await crawler.run(make_input("010414-516"))
    await crawler.run(make_input("010414-516"))

    assert [each["method"] for each in client.requests].count("GET") == 1
    assert [each["method"] for each in client.requests].count("POST") == 4


@pytest.mark.asyncio
async def test_run_degrades_when_csrf_page_unavailable():
    client = FakeAvsoxClient(page_unavailable=True)
    crawler = AvsoxCrawler(client=client)

    response = await crawler.run(make_input("010414-516"))

    assert response.debug_info.error is None
    assert response.data is not None
    assert "X-CSRF-Token" not in client.requests[1]["headers"]


@pytest.mark.asyncio
async def test_run_raises_when_api_returns_error_code():
    class ErrorClient(FakeAvsoxClient):
        async def post_text(self, url: str, **kwargs):
            return json.dumps({"code": 500, "message": "boom", "data": None}), ""

    crawler = AvsoxCrawler(client=ErrorClient())

    response = await crawler.run(make_input("010414-516"))

    assert response.data is None
    assert "接口返回异常" in str(response.debug_info.error)
