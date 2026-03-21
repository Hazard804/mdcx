from types import SimpleNamespace

import pytest

import mdcx.base.web as web_module
from mdcx.base.web import _AdaptiveRequestThrottle, _amazon_request_throttle, get_amazon_data
from mdcx.config.manager import manager


@pytest.mark.asyncio
async def test_get_amazon_data_prefers_utf8(monkeypatch: pytest.MonkeyPatch):
    await _amazon_request_throttle.reset()
    called_encodings: list[str] = []
    called_headers: list[dict | None] = []

    async def fake_get_text(url: str, *, headers=None, encoding: str = "utf-8"):
        called_encodings.append(encoding)
        called_headers.append(headers)
        return "<html>ok</html>", ""

    monkeypatch.setattr(manager.computed.async_client, "get_text", fake_get_text)

    success, html = await get_amazon_data("https://www.amazon.co.jp/s?k=test")

    assert success is True
    assert html == "<html>ok</html>"
    assert called_encodings == ["utf-8"]
    assert called_headers[0] is not None
    assert "ja" in str(called_headers[0].get("accept-language", "")).lower()


@pytest.mark.asyncio
async def test_get_amazon_data_retry_still_uses_utf8(monkeypatch: pytest.MonkeyPatch):
    await _amazon_request_throttle.reset()
    called_encodings: list[str] = []
    called_headers: list[dict | None] = []

    async def fake_get_text(url: str, *, headers=None, encoding: str = "utf-8"):
        called_encodings.append(encoding)
        called_headers.append(headers)
        if len(called_encodings) == 1:
            return None, "utf8 failed"
        return "<html>ok</html>", ""

    monkeypatch.setattr(manager.computed.async_client, "get_text", fake_get_text)

    success, html = await get_amazon_data("https://www.amazon.co.jp/s?k=test")

    assert success is True
    assert html == "<html>ok</html>"
    assert called_encodings[:2] == ["utf-8", "utf-8"]
    assert all(headers is not None for headers in called_headers[:2])
    assert all("ja" in str(headers.get("accept-language", "")).lower() for headers in called_headers[:2])


@pytest.mark.asyncio
async def test_get_amazon_data_dynamic_backoff_after_429(monkeypatch: pytest.MonkeyPatch):
    await _amazon_request_throttle.reset()
    called_encodings: list[str] = []
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    async def fake_get_text(url: str, *, headers=None, encoding: str = "utf-8"):
        called_encodings.append(encoding)
        if len(called_encodings) == 1:
            return None, "HTTP 429"
        return "<html>ok</html>", ""

    monkeypatch.setattr(manager.computed.async_client, "get_text", fake_get_text)
    monkeypatch.setattr("mdcx.base.web.asyncio.sleep", fake_sleep)

    success, html = await get_amazon_data("https://www.amazon.co.jp/s?k=test")

    assert success is True
    assert html == "<html>ok</html>"
    assert called_encodings[:2] == ["utf-8", "utf-8"]
    assert any(seconds >= 1.0 for seconds in sleep_calls)
    await _amazon_request_throttle.reset()


@pytest.mark.asyncio
async def test_adaptive_request_throttle_coalesces_same_burst_429(monkeypatch: pytest.MonkeyPatch):
    throttle = _AdaptiveRequestThrottle(
        base_spacing=0.18,
        max_spacing=1.6,
        cooldown_base=1.4,
        cooldown_max=8.0,
        throttle_burst_window=2.2,
        same_burst_extension=0.7,
    )
    monotonic_values = iter([10.0, 10.6, 11.8, 14.8])

    monkeypatch.setattr(web_module, "random", SimpleNamespace(uniform=lambda _a, _b: 0.0))
    monkeypatch.setattr(web_module, "time", SimpleNamespace(monotonic=lambda: next(monotonic_values)))

    cooldown1, level1, escalated1 = await throttle.register_result(throttled=True)
    cooldown2, level2, escalated2 = await throttle.register_result(throttled=True)
    cooldown3, level3, escalated3 = await throttle.register_result(throttled=True)
    cooldown4, level4, escalated4 = await throttle.register_result(throttled=True)

    assert escalated1 is True
    assert level1 == 1
    assert cooldown1 == pytest.approx(1.4)

    assert escalated2 is False
    assert level2 == 1
    assert cooldown2 == pytest.approx(0.8)

    assert escalated3 is False
    assert level3 == 1
    assert cooldown3 == pytest.approx(0.7)

    assert escalated4 is True
    assert level4 == 2
    assert cooldown4 == pytest.approx(2.52)


@pytest.mark.asyncio
async def test_adaptive_request_throttle_recovers_after_success(monkeypatch: pytest.MonkeyPatch):
    throttle = _AdaptiveRequestThrottle(
        base_spacing=0.2,
        max_spacing=1.6,
        cooldown_base=1.4,
        cooldown_max=8.0,
    )
    monotonic_values = iter([20.0, 24.0, 24.1, 24.2])

    monkeypatch.setattr(web_module, "random", SimpleNamespace(uniform=lambda _a, _b: 0.0))
    monkeypatch.setattr(web_module, "time", SimpleNamespace(monotonic=lambda: next(monotonic_values)))

    _, level1, _ = await throttle.register_result(throttled=True)
    _, level2, _ = await throttle.register_result(throttled=True)
    boosted_spacing = throttle._request_spacing
    _, level3, _ = await throttle.register_result(throttled=False)
    _, level4, _ = await throttle.register_result(throttled=False)

    assert level1 == 1
    assert level2 == 2
    assert level3 == 1
    assert level4 == 0
    assert throttle.base_spacing < throttle._request_spacing < boosted_spacing
