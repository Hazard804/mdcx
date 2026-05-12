import asyncio
from types import SimpleNamespace

import pytest

import mdcx.network_fingerprint as network_fingerprint
import mdcx.web_async as web_async
from mdcx.network_fingerprint import BrowserFingerprint, build_amazon_headers
from mdcx.web_async import AsyncWebClient


@pytest.mark.asyncio
async def test_request_merges_fingerprint_and_keeps_explicit_accept(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1)
    captured: dict[str, object] = {}

    async def fake_curl_request(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status_code=200, headers={}, content=b"", url=kwargs["url"])

    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response, error = await client.request(
        "GET",
        "https://api.example.test/movies?q=ssni-200",
        headers={"Accept": "application/json"},
    )

    assert response is not None
    assert error == ""
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Accept"] == "application/json"
    assert "User-Agent" in headers
    assert captured["fingerprint"] is not None
    await client.close()


@pytest.mark.asyncio
async def test_range_download_keeps_range_and_skips_document_headers(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1)
    captured: dict[str, object] = {}

    async def fake_curl_request(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status_code=206, headers={}, content=b"abc", url=kwargs["url"])

    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response, error = await client.request(
        "GET",
        "https://media.example.test/video.mp4",
        headers={"Range": "bytes=0-2"},
        stream=True,
        retry_count=1,
    )

    assert response is not None
    assert error == ""
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Range"] == "bytes=0-2"
    assert headers["Accept"] == "*/*"
    assert "Upgrade-Insecure-Requests" not in headers
    await client.close()


@pytest.mark.asyncio
async def test_cf_bypass_disabled_target_request_still_uses_fingerprint(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    captured: dict[str, object] = {}

    async def fake_curl_request(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status_code=200, headers={}, content=b"", url=kwargs["url"])

    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response, error = await client.request(
        "GET",
        "https://missav.ws/SNOS-001/cn",
        enable_cf_bypass=False,
    )

    assert response is not None
    assert error == ""
    assert captured["fingerprint"] is not None
    assert "User-Agent" in captured["headers"]
    await client.close()


@pytest.mark.asyncio
async def test_cf_bypass_service_url_skips_fingerprint(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    captured: dict[str, object] = {}

    async def fake_curl_request(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status_code=200, headers={}, content=b"ok", url=kwargs["url"])

    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response, error = await client.request("GET", "http://127.0.0.1:8000/html", enable_cf_bypass=False)

    assert response is not None
    assert error == ""
    assert captured["fingerprint"] is None
    assert captured["headers"] == {}
    await client.close()


@pytest.mark.asyncio
async def test_same_host_reuses_fingerprint_until_reset(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1)
    fingerprints: list[str] = []

    async def fake_curl_request(**kwargs):
        fingerprint = kwargs.get("fingerprint")
        fingerprints.append(fingerprint.fingerprint_id if fingerprint is not None else "")
        return SimpleNamespace(status_code=200, headers={}, content=b"", url=kwargs["url"])

    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response1, error1 = await client.request("GET", "https://example.test/a")
    response2, error2 = await client.request("GET", "https://example.test/b")

    assert response1 is not None
    assert response2 is not None
    assert error1 == ""
    assert error2 == ""
    assert fingerprints[0]
    assert fingerprints[0] == fingerprints[1]
    await client.close()


@pytest.mark.asyncio
async def test_retryable_http_status_switches_fingerprint(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1, retry=2)
    first = BrowserFingerprint(
        fingerprint_id="test_chrome_a",
        impersonate="chrome136",
        family="chrome",
        platform="Windows",
        headers={"User-Agent": "ua-a"},
    )
    second = BrowserFingerprint(
        fingerprint_id="test_chrome_b",
        impersonate="chrome131",
        family="chrome",
        platform="Windows",
        headers={"User-Agent": "ua-b"},
    )
    selected = iter([first, second])
    fingerprints: list[str] = []

    def fake_select_fingerprint(host: str, *, purpose="document", exclude_fingerprint_id=""):
        return next(selected)

    async def fake_curl_request(**kwargs):
        fingerprint = kwargs.get("fingerprint")
        fingerprints.append(fingerprint.fingerprint_id if fingerprint is not None else "")
        status_code = 429 if len(fingerprints) == 1 else 200
        return SimpleNamespace(status_code=status_code, headers={}, content=b"", url=kwargs["url"])

    monkeypatch.setattr(web_async, "select_fingerprint", fake_select_fingerprint)
    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client, "_calc_retry_sleep_seconds", lambda attempt, *, after_cf_bypass=False: 0)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response, error = await client.request("GET", "https://example.test/rate-limited")

    assert response is not None
    assert error == ""
    assert fingerprints == ["test_chrome_a", "test_chrome_b"]
    await client.close()


@pytest.mark.asyncio
async def test_expired_fingerprint_state_switches_profile_for_new_document_request(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1)
    client._fingerprint_default_lifetime_range = (1.0, 1.0)
    first = BrowserFingerprint(
        fingerprint_id="test_chrome_a",
        impersonate="chrome136",
        family="chrome",
        platform="Windows",
        headers={"User-Agent": "ua-a"},
    )
    second = BrowserFingerprint(
        fingerprint_id="test_chrome_b",
        impersonate="chrome131",
        family="chrome",
        platform="Windows",
        headers={"User-Agent": "ua-b"},
    )
    selected = iter([first, second])
    now_values = iter([10.0, 12.0])
    current_now = 12.0
    fingerprints: list[str] = []

    def fake_select_fingerprint(host: str, *, purpose="document", exclude_fingerprint_id=""):
        return next(selected)

    async def fake_curl_request(**kwargs):
        fingerprint = kwargs.get("fingerprint")
        fingerprints.append(fingerprint.fingerprint_id if fingerprint is not None else "")
        return SimpleNamespace(status_code=200, headers={}, content=b"", url=kwargs["url"])

    def fake_monotonic():
        nonlocal current_now
        try:
            current_now = next(now_values)
        except StopIteration:
            pass
        return current_now

    monkeypatch.setattr(web_async, "select_fingerprint", fake_select_fingerprint)
    monkeypatch.setattr(web_async.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response1, error1 = await client.request("GET", "https://example.test/a")
    response2, error2 = await client.request("GET", "https://example.test/b")

    assert response1 is not None
    assert response2 is not None
    assert error1 == ""
    assert error2 == ""
    assert fingerprints == ["test_chrome_a", "test_chrome_b"]
    await client.close()


@pytest.mark.asyncio
async def test_download_request_does_not_rotate_expired_fingerprint_state(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1)
    client._fingerprint_default_lifetime_range = (1.0, 1.0)
    first = BrowserFingerprint(
        fingerprint_id="test_chrome_a",
        impersonate="chrome136",
        family="chrome",
        platform="Windows",
        headers={"User-Agent": "ua-a"},
    )
    second = BrowserFingerprint(
        fingerprint_id="test_chrome_b",
        impersonate="chrome131",
        family="chrome",
        platform="Windows",
        headers={"User-Agent": "ua-b"},
    )
    selected = iter([first, second])
    now_values = iter([10.0, 12.0])
    current_now = 12.0
    fingerprints: list[str] = []

    def fake_select_fingerprint(host: str, *, purpose="document", exclude_fingerprint_id=""):
        return next(selected)

    async def fake_curl_request(**kwargs):
        fingerprint = kwargs.get("fingerprint")
        fingerprints.append(fingerprint.fingerprint_id if fingerprint is not None else "")
        return SimpleNamespace(status_code=206, headers={}, content=b"abc", url=kwargs["url"])

    def fake_monotonic():
        nonlocal current_now
        try:
            current_now = next(now_values)
        except StopIteration:
            pass
        return current_now

    monkeypatch.setattr(web_async, "select_fingerprint", fake_select_fingerprint)
    monkeypatch.setattr(web_async.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response1, error1 = await client.request("GET", "https://media.example.test/video.mp4", stream=True)
    response2, error2 = await client.request("GET", "https://media.example.test/video.mp4", stream=True)

    assert response1 is not None
    assert response2 is not None
    assert error1 == ""
    assert error2 == ""
    assert fingerprints == ["test_chrome_a", "test_chrome_a"]
    await client.close()


@pytest.mark.asyncio
async def test_request_count_limit_switches_fingerprint(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1)
    client._fingerprint_default_lifetime_range = (3600.0, 3600.0)
    client._fingerprint_default_request_range = (1, 1)
    first = BrowserFingerprint(
        fingerprint_id="test_chrome_a",
        impersonate="chrome136",
        family="chrome",
        platform="Windows",
        headers={"User-Agent": "ua-a"},
    )
    second = BrowserFingerprint(
        fingerprint_id="test_chrome_b",
        impersonate="chrome131",
        family="chrome",
        platform="Windows",
        headers={"User-Agent": "ua-b"},
    )
    selected = iter([first, second])
    fingerprints: list[str] = []

    def fake_select_fingerprint(host: str, *, purpose="document", exclude_fingerprint_id=""):
        return next(selected)

    async def fake_curl_request(**kwargs):
        fingerprint = kwargs.get("fingerprint")
        fingerprints.append(fingerprint.fingerprint_id if fingerprint is not None else "")
        return SimpleNamespace(status_code=200, headers={}, content=b"", url=kwargs["url"])

    monkeypatch.setattr(web_async, "select_fingerprint", fake_select_fingerprint)
    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response1, error1 = await client.request("GET", "https://example.test/a")
    response2, error2 = await client.request("GET", "https://example.test/b")

    assert response1 is not None
    assert response2 is not None
    assert error1 == ""
    assert error2 == ""
    assert fingerprints == ["test_chrome_a", "test_chrome_b"]
    await client.close()


def test_amazon_headers_use_japanese_desktop_profile():
    headers = build_amazon_headers("https://www.amazon.co.jp/s?k=test")

    assert headers["Host"] == "www.amazon.co.jp"
    assert headers["accept-language"].startswith("ja-JP")
    assert "User-Agent" not in headers


def test_amazon_fingerprint_pool_uses_desktop_profiles():
    seen = {each.fingerprint_id for each in network_fingerprint._AMAZON_FINGERPRINTS}

    assert any(each.startswith("chrome") for each in seen)
    assert any(each.startswith("firefox") for each in seen)
