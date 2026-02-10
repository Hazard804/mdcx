from lxml import etree

from mdcx.crawlers.mmtv import get_outline, get_title


def _build_detail_html():
    html = """
    <html>
      <body>
        <h1 class="fullvideo-title h5 mb-2">
          200GANA-3327 第一段標題
          第二段標題 2259
        </h1>
        <article>
          <div class="video-introduction-images-text">
            <p><p>第一行<br>第二行<br>第三行</p></p>
          </div>
        </article>
      </body>
    </html>
    """
    return etree.fromstring(html, etree.HTMLParser())


def test_get_title_with_multiline_text():
    html = _build_detail_html()
    title = get_title(html, "200GANA-3327")
    assert title == "第一段標題 第二段標題 2259"


def test_get_outline_with_nested_paragraph_and_br():
    html = _build_detail_html()
    outline, originalplot = get_outline(html)
    expected = "第一行\n第二行\n第三行"
    assert outline == expected
    assert originalplot == expected
