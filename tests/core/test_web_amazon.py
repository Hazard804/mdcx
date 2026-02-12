import re
import urllib.parse

import pytest

from mdcx.core.web import get_big_pic_by_amazon
from mdcx.models.types import CrawlersResult


def _extract_search_query(req_url: str) -> str:
    match = re.search(r"returnUrl=/s\?k=([^&]+)", req_url)
    assert match is not None
    return urllib.parse.unquote_plus(urllib.parse.unquote_plus(match.group(1)))


def _normalize_search_query(query: str) -> str:
    return re.sub(r" \[(DVD|Blu-ray)\]$", "", query)


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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, title_with_actor, ["みなみ羽琉"])

    assert pic_url == "https://m.media-amazon.com/images/I/81strip.jpg"
    assert queries[0] == stripped_title


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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

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

    monkeypatch.setattr("mdcx.core.web.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.web.get_imgsize", fake_get_imgsize)

    result = CrawlersResult.empty()
    pic_url = await get_big_pic_by_amazon(result, "主标题 系列名", ["演员A"], "系列名")

    assert pic_url == "https://m.media-amazon.com/images/I/81title.jpg"
    assert queries[0] == "主标题 系列名"
    assert "系列名" in queries
    assert "主标题" in queries
    assert queries.index("系列名") < queries.index("主标题")
