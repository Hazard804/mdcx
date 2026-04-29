import pytest

from mdcx.config.enums import Language, Website
from mdcx.config.manager import manager
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.javlibrary import JavlibraryCrawler
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.models.types import CrawlerInput


class FakeJavlibraryClient:
    async def get_text(self, url, **kwargs):
        if url == "https://www.javlibrary.com/ja/vl_searchbyid.php?keyword=FSDSS-200":
            return _search_html("/ja/?v=javtest200", "FSDSS-200 Japanese Title"), ""
        if url == "https://www.javlibrary.com/ja/?v=javtest200":
            return _detail_html("FSDSS-200 Japanese Title", "女優A"), ""
        if url == "https://www.javlibrary.com/cn/?v=javtest200":
            return _detail_html("FSDSS-200 中文标题", "演员A"), ""
        return None, f"unexpected url: {url}"


def _search_html(href: str, title: str) -> str:
    return f"""
    <html><body>
      <a href="{href}" title="{title}"></a>
    </body></html>
    """


def _detail_html(title: str, actor: str) -> str:
    return f"""
    <html><body>
      <div id="video_title"><h3><a>{title}</a></h3></div>
      <div id="video_id"><table><tr><td class="text">FSDSS-200</td></tr></table></div>
      <div id="video_cast"><table><tr><td class="text"><span><span class="star"><a>{actor}</a></span></span></td></tr></table></div>
      <img id="video_jacket_img" src="//img.example.test/cover.jpg" />
      <div id="video_genres"><table><tr><td class="text"><span><a>剧情</a></span></td></tr></table></div>
      <div id="video_date"><table><tr><td class="text">2026-04-03</td></tr></table></div>
      <div id="video_maker"><table><tr><td class="text"><span><a>制作商</a></span></td></tr></table></div>
      <div id="video_label"><table><tr><td class="text"><span><a>发行商</a></span></td></tr></table></div>
      <div id="video_length"><table><tr><td><span class="text">120</span></td></tr></table></div>
      <div id="video_review"><table><tr><td><span class="score">(4.20)</span></td></tr></table></div>
      <div id="video_director"><table><tr><td class="text"><span><a>导演A</a></span></td></tr></table></div>
      <a href="userswanted.php?mode=add">99</a>
    </body></html>
    """


@pytest.mark.asyncio
async def test_javlibrary_crawler_keeps_jp_original_title_for_zh_cn():
    manager.config.set_field_language(CrawlerResultFields.TITLE, Language.ZH_CN)
    crawler = JavlibraryCrawler(client=FakeJavlibraryClient(), base_url="https://www.javlibrary.com")
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="FSDSS-200",
            short_number="FSDSS-200",
            language=Language.ZH_CN,
            org_language=Language.ZH_CN,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.debug_info.search_urls == ["https://www.javlibrary.com/ja/vl_searchbyid.php?keyword=FSDSS-200"]
    assert res.debug_info.detail_urls == [
        "https://www.javlibrary.com/ja/?v=javtest200",
        "https://www.javlibrary.com/cn/?v=javtest200",
    ]
    assert res.data.source == "javlibrary"
    assert res.data.number == "FSDSS-200"
    assert res.data.title == "中文标题"
    assert res.data.originaltitle == "Japanese Title"
    assert res.data.actors == ["演员A"]
    assert res.data.tags == ["剧情"]
    assert res.data.release == "2026-04-03"
    assert res.data.year == "2026"
    assert res.data.runtime == "120"
    assert res.data.score == "4.20"
    assert res.data.directors == ["导演A"]
    assert res.data.studio == "制作商"
    assert res.data.publisher == "发行商"
    assert res.data.thumb == "https://img.example.test/cover.jpg"
    assert res.data.wanted == "99"


def test_javlibrary_crawler_is_registered():
    assert get_crawler(Website.JAVLIBRARY) is JavlibraryCrawler
