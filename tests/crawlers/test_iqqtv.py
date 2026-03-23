from lxml import etree

from mdcx.crawlers.iqqtv import getOutline


def _build_detail_html(label: str, body_html: str):
    html = f"""
    <html>
      <body>
        <div class="intro bd-light w-100 mt-1">
          <p>{label}：{body_html}</p>
        </div>
      </body>
    </html>
    """
    return etree.fromstring(html, etree.HTMLParser())


def test_get_outline_supports_japanese_intro_label():
    html = _build_detail_html("紹介", "第一段內容")
    assert getOutline(html) == "第一段內容"


def test_get_outline_reads_nested_intro_content():
    html = _build_detail_html("紹介", "<span>第一行</span><br>第二行")
    assert getOutline(html) == "第一行第二行"


def test_get_outline_removes_distribution_notice():
    html = _build_detail_html("简介", "第一段內容*根据分发方式,内容可能会有所不同")
    assert getOutline(html) == "第一段內容"
