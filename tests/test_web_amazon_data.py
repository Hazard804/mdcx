import pytest

from mdcx.base.web import get_amazon_data
from mdcx.config.manager import manager


@pytest.mark.asyncio
async def test_get_amazon_data_prefers_utf8(monkeypatch: pytest.MonkeyPatch):
    called_encodings: list[str] = []

    async def fake_get_text(url: str, *, headers=None, encoding: str = "utf-8"):
        called_encodings.append(encoding)
        return "<html>ok</html>", ""

    monkeypatch.setattr(manager.computed.async_client, "get_text", fake_get_text)

    success, html = await get_amazon_data("https://www.amazon.co.jp/s?k=test")

    assert success is True
    assert html == "<html>ok</html>"
    assert called_encodings == ["utf-8"]


@pytest.mark.asyncio
async def test_get_amazon_data_retry_still_uses_utf8(monkeypatch: pytest.MonkeyPatch):
    called_encodings: list[str] = []

    async def fake_get_text(url: str, *, headers=None, encoding: str = "utf-8"):
        called_encodings.append(encoding)
        if len(called_encodings) == 1:
            return None, "utf8 failed"
        return "<html>ok</html>", ""

    monkeypatch.setattr(manager.computed.async_client, "get_text", fake_get_text)

    success, html = await get_amazon_data("https://www.amazon.co.jp/s?k=test")

    assert success is True
    assert html == "<html>ok</html>"
    assert called_encodings[:2] == ["utf-8", "utf-8"]
