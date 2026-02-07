from mdcx.crawlers.dmm_new import DmmCrawler


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
