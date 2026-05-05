import asyncio
from types import SimpleNamespace

import aiofiles
import pytest
from curl_cffi.requests.exceptions import Timeout

from mdcx.config.models import Config
from mdcx.crawler import CrawlerProvider
from mdcx.web_async import AsyncWebClient


class _FakeSession:
    def __init__(self):
        self.closed = False
        self.requests: list[dict] = []

    async def close(self):
        self.closed = True

    async def request(self, **kwargs):
        self.requests.append(kwargs)
        return _FakeResponse()


class _FakeResponse:
    status_code = 200
    headers = {}


@pytest.mark.asyncio
async def test_async_web_client_close_closes_underlying_session():
    client = AsyncWebClient(timeout=1)
    old_session = _FakeSession()
    monkeypatch = pytest.MonkeyPatch()
    client._pool_manager._session_factory = lambda: old_session  # type: ignore[assignment]
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response, error = await client.request("GET", "https://example.test/image.jpg")

    assert response is not None
    assert error == ""

    await client.close()

    assert client._closed is True
    assert old_session.closed is True
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_async_web_client_close_when_idle_waits_for_lease():
    client = AsyncWebClient(timeout=1)
    fake_session = _FakeSession()
    client._pool_manager._session_factory = lambda: fake_session  # type: ignore[assignment]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    response, error = await client.request("GET", "https://example.test/image.jpg")

    assert response is not None
    assert error == ""

    client.retain()
    close_task = asyncio.create_task(client.close_when_idle(poll_interval=0.01))
    await asyncio.sleep(0.03)

    assert fake_session.closed is False

    await client.release()
    await asyncio.wait_for(close_task, timeout=1)

    assert fake_session.closed is True
    monkeypatch.undo()


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
async def test_reset_connections_rotates_new_requests_and_closes_old_after_active_request(
    monkeypatch: pytest.MonkeyPatch,
):
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
    sessions = iter([old_session, new_session])
    client._pool_manager._session_factory = lambda: next(sessions)  # type: ignore[assignment]
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    request_task = asyncio.create_task(client.request("GET", "https://example.test/image.jpg"))
    await asyncio.wait_for(old_session.started.wait(), timeout=1)

    pool_key = "https://example.test|proxy="
    await client.reset_connections("test", pool_key=pool_key)

    assert old_session.closed is False

    response, error = await client.request("GET", "https://example.test/next.jpg")
    assert response is not None
    assert error == ""
    assert len(new_session.requests) == 1
    assert old_session.closed is False

    old_session.finish.set()
    response, error = await asyncio.wait_for(request_task, timeout=1)

    assert response is not None
    assert error == ""
    assert old_session.closed is True
    assert new_session.closed is False
    await client.close()


@pytest.mark.asyncio
async def test_transport_error_retry_uses_rotated_host_pool(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1, retry=2)

    class FailingSession(_FakeSession):
        async def request(self, **kwargs):
            self.requests.append(kwargs)
            raise Timeout("timed out")

    failing_session = FailingSession()
    recovery_session = _FakeSession()
    sessions = iter([failing_session, recovery_session])
    client._pool_manager._session_factory = lambda: next(sessions)  # type: ignore[assignment]
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    async def fake_sleep(delay: float):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    response, error = await client.request("GET", "https://example.test/image.jpg")

    assert response is not None
    assert error == ""
    assert failing_session.closed is True
    assert len(failing_session.requests) == 1
    assert len(recovery_session.requests) == 1
    await client.close()


@pytest.mark.asyncio
async def test_pool_slot_wait_is_not_counted_by_request_watchdog(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1, retry=1)
    client._pool_manager._max_clients = 1
    monkeypatch.setattr(client, "_request_timeout_seconds", lambda timeout: 0.05)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    fake_session = _FakeSession()
    client._pool_manager._session_factory = lambda: fake_session  # type: ignore[assignment]

    first_response, first_error = await client.request("GET", "https://example.test/hold.jpg", stream=True)

    assert first_error == ""
    assert first_response is not None
    assert len(fake_session.requests) == 1

    second_task = asyncio.create_task(client.request("GET", "https://example.test/next.jpg"))
    await asyncio.sleep(0.1)

    assert not second_task.done()
    assert len(fake_session.requests) == 1

    await first_response.aclose()
    second_response, second_error = await asyncio.wait_for(second_task, timeout=1)

    assert second_error == ""
    assert second_response is not None
    assert len(fake_session.requests) == 2
    await client.close()


@pytest.mark.asyncio
async def test_request_watchdog_still_applies_after_pool_slot_is_acquired(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1, retry=1)
    client._pool_manager._max_clients = 1
    monkeypatch.setattr(client, "_request_timeout_seconds", lambda timeout: 0.05)
    monkeypatch.setattr(client.limiters, "get", lambda key: SimpleNamespace(acquire=lambda: asyncio.sleep(0)))

    class HangingSession(_FakeSession):
        async def request(self, **kwargs):
            self.requests.append(kwargs)
            await asyncio.Event().wait()
            return _FakeResponse()

    fake_session = HangingSession()
    client._pool_manager._session_factory = lambda: fake_session  # type: ignore[assignment]

    response, error = await client.request("GET", "https://example.test/hang.jpg")

    assert response is None
    assert "请求等待超时" in error
    assert len(fake_session.requests) == 1
    await client.close()


@pytest.mark.asyncio
async def test_chunk_read_error_retries_same_range(monkeypatch: pytest.MonkeyPatch, tmp_path):
    client = AsyncWebClient(timeout=1, retry=2)
    monkeypatch.setattr(client, "_calc_retry_sleep_seconds", lambda attempt: 0)

    class StreamResponse:
        headers = {}

        def __init__(self, *, fail: bool, status_code: int = 206, content: bytes = b"abc"):
            self.fail = fail
            self.status_code = status_code
            self.content = content
            self.closed = False

        async def acontent(self):
            if self.fail:
                raise Timeout("read timed out")
            return self.content

        async def aclose(self):
            self.closed = True

    calls: list[dict] = []

    async def fake_request(method, url, **kwargs):
        calls.append(kwargs)
        return StreamResponse(fail=len(calls) == 1), ""

    monkeypatch.setattr(client, "request", fake_request)
    monkeypatch.setattr(client, "_record_transport_failure", lambda error_msg, pool_key: asyncio.sleep(0))

    target = tmp_path / "chunk.bin"
    async with aiofiles.open(target, "wb") as fp:
        await fp.truncate(3)

    error = await client._download_chunk(asyncio.Semaphore(1), "https://example.test/video.mp4", target, 0, 2, 0)

    assert error == ""
    assert len(calls) == 2
    assert all(call["headers"] == {"Range": "bytes=0-2"} for call in calls)
    assert all(call["retry_count"] == 1 for call in calls)
    assert target.read_bytes() == b"abc"


@pytest.mark.asyncio
async def test_get_text_forwards_retry_count(monkeypatch: pytest.MonkeyPatch):
    client = AsyncWebClient(timeout=1)
    captured: dict[str, object] = {}

    class Response:
        status_code = 200
        headers = {}
        text = "ok"

    async def fake_request(method, url, **kwargs):
        captured.update(kwargs)
        return Response(), ""

    monkeypatch.setattr(client, "request", fake_request)

    text, error = await client.get_text("https://example.test", retry_count=1)

    assert text == "ok"
    assert error == ""
    assert captured["retry_count"] == 1


@pytest.mark.asyncio
async def test_chunk_rejects_non_partial_response(monkeypatch: pytest.MonkeyPatch, tmp_path):
    client = AsyncWebClient(timeout=1, retry=1)

    response = SimpleNamespace(
        status_code=200,
        headers={},
        acontent=lambda: asyncio.sleep(0, result=b"abc"),
        aclose=lambda: asyncio.sleep(0),
    )

    async def fake_request(method, url, **kwargs):
        return response, ""

    monkeypatch.setattr(client, "request", fake_request)

    target = tmp_path / "chunk.bin"
    async with aiofiles.open(target, "wb") as fp:
        await fp.truncate(3)

    error = await client._download_chunk(asyncio.Semaphore(1), "https://example.test/video.mp4", target, 0, 2, 0)

    assert error == "分块响应状态异常: HTTP 200"
    assert target.read_bytes() == b"\x00\x00\x00"


@pytest.mark.asyncio
async def test_chunk_download_falls_back_to_whole_file_when_range_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    client = AsyncWebClient(timeout=1, retry=1)
    target = tmp_path / "video.bin"

    async def fake_download_chunk(semaphore, url, file_path, start, end, chunk_id, use_proxy=True):
        assert chunk_id == 0
        return "分块响应状态异常: HTTP 200"

    async def fake_download_whole_file(url, file_path, *, use_proxy, expected_size=None):
        assert expected_size == 3
        file_path.write_bytes(b"abc")
        return True

    monkeypatch.setattr(client, "_download_chunk", fake_download_chunk)
    monkeypatch.setattr(client, "_download_whole_file", fake_download_whole_file)

    assert await client._download_chunks("https://example.test/video.mp4", target, 3) is True
    assert target.read_bytes() == b"abc"


@pytest.mark.asyncio
async def test_chunk_download_uses_closed_range_boundaries(monkeypatch: pytest.MonkeyPatch, tmp_path):
    client = AsyncWebClient(timeout=1, retry=1)
    target = tmp_path / "video.bin"
    calls = []
    chunk_size = 4 * 1024**2

    async def fake_download_chunk(semaphore, url, file_path, start, end, chunk_id, use_proxy=True):
        calls.append((start, end, chunk_id))
        return ""

    monkeypatch.setattr(client, "_download_chunk", fake_download_chunk)

    assert await client._download_chunks("https://example.test/video.mp4", target, chunk_size + 3) is True

    assert calls == [(0, chunk_size - 1, 0), (chunk_size, chunk_size + 2, 1)]


@pytest.mark.asyncio
async def test_chunk_download_keeps_target_untouched_until_success(monkeypatch: pytest.MonkeyPatch, tmp_path):
    client = AsyncWebClient(timeout=1, retry=1)
    target = tmp_path / "video.bin"
    target.write_bytes(b"old")

    async def fake_download_chunk(semaphore, url, file_path, start, end, chunk_id, use_proxy=True):
        async with aiofiles.open(file_path, "rb+") as fp:
            await fp.seek(start)
            await fp.write(b"abc")
        return ""

    monkeypatch.setattr(client, "_download_chunk", fake_download_chunk)

    assert await client._download_chunks("https://example.test/video.mp4", target, 3) is True

    assert target.read_bytes() == b"abc"
    assert not target.with_name(f"{target.name}.part").exists()


@pytest.mark.asyncio
async def test_chunk_rejects_size_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path):
    client = AsyncWebClient(timeout=1, retry=1)

    response = SimpleNamespace(
        status_code=206,
        headers={},
        acontent=lambda: asyncio.sleep(0, result=b"ab"),
        aclose=lambda: asyncio.sleep(0),
    )

    async def fake_request(method, url, **kwargs):
        return response, ""

    monkeypatch.setattr(client, "request", fake_request)

    target = tmp_path / "chunk.bin"
    async with aiofiles.open(target, "wb") as fp:
        await fp.truncate(3)

    error = await client._download_chunk(asyncio.Semaphore(1), "https://example.test/video.mp4", target, 0, 2, 0)

    assert error == "分块大小不匹配: 2/3"
    assert target.read_bytes() == b"\x00\x00\x00"
