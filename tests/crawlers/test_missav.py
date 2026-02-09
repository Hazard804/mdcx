import pytest
from parsel import Selector

from mdcx.crawlers.missav import MissavCrawler


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("MIDV-999-U", "midv-999"),
        ("MIDV-0999-UC", "midv-999"),
        ("MIDV999U", "midv-999"),
        ("010101-123-U", "010101-123"),
    ],
)
def test_normalize_number_for_uncensored_judge(number: str, expected: str):
    assert MissavCrawler._normalize_number_for_uncensored_judge(number) == expected


@pytest.mark.parametrize(
    ("number", "mosaic", "expected"),
    [
        ("MIDV-999-U", "无码破解", False),
        ("MIDV-999-UC", "无码", False),
        ("MIDV-999", "无码", False),
        ("HEYZO-1234-U", "有码", True),
        ("010101-123-U", "有码", True),
    ],
)
def test_should_use_uncensored_search_by_original_number(number: str, mosaic: str, expected: bool):
    assert MissavCrawler._should_use_uncensored_search(number, mosaic) is expected


def test_is_soft_404_page_detects_not_found_template():
    html = Selector(
        text="""
        <html>
            <head>
                <meta property="og:title" content="MissAV | 免費高清AV在線看" />
                <meta property="og:image" content="https://missav.ws/missav/logo-square.png" />
                <title>MissAV | 免費高清AV在線看</title>
            </head>
            <body>
                <p>404</p>
                <h1>找不到頁面</h1>
            </body>
        </html>
        """
    )

    assert MissavCrawler._is_soft_404_page(html) is True


def test_is_soft_404_page_ignores_normal_detail_page():
    html = Selector(
        text="""
        <html>
            <head>
                <meta property="og:title" content="SNOS-004 絶頂快感 - MissAV" />
                <meta property="og:image" content="https://fourhoi.com/snos-004/cover-n.jpg" />
                <title>SNOS-004 絶頂快感 - MissAV</title>
            </head>
            <body>
                <h1>SNOS-004 絶頂快感</h1>
                <p>發行日期：2024-01-01</p>
            </body>
        </html>
        """
    )

    assert MissavCrawler._is_soft_404_page(html) is False
