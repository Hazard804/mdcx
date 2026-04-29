import pytest

from mdcx.config.enums import Language
from mdcx.crawlers.kin8 import Kin8Crawler
from mdcx.models.types import CrawlerInput


class FakeKin8Client:
    async def get_text(self, url, **kwargs):
        assert url == "https://www.kin8tengoku.com/moviepages/4188/index.html"
        assert "encoding" not in kwargs
        return (
            """
            <html>
              <head>
                <meta name="description" content="紹介文" />
                <meta property="og:image" content="https://www.kin8tengoku.com/4188/pht/1.jpg" />
                <meta property="og:video" content="https://smovie.kin8tengoku.com/4188/pht/sample.mp4" />
              </head>
              <body>
                <div class="Movie_Detail_title-img__5zop4">
                  <img alt="GW Special Slender Body特集" />
                </div>
                <div class="Movie_Detail_date-movie__C6zuv">
                  <p>配信期間:<span>2026/04/28</span></p>
                </div>
                <div class="Movie_Detail_actor___uEJg">
                  <span>モデル</span>:<a href="/listpages/actor_13127_1">金髪娘</a>
                </div>
                <div class="Movie_Detail_actor-type__j5b5a">
                  <a href="/listpages/536_1">中出し</a>
                  <a href="/listpages/538_1">フェラチオ</a>
                </div>
                <video
                  src="https://smovie.kin8tengoku.com/4188/pht/sample.mp4"
                  poster="https://www.kin8tengoku.com/4188/pht/1.jpg"
                ></video>
                <div class="Movie_Detail_memo__BlQJl">本文紹介</div>
              </body>
            </html>
            """,
            "",
        )


@pytest.mark.asyncio
async def test_kin8_parses_nextjs_detail_page():
    crawler = Kin8Crawler(client=FakeKin8Client())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="kin8-4188",
            short_number="kin8-4188",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.number == "KIN8-4188"
    assert res.data.title == "GW Special Slender Body特集"
    assert res.data.actors == ["金髪娘"]
    assert res.data.tags == ["中出し", "フェラチオ"]
    assert res.data.release == "2026-04-28"
    assert res.data.year == "2026"
    assert res.data.thumb == "https://www.kin8tengoku.com/4188/pht/1.jpg"
    assert res.data.trailer == "https://smovie.kin8tengoku.com/4188/pht/sample.mp4"
