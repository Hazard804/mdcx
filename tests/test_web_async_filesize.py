import pytest

from mdcx.web_async import AsyncWebClient


class _FakeResponse:
    def __init__(self, headers: dict[str, str], status_code: int = 200):
        self.headers = headers
        self.status_code = status_code


@pytest.mark.asyncio
async def test_get_filesize_accepts_lowercase_content_length(monkeypatch: pytest.MonkeyPatch):
    logs: list[str] = []
    client = AsyncWebClient(timeout=1, log_fn=logs.append)

    async def fake_request(method: str, url: str, **kwargs):
        return _FakeResponse({"content-length": "12345"}), ""

    monkeypatch.setattr(client, "request", fake_request)

    try:
        assert await client.get_filesize("https://example.test/image.jpg") == 12345
        assert logs == []
    finally:
        await client.curl_session.close()


@pytest.mark.asyncio
async def test_get_filesize_missing_content_length_falls_back_without_error(monkeypatch: pytest.MonkeyPatch):
    logs: list[str] = []
    client = AsyncWebClient(timeout=1, log_fn=logs.append)

    async def fake_request(method: str, url: str, **kwargs):
        return _FakeResponse({"content-type": "image/jpeg", "content-encoding": "gzip"}), ""

    monkeypatch.setattr(client, "request", fake_request)

    try:
        assert await client.get_filesize("https://javday.app/upload/vod/demo.jpg") is None
        assert logs == []
    finally:
        await client.curl_session.close()
