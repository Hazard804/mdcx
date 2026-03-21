from mdcx.web_async import AsyncWebClient


def test_sanitize_url_recovers_split_scheme():
    client = AsyncWebClient(timeout=1)
    cleaned, sanitized = client._sanitize_url(
        'https"])</script><script>self.__next_f.push([1,"://www.dmm.co.jp/monthly/premium/-/detail/=/cid=dvdms00674/?i3_ref=search&i3_ord=4'
    )

    assert sanitized is True
    assert cleaned == "https://www.dmm.co.jp/monthly/premium/-/detail/=/cid=dvdms00674/?i3_ref=search&i3_ord=4"


def test_sanitize_url_recovers_split_query():
    client = AsyncWebClient(timeout=1)
    cleaned, sanitized = client._sanitize_url(
        'https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=dvdms674/?i3_"])</script><script>self.__next_f.push([1,"ref=search&i3_ord=6'
    )

    assert sanitized is True
    assert cleaned == "https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=dvdms674/?i3_ref=search&i3_ord=6"


def test_sanitize_url_keeps_unfixable_text_unchanged():
    client = AsyncWebClient(timeout=1)
    cleaned, sanitized = client._sanitize_url('not-a-url"])</script><script>self.__next_f.push([1,"still-not-url')

    assert sanitized is False
    assert cleaned == 'not-a-url"])</script><script>self.__next_f.push([1,"still-not-url'
