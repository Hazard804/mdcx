import pytest

from mdcx.utils import add_html_plain_text, clean_list, collapse_inline_script_splits
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


def test_collapse_inline_script_splits_recovers_streamed_text():
    text = 'https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=dvdms674/?i3_"])</script><script>self.__next_f.push([1,"ref=search\\u0026i3_ord=6'
    assert (
        collapse_inline_script_splits(text)
        == "https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=dvdms674/?i3_ref=search\\u0026i3_ord=6"
    )


def test_add_html_plain_text_escapes_script_like_content_and_keeps_full_message():
    text = (
        'GET https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=dvdms674/?i3_"])'
        '</script><script>self.__next_f.push([1,"ref=search&i3_ord=6'
    )
    rendered = add_html_plain_text(text)

    assert "&lt;/script&gt;&lt;script&gt;" in rendered
    assert "self.__next_f.push([1,&quot;ref=search&amp;i3_ord=6" in rendered
    assert '<a href="https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=dvdms674/?i3_' in rendered


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
