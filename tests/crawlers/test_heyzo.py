import pytest

from mdcx.config.enums import Language, Website
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.heyzo import HeyzoCrawler
from mdcx.models.types import CrawlerInput

DETAIL_HTML = """
<html>
  <head>
    <script type="application/ld+json">
    {
      "@context": "http://schema.org",
      "@type": "Movie",
      "name": "色白美肌ナースのスペシャルトリートメント",
      "image": "//www.heyzo.com/contents/3000/3836/images/player_thumbnail.jpg",
      "actor": {"@type": "Person", "name": "如月結衣"},
      "description": "お医者さんとダブル不倫している所を、担当の患者さんに見られてしまったナースの結衣さん。",
      "duration": "PT0H54M36S",
      "dateCreated": "2026-05-02T00:00:00+09:00",
      "video": {
        "@type": "VideoObject",
        "contentUrl": "https://sample.heyzo.com/contents/3000/3836/sample.mp4",
        "duration": "PT0H54M36S"
      }
    }
    </script>
  </head>
  <body>
    <div id="movie">
      <h1>色白美肌ナースのスペシャルトリートメント - 如月結衣</h1>
      <script>
        var movieId = '3836';
        var emid = '3836';
        var emimg = "//www.heyzo.com/contents/3000/3836/images/player_thumbnail_450.jpg";
        var emvideo = "//www.heyzo.com/contents/3000/3836/sample_low.mp4";
        $('.capture').append('<a><img src="/contents/3000/3836/images/capture1.jpg" /></a>');
        $('.capture').append('<a><img src="/contents/3000/3836/images/capture2.jpg" /></a>');
        $('.capture').append('<a><img src="/member/contents/3000/3836/images/capture3.jpg" /></a>');
      </script>
      <table class="movieInfo">
        <tr class="table-release-day"><td>公開日</td><td>2026-05-02</td></tr>
        <tr class="table-actor"><td>出演</td><td><a><span>如月結衣</span></a></td></tr>
        <tr class="table-series"><td>シリーズ</td><td>-----</td></tr>
        <tr class="table-estimate"><td>評価</td><td><span itemprop="ratingValue">3</span></td></tr>
        <tr class="table-actor-type">
          <td>女優タイプ</td>
          <td><a>スレンダー</a><a>美脚</a><a>美乳</a></td>
        </tr>
        <tr class="table-tag-keyword-small">
          <td colspan="2"><ul class="tag-keyword-list"><li><a>おもちゃ</a></li><li><a>騎乗位</a></li></ul></td>
        </tr>
      </table>
    </div>
  </body>
</html>
"""


class FakeHeyzoClient:
    async def get_text(self, url, **kwargs):
        _ = kwargs
        if url == "https://www.heyzo.com/moviepages/3836/index.html":
            return DETAIL_HTML, ""
        return None, f"unexpected url: {url}"


@pytest.mark.asyncio
async def test_heyzo_crawler_parses_direct_detail_page():
    crawler = HeyzoCrawler(client=FakeHeyzoClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="heyzo-3836",
            short_number="heyzo-3836",
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "heyzo"
    assert res.data.external_id == "https://www.heyzo.com/moviepages/3836/index.html"
    assert res.data.number == "HEYZO-3836"
    assert res.data.title == "色白美肌ナースのスペシャルトリートメント"
    assert res.data.originaltitle == res.data.title
    assert res.data.actors == ["如月結衣"]
    assert res.data.all_actors == ["如月結衣"]
    assert res.data.outline == "お医者さんとダブル不倫している所を、担当の患者さんに見られてしまったナースの結衣さん。"
    assert res.data.originalplot == res.data.outline
    assert res.data.release == "2026-05-02"
    assert res.data.year == "2026"
    assert res.data.runtime == "54"
    assert res.data.score == "3"
    assert res.data.series == ""
    assert res.data.tags == ["スレンダー", "美脚", "美乳", "おもちゃ", "騎乗位"]
    assert res.data.thumb == "https://www.heyzo.com/contents/3000/3836/images/player_thumbnail.jpg"
    assert res.data.poster == ""
    assert res.data.extrafanart == [
        "https://www.heyzo.com/contents/3000/3836/images/capture1.jpg",
        "https://www.heyzo.com/contents/3000/3836/images/capture2.jpg",
    ]
    assert res.data.trailer == "https://sample.heyzo.com/contents/3000/3836/sample.mp4"
    assert res.data.studio == "HEYZO"
    assert res.data.publisher == "HEYZO"
    assert res.data.mosaic == "无码"


def test_heyzo_crawler_accepts_compact_number():
    crawler = HeyzoCrawler(client=FakeHeyzoClient())

    assert crawler._build_detail_url(crawler._normalize_number("HEYZO3836")) == (
        "https://www.heyzo.com/moviepages/3836/index.html"
    )


@pytest.mark.asyncio
async def test_heyzo_crawler_rejects_non_heyzo_number():
    crawler = HeyzoCrawler(client=FakeHeyzoClient())
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
    assert "非 HEYZO 番号" in str(res.debug_info.error)


@pytest.mark.asyncio
async def test_heyzo_crawler_rejects_detail_page_with_mismatched_movie_id():
    class FakeMismatchClient:
        async def get_text(self, url, **kwargs):
            _ = url, kwargs
            return DETAIL_HTML.replace("var movieId = '3836';", "var movieId = '3837';"), ""

    crawler = HeyzoCrawler(client=FakeMismatchClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="HEYZO-3836",
            short_number="HEYZO-3836",
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.data is None
    assert res.debug_info.error is not None
    assert "影片标识不一致" in str(res.debug_info.error)


def test_heyzo_crawler_is_registered():
    assert get_crawler(Website.HEYZO) is HeyzoCrawler
