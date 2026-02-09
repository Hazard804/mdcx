import asyncio
import random
import time
from types import SimpleNamespace

import pytest

from mdcx.web_async import AsyncWebClient


@pytest.mark.asyncio
async def test_cf_bypass_singleflight_reuses_recent_cookies():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")

    call_count = 0

    async def fake_call_bypass_cookies(target_url: str, *, force_refresh: bool, use_proxy: bool):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.03)
        return {"cf_clearance": "token-1", "foo": "bar"}, "ua-test", ""

    client._call_bypass_cookies = fake_call_bypass_cookies  # type: ignore[method-assign]

    tasks = [
        client._try_bypass_cloudflare(
            host="missav.ws",
            target_url="https://missav.ws/SNOS-001/cn",
            use_proxy=False,
        )
        for _ in range(20)
    ]
    results = await asyncio.gather(*tasks)

    assert call_count == 1
    for cookies, user_agent, error in results:
        assert error == ""
        assert cookies.get("cf_clearance") == "token-1"
        assert user_agent == "ua-test"


@pytest.mark.asyncio
async def test_cf_bypass_force_refresh_is_throttled_after_recent_refresh():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    host = "missav.ws"
    client._cf_host_cookies[host] = {"cf_clearance": "cached-token"}
    client._cf_host_user_agents[host] = "ua-cached"
    client._cf_last_refresh_at[host] = time.monotonic()
    client._cf_host_challenge_hits[host] = 7

    call_count = 0

    async def fake_call_bypass_cookies(target_url: str, *, force_refresh: bool, use_proxy: bool):
        nonlocal call_count
        call_count += 1
        return {"cf_clearance": "new-token"}, "ua-new", ""

    client._call_bypass_cookies = fake_call_bypass_cookies  # type: ignore[method-assign]

    cookies, user_agent, error = await client._try_bypass_cloudflare(
        host=host,
        target_url="https://missav.ws/SNOS-002/cn",
        use_proxy=False,
        force_refresh=True,
    )

    assert error == ""
    assert call_count == 0
    assert cookies.get("cf_clearance") == "cached-token"
    assert user_agent == "ua-cached"
    assert client._cf_host_challenge_hits[host] == 7


def test_extract_bypass_payload_supports_nested_user_agent_fields():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")

    cookies, user_agent = client._extract_bypass_payload(
        {
            "data": {
                "cookies": {"cf_clearance": "token-a"},
                "headers": {"User-Agent": "ua-from-headers"},
            }
        }
    )
    assert cookies.get("cf_clearance") == "token-a"
    assert user_agent == "ua-from-headers"


@pytest.mark.asyncio
async def test_request_overrides_header_user_agent_with_bound_bypass_user_agent():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    host = "missav.ws"
    client._cf_host_cookies[host] = {"cf_clearance": "token-a"}
    client._cf_host_user_agents[host] = "ua-bound"

    captured_headers: list[dict[str, str]] = []

    async def fake_curl_request(method, url, **kwargs):
        captured_headers.append(dict(kwargs.get("headers") or {}))
        return SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "text/html"},
            content=b"ok",
        )

    client.curl_session.request = fake_curl_request  # type: ignore[method-assign]

    response, error = await client.request(
        "GET",
        "https://missav.ws/SNOS-100/cn",
        headers={"User-Agent": "ua-external"},
    )

    assert error == ""
    assert response is not None
    assert captured_headers
    assert captured_headers[0].get("User-Agent") == "ua-bound"


@pytest.mark.asyncio
async def test_try_bypass_reuses_cookie_user_agent_binding_when_user_agent_missing():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    host = "missav.ws"
    token = "token-a"
    client._remember_cf_cookie_user_agent(host, {"cf_clearance": token}, "ua-bound")

    async def fake_call_bypass_cookies(target_url: str, *, force_refresh: bool, use_proxy: bool):
        return {"cf_clearance": token}, "", ""

    client._call_bypass_cookies = fake_call_bypass_cookies  # type: ignore[method-assign]

    cookies, user_agent, error = await client._try_bypass_cloudflare(
        host=host,
        target_url="https://missav.ws/SNOS-101/cn",
        use_proxy=False,
    )

    assert error == ""
    assert cookies.get("cf_clearance") == token
    assert user_agent == "ua-bound"
    assert client._cf_host_user_agents.get(host) == "ua-bound"


@pytest.mark.asyncio
async def test_request_clears_orphan_bound_user_agent_without_cookie():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    host = "missav.ws"
    client._cf_host_user_agents[host] = "ua-orphan"

    captured_headers: list[dict[str, str]] = []

    async def fake_curl_request(method, url, **kwargs):
        captured_headers.append(dict(kwargs.get("headers") or {}))
        return SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "text/html"},
            content=b"ok",
        )

    client.curl_session.request = fake_curl_request  # type: ignore[method-assign]

    response, error = await client.request(
        "GET",
        "https://missav.ws/SNOS-102/cn",
    )

    assert error == ""
    assert response is not None
    assert captured_headers
    assert "User-Agent" not in captured_headers[0]
    assert host not in client._cf_host_user_agents


def test_clear_cf_host_binding_clears_cookie_and_user_agent():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    host = "missav.ws"
    client._cf_host_cookies[host] = {"cf_clearance": "token-a"}
    client._cf_host_user_agents[host] = "ua-a"

    client._clear_cf_host_binding(host)

    assert host not in client._cf_host_cookies
    assert host not in client._cf_host_user_agents


def test_cookie_user_agent_binding_prunes_expired_entries():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    host = "missav.ws"
    client._cf_cookie_binding_ttl = 0.01
    client._cf_cookie_binding_max_entries_per_host = 100
    client._cf_cookie_binding_max_entries_total = 100

    client._remember_cf_cookie_user_agent(host, {"cf_clearance": "token-a"}, "ua-a")
    client._cf_cookie_user_agent_binding_timestamps[host]["cf_clearance=token-a"] -= 1.0

    resolved = client._resolve_cf_cookie_user_agent(host, {"cf_clearance": "token-a"})

    assert resolved == ""
    assert host not in client._cf_cookie_user_agent_bindings


def test_cookie_user_agent_binding_prunes_host_overflow_entries():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    host = "missav.ws"
    client._cf_cookie_binding_ttl = 3600
    client._cf_cookie_binding_max_entries_per_host = 2
    client._cf_cookie_binding_max_entries_total = 100

    client._remember_cf_cookie_user_agent(host, {"cf_clearance": "token-1"}, "ua-1")
    client._remember_cf_cookie_user_agent(host, {"cf_clearance": "token-2"}, "ua-2")
    client._remember_cf_cookie_user_agent(host, {"cf_clearance": "token-3"}, "ua-3")

    host_bindings = client._cf_cookie_user_agent_bindings.get(host, {})
    assert len(host_bindings) == 2
    assert "cf_clearance=token-1" not in host_bindings
    assert host_bindings.get("cf_clearance=token-2") == "ua-2"
    assert host_bindings.get("cf_clearance=token-3") == "ua-3"


def test_cookie_user_agent_binding_prunes_global_overflow_entries():
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    client._cf_cookie_binding_ttl = 3600
    client._cf_cookie_binding_max_entries_per_host = 10
    client._cf_cookie_binding_max_entries_total = 2

    client._remember_cf_cookie_user_agent("a.example", {"cf_clearance": "token-a"}, "ua-a")
    client._remember_cf_cookie_user_agent("b.example", {"cf_clearance": "token-b"}, "ua-b")
    client._remember_cf_cookie_user_agent("c.example", {"cf_clearance": "token-c"}, "ua-c")

    total = sum(len(v) for v in client._cf_cookie_user_agent_bindings.values())
    assert total == 2
    assert client._resolve_cf_cookie_user_agent("a.example", {"cf_clearance": "token-a"}) == ""
    assert client._resolve_cf_cookie_user_agent("b.example", {"cf_clearance": "token-b"}) == "ua-b"
    assert client._resolve_cf_cookie_user_agent("c.example", {"cf_clearance": "token-c"}) == "ua-c"


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
        return SimpleNamespace(
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

    response, error = await client.request("GET", "https://missav.ws/SNOS-200/cn")

    assert response is None
    assert "HTTP 503" in error
    assert call_count == 3
    assert acquire_count == 3
    assert sleep_calls == [2.0, 5.0]


@pytest.mark.asyncio
async def test_request_uses_backoff_after_bypass_success(monkeypatch):
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    client.retry = 2
    client._cf_retry_after_bypass_base_delay = 1.2
    client._cf_retry_after_bypass_jitter = 1.3

    async def fake_try_bypass_cloudflare(*, host: str, target_url: str, use_proxy: bool, force_refresh: bool = False):
        return {"cf_clearance": "token-a"}, "ua-bound", ""

    client._try_bypass_cloudflare = fake_try_bypass_cloudflare  # type: ignore[method-assign]

    call_count = 0

    async def fake_curl_request(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return SimpleNamespace(
                status_code=503,
                headers={"Content-Type": "text/html", "server": "cloudflare", "cf-ray": "abc"},
                content=b"<html>just a moment cf-chl</html>",
            )
        return SimpleNamespace(
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

    response, error = await client.request("GET", "https://missav.ws/SNOS-201/cn")

    assert error == ""
    assert response is not None
    assert call_count == 2
    assert sleep_calls == [1.7]
