from lxml import etree

from mdcx.crawlers import fc2hub


def _parse_html(text: str):
    return etree.fromstring(text, etree.HTMLParser())


def test_fc2hub_get_trailer_video_id_from_embed_iframe():
    html = _parse_html(
        """
        <html>
            <body>
                <iframe data-src="https://contents.fc2.com/embed/4866909?i=TXpjd01Ua3hORGc9&ref=fc2"></iframe>
            </body>
        </html>
        """
    )

    assert fc2hub.getTrailerVideoId(html, "0000000") == "4866909"


def test_fc2hub_get_trailer_video_id_from_player_api():
    html = _parse_html(
        """
        <html>
            <body>
                <div class="player-api" data-id="4866909"></div>
            </body>
        </html>
        """
    )

    assert fc2hub.getTrailerVideoId(html, "0000000") == "4866909"


def test_fc2hub_get_trailer_video_id_falls_back_to_number():
    html = _parse_html("<html><body><div></div></body></html>")

    assert fc2hub.getTrailerVideoId(html, "4866909") == "4866909"
