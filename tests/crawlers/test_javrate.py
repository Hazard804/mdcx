import pytest

from mdcx.config.models import Website
from mdcx.crawlers.javrate import (
    JavrateCrawler,
    code_matches,
    image_base_key,
    mosaic_from_type,
    parse_duration_text,
    parse_iso_duration,
    parse_release,
    parse_score,
    poster_url_from_cover,
    search_candidates,
    upgrade_cover_url,
)
from mdcx.models.types import CrawlerInput

BASE_URL = "https://www.javrate.com"
DETAIL_PATH = "/movie/detail/d40966e4-73b0-4222-959b-e06c33a2a73f.html"
DETAIL_URL = f"{BASE_URL}{DETAIL_PATH}"

SEARCH_HTML = f"""
<html><body>
  <a href="{DETAIL_PATH}" data-movie-code="SONE-535" data-movie-id="d40966e4">封面</a>
  <a href="{DETAIL_PATH}" data-movie-code="SONE-535" data-movie-id="d40966e4">移动端重复卡片</a>
</body></html>
"""

DETAIL_HTML = """
<html><head>
<script type="application/ld+json">
{"@type": "VideoObject", "name": "SONE-535 對壓力敏感的求職生", "duration": "PT2H3M12S"}
</script>
</head><body>
<div class="movie-detail-bg"><img src="https://picture.avking.xyz/compressed/20260906/20260906032954963963_76080_s.webp"></div>
<article>
  <h2 class="movie-type-badge badge bg-danger"><a data-adult-type="2">有碼A片</a></h2>
  <span class="badge movie-score-badge"><span class="material-symbols-outlined">star</span>3.85</span>
  <h1><strong class="fg-main">SONE-535</strong> 對壓力敏感的求職生</h1>
  <div class="key-container">
    <a class="keyword-tag-link" data-keyword-name="美乳">美乳</a>
    <a class="keyword-tag-link" data-keyword-name="中出">中出</a>
    <a class="keyword-tag-link" data-keyword-name="美乳">美乳</a>
    <a class="keyword-tag-link" data-keyword-name="">空标签</a>
  </div>
  <div class="row info-row">
    <div><span class="info-label">番號</span></div>
    <div><span class="info-value">SONE-535</span></div>
  </div>
  <div class="row info-row">
    <div><span class="info-label">出品廠商</span></div>
    <div class="company-tag-box">
      <a class="issuer-link" data-issuer-name="S1">S1</a>
    </div>
  </div>
  <div class="row info-row">
    <div><span class="info-label">發片日期</span></div>
    <div><span class="info-value">2025年1月14日</span></div>
  </div>
  <div class="row info-row">
    <div><span class="info-label">所屬系列</span></div>
    <div><a class="movieset-link" data-movieset-name="好色妻降臨">好色妻降臨</a></div>
  </div>
  <div class="description-text">
    <p>【在綫觀看】SONE-535</p>
    <p>求职学生容易依赖网络讯息。</p>
    <p>逐渐堕落的故事。</p>
  </div>
  <a class="actress-swiper-link" data-actress-name="佐藤愛瑠">佐藤愛瑠</a>
  <a class="actress-swiper-link" data-actress-name="佐藤愛瑠">佐藤愛瑠</a>
  <div class="swiper movie-swiper">
    <a data-photo-url="https://picture.avking.xyz/compressed/20260906/20260906032954963963_76080_l.webp">封面副本</a>
    <a data-photo-url="https://picture.avking.xyz/20250109/20250109075650574574.jpg">剧照</a>
    <a data-photo-url="https://picture.avking.xyz/20250109/20250109075650574574.jpg">重复剧照</a>
    <a data-photo-url="">空剧照</a>
  </div>
</article>
</body></html>
"""


class FakeResponse:
    def __init__(self, status_code: int = 200, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}


class FakeJavrateClient:
    """按 URL 返回预置页面, 记录请求顺序以便断言搜索候选的尝试顺序."""

    def __init__(
        self,
        search_pages: dict[str, str] | None = None,
        detail_html: str = DETAIL_HTML,
        poster_available: bool = True,
    ):
        self.search_pages = search_pages or {}
        self.detail_html = detail_html
        self.poster_available = poster_available
        self.requests: list[str] = []

    async def get_text(self, url: str, **kwargs):
        self.requests.append(url)
        if url in self.search_pages:
            return self.search_pages[url], ""
        if url.startswith(f"{BASE_URL}/search/"):
            return "<html><body>未找到</body></html>", ""
        if url == DETAIL_URL:
            return self.detail_html, ""
        return None, "HTTP 404"

    async def request(self, method: str, url: str, **kwargs):
        self.requests.append(url)
        if method != "HEAD":
            return None, "仅支持 HEAD 探测"
        if self.poster_available and url.endswith("_right_l.webp"):
            return FakeResponse(200, {"Content-Type": "image/webp"}), ""
        return None, "HTTP 404"


def make_input(number: str = "SONE-535", appoint_url: str = "") -> CrawlerInput:
    input_data = CrawlerInput.empty()
    input_data.number = number
    input_data.short_number = number
    input_data.appoint_url = appoint_url
    return input_data


def test_search_candidates_for_plain_number():
    assert search_candidates("SONE-535") == ["SONE-535"]
    assert search_candidates("") == []


def test_search_candidates_for_uncensored_digit_number():
    candidates = search_candidates("052416_304")

    assert candidates[0] == "052416_304"
    # 站内实际写法优先: 一本道用下划线, 其余站族用短横线
    assert candidates[1] == "1PON-052416_304"
    assert candidates[2] == "CARIB-052416-304"
    assert "CARIB-052416_304" in candidates
    # 去重后不应出现重复项
    assert len(candidates) == len({item.upper() for item in candidates})


def test_code_matches_requires_exact_code_for_plain_number():
    assert code_matches("SONE-535", "sone-535")
    # 普通番号不允许忽略分隔符, 避免 ABC_123 被当成 ABC-123
    assert not code_matches("ABC-123", "ABC_123")
    assert not code_matches("SONE-5350", "SONE-535")
    assert not code_matches("", "SONE-535")


def test_code_matches_allows_station_prefix_for_digit_number():
    assert code_matches("1PON-052416_304", "052416_304")
    assert code_matches("CARIB-052416-304", "052416-304")
    assert not code_matches("CARIB-052416-305", "052416_304")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025年1月14日", "2025-01-14"),
        ("2025-01-14", "2025-01-14"),
        ("2025/01/14", "2025-01-14"),
        ("", ""),
        ("2025年", ""),
        ("2025年2月30日", ""),
        ("未知日期", ""),
    ],
)
def test_parse_release(raw, expected):
    assert parse_release(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("PT2H3M12S", "123"), ("PT28M50S", "28"), ("PT0S", ""), ("", ""), ("bad", "")],
)
def test_parse_iso_duration(raw, expected):
    assert parse_iso_duration(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("02 : 03 : 12", "123"), ("00 : 28 : 50", "28"), ("00 : 00 : 30", "1"), ("00:00:00", ""), ("12", "")],
)
def test_parse_duration_text(raw, expected):
    assert parse_duration_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("star3.85", "3.85"), ("4.3", "4.3"), ("9.9", ""), ("0", ""), ("", "")],
)
def test_parse_score(raw, expected):
    assert parse_score(raw) == expected


def test_mosaic_from_type():
    assert mosaic_from_type("有碼A片") == "有码"
    assert mosaic_from_type("無碼A片") == "无码"
    assert mosaic_from_type("國產A片") == "国产"
    assert mosaic_from_type("") == ""


def test_upgrade_cover_url():
    cover = "https://picture.avking.xyz/compressed/20260906/20260906032954963963_76080_s.webp"

    assert upgrade_cover_url(cover).endswith("20260906032954963963_76080_l.webp")
    # 老片封面无尺寸后缀时保持原地址
    old_cover = "https://picture.avking.xyz/20231206/20231206022523154154.jpg"
    assert upgrade_cover_url(old_cover) == old_cover
    assert upgrade_cover_url("") == ""
    assert upgrade_cover_url("not-a-url") == ""


def test_poster_url_from_cover():
    cover = "https://picture.avking.xyz/compressed/20260906/20260906032954963963_76080_s.webp"

    assert (
        poster_url_from_cover(cover)
        == "https://picture.avking.xyz/compressed/20260906/20260906032954963963_76080_right_l.webp"
    )
    old_cover = "https://picture.avking.xyz/20231206/20231206022523154154.jpg"
    assert (
        poster_url_from_cover(old_cover)
        == "https://picture.avking.xyz/compressed/20231206/20231206022523154154_right_l.webp"
    )
    assert poster_url_from_cover("") == ""


def test_image_base_key_matches_cover_and_photo():
    cover = "https://picture.avking.xyz/compressed/20260906/20260906032954963963_76080_s.webp"
    photo = "https://picture.avking.xyz/compressed/20260906/20260906032954963963_76080_l.webp"

    assert image_base_key(cover) == image_base_key(photo)


@pytest.mark.asyncio
async def test_run_searches_and_parses_detail_page():
    client = FakeJavrateClient(search_pages={f"{BASE_URL}/search/SONE-535": SEARCH_HTML})
    crawler = JavrateCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.debug_info.error is None
    data = response.data
    assert data is not None
    assert data.source == Website.JAVRATE.value
    assert data.number == "SONE-535"
    assert data.title == "對壓力敏感的求職生"
    assert data.originaltitle == data.title
    assert data.outline == "求职学生容易依赖网络讯息。\n逐渐堕落的故事。"
    assert data.actors == ["佐藤愛瑠"]
    assert data.all_actors == ["佐藤愛瑠"]
    assert data.tags == ["美乳", "中出"]
    assert data.release == "2025-01-14"
    assert data.year == "2025"
    assert data.runtime == "123"
    assert data.score == "3.85"
    assert data.studio == "S1"
    assert data.publisher == "S1"
    assert data.series == "好色妻降臨"
    assert data.mosaic == "有码"
    assert data.thumb.endswith("20260906032954963963_76080_l.webp")
    assert data.poster.endswith("20260906032954963963_76080_right_l.webp")
    assert data.image_download is True
    # 封面副本与重复剧照都应被剔除
    assert data.extrafanart == ["https://picture.avking.xyz/20250109/20250109075650574574.jpg"]
    assert data.external_id == DETAIL_URL
    assert response.debug_info.detail_urls == [DETAIL_URL]


@pytest.mark.asyncio
async def test_run_uses_prefix_candidate_for_uncensored_digit_number():
    prefix_search_html = SEARCH_HTML.replace("SONE-535", "1PON-052416_304")
    client = FakeJavrateClient(search_pages={f"{BASE_URL}/search/1PON-052416_304": prefix_search_html})
    crawler = JavrateCrawler(client=client)

    response = await crawler.run(make_input("052416_304"))

    assert response.data is not None
    # 原始番号优先, 命中后不再尝试后续候选
    assert client.requests[0] == f"{BASE_URL}/search/052416_304"
    assert client.requests[1] == f"{BASE_URL}/search/1PON-052416_304"
    assert client.requests[2] == DETAIL_URL


@pytest.mark.asyncio
async def test_run_rejects_fuzzy_search_result():
    fuzzy_html = '<html><body><a href="/movie/detail/other.html" data-movie-code="SONE-5350">近似结果</a></body></html>'
    client = FakeJavrateClient(search_pages={f"{BASE_URL}/search/SONE-535": fuzzy_html})
    crawler = JavrateCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is None
    assert "未匹配到番号" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_uses_h1_code_when_info_row_missing():
    detail_html = DETAIL_HTML.replace('<span class="info-value">SONE-535</span>', "")
    client = FakeJavrateClient(search_pages={f"{BASE_URL}/search/SONE-535": SEARCH_HTML}, detail_html=detail_html)
    crawler = JavrateCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is not None
    # 信息行缺失时用标题前缀兜底番号, 并把它从标题中去掉
    assert response.data.number == "SONE-535"
    assert response.data.title == "對壓力敏感的求職生"


@pytest.mark.asyncio
async def test_run_falls_back_to_input_number_when_site_code_missing():
    detail_html = DETAIL_HTML.replace('<span class="info-value">SONE-535</span>', "")
    detail_html = detail_html.replace('<strong class="fg-main">SONE-535</strong>', "")
    client = FakeJavrateClient(search_pages={f"{BASE_URL}/search/SONE-535": SEARCH_HTML}, detail_html=detail_html)
    crawler = JavrateCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is not None
    # 番号缺失时回退到输入番号, 而不是空值或错误数据
    assert response.data.number == "SONE-535"
    assert response.data.title == "對壓力敏感的求職生"


@pytest.mark.asyncio
async def test_run_leaves_poster_empty_when_image_unavailable():
    client = FakeJavrateClient(search_pages={f"{BASE_URL}/search/SONE-535": SEARCH_HTML}, poster_available=False)
    crawler = JavrateCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is not None
    assert response.data.poster == ""
    assert response.data.image_download is False


@pytest.mark.asyncio
async def test_run_uses_appoint_url_without_search():
    client = FakeJavrateClient()
    crawler = JavrateCrawler(client=client)

    response = await crawler.run(make_input("SONE-535", appoint_url=DETAIL_URL))

    assert response.debug_info.error is None
    assert response.data is not None
    # 指定 URL 时跳过搜索, 首个请求即详情页
    assert client.requests[0] == DETAIL_URL


@pytest.mark.asyncio
async def test_run_matches_number_case_insensitively():
    client = FakeJavrateClient(search_pages={f"{BASE_URL}/search/sone-535": SEARCH_HTML})
    crawler = JavrateCrawler(client=client)

    response = await crawler.run(make_input("sone-535"))

    assert response.debug_info.error is None
    assert response.data is not None
    assert response.debug_info.detail_urls == [DETAIL_URL]


@pytest.mark.asyncio
async def test_run_reports_cloudflare_challenge_instead_of_not_found():
    class ChallengeClient(FakeJavrateClient):
        async def get_text(self, url: str, **kwargs):
            self.requests.append(url)
            return "<html><title>Just a moment...</title><div id='__cf_chl_opt'></div></html>", ""

    crawler = JavrateCrawler(client=ChallengeClient())

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is None
    assert "Cloudflare" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_reports_network_error_when_search_requests_fail():
    class FailingClient(FakeJavrateClient):
        async def get_text(self, url: str, **kwargs):
            self.requests.append(url)
            return None, "HTTP 500"

    crawler = JavrateCrawler(client=FailingClient())

    response = await crawler.run(make_input("052416_304"))

    assert response.data is None
    assert "搜索页请求失败" in str(response.debug_info.error)
    # 无码数字番号会依次尝试原始番号与站族前缀候选
    assert len(response.debug_info.search_urls or []) > 1


@pytest.mark.asyncio
async def test_run_raises_when_detail_page_has_no_title():
    client = FakeJavrateClient(search_pages={f"{BASE_URL}/search/SONE-535": SEARCH_HTML}, detail_html="<html></html>")
    crawler = JavrateCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is None
    assert "未获取到标题" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_falls_back_to_badge_when_ld_json_duration_missing():
    detail_html = DETAIL_HTML.replace('"duration": "PT2H3M12S"', '"duration": 0').replace(
        '<span class="badge movie-score-badge">',
        '<span class="badge bg-default">00 : 58 : 40</span><span class="badge movie-score-badge">',
    )
    client = FakeJavrateClient(search_pages={f"{BASE_URL}/search/SONE-535": SEARCH_HTML}, detail_html=detail_html)
    crawler = JavrateCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is not None
    assert response.data.runtime == "58"
    assert response.data.score == "3.85"
