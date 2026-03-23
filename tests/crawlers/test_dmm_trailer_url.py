import pytest
from parsel import Selector

import mdcx.crawlers.dmm_new as dmm_module
from mdcx.config.enums import DownloadableFile
from mdcx.config.manager import manager
from mdcx.crawlers.base.types import NOT_SUPPORT, Context, CrawlerData
from mdcx.crawlers.dmm_new import Category, DMMContext, DmmCrawler
from mdcx.crawlers.dmm_new.parsers import MediaVariant, parse_media_variant
from mdcx.models.types import CrawlerInput
from mdcx.web_async import AsyncWebClient


def test_build_fanza_trailer_url_from_standard_playlist():
    url = "https://cc3001.dmm.co.jp/hlsvideo/freepv/s/ssi/ssis00497/playlist.m3u8"
    trailer = DmmCrawler._build_fanza_trailer_url(url)
    assert trailer == "https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00497/ssis00497_sm_w.mp4"


def test_build_fanza_trailer_url_from_temporary_pv_mp4():
    url = "https://cc3001.dmm.co.jp/pv/temporary_key/asfb00192_mhb_w.mp4"
    trailer = DmmCrawler._build_fanza_trailer_url(url)
    assert trailer == url


def test_build_fanza_trailer_url_rejects_playlist_filename_and_uses_fallback_cid():
    url = "https://cc3001.dmm.co.jp/litevideo/pv/temporary_key/playlist.m3u8"
    thumbnail = "https://pics.litevideo.dmm.co.jp/pv/CQETQyMApFZ6pd-2FuHb0sQu0WCkNJmaB033knOvNDSPMGhUyFDAkNiB9Jai8m/cspl00022.jpg"
    trailer = DmmCrawler._build_fanza_trailer_url(url, sample_movie_thumbnail=thumbnail, fallback_cid="cspl00022")
    assert trailer == ""


def test_build_fanza_trailer_url_rejects_playlist_filename_without_fallback():
    url = "https://cc3001.dmm.co.jp/litevideo/pv/temporary_key/playlist.m3u8"
    trailer = DmmCrawler._build_fanza_trailer_url(url)
    assert trailer == ""


def test_build_fanza_trailer_url_uses_fallback_when_thumbnail_missing():
    url = "https://cc3001.dmm.co.jp/litevideo/pv/temporary_key/playlist.m3u8"
    trailer = DmmCrawler._build_fanza_trailer_url(url, sample_movie_thumbnail="", fallback_cid="cspl00022")
    assert trailer == ""


def test_build_freepv_trailer_from_cid():
    assert (
        DmmCrawler._build_freepv_trailer_from_cid("cspl00022", "_hhb_w")
        == "https://cc3001.dmm.co.jp/litevideo/freepv/c/csp/cspl00022/cspl00022_hhb_w.mp4"
    )


def test_build_fanza_fallback_candidates_order_and_content():
    thumbnail = "https://pics.litevideo.dmm.co.jp/pv/TOKEN/cspl00022.jpg"
    candidates = DmmCrawler._build_fanza_fallback_candidates(thumbnail, "cspl00022")
    assert candidates[0].endswith("_4k_w.mp4")
    assert candidates[1].endswith("_hhb_w.mp4")
    assert candidates[-1] == "https://cc3001.dmm.co.jp/pv/TOKEN/cspl00022mhb.mp4"


def test_extract_litevideo_player_url():
    html = '<iframe src="https://www.dmm.co.jp/service/digitalapi/-/html5_player/=/cid=cspl00022/" />'
    assert (
        DmmCrawler._extract_litevideo_player_url(html)
        == "https://www.dmm.co.jp/service/digitalapi/-/html5_player/=/cid=cspl00022/"
    )


def test_extract_litevideo_trailer_candidates():
    player_html = (
        '{"src":"\\/\\/cc3001.dmm.co.jp\\/pv\\/TOKEN\\/cspl00022sm.mp4"},'
        '{"src":"\\/\\/cc3001.dmm.co.jp\\/pv\\/TOKEN\\/cspl00022hhb.mp4"},'
        '{"src":"\\/\\/cc3001.dmm.co.jp\\/pv\\/TOKEN\\/cspl00022sm.mp4"}'
    )
    trailers = DmmCrawler._extract_litevideo_trailer_candidates("".join(player_html))
    assert trailers == [
        "https://cc3001.dmm.co.jp/pv/TOKEN/cspl00022sm.mp4",
        "https://cc3001.dmm.co.jp/pv/TOKEN/cspl00022hhb.mp4",
    ]


def test_trailer_quality_rank_supports_hhb_hmb_mmb_and_suffix_s():
    assert DmmCrawler._trailer_quality_rank("https://x/cspl00022hhb.mp4") > DmmCrawler._trailer_quality_rank(
        "https://x/cspl00022mhb.mp4"
    )
    assert DmmCrawler._trailer_quality_rank("https://x/cspl00022hmb.mp4") > DmmCrawler._trailer_quality_rank(
        "https://x/cspl00022mmb.mp4"
    )
    assert DmmCrawler._trailer_quality_rank("https://x/cspl00022_4ks_w.mp4") > DmmCrawler._trailer_quality_rank(
        "https://x/cspl00022_hhbs_w.mp4"
    )


def test_is_hls_playlist_trailer():
    assert DmmCrawler._is_hls_playlist_trailer("https://x/playlist.m3u8")
    assert not DmmCrawler._is_hls_playlist_trailer("https://x/cspl00022hhb.mp4")


def test_pick_best_unvalidated_trailer_skips_m3u8():
    best = DmmCrawler._pick_best_unvalidated_trailer(
        "",
        [
            "https://x/playlist.m3u8",
            "https://x/cspl00022sm.mp4",
            "https://x/cspl00022hhb.mp4",
        ],
    )
    assert best == "https://x/cspl00022hhb.mp4"


def test_extract_search_detail_urls_prefers_clean_hrefs():
    html = Selector(
        """
        <html><body>
        <a href="https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=dvdms674/?i3_ref=search&amp;i3_ord=6">mono</a>
        <script>
        {"detailUrl":"https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=dvdms674/?i3_"])</script><script>self.__next_f.push([1,"ref=search\\u0026i3_ord=6"}
        </script>
        </body></html>
        """
    )

    assert DmmCrawler._extract_search_detail_urls(
        html, "https://www.dmm.co.jp/search/=/searchstr=dvdms00674/sort=ranking/"
    ) == ["https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=dvdms674/?i3_ref=search&i3_ord=6"]


def test_extract_search_detail_urls_recovers_split_detail_url_without_href():
    html = Selector(
        """
        <html><body><script>
        {"detailUrl":"https"])</script><script>self.__next_f.push([1,"://www.dmm.co.jp/monthly/premium/-/detail/=/cid=dvdms00674/?i3_ref=search\\u0026i3_ord=4"}
        </script></body></html>
        """
    )

    assert DmmCrawler._extract_search_detail_urls(
        html, "https://www.dmm.co.jp/search/=/searchstr=dvdms00674/sort=ranking/"
    ) == ["https://www.dmm.co.jp/monthly/premium/-/detail/=/cid=dvdms00674/?i3_ref=search&i3_ord=4"]


@pytest.mark.asyncio
async def test_fetch_digital_uses_graphql_response(monkeypatch: pytest.MonkeyPatch):
    crawler = DmmCrawler(client=AsyncWebClient(timeout=1))
    ctx = DMMContext(input=CrawlerInput.empty())
    detail_url = "https://video.dmm.co.jp/av/content/?id=ipzz00841&i3_ref=search&i3_ord=1"
    captured: dict[str, object] = {}

    async def fake_http_request_with_retry(method: str, url: str, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return (
            {
                "data": {
                    "ppvContent": {
                        "id": "ipzz00841",
                        "title": "FIRST IMPRESSION 191 辻みいな",
                        "description": "福岡県出身 22歳<br>趣味:推し活",
                        "packageImage": {
                            "largeUrl": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipzz00841/ipzz00841pl.jpg",
                            "mediumUrl": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipzz00841/ipzz00841ps.jpg",
                        },
                        "sampleImages": [
                            {
                                "largeImageUrl": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipzz00841/ipzz00841jp-1.jpg"
                            },
                            {
                                "largeImageUrl": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipzz00841/ipzz00841jp-2.jpg"
                            },
                        ],
                        "sample2DMovie": {
                            "highestMovieUrl": "https://cc3001.dmm.co.jp/pv/TOKEN/ipzz00841hhb.mp4",
                            "hlsMovieUrl": "https://cc3001.dmm.co.jp/pv/TOKEN/playlist.m3u8",
                        },
                        "sampleVRMovie": {
                            "highestMovieUrl": "",
                        },
                        "deliveryStartDate": "2026-03-05T15:00:00Z",
                        "makerReleasedAt": "2026-03-09T15:00:00Z",
                        "duration": 11288,
                        "actresses": [{"name": "辻みいな"}],
                        "directors": [{"name": "豆沢豆太郎"}],
                        "series": {"name": "First Impression"},
                        "maker": {"name": "アイデアポケット"},
                        "label": {"name": "ティッシュ"},
                        "genres": [{"name": "独占配信"}, {"name": "4K"}],
                    },
                    "reviewSummary": {"average": 3.8824},
                }
            },
            "",
        )

    monkeypatch.setattr(crawler, "_http_request_with_retry", fake_http_request_with_retry)

    result = await crawler.fetch_digital(ctx, detail_url)

    assert result.title == "FIRST IMPRESSION 191 辻みいな"
    assert result.outline == "福岡県出身 22歳\n趣味:推し活"
    assert result.release == "2026-03-05"
    assert result.runtime == "188"
    assert result.actors == ["辻みいな"]
    assert result.directors == ["豆沢豆太郎"]
    assert result.series == "First Impression"
    assert result.studio == "アイデアポケット"
    assert result.publisher == "ティッシュ"
    assert result.tags == ["独占配信", "4K"]
    assert result.score == "3.8824"
    assert result.thumb == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipzz00841/ipzz00841pl.jpg"
    assert result.poster == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipzz00841/ipzz00841ps.jpg"
    assert result.extrafanart == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipzz00841/ipzz00841jp-1.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipzz00841/ipzz00841jp-2.jpg",
    ]
    assert result.trailer == "https://cc3001.dmm.co.jp/pv/TOKEN/ipzz00841hhb.mp4"

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.video.dmm.co.jp/graphql"
    assert captured["kwargs"] == {
        "json_data": {
            "operationName": "MDCxDigitalContent",
            "variables": {"id": "ipzz00841"},
            "query": dmm_module.dmm_digital_payload("ipzz00841")["query"],
        },
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://video.dmm.co.jp",
            "Referer": detail_url,
        },
        "cookies": {"age_check_done": "1"},
    }


@pytest.mark.asyncio
async def test_fetch_digital_tolerates_nullable_graphql_fields(monkeypatch: pytest.MonkeyPatch):
    crawler = DmmCrawler(client=AsyncWebClient(timeout=1))
    ctx = DMMContext(input=CrawlerInput.empty())
    detail_url = "https://video.dmm.co.jp/av/content/?id=mida00557&i3_ref=search&i3_ord=1"

    async def fake_http_request_with_retry(method: str, url: str, **kwargs):
        return (
            {
                "data": {
                    "ppvContent": {
                        "id": "mida00557",
                        "title": "内気な性格で嫌と言えずエロ整体師の媚薬マッサージにイカされ続けた部活少女 七沢みあ",
                        "description": None,
                        "packageImage": None,
                        "sampleImages": None,
                        "sample2DMovie": None,
                        "sampleVRMovie": None,
                        "deliveryStartDate": None,
                        "makerReleasedAt": "2026-03-16T15:00:00Z",
                        "duration": None,
                        "actresses": [None, {"name": None}, {"name": "七沢みあ"}],
                        "directors": None,
                        "series": None,
                        "maker": None,
                        "label": {"name": None},
                        "genres": [None, {"name": None}, {"name": "4K"}],
                    },
                    "reviewSummary": None,
                }
            },
            "",
        )

    monkeypatch.setattr(crawler, "_http_request_with_retry", fake_http_request_with_retry)

    result = await crawler.fetch_digital(ctx, detail_url)

    assert result.title == "内気な性格で嫌と言えずエロ整体師の媚薬マッサージにイカされ続けた部活少女 七沢みあ"
    assert result.outline == ""
    assert result.release == "2026-03-16"
    assert result.runtime == ""
    assert result.actors == ["七沢みあ"]
    assert result.directors == []
    assert result.series == ""
    assert result.studio == ""
    assert result.publisher == ""
    assert result.tags == ["4K"]
    assert result.score == ""
    assert result.thumb == ""
    assert result.poster == ""
    assert result.extrafanart == []
    assert result.trailer == ""
    assert any("digital GraphQL 请求成功" in log for log in ctx.debug_info.logs)


@pytest.mark.asyncio
async def test_detail_uses_fetch_digital_for_digital_urls(monkeypatch: pytest.MonkeyPatch):
    crawler = DmmCrawler(client=AsyncWebClient(timeout=1))
    ctx = DMMContext(input=CrawlerInput.empty())
    detail_url = "https://video.dmm.co.jp/av/content/?id=ipzz00841&i3_ref=search&i3_ord=1"
    calls: list[tuple[str, str]] = []

    async def fake_fetch_digital(inner_ctx, url: str):
        calls.append(("digital", url))
        return CrawlerData(title="digital title", release="2026-03-05", external_id=url)

    async def fake_fetch_and_parse(inner_ctx, url: str, parser):
        calls.append(("parser", url))
        if url == detail_url:
            raise AssertionError("digital 详情不应再走 fetch_and_parse")
        return CrawlerData(title="mono title", external_id=url)

    async def fake_sanitize_candidate_images(inner_ctx, category, url: str, item: CrawlerData):
        return item

    async def fake_finalize_result_images(inner_ctx, item, *, label: str, validate_thumb: bool):
        return item

    monkeypatch.setattr(crawler, "fetch_digital", fake_fetch_digital)
    monkeypatch.setattr(crawler, "fetch_and_parse", fake_fetch_and_parse)
    monkeypatch.setattr(crawler, "_sanitize_candidate_images", fake_sanitize_candidate_images)
    monkeypatch.setattr(crawler, "_finalize_result_images", fake_finalize_result_images)

    result = await crawler._detail(ctx, [detail_url])

    assert result is not None
    assert result.title == "digital title"
    assert calls == [("digital", detail_url)]


def test_merge_detail_results_prefers_digital_release_over_tv():
    ctx = Context(input=CrawlerInput.empty())
    tv_result = CrawlerData(
        title="tv title",
        release="2023-07-14T01:00:00Z",
        year="2023",
        thumb="https://tv.example/thumb.jpg",
        external_id="tv",
    )
    digital_result = CrawlerData(
        title="digital title",
        release="2017-09-16",
        year="2017",
        external_id="digital",
    )

    merged, best_trailer = DmmCrawler._merge_detail_results(
        ctx,
        [
            (Category.DMM_TV, tv_result),
            (Category.DIGITAL, digital_result),
        ],
    )

    assert merged is not None
    assert best_trailer == ""
    assert merged.title == "digital title"
    assert merged.thumb == "https://tv.example/thumb.jpg"
    assert merged.release == "2017-09-16"
    assert merged.year == "2017"
    assert merged.external_id == "digital"


def test_merge_detail_results_uses_tv_release_as_last_fallback():
    ctx = Context(input=CrawlerInput.empty())
    tv_result = CrawlerData(
        title="tv title",
        release="2023-07-14T01:00:00Z",
        year="2023",
        external_id="tv",
    )
    mono_result = CrawlerData(
        title="mono title",
        release="",
        year="",
        external_id="mono",
    )

    merged, best_trailer = DmmCrawler._merge_detail_results(
        ctx,
        [
            (Category.DMM_TV, tv_result),
            (Category.MONO, mono_result),
        ],
    )

    assert merged is not None
    assert best_trailer == ""
    assert merged.release == "2023-07-14T01:00:00Z"
    assert merged.year == "2023"


def test_merge_detail_results_keeps_lower_priority_value_when_digital_field_empty():
    ctx = Context(input=CrawlerInput.empty())
    mono_result = CrawlerData(
        title="mono title",
        release="2026-03-17",
        publisher="mono publisher",
        external_id="mono",
    )
    digital_result = CrawlerData(
        title="digital title",
        release="",
        publisher="",
        external_id="digital",
    )

    merged, best_trailer = DmmCrawler._merge_detail_results(
        ctx,
        [
            (Category.MONO, mono_result),
            (Category.DIGITAL, digital_result),
        ],
    )

    assert merged is not None
    assert best_trailer == ""
    assert merged.title == "digital title"
    assert merged.release == "2026-03-17"
    assert merged.publisher == "mono publisher"
    assert merged.external_id == "digital"


def test_parse_media_variant_prefers_active_media():
    html = Selector(
        """
        <html><body>
        <div class="area-editiontype">
          <ul class="list-media">
            <li class="item-media"><span class="ttl-media">DVD</span></li>
            <li class="item-media is-active"><span class="ttl-media">Blu-ray</span></li>
          </ul>
        </div>
        </body></html>
        """
    )

    assert parse_media_variant(html) == MediaVariant.BLURAY


def test_parse_media_variant_uses_breadcrumb_as_high_confidence_fallback():
    html = Selector(
        """
        <html><body>
        <nav class="area-breadcrumbs">
          <ul>
            <li class="item-breadcrumbs"><span itemprop="name">通販</span></li>
            <li class="item-breadcrumbs"><span itemprop="name">DVD</span></li>
          </ul>
        </nav>
        </body></html>
        """
    )

    assert parse_media_variant(html) == MediaVariant.DVD


def test_pick_preferred_image_candidate_demotes_bluray_cover():
    ctx = DMMContext(input=CrawlerInput.empty())
    dvd_url = "https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=pred816/?i3_ref=search&i3_ord=2"
    bluray_url = "https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=9pred816/?i3_ref=search&i3_ord=3"
    dvd_key = DmmCrawler._canonicalize_detail_url(dvd_url)
    bluray_key = DmmCrawler._canonicalize_detail_url(bluray_url)
    ctx.detail_media_variants = {
        dvd_key: MediaVariant.DVD,
        bluray_key: MediaVariant.BLURAY,
    }

    candidate = DmmCrawler._pick_preferred_image_candidate(
        ctx,
        [
            (
                Category.MONO,
                bluray_url,
                CrawlerData(
                    thumb="https://pics.dmm.co.jp/mono/movie/adult/9pred816/9pred816pl.jpg",
                    external_id=bluray_url,
                ),
            ),
            (
                Category.MONO,
                dvd_url,
                CrawlerData(
                    thumb="https://pics.dmm.co.jp/mono/movie/adult/pred816/pred816pl.jpg",
                    external_id=dvd_url,
                ),
            ),
        ],
        {
            dvd_key: 0,
            bluray_key: 1,
        },
    )

    assert candidate is not None
    category, variant, data = candidate
    assert category == Category.MONO
    assert variant == MediaVariant.DVD
    assert data.thumb == "https://pics.dmm.co.jp/mono/movie/adult/pred816/pred816pl.jpg"


def test_pick_preferred_image_candidate_keeps_bluray_as_fallback():
    ctx = DMMContext(input=CrawlerInput.empty())
    bluray_url = "https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=9pred816/?i3_ref=search&i3_ord=3"
    bluray_key = DmmCrawler._canonicalize_detail_url(bluray_url)
    ctx.detail_media_variants = {
        bluray_key: MediaVariant.BLURAY,
    }

    candidate = DmmCrawler._pick_preferred_image_candidate(
        ctx,
        [
            (
                Category.MONO,
                bluray_url,
                CrawlerData(
                    thumb="https://pics.dmm.co.jp/mono/movie/adult/9pred816/9pred816pl.jpg",
                    external_id=bluray_url,
                ),
            ),
        ],
        {
            bluray_key: 0,
        },
    )

    assert candidate is not None
    _, variant, data = candidate
    assert variant == MediaVariant.BLURAY
    assert data.thumb == "https://pics.dmm.co.jp/mono/movie/adult/9pred816/9pred816pl.jpg"


@pytest.mark.asyncio
async def test_sanitize_candidate_images_prefers_aws_thumb_without_eagerly_validating_other_images(
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        if "badextra" in url:
            return None
        if url == "https://pics.dmm.co.jp/digital/video/pred00816/pred00816pl.jpg":
            return None
        return url

    monkeypatch.setattr(dmm_module, "check_url", fake_check_url)

    crawler = DmmCrawler(client=None)
    ctx = DMMContext(input=CrawlerInput.empty())
    ctx.number_00 = "pred00816"
    ctx.number_no_00 = "pred00816"

    data = CrawlerData(
        thumb="https://pics.dmm.co.jp/digital/video/pred00816/pred00816pl.jpg",
        extrafanart=[
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/badextra.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
        ],
        external_id="https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=pred00816/",
    )

    sanitized = await crawler._sanitize_candidate_images(
        ctx,
        Category.DIGITAL,
        "https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=pred00816/",
        data,
    )

    assert sanitized.thumb == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/pred00816pl.jpg"
    assert sanitized.poster is NOT_SUPPORT
    assert sanitized.extrafanart == [
        "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
        "https://pics.dmm.co.jp/digital/video/pred00816/badextra.jpg",
        "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
    ]


@pytest.mark.asyncio
async def test_finalize_result_images_validates_poster_and_filters_invalid_extrafanart(
    monkeypatch: pytest.MonkeyPatch,
):
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        if "badextra" in url:
            return None
        return url

    monkeypatch.setattr(dmm_module, "check_url", fake_check_url)
    monkeypatch.setattr(
        manager.config,
        "download_files",
        [DownloadableFile.POSTER, DownloadableFile.THUMB, DownloadableFile.EXTRAFANART],
    )

    crawler = DmmCrawler(client=None)
    ctx = DMMContext(input=CrawlerInput.empty())

    data = CrawlerData(
        thumb="https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/pred00816pl.jpg",
        poster="https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/pred00816ps.jpg",
        extrafanart=[
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/badextra.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
        ],
    )

    finalized = await crawler._finalize_result_images(ctx, data, label="最终图片", validate_thumb=False)

    assert finalized.poster == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/pred00816ps.jpg"
    assert finalized.extrafanart == ["https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg"]
    assert called_urls == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/pred00816ps.jpg",
        "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
        "https://pics.dmm.co.jp/digital/video/pred00816/badextra.jpg",
    ]


@pytest.mark.asyncio
async def test_post_process_disables_direct_download_when_poster_candidates_are_invalid(
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        if url.endswith("ps.jpg"):
            return None
        return url

    monkeypatch.setattr(dmm_module, "check_url", fake_check_url)

    crawler = DmmCrawler(client=None)
    ctx = DMMContext(input=CrawlerInput.empty())
    result = CrawlerData(
        title="VR SAMPLE",
        thumb="https://pics.dmm.co.jp/mono/movie/adult/pred816/pred816pl.jpg",
        studio="",
    ).to_result()

    processed = await crawler.post_process(ctx, result)

    assert processed.thumb == "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816pl.jpg"
    assert processed.poster == ""
    assert processed.image_download is False


@pytest.mark.asyncio
async def test_sanitize_candidate_images_skips_extrafanart_validation_when_download_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        return url

    monkeypatch.setattr(dmm_module, "check_url", fake_check_url)
    monkeypatch.setattr(manager.config, "download_files", [DownloadableFile.POSTER, DownloadableFile.THUMB])

    crawler = DmmCrawler(client=None)
    ctx = DMMContext(input=CrawlerInput.empty())
    ctx.number_00 = "pred00816"
    ctx.number_no_00 = "pred00816"

    data = CrawlerData(
        thumb="https://pics.dmm.co.jp/digital/video/pred00816/pred00816pl.jpg",
        extrafanart=[
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample2.jpg",
        ],
        external_id="https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=pred00816/",
    )

    sanitized = await crawler._sanitize_candidate_images(
        ctx,
        Category.DIGITAL,
        "https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=pred00816/",
        data,
    )

    assert sanitized.extrafanart == [
        "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
        "https://pics.dmm.co.jp/digital/video/pred00816/sample2.jpg",
    ]
    assert all("sample" not in url for url in called_urls)


@pytest.mark.asyncio
async def test_post_process_skips_image_revalidation_when_final_images_already_resolved(
    monkeypatch: pytest.MonkeyPatch,
):
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        return url

    monkeypatch.setattr(dmm_module, "check_url", fake_check_url)

    crawler = DmmCrawler(client=None)
    ctx = DMMContext(input=CrawlerInput.empty(), final_images_resolved=True)
    result = CrawlerData(
        title="SAMPLE",
        thumb="https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816pl.jpg",
        poster="https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816ps.jpg",
    ).to_result()

    processed = await crawler.post_process(ctx, result)

    assert processed.thumb == "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816pl.jpg"
    assert processed.poster == "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816ps.jpg"
    assert called_urls == []


@pytest.mark.asyncio
async def test_detail_preferred_image_does_not_leak_notsupport_poster(monkeypatch: pytest.MonkeyPatch):
    crawler = DmmCrawler(client=None)
    ctx = DMMContext(input=CrawlerInput.empty())

    async def fake_fetch_and_parse(*args, **kwargs):
        return CrawlerData(
            thumb="https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816pl.jpg",
            poster=NOT_SUPPORT,
            external_id="https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=pred816/",
        )

    async def fake_sanitize_candidate_images(ctx, category, detail_url, item):
        return item

    async def fake_finalize_result_images(ctx, item, *, label: str, validate_thumb: bool):
        return item

    monkeypatch.setattr(crawler, "fetch_and_parse", fake_fetch_and_parse)
    monkeypatch.setattr(crawler, "_sanitize_candidate_images", fake_sanitize_candidate_images)
    monkeypatch.setattr(crawler, "_finalize_result_images", fake_finalize_result_images)

    result = await crawler._detail(ctx, ["https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=pred816/"])

    assert result is not None
    assert result.thumb == "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816pl.jpg"
    assert result.poster is NOT_SUPPORT
    assert result.to_result().poster == ""
