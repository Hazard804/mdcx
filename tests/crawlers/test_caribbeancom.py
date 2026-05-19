import pytest

from mdcx.config.enums import Language, Website
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.caribbeancom import CaribbeancomCrawler, CaribbeancomprCrawler
from mdcx.models.types import CrawlerInput

DETAIL_HTML = """
<html>
  <head><meta http-equiv="Content-Type" content="text/html; charset=euc-jp"></head>
  <body>
    <script>
      var Movie = {
        "movie_id":"051726-001",
        "sample_flash_url":"https:\\/\\/smovie.caribbeancom.com\\/sample\\/movies\\/051726-001\\/480p.mp4",
        "sample_m_flash_url":"https:\\/\\/smovie.caribbeancom.com\\/sample\\/movies\\/051726-001\\/sample_m.mp4",
        "sample_aff_flash_url":"https:\\/\\/smovie.caribbeancom.com\\/sample\\/movies\\/051726-001\\/sample.mp4"
      };
      var emimg =  '/moviepages/051726-001/images/l_l.jpg';
    </script>
    <h1 itemprop="name">恍惚 ~エグい程のGカップ肉感美少女~</h1>
    <p itemprop="description">スポーツで鍛え上げられたサンプル紹介文。</p>
    <ul>
      <li class="movie-spec">
        <span class="spec-title">出演</span>
        <span class="spec-content"><a><span itemprop="name">白石真琴</span></a></span>
      </li>
      <li class="movie-spec">
        <span class="spec-title">配信日</span>
        <span class="spec-content">2026/05/17</span>
      </li>
      <li class="movie-spec">
        <span class="spec-title">再生時間</span>
        <span class="spec-content"><span itemprop="duration">01:04:05</span></span>
      </li>
      <li class="movie-spec">
        <span class="spec-title">シリーズ</span>
        <span class="spec-content"><a>恍惚</a></span>
      </li>
      <li class="movie-spec">
        <span class="spec-title">タグ</span>
        <span class="spec-content">
          <a>オリジナル動画</a><a>美乳</a><a>中出し</a>
        </span>
      </li>
      <li class="movie-spec">
        <span class="spec-title">ユーザー評価</span>
        <span class="spec-content rating meta-rating">★★★★★</span>
      </li>
    </ul>
    <a class="gallery-image-wrap fancy-gallery" href="/moviepages/051726-001/images/l/001.jpg"></a>
    <a class="gallery-image-wrap fancy-gallery" href="/moviepages/051726-001/images/l/002.jpg"></a>
    <a class="gallery-image-wrap fancy-gallery" href="/member/moviepages/051726-001/images/l/003.jpg"></a>
  </body>
</html>
"""


class FakeCaribbeancomClient:
    async def get_text(self, url, **kwargs):
        assert kwargs.get("encoding") == "euc-jp"
        if url == "https://www.caribbeancom.com/moviepages/051726-001/index.html":
            return DETAIL_HTML, ""
        return None, f"unexpected url: {url}"


CARIBBEANCOMPR_HTML = """
<html>
  <body>
    <script>
      var Movie = {
        "movie_id":"122321_913",
        "sample_flash_url":"https:\\/\\/smovie.caribbeancompr.com\\/sample\\/movies\\/122321_913\\/480p.mp4"
      };
    </script>
    <div class="movie-info">
      <div class="heading"><h1>人妻マンコ図鑑 47</h1></div>
      <p>感度抜群、欲しがりエロエロ美熟女、杉浦れいらのオマンコを徹底観察！</p>
      <ul>
        <li class="movie-spec">
          <span class="spec-title">出演</span>
          <span class="spec-content"><a>杉浦れいら</a></span>
        </li>
        <li class="movie-spec">
          <span class="spec-title">再生時間</span>
          <span class="spec-content">00:16:12</span>
        </li>
        <li class="movie-spec">
          <span class="spec-title">スタジオ</span>
          <span class="spec-content"><a>パコパコママ</a></span>
        </li>
        <li class="movie-spec">
          <span class="spec-title">タグ</span>
          <span class="spec-content"><a>素人</a><a>美乳</a><a>オナニー</a><a>熟女/人妻</a></span>
        </li>
      </ul>
    </div>
  </body>
</html>
"""


class FakeCaribbeancomprClient:
    async def get_text(self, url, **kwargs):
        assert kwargs.get("encoding") == "euc-jp"
        if url == "https://www.caribbeancompr.com/moviepages/122321_913/index.html":
            return CARIBBEANCOMPR_HTML, ""
        return None, f"unexpected url: {url}"


@pytest.mark.asyncio
async def test_caribbeancom_crawler_parses_direct_detail_page():
    crawler = CaribbeancomCrawler(client=FakeCaribbeancomClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="caribbeancom-051726-001",
            short_number="051726-001",
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "caribbeancom"
    assert res.data.external_id == "https://www.caribbeancom.com/moviepages/051726-001/index.html"
    assert res.data.number == "051726-001"
    assert res.data.title == "恍惚 ~エグい程のGカップ肉感美少女~"
    assert res.data.originaltitle == res.data.title
    assert res.data.actors == ["白石真琴"]
    assert res.data.all_actors == ["白石真琴"]
    assert res.data.outline == "スポーツで鍛え上げられたサンプル紹介文。"
    assert res.data.originalplot == res.data.outline
    assert res.data.release == "2026-05-17"
    assert res.data.year == "2026"
    assert res.data.runtime == "64"
    assert res.data.series == "恍惚"
    assert res.data.tags == ["オリジナル動画", "美乳", "中出し"]
    assert res.data.score == "5.0"
    assert res.data.thumb == "https://www.caribbeancom.com/moviepages/051726-001/images/l_l.jpg"
    assert res.data.poster == ""
    assert res.data.extrafanart == [
        "https://www.caribbeancom.com/moviepages/051726-001/images/l/001.jpg",
        "https://www.caribbeancom.com/moviepages/051726-001/images/l/002.jpg",
    ]
    assert res.data.trailer == "https://smovie.caribbeancom.com/sample/movies/051726-001/sample_m.mp4"
    assert res.data.studio == "Caribbeancom"
    assert res.data.publisher == "Caribbeancom"
    assert res.data.mosaic == "无码"


def test_caribbeancom_crawler_is_registered():
    assert get_crawler(Website.CARIBBEANCOM) is CaribbeancomCrawler


def test_caribbean_crawlers_do_not_rewrite_number_separator():
    assert CaribbeancomCrawler(client=FakeCaribbeancomClient())._build_detail_url("051726_001") == (
        "https://www.caribbeancom.com/moviepages/051726_001/index.html"
    )
    assert CaribbeancomprCrawler(client=FakeCaribbeancomprClient())._build_detail_url("051726-001") == (
        "https://www.caribbeancompr.com/moviepages/051726-001/index.html"
    )


@pytest.mark.asyncio
async def test_caribbeancom_rejects_detail_page_with_mismatched_movie_id():
    class FakeMismatchClient:
        async def get_text(self, url, **kwargs):
            _ = url, kwargs
            return DETAIL_HTML.replace('"movie_id":"051726-001"', '"movie_id":"051726_001"'), ""

    crawler = CaribbeancomCrawler(client=FakeMismatchClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="051726-001",
            short_number="051726-001",
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.data is None
    assert res.debug_info.error is not None
    assert "影片标识不一致" in str(res.debug_info.error)


@pytest.mark.asyncio
async def test_caribbeancompr_crawler_parses_direct_detail_page():
    crawler = CaribbeancomprCrawler(client=FakeCaribbeancomprClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="caribbeancompr-122321_913",
            short_number="122321_913",
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "caribbeancompr"
    assert res.data.external_id == "https://www.caribbeancompr.com/moviepages/122321_913/index.html"
    assert res.data.number == "122321_913"
    assert res.data.title == "人妻マンコ図鑑 47"
    assert res.data.actors == ["杉浦れいら"]
    assert res.data.outline == "感度抜群、欲しがりエロエロ美熟女、杉浦れいらのオマンコを徹底観察！"
    assert res.data.release == ""
    assert res.data.year == ""
    assert res.data.runtime == "16"
    assert res.data.tags == ["素人", "美乳", "オナニー", "熟女/人妻"]
    assert res.data.score == "0.0"
    assert res.data.thumb == "https://www.caribbeancompr.com/moviepages/122321_913/images/l_l.jpg"
    assert res.data.extrafanart == []
    assert res.data.trailer == "https://smovie.caribbeancompr.com/sample/movies/122321_913/480p.mp4"
    assert res.data.studio == "パコパコママ"
    assert res.data.publisher == "パコパコママ"
    assert res.data.mosaic == "无码"


def test_caribbeancompr_crawler_is_registered():
    assert get_crawler(Website.CARIBBEANCOMPR) is CaribbeancomprCrawler


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("crawler_cls", "base_url", "movie_id", "site_name", "title", "sample_host"),
    [
        (
            CaribbeancomCrawler,
            "https://www.caribbeancom.com",
            "051926_100",
            "pacopacomama.com",
            "巨乳上司の誘惑",
            "smovie.pacopacomama.com",
        ),
        (
            CaribbeancomprCrawler,
            "https://www.caribbeancompr.com",
            "122321_913",
            "caribbeancompr.com",
            "人妻マンコ図鑑 47",
            "smovie.caribbeancompr.com",
        ),
    ],
)
async def test_caribbean_crawler_uses_movie_image_data_before_emimg_fragment(
    crawler_cls, base_url, movie_id, site_name, title, sample_host
):
    html = f"""
    <html>
      <body>
        <script>
          var Movie = {{
            "movie_id":"{movie_id}",
            "site_name":"{site_name}",
            "image_name":"l_hd.jpg",
            "sample_flash_url":"https:\\/\\/{sample_host}\\/sample\\/movies\\/{movie_id}\\/480p.mp4"
          }};
          var emimg = 'https://www.'+Movie.site_name+'/assets/sample/{movie_id}/'+'l_hd.jpg';
        </script>
        <h1 itemprop="name">{title}</h1>
      </body>
    </html>
    """

    class FakeExpressionImageClient:
        async def get_text(self, url, **kwargs):
            _ = kwargs
            if url == f"{base_url}/moviepages/{movie_id}/index.html":
                return html, ""
            return None, f"unexpected url: {url}"

    crawler = crawler_cls(client=FakeExpressionImageClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number=movie_id,
            short_number=movie_id,
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.thumb == f"https://www.{site_name}/assets/sample/{movie_id}/l_hd.jpg"
