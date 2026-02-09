import pytest

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
