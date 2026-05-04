import asyncio
from types import SimpleNamespace

import pytest

from mdcx.config.models import Config
from mdcx.crawler import CrawlerProvider
from mdcx.web_async import AsyncWebClient


class _FakeSession:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _FakeResponse:
    status_code = 200
    headers = {}


@pytest.mark.asyncio
async def test_async_web_client_close_closes_underlying_session():
    client = AsyncWebClient(timeout=1)
    old_session = client.curl_session

    await client.close()

    assert client._closed is True
    assert getattr(old_session, "_closed", True) is True


@pytest.mark.asyncio
async def test_async_web_client_close_when_idle_waits_for_lease():
    client = AsyncWebClient(timeout=1)
    fake_session = _FakeSession()
    client.curl_session = fake_session  # type: ignore[assignment]

    client.retain()
    close_task = asyncio.create_task(client.close_when_idle(poll_interval=0.01))
    await asyncio.sleep(0.03)

    assert fake_session.closed is False

    await client.release()
    await asyncio.wait_for(close_task, timeout=1)

    assert fake_session.closed is True


@pytest.mark.asyncio
async def test_crawler_provider_retains_client_until_close():
    client = AsyncWebClient(timeout=1)
    provider = CrawlerProvider(Config(), client)

    assert client._lease_count() == 1

    await provider.close()

    assert client._lease_count() == 0
    await client.close()


@pytest.mark.asyncio
async def test_stream_failure_response_is_closed(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1, retry=1)
    closed: list[bool] = []

    class Response:
        status_code = 500
        headers = {}

        async def aclose(self):
            closed.append(True)

    async def fake_curl_request(**kwargs):
        return Response()

    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response, error = await client.request("GET", "https://example.test/image.jpg", stream=True)

    assert response is None
    assert "HTTP 500" in error
    assert closed == [True]
    await client.close()


@pytest.mark.asyncio
async def test_reset_connections_waits_for_active_request(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1, retry=1)

    class SlowSession(_FakeSession):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.finish = asyncio.Event()

        async def request(self, **kwargs):
            self.started.set()
            await self.finish.wait()
            return _FakeResponse()

    old_session = SlowSession()
    new_session = _FakeSession()
    client.curl_session = old_session  # type: ignore[assignment]
    monkeypatch.setattr(client, "_new_curl_session", lambda: new_session)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    request_task = asyncio.create_task(client.request("GET", "https://example.test/image.jpg"))
    await asyncio.wait_for(old_session.started.wait(), timeout=1)

    await client.reset_connections("test")

    assert old_session.closed is False
    assert client.curl_session is old_session

    old_session.finish.set()
    response, error = await asyncio.wait_for(request_task, timeout=1)

    assert response is not None
    assert error == ""
    assert old_session.closed is True
    assert client.curl_session is new_session
