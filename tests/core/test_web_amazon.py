import pytest

from mdcx.core.web import get_big_pic_by_amazon
from mdcx.models.types import CrawlersResult


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
