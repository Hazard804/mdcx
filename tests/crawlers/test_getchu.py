from lxml import etree

from mdcx.crawlers.getchu import get_attestation_continue_url, get_extrafanart, get_title, normalize_detail_url


def test_normalize_detail_url_converts_legacy_soft_url():
    url = "http://www.getchu.com/soft.phtml?id=1355679&gc=gc"
    assert normalize_detail_url(url) == "https://www.getchu.com/item/1355679/?gc=gc"


def test_get_attestation_continue_url_reads_continue_link():
    html = etree.fromstring(
        """
        <html>
          <body>
            <h1>年齢認証ページ</h1>
            <table>
              <tr>
                <td><a href="https://www.getchu.com/item/1355679/?gc=gc">【すすむ】</a></td>
              </tr>
            </table>
          </body>
        </html>
        """,
        etree.HTMLParser(),
    )

    assert get_attestation_continue_url(html) == "https://www.getchu.com/item/1355679/?gc=gc"


def test_get_title_falls_back_to_og_title():
    html = etree.fromstring(
        """
        <html>
          <head>
            <meta property="og:title" content="OVA シスターブリーダー ＃4  | ばにぃうぉ〜か〜" />
          </head>
          <body></body>
        </html>
        """,
        etree.HTMLParser(),
    )

    assert get_title(html) == "OVA シスターブリーダー ＃4"


def test_get_extrafanart_supports_new_item_samplecard_structure():
    html = etree.fromstring(
        """
        <html>
          <body>
            <div class="item-Samplecard-container">
              <div class="item-Samplecard">
                <a class="highslide" href="/brandnew/1355679/c1355679sample1.jpg"></a>
              </div>
              <div class="item-Samplecard">
                <a class="highslide" href="/brandnew/1355679/c1355679sample2.jpg"></a>
              </div>
            </div>
          </body>
        </html>
        """,
        etree.HTMLParser(),
    )

    assert get_extrafanart(html) == [
        "https://www.getchu.com/brandnew/1355679/c1355679sample1.jpg",
        "https://www.getchu.com/brandnew/1355679/c1355679sample2.jpg",
    ]
