from lxml import etree

from mdcx.crawlers.javbus import getRelease, getValidRelease, getYear


def _build_html(release: str):
    html = f"""
    <html>
      <body>
        <p><span class="header">發行日期:</span> {release}</p>
      </body>
    </html>
    """
    return etree.fromstring(html, etree.HTMLParser())


def test_get_valid_release_and_year():
    assert getValidRelease("2024-1-2") == "2024-01-02"
    assert getYear("2024-1-2") == "2024"


def test_get_release_placeholder_date_returns_invalid():
    html = _build_html("0000-00-00")
    release = getRelease(html)
    assert release == "0000-00-00"
    assert getValidRelease(release) == ""
    assert getYear(release) == ""
