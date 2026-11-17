import pytest
from parsel import Selector

from mdcx.config.models import Website
from mdcx.crawlers.base import Context
from mdcx.crawlers.javarchive import (
    BASE_URL,
    JavarchiveCrawler,
    JavarchiveParser,
    clean_title,
    exact_number_match,
    field_value,
    match_number,
    parse_date,
    parse_gallery,
    parse_info_map,
    parse_poster,
    parse_runtime,
    parse_tags,
    parse_thumb,
    split_info_line,
    version_rank,
)
from mdcx.models.types import CrawlerInput

DETAIL_PATH = (
    "/1172611-%5BFHD%2FSD%5D-SNOS-416-"
    "%E5%A4%A7%E4%BA%BA%E3%81%A3%E3%81%BD%E3%81%8F%E3%81%A6%E5%8F%AF%E6%84%9B%E3%81%843%E3%81%A4%E4%B8%8A%E3%81%AE"
    "%E5%AE%B6%E5%BA%AD%E6%95%99%E5%B8%AB%E3%81%8A%E5%A7%89%E3%81%95%E3%82%93-%E6%B8%9A%E3%81%82%E3%81%84%E3%82%8A-pn.html"
)

SEARCH_HTML = """
<html><body>
  <div class="news_1n">
    <h2><a href="#">Search</a></h2>
    <ul>
      <li><a href="/1170000-nav-pn.html" title="导航里也有一个假标题">菜单</a></li>
    </ul>
  </div>
  <div class="news_1n">
    <h2><a href="#">Search Results</a></h2>
    <ul>
      <li>
        <a href="/1176843-[ENGSUB]SNOS-416-english-title-pn.html" title="[ENGSUB]SNOS-416 I kept fucking like crazy">
          <img src="https://pics.dmm.co.jp/mono/movie/adult/snos416/snos416ps.jpg" alt="[ENGSUB]SNOS-416" />
        </a>
        <h3><span><a href="/1176843-[ENGSUB]SNOS-416-english-title-pn.html">[ENGSUB]SNOS-416 I kept</a></span></h3>
      </li>
      <li>
        <a href="/1172611-[FHD/SD]-SNOS-416-title-pn.html" title="[FHD/SD] SNOS-416 大人っぽくて可愛い家庭教師 渚あいり">
          <img src="https://pics.dmm.co.jp/mono/movie/adult/snos416/snos416ps.jpg" alt="[FHD/SD] SNOS-416" />
        </a>
      </li>
      <li>
        <a href="/1174076-[4K]-SNOS-416-title-pn.html" title="[4K] SNOS-416 大人っぽくて可愛い家庭教師 渚あいり">
          <img src="https://pics.dmm.co.jp/mono/movie/adult/snos416/snos416ps.jpg" alt="[4K] SNOS-416" />
        </a>
      </li>
      <li>
        <a href="/1176830-Reducing-Mosaic-SNOS-416-title-pn.html" title="Reducing Mosaic SNOS-416 大人っぽくて可愛い家庭教師">
          <img src="https://pics.dmm.co.jp/mono/movie/adult/snos416/snos416ps.jpg" alt="SNOS-416" />
        </a>
      </li>
      <li>
        <a href="/9999999-SNOS-4160-pn.html" title="SNOS-4160 近似番号, 不能命中">
          <img src="https://pics.dmm.co.jp/mono/movie/adult/snos4160/snos4160ps.jpg" alt="SNOS-4160" />
        </a>
      </li>
      <li>
        <a href="https://evil.example/1-SNOS-416-pn.html" title="SNOS-416 站外链接">
          <img src="https://evil.example/a.jpg" alt="SNOS-416" />
        </a>
      </li>
    </ul>
  </div>
</body></html>
"""

DETAIL_HTML = """
<html><head><title>[FHD/SD] SNOS-416 大人っぽくて可愛い家庭教師 渚あいり - JavArchive</title></head><body>
<div class="news">
  <div class="first_des">[FHD/SD] SNOS-416 大人っぽくて可愛い家庭教師 渚あいり <br class="a5555" /></div>
  <div class="fisrst_sc">
    <img src="https://pics.dmm.co.jp/mono/movie/adult/snos416/snos416pl.jpg" alt="标题" />
  </div>
  <div class="Recipepod" itemscope itemtype="http://schema.org/Recipe">
    <span itemprop="name" class="name">[FHD/SD] SNOS-416 大人っぽくて可愛い家庭教師 渚あいり</span>
    <img itemprop="image" src="https://pics.dmm.co.jp/mono/movie/adult/snos416/snos416ps.jpg" alt="标题" />
    <div class="aggregateRating" itemprop="aggregateRating">
      <span itemprop="ratingValue"><span class="vote-count-likes">7</span></span>
      <span class="bestRating" itemprop="bestRating"><span class="vote-count-likes">7</span></span>
    </div>
  </div>
  <ul class="highslide-gallery" id="lightgallery">
    <li data-src="https://pics.dmm.co.jp/digital/video/snos00416/snos00416jp-1.jpg"><a href="javascript:;"><img src="x" /></a></li>
    <li data-src="https://pics.dmm.co.jp/digital/video/snos00416/snos00416jp-2.jpg"><a href="javascript:;"><img src="x" /></a></li>
    <li data-src="https://pics.dmm.co.jp/digital/video/snos00416/snos00416jp-1.jpg"><a href="javascript:;"><img src="x" /></a></li>
  </ul>
  発売日	2025-01-14 <br class='a5555' />収録時間	110 分 <br class='a5555' />監督	ZAMPA <br class='a5555' />メーカー	エスワン ナンバーワンスタイル <br class='a5555' />レーベル	S1 NO.1 STYLE <br class='a5555' />シリーズ	テストシリーズ <br class='a5555' />
</div>
</body></html>
"""

# 同一番号的另一个版本: 缺发行日与导演, 用于验证"只补空字段"
DETAIL_HTML_PARTIAL = DETAIL_HTML.replace("発売日	2025-01-14 <br class='a5555' />", "").replace(
    "監督	ZAMPA <br class='a5555' />", ""
)

# 中文冒号模板: 制作/发行商/类型/出演者
DETAIL_HTML_CHINESE = """
<html><body>
<div class="news">
  <div class="first_des">[FHD]START-669 箱根温泉を訪れた新川空ちゃん <br class="a5555" /></div>
  <div class="fisrst_sc">
    <img src="https://pics.dmm.co.jp/digital/video/1start00669/1start00669jp-8.jpg" alt="剧照" />
  </div>
  <div class="Recipepod"><span itemprop="name" class="name">[FHD]START-669 箱根温泉を訪れた新川空ちゃん</span>
    <img itemprop="image" src="https://pics.dmm.co.jp/mono/movie/adult/1start00669/1start00669ps.jpg" />
  </div>
  <ul id="lightgallery"><li data-src="https://pics.dmm.co.jp/digital/video/1start00669/1start00669jp-1.jpg"></li></ul>
  出演者：新川空 <br class='a5555' />監督：CHAIN宗 <br class='a5555' />制作：SODクリエイト <br class='a5555' />发行商：SODSTAR <br class='a5555' />类型：単体作品｜温泉｜4K｜ハイビジョン <br class='a5555' />品番：1start00669 <br class='a5555' />商品発売日：2026/11/17 <br class='a5555' />配信開始日：2026/11/10 <br class='a5555' />
</div>
</body></html>
"""

# FC2 模板: 标签/卖家/日期/时长, fisrst_sc 里放的是随机剧照而不是竖版海报
DETAIL_HTML_FC2 = """
<html><body>
<div class="news">
  <div class="first_des">FC2PPV 5006586 【12/1迄1290pt】【初撮】19歳看護師志望ムスメ <br class="a5555" /></div>
  <div class="fisrst_sc">
    <img src="https://contents-thumbnail2.fc2.com/w1280/storage/file/1794292450.03.png" alt="剧照" />
  </div>
  <div class="Recipepod"><span itemprop="name" class="name">FC2PPV 5006586 【12/1迄1290pt】</span>
    <img itemprop="image" src="http://img2.javstore.net/images/2026/11/11/5006586ps.png" />
  </div>
  <ul id="lightgallery"></ul>
  标签：1500pt｜素人｜美乳｜中出し｜無修正｜19歳 <br class='a5555' />卖家：素人Rendezvous <br class='a5555' />日期：2026/11/10 <br class='a5555' />时长：01:09:38 <br class='a5555' />
</div>
</body></html>
"""

# 老帖模板: 字段名与值用空格分隔, シリーズ 是破折号占位符, 封面地址还带空格
DETAIL_HTML_LEGACY = """
<html><body>
<div class="news">
  <div class="first_des">HEYZO 1234 都盛星空の足コキでイケ！ – 都盛星空 <br class="a5555" /></div>
  <div class="fisrst_sc">
    <img src="http://img.javarchive.com/HEYZO 1234.jpg-1474431319871-.jpg" alt="封面" />
  </div>
  <div class="Recipepod"><span itemprop="name" class="name">HEYZO 1234 都盛星空の足コキでイケ！</span>
    <img itemprop="image" src="http://img.javarchive.com/HEYZO 1234.jpg-1474431319871-.jpg" />
  </div>
  公開日 2016-08-16 <br class='a5555' />出演 都盛星空 <br class='a5555' />シリーズ —– <br class='a5555' />タグキーワード 手コキ 足コキ ハゲ親父 <br class='a5555' />
</div>
</body></html>
"""

# 只有 配信開始日, 没有 発売日: 不能拿配信日冒充发行日
DETAIL_HTML_NO_RELEASE = DETAIL_HTML.replace(
    "発売日	2025-01-14 <br class='a5555' />", "配信開始日	2025-01-05 <br class='a5555' />"
).replace("レーベル	S1 NO.1 STYLE <br class='a5555' />", "レーベル	---- <br class='a5555' />")


class FakeJavarchiveClient:
    """按 URL 返回预置页面, 并记录请求顺序."""

    def __init__(
        self,
        search_html: str | None = SEARCH_HTML,
        detail_html: str = DETAIL_HTML,
        detail_pages: dict[str, str] | None = None,
    ):
        self.search_html = search_html
        self.detail_html = detail_html
        self.detail_pages = detail_pages or {}
        self.requests: list[str] = []

    async def get_text(self, url: str, **kwargs):
        self.requests.append(url)
        if "/search?" in url:
            if self.search_html is None:
                return None, "HTTP 500"
            return self.search_html, ""
        for post_id, page in self.detail_pages.items():
            if f"/{post_id}-" in url:
                return page, ""
        if "-pn.html" in url:
            return self.detail_html, ""
        return None, "HTTP 404"


def make_input(number: str = "SNOS-416", appoint_url: str = "") -> CrawlerInput:
    input_data = CrawlerInput.empty()
    input_data.number = number
    input_data.short_number = number
    input_data.appoint_url = appoint_url
    return input_data


def make_context(number: str = "SNOS-416") -> Context:
    return Context(input=make_input(number))


def test_parse_info_map_reads_japanese_template():
    info = parse_info_map(Selector(text=DETAIL_HTML))

    assert info["発売日"] == "2025-01-14"
    assert info["収録時間"] == "110 分"
    assert info["監督"] == "ZAMPA"
    assert info["メーカー"] == "エスワン ナンバーワンスタイル"
    assert info["レーベル"] == "S1 NO.1 STYLE"
    assert info["シリーズ"] == "テストシリーズ"


def test_parse_info_map_reads_chinese_colon_template():
    info = parse_info_map(Selector(text=DETAIL_HTML_CHINESE))

    assert info["出演者"] == "新川空"
    assert info["制作"] == "SODクリエイト"
    assert info["发行商"] == "SODSTAR"
    assert info["品番"] == "1start00669"
    assert info["商品発売日"] == "2026/11/17"


def test_parse_info_map_reads_fc2_template():
    info = parse_info_map(Selector(text=DETAIL_HTML_FC2))

    assert info["卖家"] == "素人Rendezvous"
    assert info["日期"] == "2026/11/10"
    assert info["时长"] == "01:09:38"
    assert info["标签"].startswith("1500pt｜素人")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("監督\tZAMPA", ("監督", "ZAMPA")),
        ("出演者：新川空", ("出演者", "新川空")),
        (
            "【影片名称】【逮〇覚悟4発射】50万貸して飛んだS級19歳",
            ("【影片名称】", "【逮〇覚悟4発射】50万貸して飛んだS級19歳"),
        ),
        # 老帖是空格分隔, 甚至字段名和值直接黏在一起
        ("公開日 2016-08-16", ("公開日", "2016-08-16")),
        ("女優タイプ熟女 美脚", ("女優タイプ", "熟女 美脚")),
        ("普通的说明文字", ("", "")),
    ],
)
def test_split_info_line(line, expected):
    assert split_info_line(line) == expected


@pytest.mark.parametrize("placeholder", ["----", "---", "TODO", "N/A", "—–", ""])
def test_field_value_skips_placeholder(placeholder):
    info = {"レーベル": placeholder, "发行商": "SODSTAR"}

    assert field_value(info, "レーベル", "发行商") == "SODSTAR"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-01-14", "2025-01-14"),
        ("2026/11/10", "2026-11-10"),
        ("2026年11月10日", "2026-11-10"),
        ("0000-00-00", ""),
        ("2025-13-14", ""),
        ("", ""),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("110 分", "110"),
        ("2時間3分", "123"),
        ("01:09:38", "70"),
        ("57:01", "57"),
        ("", ""),
        ("未知", ""),
    ],
)
def test_parse_runtime(raw, expected):
    assert parse_runtime(raw) == expected


@pytest.mark.parametrize(
    ("title", "number", "matched"),
    [
        ("[FHD/SD] SNOS-416 标题", "SNOS-416", True),
        ("FC2PPV 5006586 【初撮】", "FC2-PPV-5006586", True),
        ("SNOS-4160 近似番号", "SNOS-416", False),
        ("SNIS-416 别的番号", "SNOS-416", False),
        ("", "SNOS-416", False),
    ],
)
def test_match_number(title, number, matched):
    assert bool(match_number(title, number)) is matched


def test_exact_number_match_requires_same_separator():
    assert exact_number_match("[FHD/SD] SNOS-416 标题", "SNOS-416") is not None
    assert exact_number_match("FC2PPV 5006586 标题", "FC2-PPV-5006586") is None


@pytest.mark.parametrize(
    ("title", "number", "expected"),
    [
        ("[FHD/SD] SNOS-416 大人っぽくて可愛い家庭教師 渚あいり", "SNOS-416", "大人っぽくて可愛い家庭教師 渚あいり"),
        ("FC2PPV 5006586 【12/1迄1290pt】【初撮】19歳", "FC2-PPV-5006586", "【12/1迄1290pt】【初撮】19歳"),
        ("SNIS-416 Reducing Mosaic やたらと目の合う誘惑お姉さん", "SNIS-416", "やたらと目の合う誘惑お姉さん"),
        ("没有番号的标题", "SNOS-416", "没有番号的标题"),
    ],
)
def test_clean_title(title, number, expected):
    assert clean_title(title, number) == expected


def test_version_rank_prefers_plain_title():
    titles = [
        "SNOS-416 标题",
        "[FHD/SD] SNOS-416 标题",
        "Reducing Mosaic SNOS-416 标题",
        "[ENGSUB]SNOS-416 标题",
        "Uncensored Leaked SNOS-416 标题",
    ]
    ranks = [version_rank(title, match_number(title, "SNOS-416")) for title in titles]

    assert ranks == sorted(ranks)
    assert ranks[0] == 0


def test_parse_poster_ignores_sample_and_uses_pl():
    html = Selector(text=DETAIL_HTML_CHINESE)

    assert (
        parse_poster(html, parse_thumb(html)) == "https://pics.dmm.co.jp/mono/movie/adult/1start00669/1start00669pl.jpg"
    )


def test_parse_poster_derives_from_fc2_thumb_when_page_has_only_sample():
    html = Selector(text=DETAIL_HTML_FC2)

    # fisrst_sc 里是随机剧照, 只能由横版封面 ps.png 推导 pl.png
    assert parse_poster(html, parse_thumb(html)) == "http://img2.javstore.net/images/2026/11/11/5006586pl.png"


def test_parse_gallery_dedupes_and_keeps_order():
    assert parse_gallery(Selector(text=DETAIL_HTML)) == [
        "https://pics.dmm.co.jp/digital/video/snos00416/snos00416jp-1.jpg",
        "https://pics.dmm.co.jp/digital/video/snos00416/snos00416jp-2.jpg",
    ]


def test_parse_tags_filters_price_and_quality_markers():
    info = {"类型": "単体作品｜温泉｜4K｜ハイビジョン"}
    assert parse_tags(info) == ["単体作品", "温泉"]

    fc2_info = {"标签": "1500pt｜素人｜美乳"}
    assert parse_tags(fc2_info) == ["素人", "美乳"]


@pytest.mark.asyncio
async def test_parse_search_page_matches_exactly_and_orders_by_version():
    crawler = JavarchiveCrawler(client=FakeJavarchiveClient())

    urls = await crawler._parse_search_page(
        make_context("SNOS-416"), Selector(text=SEARCH_HTML), f"{BASE_URL}/search?q=SNOS-416"
    )

    # 裸标题优先, 其次 [FHD/SD]、[4K], 再降码与字幕; 近似番号与站外链接必须排除
    assert urls == [
        f"{BASE_URL}/1172611-[FHD/SD]-SNOS-416-title-pn.html",
        f"{BASE_URL}/1174076-[4K]-SNOS-416-title-pn.html",
        f"{BASE_URL}/1176830-Reducing-Mosaic-SNOS-416-title-pn.html",
        f"{BASE_URL}/1176843-[ENGSUB]SNOS-416-english-title-pn.html",
    ]


@pytest.mark.asyncio
async def test_parse_search_page_returns_empty_list_when_all_fuzzy():
    crawler = JavarchiveCrawler(client=FakeJavarchiveClient())
    fuzzy_html = SEARCH_HTML.replace("SNOS-416", "SNOS-426")

    urls = await crawler._parse_search_page(
        make_context("SNOS-416"), Selector(text=fuzzy_html), f"{BASE_URL}/search?q=SNOS-416"
    )

    assert urls == []


@pytest.mark.asyncio
async def test_parse_search_page_returns_none_when_no_results():
    crawler = JavarchiveCrawler(client=FakeJavarchiveClient())
    empty_html = '<html><body><div class="news_1n"><h2><a href="#">Search</a></h2></div></body></html>'

    urls = await crawler._parse_search_page(
        make_context("SNOS-416"), Selector(text=empty_html), f"{BASE_URL}/search?q=SNOS-416"
    )

    assert urls is None


@pytest.mark.asyncio
async def test_run_parses_detail_fields():
    client = FakeJavarchiveClient()
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("SNOS-416"))

    assert response.debug_info.error is None
    data = response.data
    assert data is not None
    assert data.source == Website.JAVARCHIVE.value
    assert data.number == "SNOS-416"
    assert data.title == "大人っぽくて可愛い家庭教師 渚あいり"
    assert data.originaltitle == data.title
    assert data.release == "2025-01-14"
    assert data.year == "2025"
    assert data.runtime == "110"
    assert data.directors == ["ZAMPA"]
    assert data.studio == "エスワン ナンバーワンスタイル"
    assert data.publisher == "S1 NO.1 STYLE"
    assert data.series == "テストシリーズ"
    assert data.thumb == "https://pics.dmm.co.jp/mono/movie/adult/snos416/snos416ps.jpg"
    assert data.poster == "https://pics.dmm.co.jp/mono/movie/adult/snos416/snos416pl.jpg"
    assert data.image_download is True
    assert data.extrafanart == [
        "https://pics.dmm.co.jp/digital/video/snos00416/snos00416jp-1.jpg",
        "https://pics.dmm.co.jp/digital/video/snos00416/snos00416jp-2.jpg",
    ]
    # 站点不提供这些字段, 且 ratingValue 是点赞数, 不能当评分
    for field in ("score", "wanted", "outline", "originalplot", "trailer", "mosaic", "actors"):
        value = getattr(data, field)
        assert value in ("", []), field
    assert response.debug_info.detail_urls[0].endswith("1172611-[FHD/SD]-SNOS-416-title-pn.html")
    # 关键字段齐全后不应再抓其它版本
    assert len([url for url in client.requests if "-pn.html" in url]) == 1


@pytest.mark.asyncio
async def test_run_merges_missing_fields_from_other_version():
    # 主版本缺发行日/导演, 第二个版本能补齐; 标题与封面不允许被覆盖
    client = FakeJavarchiveClient(
        detail_pages={"1172611": DETAIL_HTML_PARTIAL, "1174076": DETAIL_HTML},
        detail_html=DETAIL_HTML_PARTIAL,
    )
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("SNOS-416"))

    data = response.data
    assert data is not None
    assert data.release == "2025-01-14"
    assert data.directors == ["ZAMPA"]
    assert data.title == "大人っぽくて可愛い家庭教師 渚あいり"
    assert data.poster.endswith("snos416pl.jpg")


@pytest.mark.asyncio
async def test_run_keeps_publisher_empty_when_label_missing():
    client = FakeJavarchiveClient(detail_html=DETAIL_HTML_NO_RELEASE)
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("SNOS-416"))

    data = response.data
    assert data is not None
    # 只有 配信開始日 时不能冒充发行日
    assert data.release == ""
    assert data.year == ""
    # レーベル 是占位符时不能拿 メーカー 顶替
    assert data.studio == "エスワン ナンバーワンスタイル"
    assert data.publisher == ""


@pytest.mark.asyncio
async def test_run_parses_chinese_template_and_skips_dmm_content_id():
    search_html = SEARCH_HTML.replace("SNOS-416", "START-669")
    client = FakeJavarchiveClient(search_html=search_html, detail_html=DETAIL_HTML_CHINESE)
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("START-669"))

    data = response.data
    assert data is not None
    assert data.number == "START-669"
    assert data.actors == ["新川空"]
    assert data.all_actors == ["新川空"]
    assert data.directors == ["CHAIN宗"]
    assert data.studio == "SODクリエイト"
    assert data.publisher == "SODSTAR"
    assert data.tags == ["単体作品", "温泉"]
    # 商品発売日 优先于 配信開始日
    assert data.release == "2026-11-17"


@pytest.mark.asyncio
async def test_run_parses_fc2_template():
    search_html = SEARCH_HTML.replace("SNOS-416", "FC2PPV 5006586")
    client = FakeJavarchiveClient(search_html=search_html, detail_html=DETAIL_HTML_FC2)
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("FC2-PPV-5006586"))

    data = response.data
    assert data is not None
    assert data.number == "FC2-PPV-5006586"
    assert data.tags == ["素人", "美乳", "中出し", "無修正", "19歳"]
    assert data.studio == "素人Rendezvous"
    assert data.publisher == ""
    assert data.release == "2026-11-10"
    assert data.runtime == "70"
    assert data.image_download is True


@pytest.mark.asyncio
async def test_run_parses_legacy_space_separated_template():
    search_html = SEARCH_HTML.replace("SNOS-416", "HEYZO 1234")
    client = FakeJavarchiveClient(search_html=search_html, detail_html=DETAIL_HTML_LEGACY)
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("HEYZO-1234"))

    data = response.data
    assert data is not None
    assert data.number == "HEYZO-1234"
    assert data.release == "2016-08-16"
    assert data.actors == ["都盛星空"]
    # シリーズ 是破折号占位符, 不能写成系列名
    assert data.series == ""
    assert data.tags == ["手コキ", "足コキ", "ハゲ親父"]
    # 没有竖版海报时走裁剪
    assert data.poster == ""
    assert data.image_download is False
    # 带空格的封面地址要编码成合法 URL
    assert " " not in data.thumb
    assert data.thumb.endswith("1234.jpg-1474431319871-.jpg")


@pytest.mark.asyncio
async def test_run_rejects_fuzzy_search_result():
    client = FakeJavarchiveClient(search_html=SEARCH_HTML.replace("SNOS-416", "SNOS-426"))
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("SNOS-416"))

    assert response.data is None
    assert "未匹配到番号" in str(response.debug_info.error)
    # 模糊页面不应触发详情页请求
    assert all("/search?" in url for url in client.requests)


@pytest.mark.asyncio
async def test_run_scans_next_page_when_first_page_has_no_exact_match():
    first_page = SEARCH_HTML.replace("SNOS-416", "SNOS-426")
    client = FakeJavarchiveClient(search_html=first_page)

    # 第一页全是模糊结果, 第二页才出现精确命中
    original_get_text = client.get_text

    async def get_text(url: str, **kwargs):
        if "&page=2" in url:
            client.requests.append(url)
            return SEARCH_HTML, ""
        return await original_get_text(url, **kwargs)

    client.get_text = get_text  # type: ignore[method-assign]
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("SNOS-416"))

    assert response.data is not None
    assert any("&page=2" in url for url in client.requests)


@pytest.mark.asyncio
async def test_run_does_not_fetch_next_page_when_first_page_has_hit():
    client = FakeJavarchiveClient()
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("SNOS-416"))

    assert response.data is not None
    # 首页已命中时不应再翻页, 避免每个文件多打两次搜索请求
    assert not any("&page=" in url for url in client.requests)


@pytest.mark.asyncio
async def test_run_uses_appoint_url_and_encodes_path():
    client = FakeJavarchiveClient()
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("SNOS-416", appoint_url=f"{BASE_URL}{DETAIL_PATH}"))

    assert response.debug_info.error is None
    assert response.data is not None
    # 指定 URL 时跳过搜索, 且路径中的日文与方括号已编码
    assert len(client.requests) == 1
    assert client.requests[0].startswith(f"{BASE_URL}/1172611-")
    assert "%5B" in client.requests[0] or "%E5" in client.requests[0]
    assert response.data.external_id.startswith(f"{BASE_URL}/1172611-")


@pytest.mark.asyncio
async def test_run_reports_missing_info_block():
    client = FakeJavarchiveClient(detail_html="<html><head><title>Not Found</title></head><body>404</body></html>")
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("SNOS-416"))

    assert response.data is None
    assert "未找到影片信息区块" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_reports_network_error_when_search_fails():
    client = FakeJavarchiveClient(search_html=None)
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("SNOS-416"))

    assert response.data is None
    assert "搜索页请求失败" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_run_falls_back_to_input_number_when_title_has_no_number():
    detail_html = DETAIL_HTML.replace("SNOS-416", "标题里没有番号")
    client = FakeJavarchiveClient(detail_html=detail_html)
    crawler = JavarchiveCrawler(client=client)

    response = await crawler.run(make_input("SNOS-416", appoint_url=f"{BASE_URL}{DETAIL_PATH}"))

    assert response.data is not None
    assert response.data.number == "SNOS-416"


@pytest.mark.asyncio
async def test_parser_number_uses_product_code_when_title_lacks_number():
    parser = JavarchiveParser()
    html = Selector(
        text="""
        <html><body><div class="news">
          <div class="first_des">标题里没有番号</div>
          メーカー品番	MFCS-233 <br class='a5555' />品番	h_1472erofv00400 <br class='a5555' />
        </div></body></html>
        """
    )

    number = await parser.number(make_context(""), html)

    # メーカー品番 可用; DMM 内容 ID(h_xxx) 不能被当成番号
    assert number == "MFCS-233"
