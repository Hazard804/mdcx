import asyncio
import random
from types import SimpleNamespace

import pytest

from mdcx.web_async import AsyncWebClient


def _fake_response(
    *,
    status_code: int,
    headers: dict[str, str] | None = None,
    content: bytes = b"ok",
    url: str = "",
):
    return SimpleNamespace(status_code=status_code, headers=headers or {}, content=content, url=url)


def _default_try_kwargs():
    return {
        "method": "GET",
        "headers": {},
        "cookies": None,
        "data": None,
        "json_data": None,
        "timeout": None,
        "allow_redirects": True,
        "use_proxy": False,
    }


@pytest.mark.asyncio
async def test_try_bypass_cloudflare_throttles_concurrent_attempts_without_failing():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    client._cf_bypass_min_interval = 0.02
    host = "missav.ws"

    call_count = 0

    async def fake_call_bypass_mirror(**kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_response(status_code=200, content=b"<html>ok</html>"), ""

    client._call_bypass_mirror = fake_call_bypass_mirror  # type: ignore[method-assign]

    tasks = [
        client._try_bypass_cloudflare(
            host=host,
            target_url="https://missav.ws/SNOS-001/cn",
            **_default_try_kwargs(),
        )
        for _ in range(3)
    ]
    results = await asyncio.gather(*tasks)

    assert call_count == 3
    success_count = sum(1 for response, error in results if response is not None and error == "")
    assert success_count == 3


@pytest.mark.asyncio
async def test_try_bypass_cloudflare_waits_internally_during_cooldown():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    client._cf_bypass_min_interval = 0.05
    host = "missav.ws"

    call_count = 0

    async def fake_call_bypass_mirror(**kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_response(status_code=200, content=b"<html>ok</html>"), ""

    client._call_bypass_mirror = fake_call_bypass_mirror  # type: ignore[method-assign]

    first_response, first_error = await client._try_bypass_cloudflare(
        host=host,
        target_url="https://missav.ws/SNOS-002/cn",
        **_default_try_kwargs(),
    )
    start = asyncio.get_running_loop().time()
    second_response, second_error = await client._try_bypass_cloudflare(
        host=host,
        target_url="https://missav.ws/SNOS-002/cn",
        **_default_try_kwargs(),
    )
    elapsed = asyncio.get_running_loop().time() - start

    assert first_error == ""
    assert first_response is not None
    assert second_error == ""
    assert second_response is not None
    assert elapsed >= 0.04
    assert call_count == 2


@pytest.mark.asyncio
async def test_call_bypass_html_uses_html_endpoint_and_params_and_sets_final_url():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    captured: dict[str, object] = {}

    async def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return (
            _fake_response(
                status_code=200,
                content=b"<html>ok</html>",
                headers={
                    "x-cf-bypasser-final-url": "https://missav.ws/dm2/SNOS-003/cn",
                },
            ),
            "",
        )

    client.request = fake_request  # type: ignore[method-assign]

    response, error = await client._call_bypass_html("https://missav.ws/SNOS-003/cn", use_proxy=False)

    assert error == ""
    assert response is not None
    assert captured["method"] == "GET"
    assert captured["url"] == "http://127.0.0.1:8000/html"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["params"] == {"url": "https://missav.ws/SNOS-003/cn"}
    assert kwargs["enable_cf_bypass"] is False
    assert response.url == "https://missav.ws/dm2/SNOS-003/cn"
    assert response.headers.get("x-mdcx-bypass-mode") == "html"


@pytest.mark.asyncio
async def test_call_bypass_html_appends_proxy_param_when_configured():
    client = AsyncWebClient(
        timeout=1,
        cf_bypass_url="http://127.0.0.1:8000",
        cf_bypass_proxy="http://127.0.0.1:7890",
    )
    captured: dict[str, object] = {}

    async def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _fake_response(status_code=200, content=b"<html>ok</html>", headers={}), ""

    client.request = fake_request  # type: ignore[method-assign]

    response, error = await client._call_bypass_html("https://missav.ws/SNOS-010/cn", use_proxy=True)

    assert error == ""
    assert response is not None
    assert captured["method"] == "GET"
    assert captured["url"] == "http://127.0.0.1:8000/html"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["params"] == {
        "url": "https://missav.ws/SNOS-010/cn",
        "proxy": "http://127.0.0.1:7890",
    }
    assert kwargs["use_proxy"] is False
    assert kwargs["enable_cf_bypass"] is False


@pytest.mark.asyncio
async def test_call_bypass_html_appends_bypass_cache_param_when_forced():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    captured: dict[str, object] = {}

    async def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _fake_response(status_code=200, content=b"<html>ok</html>", headers={}), ""

    client.request = fake_request  # type: ignore[method-assign]

    response, error = await client._call_bypass_html(
        "https://missav.ws/SNOS-013/cn",
        use_proxy=False,
        bypass_cache=True,
    )

    assert error == ""
    assert response is not None
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["params"] == {
        "url": "https://missav.ws/SNOS-013/cn",
        "bypassCookieCache": "true",
    }


@pytest.mark.asyncio
async def test_call_bypass_mirror_returns_error_on_http_status():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")

    async def fake_request(method, url, **kwargs):
        return _fake_response(status_code=404, headers={"Content-Type": "text/html"}, content=b"not found")

    client.curl_session.request = fake_request  # type: ignore[method-assign]

    response, error = await client._call_bypass_mirror(
        method="GET",
        target_url="https://missav.ws/SNOS-404/cn",
        headers={"Accept": "text/html"},
        cookies=None,
        use_proxy=False,
        allow_redirects=True,
    )

    assert response is None
    assert error == "mirror HTTP 404"


@pytest.mark.asyncio
async def test_call_bypass_mirror_follows_redirect_and_updates_final_url():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    captured_calls: list[tuple[str, dict[str, str]]] = []

    async def fake_request(method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        captured_calls.append((url, headers))
        if url.endswith("/hmgl-183/cn") and "/dm18/" not in url:
            return _fake_response(
                status_code=301,
                headers={"Location": "https://missav.ws/dm18/hmgl-183/cn", "Content-Type": "text/html"},
                content=b"",
            )
        return _fake_response(status_code=200, headers={"Content-Type": "text/html"}, content=b"<html>ok</html>")

    client.curl_session.request = fake_request  # type: ignore[method-assign]

    response, error = await client._call_bypass_mirror(
        method="GET",
        target_url="https://missav.ws//hmgl-183/cn",
        headers={"Accept": "text/html"},
        cookies={"sessionid": "abc"},
        use_proxy=False,
        allow_redirects=True,
    )

    assert error == ""
    assert response is not None
    assert len(captured_calls) == 2
    assert captured_calls[0][0] == "http://127.0.0.1:8000/hmgl-183/cn"
    assert captured_calls[1][0] == "http://127.0.0.1:8000/dm18/hmgl-183/cn"
    assert captured_calls[0][1].get("x-hostname") == "missav.ws"
    assert "sessionid=abc" in captured_calls[0][1].get("Cookie", "")
    assert response.url == "https://missav.ws/dm18/hmgl-183/cn"
    assert response.headers.get("x-mdcx-bypass-mode") == "mirror"


@pytest.mark.asyncio
async def test_call_bypass_mirror_sets_x_proxy_header_when_enabled():
    client = AsyncWebClient(
        timeout=1,
        cf_bypass_url="http://127.0.0.1:8000",
        cf_bypass_proxy="http://127.0.0.1:7890",
    )
    captured_headers: dict[str, str] = {}

    async def fake_request(method, url, **kwargs):
        nonlocal captured_headers
        captured_headers = dict(kwargs.get("headers") or {})
        return _fake_response(status_code=200, headers={"Content-Type": "text/html"}, content=b"<html>ok</html>")

    client.curl_session.request = fake_request  # type: ignore[method-assign]

    response, error = await client._call_bypass_mirror(
        method="GET",
        target_url="https://missav.ws/SNOS-011/cn",
        headers={"Accept": "text/html"},
        cookies=None,
        use_proxy=True,
        allow_redirects=True,
    )

    assert error == ""
    assert response is not None
    assert captured_headers.get("x-hostname") == "missav.ws"
    assert captured_headers.get("x-proxy") == "http://127.0.0.1:7890"


@pytest.mark.asyncio
async def test_call_bypass_mirror_sets_x_bypass_cache_header_when_forced():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    captured_headers: dict[str, str] = {}

    async def fake_request(method, url, **kwargs):
        nonlocal captured_headers
        captured_headers = dict(kwargs.get("headers") or {})
        return _fake_response(status_code=200, headers={"Content-Type": "text/html"}, content=b"<html>ok</html>")

    client.curl_session.request = fake_request  # type: ignore[method-assign]

    response, error = await client._call_bypass_mirror(
        method="GET",
        target_url="https://missav.ws/SNOS-014/cn",
        headers={"Accept": "text/html"},
        cookies=None,
        use_proxy=False,
        bypass_cache=True,
        allow_redirects=True,
    )

    assert error == ""
    assert response is not None
    assert captured_headers.get("x-bypass-cache") == "true"


@pytest.mark.asyncio
async def test_try_bypass_cloudflare_fallbacks_to_html_when_mirror_failed():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")

    mirror_call_count = 0
    html_call_count = 0

    async def fake_call_bypass_mirror(**kwargs):
        nonlocal mirror_call_count
        mirror_call_count += 1
        return None, "mirror failed"

    async def fake_call_bypass_html(target_url: str, *, use_proxy: bool, bypass_cache: bool = False):
        nonlocal html_call_count
        html_call_count += 1
        return _fake_response(status_code=200, content=b"<html>ok</html>"), ""

    client._call_bypass_mirror = fake_call_bypass_mirror  # type: ignore[method-assign]
    client._call_bypass_html = fake_call_bypass_html  # type: ignore[method-assign]

    response, error = await client._try_bypass_cloudflare(
        host="missav.ws",
        target_url="https://missav.ws/SNOS-005/cn",
        **_default_try_kwargs(),
    )

    assert error == ""
    assert response is not None
    assert mirror_call_count == 1
    assert html_call_count == 1


@pytest.mark.asyncio
async def test_try_bypass_cloudflare_force_refresh_mirror_before_html_fallback():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    mirror_bypass_cache_flags: list[bool] = []
    html_bypass_cache_flags: list[bool] = []

    async def fake_call_bypass_mirror(**kwargs):
        mirror_bypass_cache_flags.append(bool(kwargs.get("bypass_cache")))
        return None, "mirror 返回 Cloudflare 挑战页"

    async def fake_call_bypass_html(target_url: str, *, use_proxy: bool, bypass_cache: bool = False):
        html_bypass_cache_flags.append(bypass_cache)
        return _fake_response(status_code=200, content=b"<html>ok</html>"), ""

    client._call_bypass_mirror = fake_call_bypass_mirror  # type: ignore[method-assign]
    client._call_bypass_html = fake_call_bypass_html  # type: ignore[method-assign]

    response, error = await client._try_bypass_cloudflare(
        host="javdb.com",
        target_url="https://javdb.com/search?q=SNOS-040&locale=zh",
        **_default_try_kwargs(),
    )

    assert error == ""
    assert response is not None
    assert mirror_bypass_cache_flags == [False, True]
    assert html_bypass_cache_flags == [False]


@pytest.mark.asyncio
async def test_try_bypass_cloudflare_skips_html_fallback_for_terminal_mirror_http_status():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")

    mirror_call_count = 0
    html_call_count = 0

    async def fake_call_bypass_mirror(**kwargs):
        nonlocal mirror_call_count
        mirror_call_count += 1
        return None, "mirror HTTP 404"

    async def fake_call_bypass_html(target_url: str, *, use_proxy: bool, bypass_cache: bool = False):
        nonlocal html_call_count
        html_call_count += 1
        return _fake_response(status_code=200, content=b"<html>ok</html>"), ""

    client._call_bypass_mirror = fake_call_bypass_mirror  # type: ignore[method-assign]
    client._call_bypass_html = fake_call_bypass_html  # type: ignore[method-assign]

    response, error = await client._try_bypass_cloudflare(
        host="missav.ws",
        target_url="https://missav.ws/SNOS-404/cn",
        **_default_try_kwargs(),
    )

    assert response is None
    assert "mirror 返回终态 HTTP 404，跳过 /html 回退" in error
    assert mirror_call_count == 1
    assert html_call_count == 0


@pytest.mark.asyncio
async def test_try_bypass_cloudflare_non_get_does_not_fallback_to_html():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    client._cf_bypass_retries = 1

    async def fake_call_bypass_mirror(**kwargs):
        return None, "mirror failed"

    client._call_bypass_mirror = fake_call_bypass_mirror  # type: ignore[method-assign]

    response, error = await client._try_bypass_cloudflare(
        host="missav.ws",
        method="HEAD",
        target_url="https://missav.ws/SNOS-006/cn",
        headers={},
        cookies=None,
        data=None,
        json_data=None,
        timeout=None,
        allow_redirects=True,
        use_proxy=False,
    )

    assert response is None
    assert "HEAD 不支持 /html 兜底" in error


@pytest.mark.asyncio
async def test_try_bypass_cloudflare_second_retry_forces_bypass_cache():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    client._cf_bypass_retries = 2

    bypass_cache_flags: list[bool] = []

    async def fake_call_bypass_mirror(**kwargs):
        bypass_cache_flags.append(bool(kwargs.get("bypass_cache")))
        if len(bypass_cache_flags) == 1:
            return None, "mirror failed"
        return _fake_response(status_code=200, content=b"<html>ok</html>"), ""

    client._call_bypass_mirror = fake_call_bypass_mirror  # type: ignore[method-assign]

    response, error = await client._try_bypass_cloudflare(
        host="missav.ws",
        method="HEAD",
        target_url="https://missav.ws/SNOS-015/cn",
        headers={},
        cookies=None,
        data=None,
        json_data=None,
        timeout=None,
        allow_redirects=True,
        use_proxy=False,
    )

    assert error == ""
    assert response is not None
    assert bypass_cache_flags == [False, True]


@pytest.mark.asyncio
async def test_request_returns_bypass_response_when_cf_challenge_hit():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    host = "missav.ws"

    call_count = 0

    async def fake_curl_request(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_response(
            status_code=503,
            headers={"Content-Type": "text/html", "server": "cloudflare", "cf-ray": "abc"},
            content=b"<html>just a moment cf-chl</html>",
        )

    client.curl_session.request = fake_curl_request  # type: ignore[method-assign]

    bypass_response = _fake_response(
        status_code=200,
        headers={"Content-Type": "text/html", "x-mdcx-bypass-mode": "mirror"},
        content=b"<html>bypass</html>",
    )

    async def fake_try_bypass_cloudflare(**kwargs):
        return bypass_response, ""

    client._try_bypass_cloudflare = fake_try_bypass_cloudflare  # type: ignore[method-assign]

    response, error = await client.request("GET", f"https://{host}/SNOS-007/cn")

    assert error == ""
    assert response is bypass_response
    assert call_count == 1


@pytest.mark.asyncio
async def test_request_enables_bypass_proxy_when_configured():
    client = AsyncWebClient(
        timeout=1,
        cf_bypass_url="http://127.0.0.1:8000",
        cf_bypass_proxy="http://127.0.0.1:7890",
    )
    host = "missav.ws"

    async def fake_curl_request(method, url, **kwargs):
        return _fake_response(
            status_code=503,
            headers={"Content-Type": "text/html", "server": "cloudflare", "cf-ray": "abc"},
            content=b"<html>just a moment cf-chl</html>",
        )

    client.curl_session.request = fake_curl_request  # type: ignore[method-assign]

    captured_use_proxy: bool | None = None
    bypass_response = _fake_response(
        status_code=200,
        headers={"Content-Type": "text/html", "x-mdcx-bypass-mode": "mirror"},
        content=b"<html>bypass</html>",
    )

    async def fake_try_bypass_cloudflare(**kwargs):
        nonlocal captured_use_proxy
        captured_use_proxy = kwargs.get("use_proxy")
        return bypass_response, ""

    client._try_bypass_cloudflare = fake_try_bypass_cloudflare  # type: ignore[method-assign]

    response, error = await client.request("GET", f"https://{host}/SNOS-012/cn")

    assert error == ""
    assert response is bypass_response
    assert captured_use_proxy is True


@pytest.mark.asyncio
async def test_request_retries_when_bypass_failed(monkeypatch):
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    client.retry = 2
    host = "missav.ws"

    async def fake_try_bypass_cloudflare(**kwargs):
        return None, "bypass cooling down"

    client._try_bypass_cloudflare = fake_try_bypass_cloudflare  # type: ignore[method-assign]

    call_count = 0

    async def fake_curl_request(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _fake_response(
                status_code=503,
                headers={"Content-Type": "text/html", "server": "cloudflare", "cf-ray": "abc"},
                content=b"<html>just a moment cf-chl</html>",
            )
        return _fake_response(
            status_code=200,
            headers={"Content-Type": "text/html"},
            content=b"ok",
        )

    client.curl_session.request = fake_curl_request  # type: ignore[method-assign]

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0.5)

    response, error = await client.request("GET", f"https://{host}/SNOS-008/cn")

    assert error == ""
    assert response is not None
    assert call_count == 2
    assert sleep_calls == [2.5]


@pytest.mark.asyncio
async def test_request_stops_retry_when_bypass_failed_with_terminal_status(monkeypatch):
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    client.retry = 5
    host = "missav.ws"

    async def fake_try_bypass_cloudflare(**kwargs):
        return None, "mirror 返回终态 HTTP 404，跳过 /html 回退"

    client._try_bypass_cloudflare = fake_try_bypass_cloudflare  # type: ignore[method-assign]

    call_count = 0

    async def fake_curl_request(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_response(
            status_code=503,
            headers={"Content-Type": "text/html", "server": "cloudflare", "cf-ray": "abc"},
            content=b"<html>just a moment cf-chl</html>",
        )

    client.curl_session.request = fake_curl_request  # type: ignore[method-assign]

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    response, error = await client.request("GET", f"https://{host}/SNOS-404/cn")

    assert response is None
    assert "终态 HTTP 404" in error
    assert call_count == 1
    assert sleep_calls == []


@pytest.mark.asyncio
async def test_request_stops_retry_when_bypass_failed_with_http_terminal_status(monkeypatch):
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    client.retry = 5
    host = "missav.ws"

    async def fake_try_bypass_cloudflare(**kwargs):
        return None, "HTTP 404"

    client._try_bypass_cloudflare = fake_try_bypass_cloudflare  # type: ignore[method-assign]

    call_count = 0

    async def fake_curl_request(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_response(
            status_code=503,
            headers={"Content-Type": "text/html", "server": "cloudflare", "cf-ray": "abc"},
            content=b"<html>just a moment cf-chl</html>",
        )

    client.curl_session.request = fake_curl_request  # type: ignore[method-assign]

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    response, error = await client.request("GET", f"https://{host}/SNOS-404/cn")

    assert response is None
    assert "HTTP 404" in error
    assert call_count == 1
    assert sleep_calls == []


@pytest.mark.asyncio
async def test_request_acquires_limiter_for_each_attempt(monkeypatch):
    client = AsyncWebClient(timeout=1, cf_bypass_url="")
    client.retry = 3

    acquire_count = 0

    class FakeLimiter:
        async def acquire(self):
            nonlocal acquire_count
            acquire_count += 1

    class FakeLimiters:
        def get(self, key):
            return FakeLimiter()

    client.limiters = FakeLimiters()  # type: ignore[assignment]

    call_count = 0

    async def fake_curl_request(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_response(
            status_code=503,
            headers={"Content-Type": "text/html"},
            content=b"busy",
        )

    client.curl_session.request = fake_curl_request  # type: ignore[method-assign]

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0.0)

    response, error = await client.request("GET", "https://missav.ws/SNOS-009/cn")

    assert response is None
    assert "HTTP 503" in error
    assert call_count == 3
    assert acquire_count == 3
    assert sleep_calls == [2.0, 5.0]
