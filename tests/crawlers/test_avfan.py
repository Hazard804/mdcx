import re

import pytest
from parsel import Selector

from mdcx.config.models import Website
from mdcx.crawlers.avfan import (
    AvfanCrawler,
    AvfanParser,
    card_number,
    movie_url,
    normalize_number,
    parse_gallery,
    parse_iso_duration,
    parse_json_ld,
    parse_mosaic,
    parse_release,
    parse_runtime,
    parse_score,
    parse_wanted,
)
from mdcx.crawlers.base import Context
from mdcx.models.types import CrawlerInput

BASE_URL = "https://avfan.com"
DETAIL_PATH = "/zh-CN/movies/lxACycyA"
DETAIL_URL = f"{BASE_URL}{DETAIL_PATH}"

SEARCH_HTML = f"""
<html><body>
  <div class="grid">
    <div class="flex flex-col relative group">
      <a href="{DETAIL_PATH}" class="block relative overflow-hidden pt-ar">
        <img src="https://c1.avfan.com/covers/se/sewuC8.jpg" loading="lazy"
             alt="SONE-535 一个容易被说服的求职应届生" />
      </a>
      <a href="{DETAIL_PATH}" class="block px-1 pb-2" title="[SONE-535] 一个容易被说服的求职应届生">
        <div class="title text-zinc-600 mt-2 text-sm">
          <strong class="block line-clamp-1 text-ellipsis history-link">SONE-535</strong>
        </div>
      </a>
    </div>
    <div class="flex flex-col relative group">
      <a href="/zh-CN/movies/fuzzy01">
        <img src="https://c1.avfan.com/covers/se/fuzzy.jpg" alt="SONE-5350 近似结果" />
      </a>
    </div>
  </div>
</body></html>
"""

DETAIL_HTML = """
<html><head>
<meta property="og:title" content="SONE-535 一个容易被说服的求职应届生" />
<meta property="og:image" content="https://c1.avfan.com/covers/se/sewuC8.jpg" />
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"WebSite","name":"AVFan"}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"VideoObject","name":"SONE-535 一个容易被说服的求职应届生",
 "description":"就活生はその後も先輩社員の性処理おもちゃとしての業務を日々過ごしていく。",
 "thumbnailUrl":"https://c1.avfan.com/covers/se/sewuC8.jpg",
 "contentUrl":"https://cc3001.dmm.co.jp/litevideo/freepv/s/son/sone00535/sone00535mmb.mp4",
 "uploadDate":"2025-01-14T01:01:41+08:00","duration":"PT120M",
 "aggregateRating":{"@type":"AggregateRating","ratingValue":3.9,"bestRating":5}}
</script>
</head><body>
<h1 class="text-lg" data-movie-target="title">
  一个容易被说服的求职应届生
  <a href="javascript:;" data-origin-title="押しに弱い空気読み就活生">[原标题]</a>
</h1>
<span class="text-sm"> 3.92分, 由383人评分, 1215人想看 </span>
<dl class="movie-info grid">
  <dt>番号</dt>
  <dd><span class="movie-number font-semibold"><a href="/zh-CN/number_letters/SONE">SONE</a>-535</span></dd>
  <dt>发行日期</dt>
  <dd>2025-01-14</dd>
  <dt>片长</dt>
  <dd>120 分钟</dd>
  <dt>制作商</dt>
  <dd><a href="/zh-CN/makers/VuD9Pm1D">エスワン ナンバーワンスタイル</a></dd>
  <dt>发行商</dt>
  <dd><a href="/zh-CN/publishers/RzwYgG9N">S1 NO.1 STYLE</a></dd>
  <dt>导演</dt>
  <dd><a href="/zh-CN/directors/YTDaEoCt">麒麟</a></dd>
  <dt>系列</dt>
  <dd>测试系列</dd>
  <dt>演员</dt>
  <dd><a class="female" href="/zh-CN/casts/5RWR4MPf">佐藤愛瑠</a>,&nbsp;
      <a class="male" href="/zh-CN/casts/S8ZcRQVO">武田大樹</a></dd>
  <dt>标签</dt>
  <dd><a class="tag-chip" href="/zh-CN/tags?t=censored&amp;ts=33">绝顶高潮</a>
      <a class="tag-chip" href="/zh-CN/tags?t=censored&amp;ts=27">玩具</a>
      <a class="tag-chip" href="/zh-CN/tags?t=censored&amp;ts=33">绝顶高潮</a></dd>
</dl>
<div data-controller="expandable">
  <a href="/zh-CN/sign_in" class="relative" data-fancybox="" data-caption="预告片">预告片</a>
  <a href="https://c1.avfan.com/covers/se/sewuC8.jpg" data-fancybox="gallery" data-caption="封面">封面</a>
  <a href="https://c1.avfan.com/samples/se/sewuC8/l_1.jpg" data-fancybox="gallery" data-caption="1/2">剧照1</a>
  <a href="https://c1.avfan.com/samples/se/sewuC8/l_2.jpg" data-fancybox="gallery" data-caption="2/2">剧照2</a>
  <a href="https://c1.avfan.com/samples/se/sewuC8/l_1.jpg" data-fancybox="gallery" data-caption="重复">重复剧照</a>
</div>
</body></html>
"""

LOGIN_HTML = """
<html><head><title>登录 | AVFan</title></head><body>
<form action="/zh-CN/sessions" method="post">
  <input type="text" name="email" />
  <input type="password" name="password" />
</form>
</body></html>
"""


class FakeAvfanClient:
    """按 URL 返回预置页面, 并记录请求顺序."""

    def __init__(self, search_html: str | None = SEARCH_HTML, detail_html: str = DETAIL_HTML):
        self.search_html = search_html
        self.detail_html = detail_html
        self.requests: list[str] = []

    async def get_text(self, url: str, **kwargs):
        self.requests.append(url)
        if "/search?" in url:
            if self.search_html is None:
                return None, "HTTP 500"
            return self.search_html, ""
        if "/movies/" in url:
            return self.detail_html, ""
        return None, "HTTP 404"


def make_input(number: str = "SONE-535", appoint_url: str = "") -> CrawlerInput:
    input_data = CrawlerInput.empty()
    input_data.number = number
    input_data.short_number = number
    input_data.appoint_url = appoint_url
    return input_data


def test_parse_json_ld_returns_video_object_only():
    html = Selector(text=DETAIL_HTML)

    data = parse_json_ld(html)

    assert data["@type"] == "VideoObject"
    assert data["contentUrl"].endswith("sone00535mmb.mp4")


def test_parse_json_ld_accepts_type_list_and_skips_broken_script():
    html = Selector(
        text="""
        <html><body>
        <script type="application/ld+json">{broken json</script>
        <script type="application/ld+json">{"@type":["VideoObject"],"name":"ok"}</script>
        </body></html>
        """
    )

    assert parse_json_ld(html)["name"] == "ok"


def test_parse_json_ld_returns_empty_when_missing():
    assert parse_json_ld(Selector(text="<html></html>")) == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("120 分钟", "120"),
        ("2 小时 3 分钟", "123"),
        ("90", "90"),
        ("", ""),
        ("未知", ""),
        ("0 分钟", ""),
    ],
)
def test_parse_runtime(raw, expected):
    assert parse_runtime(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("PT120M", "120"), ("PT2H3M12S", "123"), ("PT1H", "60"), ("PT0S", ""), ("", ""), ("bad", "")],
)
def test_parse_iso_duration(raw, expected):
    assert parse_iso_duration(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-01-14", "2025-01-14"),
        ("2025/01/14", "2025-01-14"),
        ("2025-01-14T01:01:41+08:00", "2025-01-14"),
        ("", ""),
        ("2025-13-14", ""),
    ],
)
def test_parse_release(raw, expected):
    assert parse_release(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(" 3.92分, 由383人评分, 1215人想看 ", "3.92"), ("3.9", "3.9"), ("5.1", ""), ("0", ""), ("", "")],
)
def test_parse_score(raw, expected):
    assert parse_score(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(" 3.92分, 由383人评分, 1215人想看 ", "1215"), ("1,024人想看", "1024"), ("", "")],
)
def test_parse_wanted(raw, expected):
    assert parse_wanted(raw) == expected


def test_parse_mosaic():
    assert parse_mosaic(Selector(text='<a class="tag-chip" href="/zh-CN/tags?t=censored&amp;ts=1">标签</a>')) == "有码"
    assert parse_mosaic(Selector(text='<a class="tag-chip" href="/zh-CN/tags?t=uncensored">标签</a>')) == "无码"
    assert parse_mosaic(Selector(text='<a class="tag-chip" href="/zh-CN/tags?t=western">标签</a>')) == "欧美"
    assert parse_mosaic(Selector(text="<html></html>")) == ""


def test_parse_gallery_ignores_trailer_and_dedupes():
    cover, images = parse_gallery(Selector(text=DETAIL_HTML))

    assert cover == "https://c1.avfan.com/covers/se/sewuC8.jpg"
    assert images == [
        "https://c1.avfan.com/samples/se/sewuC8/l_1.jpg",
        "https://c1.avfan.com/samples/se/sewuC8/l_2.jpg",
    ]


def test_normalize_number():
    assert normalize_number("sone-535") == normalize_number("SONE_535") == "SONE535"
    assert normalize_number("SONE-535") != normalize_number("SONE-5350")
    assert normalize_number("") == ""


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{BASE_URL}{DETAIL_PATH}", f"{BASE_URL}{DETAIL_PATH}"),
        (f"{BASE_URL}/ja/movies/lxACycyA", f"{BASE_URL}{DETAIL_PATH}"),
        (f"{BASE_URL}/zh-TW/movies/lxACycyA?from=list", f"{BASE_URL}{DETAIL_PATH}"),
        (f"{BASE_URL}/movies/lxACycyA#top", f"{BASE_URL}{DETAIL_PATH}"),
        ("HTTPS://AVFAN.COM/zh-CN/movies/lxACycyA", f"{BASE_URL}{DETAIL_PATH}"),
        (f"{BASE_URL}/zh-CN/search?q=SONE-535", ""),
        ("", ""),
    ],
)
def test_movie_url(url, expected):
    assert movie_url(url) == expected


def test_card_number_falls_back_to_cover_alt():
    card = Selector(
        text="""
        <a href="/zh-CN/movies/abc">
          <img alt="SSIS-001 交わる体液" />
        </a>
        """
    ).xpath("//a")

    assert card_number(card) == "SSIS-001"


@pytest.mark.asyncio
async def test_parser_falls_back_to_json_ld_when_info_rows_missing():
    detail_html = DETAIL_HTML.replace("<dt>片长</dt>", "<dt>时长</dt>").replace("<dt>发行日期</dt>", "<dt>配信日</dt>")
    html = Selector(text=detail_html)
    ctx = Context(input=CrawlerInput.empty())

    data = await AvfanParser().parse(ctx, html)

    # dl.movie-info 取不到时回退结构化数据的 duration 与 uploadDate
    assert data.runtime == "120"
    assert data.release == "2025-01-14"


@pytest.mark.asyncio
async def test_parser_falls_back_to_og_title_and_strips_number():
    detail_html = re.sub(r"<h1.*?</h1>", "", DETAIL_HTML, flags=re.S)
    html = Selector(text=detail_html)
    ctx = Context(input=CrawlerInput.empty())

    data = await AvfanParser().parse(ctx, html)

    assert data.title == "一个容易被说服的求职应届生"


@pytest.mark.asyncio
async def test_run_searches_and_parses_detail_page():
    client = FakeAvfanClient()
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.debug_info.error is None
    data = response.data
    assert data is not None
    assert data.source == Website.AVFAN.value
    assert data.number == "SONE-535"
    assert data.title == "一个容易被说服的求职应届生"
    assert data.originaltitle == "押しに弱い空気読み就活生"
    assert data.outline.startswith("就活生はその後も")
    assert data.originalplot == data.outline
    assert data.actors == ["佐藤愛瑠"]
    assert data.all_actors == ["佐藤愛瑠", "武田大樹"]
    assert data.directors == ["麒麟"]
    assert data.tags == ["绝顶高潮", "玩具"]
    assert data.release == "2025-01-14"
    assert data.year == "2025"
    assert data.runtime == "120"
    assert data.score == "3.92"
    assert data.wanted == "1215"
    assert data.series == "测试系列"
    assert data.studio == "エスワン ナンバーワンスタイル"
    assert data.publisher == "S1 NO.1 STYLE"
    assert data.thumb == "https://c1.avfan.com/covers/se/sewuC8.jpg"
    assert data.poster == ""
    assert data.image_download is False
    assert data.extrafanart == [
        "https://c1.avfan.com/samples/se/sewuC8/l_1.jpg",
        "https://c1.avfan.com/samples/se/sewuC8/l_2.jpg",
    ]
    assert data.trailer.endswith("sone00535mmb.mp4")
    assert data.mosaic == "有码"
    assert data.external_id == DETAIL_URL
    assert response.debug_info.detail_urls == [DETAIL_URL]


@pytest.mark.asyncio
async def test_run_rejects_fuzzy_search_result():
    fuzzy_html = '<html><body><a href="/zh-CN/movies/other"><img alt="SONE-5350 近似" /></a></body></html>'
    client = FakeAvfanClient(search_html=fuzzy_html)
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is None
    assert "未匹配到番号" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_matches_number_ignoring_separator_case():
    search_html = SEARCH_HTML.replace("SONE-535", "sone_535")
    client = FakeAvfanClient(search_html=search_html)
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.debug_info.error is None
    assert response.data is not None
    assert response.debug_info.detail_urls == [DETAIL_URL]


@pytest.mark.asyncio
async def test_run_uses_appoint_url_and_normalizes_locale():
    client = FakeAvfanClient()
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("SONE-535", appoint_url="https://avfan.com/ja/movies/lxACycyA?from=list"))

    assert response.debug_info.error is None
    assert response.data is not None
    # 指定 URL 时跳过搜索, 首个请求即为简体中文详情页
    assert client.requests == [DETAIL_URL]
    assert response.data.external_id == DETAIL_URL


@pytest.mark.asyncio
async def test_run_reports_login_required_page():
    client = FakeAvfanClient(search_html=SEARCH_HTML.replace("SONE-535", "FC2-1234565"), detail_html=LOGIN_HTML)
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("FC2-1234565"))

    assert response.data is None
    assert "登录" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_reports_network_error_when_search_fails():
    client = FakeAvfanClient(search_html=None)
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is None
    assert "搜索页请求失败" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_raises_when_detail_page_has_no_title():
    client = FakeAvfanClient(detail_html='<html><body><dl class="movie-info"></dl></body></html>')
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is None
    assert "未获取到标题" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_falls_back_to_input_number_when_site_number_missing():
    detail_html = DETAIL_HTML.replace('<span class="movie-number font-semibold">', '<span class="other">')
    client = FakeAvfanClient(detail_html=detail_html)
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is not None
    assert response.data.number == "SONE-535"


@pytest.mark.asyncio
async def test_run_parses_page_with_login_modal():
    # 正常详情页可能带登录弹窗, 不能因为有密码框就判定为登录拦截
    detail_html = DETAIL_HTML.replace("<body>", '<body><div class="modal"><input type="password" /></div>')
    client = FakeAvfanClient(detail_html=detail_html)
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.debug_info.error is None
    assert response.data is not None
    assert response.data.number == "SONE-535"


@pytest.mark.asyncio
async def test_run_reports_broken_page_without_login_markers():
    client = FakeAvfanClient(detail_html="<html><head><title>AVFan</title></head><body>维护中</body></html>")
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.data is None
    assert "未找到影片信息区块" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_skips_external_card_links():
    search_html = SEARCH_HTML.replace(
        "</body>",
        '<a href="https://evil.example/movies/fake"><img alt="SONE-535" /></a></body>',
    )
    client = FakeAvfanClient(search_html=search_html)
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("SONE-535"))

    assert response.debug_info.error is None
    # 站外同名卡片不能覆盖真实详情页地址
    assert response.debug_info.detail_urls == [DETAIL_URL]


MINIMAL_HTML = """
<html><body>
<h1>只有标题和番号的页面</h1>
<dl class="movie-info">
  <dt>番号</dt><dd><span class="movie-number">ABC-123</span></dd>
  <dt>发行日期</dt><dd></dd>
</dl>
</body></html>
"""


@pytest.mark.asyncio
async def test_run_tolerates_missing_fields():
    # 站点缺字段(无评分/想看/标签/演员/图集/结构化数据)时应返回空值而不是报错
    client = FakeAvfanClient(search_html=SEARCH_HTML.replace("SONE-535", "ABC-123"), detail_html=MINIMAL_HTML)
    crawler = AvfanCrawler(client=client)

    response = await crawler.run(make_input("ABC-123"))

    assert response.debug_info.error is None
    data = response.data
    assert data is not None
    assert data.number == "ABC-123"
    assert data.title == "只有标题和番号的页面"
    assert data.originaltitle == data.title
    for field in (
        "outline",
        "originalplot",
        "score",
        "wanted",
        "release",
        "year",
        "runtime",
        "series",
        "studio",
        "poster",
        "thumb",
        "trailer",
        "mosaic",
    ):
        assert getattr(data, field) == "", field
    for field in ("actors", "all_actors", "directors", "tags", "extrafanart"):
        assert getattr(data, field) == [], field
    assert data.publisher == ""
    assert data.image_download is False
