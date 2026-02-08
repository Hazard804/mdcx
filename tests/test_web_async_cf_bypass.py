import asyncio
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
