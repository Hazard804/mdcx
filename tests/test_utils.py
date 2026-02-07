import pytest

from mdcx.utils import clean_list
from mdcx.utils.language import is_english, is_japanese, is_probably_english_for_translation


@pytest.mark.parametrize(
    "s,expected",
    [
        ("", False),
        ("こんにちは", True),
        ("カタカナ", True),
        ("abc123", False),
        ("テスト123", True),
        ("Hello世界", False),
    ],
)
def test_is_japanese(s, expected):
    assert is_japanese(s) == expected


@pytest.mark.parametrize(
    "s,expected",
    [
        ("", False),
        ("Hello, world!", True),
        ("1234567890", True),
        ("This is a test.", True),
        ("こんにちは", False),
        ("テスト123", False),
        ("中文", False),
        ("abc@#%&*()", True),
        ("abc中文", False),
    ],
)
def test_is_english(s, expected):
    assert is_english(s) == expected


@pytest.mark.parametrize(
    "s,expected",
    [
        ("a,b,a,c", "a,b,c"),
        ("a,b,c", "a,b,c"),
        (" a ,b, a,c ", "a,b,c"),
        ("", ""),
        ("a,,b", "a,b"),
        ("A,a,B,b", "A,a,B,b"),
    ],
)
def test_clean_list(s, expected):
    assert clean_list(s) == expected


@pytest.mark.parametrize(
    "s,expected",
    [
        ("", False),
        ("Youngermommy.24.11.09", True),
        ("Ricky Spanish is on the phone with his friend.", True),
        ("Scarlett’s fantasy gets wild — and explicit.", True),
        ("これは日本語の文章です。", False),
        ("中文简介内容", False),
        ("abc 中文 mixed", False),
    ],
)
def test_is_probably_english_for_translation(s, expected):
    assert is_probably_english_for_translation(s) == expected
