import pytest

from mdcx.crawlers.avbase_new import AvbaseCrawler


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("55", "55"),
        ("収録分数 55", "55"),
        ("収録分数 0:55:00", "55"),
        ("収録分数 00:55:00", "55"),
        ("収録分数 1:05:30", "65"),
        ("収録分数 0:00:30", "1"),
    ],
)
def test_parse_runtime(raw: str, expected: str):
    assert AvbaseCrawler._parse_runtime(raw) == expected
