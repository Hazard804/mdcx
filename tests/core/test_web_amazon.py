import re
import urllib.parse

import numpy as np
import pytest

from mdcx.config.enums import HDPicSource
from mdcx.config.manager import manager
from mdcx.core.web import (
    _beam_search_amazon_ean13_from_ranked_digits,
    _extract_amazon_barcode_label_roi,
    _get_big_poster,
    get_big_pic_by_amazon,
    try_get_amazon_barcode_from_covers,
)
from mdcx.models.log_buffer import LogBuffer
from mdcx.models.types import CrawlersResult, OtherInfo


def _extract_search_query(req_url: str) -> str:
    match = re.search(r"returnUrl=/s\?k=([^&]+)", req_url)
    assert match is not None
    return urllib.parse.unquote_plus(urllib.parse.unquote_plus(match.group(1)))


def _normalize_search_query(query: str) -> str:
    return re.sub(r" \[(DVD|Blu-ray)\]$", "", query)


@pytest.mark.asyncio
async def test_get_big_poster_uses_amazon_only_for_non_suren_censored(monkeypatch: pytest.MonkeyPatch):
    called = False

    async def fake_get_big_pic_by_amazon(*args, **kwargs):
        nonlocal called
        called = True
        return "https://m.media-amazon.com/images/I/81poster.jpg"

    monkeypatch.setattr(manager.config, "download_hd_pics", [HDPicSource.POSTER, HDPicSource.AMAZON])
    monkeypatch.setattr("mdcx.core.web.get_big_pic_by_amazon", fake_get_big_pic_by_amazon)

    result = CrawlersResult.empty()
    result.mosaic = "有码"
    result.originaltitle_amazon = "测试标题"
    other = OtherInfo.empty()

    await _get_big_poster(result, other)

    assert called is True
    assert result.poster == "https://m.media-amazon.com/images/I/81poster.jpg"
    assert result.poster_from == "Amazon"


@pytest.mark.asyncio
async def test_get_big_poster_keeps_original_amazon_whitelist(monkeypatch: pytest.MonkeyPatch):
    called = False

    async def fake_get_big_pic_by_amazon(*args, **kwargs):
        nonlocal called
        called = True
        return "https://m.media-amazon.com/images/I/81poster.jpg"

    monkeypatch.setattr(manager.config, "download_hd_pics", [HDPicSource.POSTER, HDPicSource.AMAZON])
    monkeypatch.setattr("mdcx.core.web.get_big_pic_by_amazon", fake_get_big_pic_by_amazon)

    result = CrawlersResult.empty()
    result.mosaic = "流出"
    result.originaltitle_amazon = "流出标题"
    other = OtherInfo.empty()

    await _get_big_poster(result, other)

    assert called is True
    assert result.poster == "https://m.media-amazon.com/images/I/81poster.jpg"
    assert result.poster_from == "Amazon"


@pytest.mark.asyncio
async def test_get_big_poster_skips_amazon_for_suren(monkeypatch: pytest.MonkeyPatch):
    called = False

    async def fake_get_big_pic_by_amazon(*args, **kwargs):
        nonlocal called
        called = True
        return "https://m.media-amazon.com/images/I/81poster.jpg"

    monkeypatch.setattr(manager.config, "download_hd_pics", [HDPicSource.POSTER, HDPicSource.AMAZON])
    monkeypatch.setattr("mdcx.core.web.get_big_pic_by_amazon", fake_get_big_pic_by_amazon)

    result = CrawlersResult.empty()
    result.mosaic = "有码"
    result.is_suren = True
    result.originaltitle_amazon = "素人标题"
    other = OtherInfo.empty()

    await _get_big_poster(result, other)

    assert called is False
    assert result.poster == ""
    assert result.poster_from == ""


@pytest.mark.asyncio
async def test_get_big_poster_skips_amazon_for_non_censored(monkeypatch: pytest.MonkeyPatch):
    called = False

    async def fake_get_big_pic_by_amazon(*args, **kwargs):
        nonlocal called
        called = True
        return "https://m.media-amazon.com/images/I/81poster.jpg"

    monkeypatch.setattr(manager.config, "download_hd_pics", [HDPicSource.POSTER, HDPicSource.AMAZON])
    monkeypatch.setattr("mdcx.core.web.get_big_pic_by_amazon", fake_get_big_pic_by_amazon)

    result = CrawlersResult.empty()
    result.mosaic = "无码"
    result.originaltitle_amazon = "无码标题"
    other = OtherInfo.empty()

    await _get_big_poster(result, other)

    assert called is False
    assert result.poster == ""
    assert result.poster_from == ""


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_supports_new_search_card_selector(monkeypatch: pytest.MonkeyPatch):
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000TEST">
          <h2><a href="/s?keywords=めぐり"><span>妻の残業NTR めぐり</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=めぐり"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81example._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """

    async def fake_get_amazon_data(req_url: str):
        return True, html_search

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, "妻の残業NTR", ["めぐり"])

    assert pic_url == "https://m.media-amazon.com/images/I/81example.jpg"


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_supports_actor_alias_with_brackets(monkeypatch: pytest.MonkeyPatch):
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000TEST">
          <h2><a href="/s?keywords=none"><span>妻の残業NTR めぐり</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=none"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81alias._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """

    async def fake_get_amazon_data(req_url: str):
        return True, html_search

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, "妻の残業NTR", ["めぐり（藤浦めぐ）"])

    assert pic_url == "https://m.media-amazon.com/images/I/81alias.jpg"


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_retry_with_series_when_first_no_result(monkeypatch: pytest.MonkeyPatch):
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_series_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000SERIES">
          <h2><a href="/s?keywords=演员A"><span>系列名 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=演员A"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81series._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _normalize_search_query(_extract_search_query(req_url))
        queries.append(query)
        if query == "主标题长字符串":
            return True, html_no_result
        return True, html_series_match

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, "主标题长字符串", ["演员A"], "系列名")

    assert pic_url == "https://m.media-amazon.com/images/I/81series.jpg"
    assert queries[0] == "主标题长字符串"
    assert "系列名" in queries
    assert queries.index("系列名") > 0


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_retry_with_no_result_class_marker(monkeypatch: pytest.MonkeyPatch):
    html_no_result_marker = """
    <html>
      <body>
        <div class="s-no-results">No matches</div>
      </body>
    </html>
    """
    html_series_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000SERIES">
          <h2><a href="/s?keywords=演员A"><span>系列名 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=演员A"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81marker._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _normalize_search_query(_extract_search_query(req_url))
        queries.append(query)
        if query == "系列名":
            return True, html_series_match
        return True, html_no_result_marker

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, "主标题长字符串", ["演员A"], "系列名")

    assert pic_url == "https://m.media-amazon.com/images/I/81marker.jpg"
    assert queries[0] == "主标题长字符串"
    assert "系列名" in queries


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_searches_replaced_title_before_original(monkeypatch: pytest.MonkeyPatch):
    masked_title = "テスト痴●タイトル"
    replaced_title = "テスト痴漢タイトル"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_masked_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000MASK">
          <h2><a href="/s?keywords=演员A"><span>テスト痴●タイトル 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=演员A"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81masked._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _normalize_search_query(_extract_search_query(req_url))
        queries.append(query)
        if query == replaced_title:
            return True, html_no_result
        if query == masked_title:
            return True, html_masked_match
        return True, "<html><body></body></html>"

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, replaced_title, ["演员A"], "", masked_title, "")

    assert pic_url == "https://m.media-amazon.com/images/I/81masked.jpg"
    assert queries[0] == replaced_title
    assert masked_title in queries
    assert queries.index(masked_title) > 0


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_strip_actor_suffix_before_first_search(monkeypatch: pytest.MonkeyPatch):
    title_with_actor = "タイトル本文 みなみ羽琉"
    stripped_title = "タイトル本文"
    html_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000STRIP">
          <h2><a href="/s?keywords=みなみ羽琉"><span>タイトル本文 みなみ羽琉</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=みなみ羽琉"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81strip._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _extract_search_query(req_url)
        queries.append(query)
        if query == stripped_title:
            return True, html_match
        return True, "<html><body></body></html>"

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, title_with_actor, ["みなみ羽琉"])

    assert pic_url == "https://m.media-amazon.com/images/I/81strip.jpg"
    assert queries[0] == stripped_title


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_strips_trailing_dod_noise_and_prefers_plain_title_first(
    monkeypatch: pytest.MonkeyPatch,
):
    title_with_actor_and_dod = (
        "本番オーケー！？噂の裏ピンサロ 05 AV界随一のG乳＆美尻を味わい尽くせ！ 園田みおん （DOD）"
    )
    stripped_title = "本番オーケー！？噂の裏ピンサロ 05 AV界随一のG乳＆美尻を味わい尽くせ！"
    html_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000DOD">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000DOD"><span>本番オーケー！？噂の裏ピンサロ 05 AV界随一のG乳＆美尻を味わい尽くせ！ 園田みおん （DOD）</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000DOD"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81dod._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_detail = """
    <html>
      <body>
        <span id="productTitle">本番オーケー！？噂の裏ピンサロ 05 AV界随一のG乳＆美尻を味わい尽くせ！ 園田みおん （DOD）</span>
        <div id="bylineInfo_feature_div"><a>園田みおん</a></div>
      </body>
    </html>
    """
    html_no_result = """
    <html>
      <body>
        <div class="s-no-results">No matches</div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000DOD" in req_url:
            return True, html_detail
        query = _extract_search_query(req_url)
        queries.append(query)
        if query == stripped_title:
            return True, html_match
        return True, html_no_result

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.number = "ABP-816"
    pic_url = await get_big_pic_by_amazon(result, title_with_actor_and_dod, ["園田みおん"])

    assert pic_url == "https://m.media-amazon.com/images/I/81dod.jpg"
    assert queries[0] == stripped_title
    assert all("DOD" not in query for query in queries[:2])
    assert f"{stripped_title} ABP-816" in queries


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_actor_fallback_matches_cleaned_title_confidence(
    monkeypatch: pytest.MonkeyPatch,
):
    original_title = (
        "目を覚ますと下着姿のグラドルとホテルで二人きり…慌てる僕を横目に誘惑してくる芸能人一体酔っている間に何があった!? 強●魔"
        " 紫堂るい エスワン ナンバーワンスタイル [DVD]"
    )
    actor_name = "紫堂るい"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_actor_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000FALLBACK">
          <a class="a-text-bold">DVD</a>
          <h2>
                <a href="/s?keywords=none">
                  <span>
                    目を覚ますと下着姿のグラドルとホテルで二人きり…慌てる僕を横目に誘惑してくる芸能人一体酔っている間に何があった!?
                    強姦魔 紫堂るい ナンバーワンスタイル エスワン [DVD]
                  </span>
                </a>
              </h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=none"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81fallback._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _extract_search_query(req_url)
        queries.append(query)
        if query == actor_name:
            return True, html_actor_match
        return True, html_no_result

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.studio = "エスワン"
    result.publisher = "ナンバーワンスタイル"

    pic_url = await get_big_pic_by_amazon(result, original_title, [actor_name])

    assert pic_url == "https://m.media-amazon.com/images/I/81fallback.jpg"
    assert queries[0].startswith("目を覚ますと下着姿のグラドルとホテルで二人きり")
    assert actor_name in queries


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_actor_fallback_treats_mask_symbol_in_amazon_title_as_wildcard(
    monkeypatch: pytest.MonkeyPatch,
):
    original_title = "名門私立の女子大生が強姦魔にさらわれる。"
    actor_name = "音無鈴"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_actor_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000MASKWILD">
          <a class="a-text-bold">DVD</a>
          <h2>
            <a href="/s?keywords=none">
              <span>名門私立の女子大生が強●魔にさらわれる。 音無鈴 エスワン ナンバーワンスタイル [DVD]</span>
            </a>
          </h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=none"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81maskwild._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _extract_search_query(req_url)
        queries.append(query)
        if query == actor_name:
            return True, html_actor_match
        return True, html_no_result

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.studio = "エスワン"
    result.publisher = "ナンバーワンスタイル"

    pic_url = await get_big_pic_by_amazon(result, original_title, [actor_name])

    assert pic_url == "https://m.media-amazon.com/images/I/81maskwild.jpg"
    assert queries[0].startswith("名門私立の女子大生が強姦魔にさらわれる")
    assert actor_name in queries


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_actor_fallback_treats_mask_symbol_in_original_title_as_wildcard(
    monkeypatch: pytest.MonkeyPatch,
):
    original_title = "名門私立の女子大生が強●魔にさらわれる。"
    actor_name = "音無鈴"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_actor_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000MASKWILDREV">
          <a class="a-text-bold">DVD</a>
          <h2>
            <a href="/s?keywords=none">
              <span>名門私立の女子大生が強姦魔にさらわれる。 音無鈴 エスワン ナンバーワンスタイル [DVD]</span>
            </a>
          </h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=none"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81maskwildrev._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _extract_search_query(req_url)
        queries.append(query)
        if query == actor_name:
            return True, html_actor_match
        return True, html_no_result

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.studio = "エスワン"
    result.publisher = "ナンバーワンスタイル"

    pic_url = await get_big_pic_by_amazon(result, original_title, [actor_name])

    assert pic_url == "https://m.media-amazon.com/images/I/81maskwildrev.jpg"
    assert queries[0].startswith("名門私立の女子大生が強●魔にさらわれる")
    assert actor_name in queries


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_actor_fallback_handles_mask_and_unknown_suffix_without_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    original_title = "大量失禁が止まらない…！新木希空、初めての恥じらい超お漏らしアクメ"
    actor_name = "新木希空"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_actor_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000SNOS007">
          <a class="a-text-bold">DVD</a>
          <h2>
            <a href="/s?keywords=none">
              <span>大量失●が止まらない…!新木希空、初めての恥じらい超お●らしアクメ 新木希空 エスワン ナンバーワンスタイル [DVD]</span>
            </a>
          </h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=none"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81snos007._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _extract_search_query(req_url)
        queries.append(query)
        if query == actor_name:
            return True, html_actor_match
        return True, html_no_result

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()

    pic_url = await get_big_pic_by_amazon(result, original_title, [actor_name])

    assert pic_url == "https://m.media-amazon.com/images/I/81snos007.jpg"
    assert queries[0].startswith("大量失禁が止まらない")
    assert actor_name in queries


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_actor_fallback_cleans_raw_and_mapped_metadata_keywords(
    monkeypatch: pytest.MonkeyPatch,
):
    original_title = "短标题"
    actor_name = "演员A"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_actor_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000METABOTH">
          <a class="a-text-bold">DVD</a>
          <h2>
            <a href="/s?keywords=none">
              <span>短标题 映射厂商 [DVD]</span>
            </a>
          </h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=none"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81metaboth._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _extract_search_query(req_url)
        queries.append(query)
        if query == actor_name:
            return True, html_actor_match
        return True, html_no_result

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.amazon_raw_studio = "原始厂商"
    result.studio = "映射厂商"

    pic_url = await get_big_pic_by_amazon(result, original_title, [actor_name])

    assert pic_url == "https://m.media-amazon.com/images/I/81metaboth.jpg"
    assert queries[0] == original_title
    assert actor_name in queries


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_accepts_bluray_result_with_plain_title(
    monkeypatch: pytest.MonkeyPatch,
):
    title = "标题测试"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_bluray_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000BLURAY">
          <a class="a-text-bold">Blu-ray</a>
          <h2><a href="/s?keywords=演员A"><span>标题测试 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=演员A"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81bluray._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _extract_search_query(req_url)
        queries.append(query)
        if query == title:
            return True, html_bluray_match
        return True, html_no_result

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, title, ["演员A"])

    assert pic_url == "https://m.media-amazon.com/images/I/81bluray.jpg"
    assert queries[0] == title
    assert queries.count(title) == 1


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_series_fallback_pairs_with_each_initial_title(monkeypatch: pytest.MonkeyPatch):
    replaced_title = "主标题A 系列漢"
    raw_title = "主标题B 系列●"
    replaced_series = "系列漢"
    raw_series = "系列●"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_raw_stripped_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000PAIR">
          <h2><a href="/s?keywords=演员A"><span>主标题B 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=演员A"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81pair._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _normalize_search_query(_extract_search_query(req_url))
        queries.append(query)
        if query == "主标题B":
            return True, html_raw_stripped_match
        return True, html_no_result

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, replaced_title, ["演员A"], replaced_series, raw_title, raw_series)

    assert pic_url == "https://m.media-amazon.com/images/I/81pair.jpg"
    assert queries[0] == replaced_title
    assert raw_title in queries
    assert raw_series in queries
    assert "主标题B" in queries
    assert queries.index(raw_series) < queries.index("主标题B")


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_retry_with_title_without_series_when_no_actor_match(
    monkeypatch: pytest.MonkeyPatch,
):
    html_no_actor_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000NONE">
          <h2><a href="/s?keywords=none"><span>无关标题</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=none"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81none._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_title_without_series_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000TITLE">
          <h2><a href="/s?keywords=演员A"><span>主标题 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=演员A"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81title._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        query = _normalize_search_query(_extract_search_query(req_url))
        queries.append(query)
        if query == "主标题 系列名":
            return True, html_no_actor_match
        if query == "系列名":
            return True, html_no_actor_match
        if query == "主标题":
            return True, html_title_without_series_match
        return True, "<html><body></body></html>"

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, "主标题 系列名", ["演员A"], "系列名")

    assert pic_url == "https://m.media-amazon.com/images/I/81title.jpg"
    assert queries[0] == "主标题 系列名"
    assert "系列名" in queries
    assert "主标题" in queries
    assert queries.index("系列名") < queries.index("主标题")


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_prefers_title_with_number_query(monkeypatch: pytest.MonkeyPatch):
    title = "互いに素性を知った美魔女ママ友と箱ヘルで出逢い、裏引き不倫。"
    numbered_title = f"{title} DASS-907"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000NUM">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000NUM"><span>互いに素性を知った美魔女ママ友と箱ヘルで出逢い、裏引き不倫。</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000NUM"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81number._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_detail = """
    <html>
      <body>
        <span id="productTitle">互いに素性を知った美魔女ママ友と箱ヘルで出逢い、裏引き不倫。</span>
        <div id="detailBulletsWrapper_feature_div">製造元リファレンス : DASS-907</div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000NUM" in req_url:
            return True, html_detail
        query = _extract_search_query(req_url)
        queries.append(query)
        if query == numbered_title:
            return True, html_match
        return True, html_no_result

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.number = "DASS-907"
    pic_url = await get_big_pic_by_amazon(result, title, ["演员A"])

    assert pic_url == "https://m.media-amazon.com/images/I/81number.jpg"
    assert queries[0] == numbered_title


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_prefers_single_actor_candidate_over_multi_actor_candidate(
    monkeypatch: pytest.MonkeyPatch,
):
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000WRONG">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000WRONG"><span>作品标题 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000WRONG"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81wrong._AC_UL320_.jpg" />
        </div>
        <div data-component-type="s-search-result" data-asin="B000RIGHT">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000RIGHT"><span>作品标题 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000RIGHT"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81right._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_wrong_detail = """
    <html>
      <body>
        <span id="productTitle">作品标题 演员A</span>
        <div id="bylineInfo_feature_div">
          <a>演员A</a>
          <a>演员B</a>
        </div>
      </body>
    </html>
    """
    html_right_detail = """
    <html>
      <body>
        <span id="productTitle">作品标题 演员A</span>
        <div id="bylineInfo_feature_div">
          <a>演员A</a>
        </div>
      </body>
    </html>
    """

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000WRONG" in req_url:
            return True, html_wrong_detail
        if "/dp/B000RIGHT" in req_url:
            return True, html_right_detail
        return True, html_search

    async def fake_get_imgsize(url: str):
        if "81wrong" in url:
            return 1200, 1700
        if "81right" in url:
            return 801, 1200
        return 0, 0

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, "作品标题", ["演员A"])

    assert pic_url == "https://m.media-amazon.com/images/I/81right.jpg"


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_probes_candidates_lazily_until_first_hd_hit(
    monkeypatch: pytest.MonkeyPatch,
):
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000FIRST">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000FIRST"><span>标题测试 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000FIRST"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81first._AC_UL320_.jpg" />
        </div>
        <div data-component-type="s-search-result" data-asin="B000SECOND">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000SECOND"><span>标题测试 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000SECOND"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81second._AC_UL320_.jpg" />
        </div>
        <div data-component-type="s-search-result" data-asin="B000THIRD">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000THIRD"><span>标题测试 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000THIRD"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81third._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_detail = """
    <html>
      <body>
        <span id="productTitle">标题测试 演员A</span>
        <div id="bylineInfo_feature_div"><a>演员A</a></div>
      </body>
    </html>
    """
    probed_urls: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        if "/dp/" in req_url:
            return True, html_detail
        return True, html_search

    async def fake_get_imgsize(url: str):
        probed_urls.append(url)
        if "81first" in url:
            return 600, 900
        if "81second" in url:
            return 801, 1200
        pytest.fail(f"命中高清候选后不应继续探测: {url}")

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, "标题测试", ["演员A"])

    assert pic_url == "https://m.media-amazon.com/images/I/81second.jpg"
    assert probed_urls == [
        "https://m.media-amazon.com/images/I/81first.jpg",
        "https://m.media-amazon.com/images/I/81second.jpg",
    ]


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_prefers_verified_candidate_over_wider_unverified_candidate(
    monkeypatch: pytest.MonkeyPatch,
):
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000WRONG">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/s?keywords=wrong"><span>标题测试 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/s?keywords=wrong"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81wrongwide._AC_UL320_.jpg" />
        </div>
        <div data-component-type="s-search-result" data-asin="B000RIGHT">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000RIGHT"><span>标题测试 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000RIGHT"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81rightverified._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_right_detail = """
    <html>
      <body>
        <span id="productTitle">标题测试 演员A</span>
        <div id="bylineInfo_feature_div"><a>演员A</a></div>
      </body>
    </html>
    """
    probed_urls: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000RIGHT" in req_url:
            return True, html_right_detail
        return True, html_search

    async def fake_get_imgsize(url: str):
        probed_urls.append(url)
        if "81rightverified" in url:
            return 801, 1200
        if "81wrongwide" in url:
            pytest.fail(f"已验证候选命中高清后，不应再探测未验证宽图: {url}")
        return 0, 0

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, "标题测试", ["演员A"])

    assert pic_url == "https://m.media-amazon.com/images/I/81rightverified.jpg"
    assert probed_urls == ["https://m.media-amazon.com/images/I/81rightverified.jpg"]


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_prefers_dvd_over_bluray_for_same_work(monkeypatch: pytest.MonkeyPatch):
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000DVD">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000DVD"><span>标题测试 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000DVD"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81dvd._AC_UL320_.jpg" />
        </div>
        <div data-component-type="s-search-result" data-asin="B000BLURAY">
          <a class="a-text-bold">Blu-ray</a>
          <h2><a href="/dp/B000BLURAY"><span>标题测试 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000BLURAY"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81bluray2._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_detail = """
    <html>
      <body>
        <span id="productTitle">标题测试 演员A</span>
        <div id="bylineInfo_feature_div"><a>演员A</a></div>
        <div id="detailBulletsWrapper_feature_div">製造元リファレンス : ABC-123</div>
      </body>
    </html>
    """

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000DVD" in req_url or "/dp/B000BLURAY" in req_url:
            return True, html_detail
        return True, html_search

    async def fake_get_imgsize(url: str):
        if "81dvd" in url:
            return 801, 1200
        if "81bluray2" in url:
            return 1200, 1200
        return 0, 0

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.number = "ABC-123"
    pic_url = await get_big_pic_by_amazon(result, "标题测试", ["演员A"])

    assert pic_url == "https://m.media-amazon.com/images/I/81dvd.jpg"


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_barcode_fast_path_skips_title_search(monkeypatch: pytest.MonkeyPatch):
    barcode = "4550566395912"
    title = "作品标题 CJOD-486"
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000BARCODE">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000BARCODE"><span>作品标题 JULIA</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000BARCODE"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81barcode._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_detail = f"""
    <html>
      <body>
        <span id="productTitle">作品标题 JULIA</span>
        <div id="bylineInfo_feature_div"><a>JULIA</a></div>
        <div id="detailBulletsWrapper_feature_div">EAN : {barcode}</div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_try_get_amazon_barcodes_from_covers(_result: CrawlersResult):
        return [barcode]

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000BARCODE" in req_url:
            return True, html_detail
        query = _normalize_search_query(_extract_search_query(req_url))
        queries.append(query)
        assert query == barcode
        return True, html_search

    async def fake_get_imgsize(url: str):
        assert "81barcode" in url
        return 801, 1200

    monkeypatch.setattr(
        "mdcx.core.amazon.try_get_amazon_barcodes_from_covers", fake_try_get_amazon_barcodes_from_covers
    )
    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.number = "CJOD-486"

    pic_url = await get_big_pic_by_amazon(result, title, ["JULIA"])

    assert pic_url == "https://m.media-amazon.com/images/I/81barcode.jpg"
    assert queries == [barcode]


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_barcode_fast_path_prefers_dvd_over_bluray(monkeypatch: pytest.MonkeyPatch):
    barcode = "4550566395912"
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000DVD">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000DVD"><span>标题测试 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000DVD"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81dvdbarcode._AC_UL320_.jpg" />
        </div>
        <div data-component-type="s-search-result" data-asin="B000BLURAY">
          <a class="a-text-bold">Blu-ray</a>
          <h2><a href="/dp/B000BLURAY"><span>标题测试 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000BLURAY"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81bluraybarcode._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_detail = f"""
    <html>
      <body>
        <span id="productTitle">标题测试 演员A</span>
        <div id="bylineInfo_feature_div"><a>演员A</a></div>
        <div id="detailBulletsWrapper_feature_div">JAN：{barcode}</div>
      </body>
    </html>
    """

    async def fake_try_get_amazon_barcodes_from_covers(_result: CrawlersResult):
        return [barcode]

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000DVD" in req_url or "/dp/B000BLURAY" in req_url:
            return True, html_detail
        query = _normalize_search_query(_extract_search_query(req_url))
        assert query == barcode
        return True, html_search

    async def fake_get_imgsize(url: str):
        if "81dvdbarcode" in url:
            return 801, 1200
        if "81bluraybarcode" in url:
            return 1200, 1200
        return 0, 0

    monkeypatch.setattr(
        "mdcx.core.amazon.try_get_amazon_barcodes_from_covers", fake_try_get_amazon_barcodes_from_covers
    )
    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.number = "CJOD-486"

    pic_url = await get_big_pic_by_amazon(result, "标题测试", ["演员A"])

    assert pic_url == "https://m.media-amazon.com/images/I/81dvdbarcode.jpg"


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_barcode_fast_path_falls_back_to_title_search_when_no_result(
    monkeypatch: pytest.MonkeyPatch,
):
    barcode = "4550566395912"
    title = "标题测试 ABC-123"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_title_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000TITLE">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000TITLE"><span>标题测试 ABC-123 演员A</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000TITLE"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81titlefallback._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_detail = """
    <html>
      <body>
        <span id="productTitle">标题测试 ABC-123 演员A</span>
        <div id="bylineInfo_feature_div"><a>演员A</a></div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_try_get_amazon_barcodes_from_covers(_result: CrawlersResult):
        return [barcode]

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000TITLE" in req_url:
            return True, html_detail
        query = _normalize_search_query(_extract_search_query(req_url))
        queries.append(query)
        if query == barcode:
            return True, html_no_result
        if query == title:
            return True, html_title_search
        pytest.fail(f"未预期的搜索词: {query}")

    async def fake_get_imgsize(url: str):
        assert "81titlefallback" in url
        return 801, 1200

    monkeypatch.setattr(
        "mdcx.core.amazon.try_get_amazon_barcodes_from_covers", fake_try_get_amazon_barcodes_from_covers
    )
    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.number = "ABC-123"

    pic_url = await get_big_pic_by_amazon(result, title, ["演员A"])

    assert pic_url == "https://m.media-amazon.com/images/I/81titlefallback.jpg"
    assert queries == [barcode, title]


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_barcode_fast_path_tries_next_barcode_candidate(
    monkeypatch: pytest.MonkeyPatch,
):
    first_barcode = "1111111111111"
    second_barcode = "4550566395912"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000BARCODE2">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000BARCODE2"><span>作品标题 JULIA</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000BARCODE2"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81barcode2._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_detail = f"""
    <html>
      <body>
        <span id="productTitle">作品标题 JULIA</span>
        <div id="bylineInfo_feature_div"><a>JULIA</a></div>
        <div id="detailBulletsWrapper_feature_div">EAN : {second_barcode}</div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_try_get_amazon_barcodes_from_covers(_result: CrawlersResult):
        return [first_barcode, second_barcode]

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000BARCODE2" in req_url:
            return True, html_detail
        query = _normalize_search_query(_extract_search_query(req_url))
        queries.append(query)
        if query == first_barcode:
            return True, html_no_result
        if query == second_barcode:
            return True, html_search
        pytest.fail(f"未预期的搜索词: {query}")

    async def fake_get_imgsize(url: str):
        assert "81barcode2" in url
        return 801, 1200

    monkeypatch.setattr(
        "mdcx.core.amazon.try_get_amazon_barcodes_from_covers", fake_try_get_amazon_barcodes_from_covers
    )
    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.number = "CJOD-486"

    pic_url = await get_big_pic_by_amazon(result, "作品标题 CJOD-486", ["JULIA"])

    assert pic_url == "https://m.media-amazon.com/images/I/81barcode2.jpg"
    assert queries == [first_barcode, second_barcode]


@pytest.mark.asyncio
async def test_try_get_amazon_barcode_from_covers_logs_missing_detector(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "mdcx.core.amazon._get_amazon_barcode_detector_skip_reason",
        lambda: "当前环境缺少扫码依赖 opencv-contrib-python-headless",
    )

    LogBuffer.clear_task()
    result = CrawlersResult.empty()
    result.thumb_from = "DMM"
    result.thumb = "https://example.com/cover.jpg"

    barcode = await try_get_amazon_barcode_from_covers(result)

    logs = LogBuffer.log().get()
    LogBuffer.clear_task()

    assert barcode == ""
    assert "Amazon条码快路径：开始扫描封面条码" in logs
    assert "Amazon条码快路径跳过：当前环境缺少扫码依赖 opencv-contrib-python-headless" in logs


@pytest.mark.asyncio
async def test_try_get_amazon_barcode_from_covers_logs_ocr_fallback_hit(monkeypatch: pytest.MonkeyPatch):
    async def fake_get_content(_cover: str):
        return b"fake-image", ""

    monkeypatch.setattr(manager.computed.async_client, "get_content", fake_get_content)
    monkeypatch.setattr(
        "mdcx.core.amazon._detect_amazon_barcode_candidates_from_image_bytes_with_reason",
        lambda _content: (["4549831546432", "4549831546439"], "ocr_digits"),
    )

    LogBuffer.clear_task()
    result = CrawlersResult.empty()
    result.thumb_from = "dmm"
    result.thumb = "https://example.com/club00614pl.jpg"

    barcode = await try_get_amazon_barcode_from_covers(result)

    logs = LogBuffer.log().get()
    LogBuffer.clear_task()

    assert barcode == "4549831546432"
    assert "Amazon条码识别：OCR回退命中 EAN/JAN 4549831546432 (dmm) 候选2个" in logs


def test_beam_search_amazon_ean13_prefers_checksum_valid_candidate():
    target = "4549831546432"
    ranked_digits: list[list[tuple[float, str]]] = [[(0.95, digit), (0.90, "0")] for digit in target]
    ranked_digits[-1] = [(0.95, "0"), (0.90, target[-1])]

    assert _beam_search_amazon_ean13_from_ranked_digits(ranked_digits) == target


def test_extract_amazon_barcode_label_roi_finds_bright_label_under_barcode():
    image = np.full((220, 320), 25, dtype=np.uint8)
    image[150:198, 42:170] = 245
    points = np.array([[60, 188], [60, 158], [156, 158], [156, 188]], dtype=np.float32)

    label_roi = _extract_amazon_barcode_label_roi(image, points)

    assert label_roi is not None
    assert label_roi.shape[1] >= 100
    assert label_roi.shape[0] >= 40
    assert float(np.mean(label_roi)) > 200


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_logs_barcode_skip_before_title_fallback(monkeypatch: pytest.MonkeyPatch):
    title = "标题测试 ABC-123"
    html_no_result = """
    <html>
      <body>キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。</body>
    </html>
    """
    queries: list[str] = []

    async def fake_try_get_amazon_barcodes_from_covers(_result: CrawlersResult):
        return []

    async def fake_get_amazon_data(req_url: str):
        query = _normalize_search_query(_extract_search_query(req_url))
        queries.append(query)
        return True, html_no_result

    monkeypatch.setattr(
        "mdcx.core.amazon.try_get_amazon_barcodes_from_covers", fake_try_get_amazon_barcodes_from_covers
    )
    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)

    LogBuffer.clear_task()
    result = CrawlersResult.empty()
    result.number = "ABC-123"

    pic_url = await get_big_pic_by_amazon(result, title, ["演员A"])

    logs = LogBuffer.log().get()
    LogBuffer.clear_task()

    assert pic_url == ""
    assert queries[0] == title
    assert "Amazon条码快路径跳过：未获取到条码，回退标题搜索" in logs


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_supports_no_actor_when_detail_contains_number(monkeypatch: pytest.MonkeyPatch):
    title = "互いに素性を知った美魔女ママ友と箱ヘルで出逢い、裏引き不倫。"
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000NOACTOR">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000NOACTOR"><span>互いに素性を知った美魔女ママ友と箱ヘルで出逢い、裏引き不倫。</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000NOACTOR"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81noactor._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_detail = """
    <html>
      <body>
        <span id="productTitle">互いに素性を知った美魔女ママ友と箱ヘルで出逢い、裏引き不倫。</span>
        <div id="detailBulletsWrapper_feature_div">製造元リファレンス : DASS-907</div>
      </body>
    </html>
    """

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000NOACTOR" in req_url:
            return True, html_detail
        return True, html_search

    async def fake_get_imgsize(url: str):
        return 801, 1200

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    result.number = "DASS-907"
    pic_url = await get_big_pic_by_amazon(result, title, ["未知演员"])

    assert pic_url == "https://m.media-amazon.com/images/I/81noactor.jpg"


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_retries_actor_fragment_when_full_title_only_hits_actor_noise(
    monkeypatch: pytest.MonkeyPatch,
):
    title = "新人NO.1STYLE 枫ふうあAVデビュー"
    fragment = "枫ふうあAVデビュー"
    html_actor_noise = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000NOISE">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000NOISE"><span>枫ふうあ BEST SELECTION</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000NOISE"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81noise._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_fragment_match = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000FRAGMENT">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000FRAGMENT"><span>枫ふうあAVデビュー</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000FRAGMENT"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81fragment._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_noise_detail = """
    <html>
      <body>
        <span id="productTitle">枫ふうあ BEST SELECTION</span>
        <div id="bylineInfo_feature_div"><a>枫ふうあ</a></div>
      </body>
    </html>
    """
    html_fragment_detail = """
    <html>
      <body>
        <span id="productTitle">枫ふうあAVデビュー</span>
        <div id="bylineInfo_feature_div"><a>枫ふうあ</a></div>
      </body>
    </html>
    """
    queries: list[str] = []

    async def fake_get_amazon_data(req_url: str):
        if "/dp/B000NOISE" in req_url:
            return True, html_noise_detail
        if "/dp/B000FRAGMENT" in req_url:
            return True, html_fragment_detail
        query = _extract_search_query(req_url)
        queries.append(query)
        if query == title:
            return True, html_actor_noise
        if query == fragment:
            return True, html_fragment_match
        return True, "<html><body></body></html>"

    async def fake_get_imgsize(url: str):
        if "81fragment" in url:
            return 801, 1200
        if "81noise" in url:
            return 900, 1200
        return 0, 0

    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, title, ["枫ふうあ"])

    assert pic_url == "https://m.media-amazon.com/images/I/81fragment.jpg"
    assert fragment in queries
