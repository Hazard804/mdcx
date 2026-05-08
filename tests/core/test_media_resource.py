from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from mdcx.config.manager import manager
from mdcx.core.media_resource import MediaResourceContext


class _FakeResponse:
    def __init__(self, url: str, content: bytes = b""):
        self.url = url
        self.content = content
        self.status_code = 200

    def iter_content(self, chunk_size: int):
        content = self.content

        async def _chunk():
            return content[:chunk_size]

        yield _chunk()

    async def aclose(self):
        return None


def _jpeg_bytes(size: tuple[int, int] = (12, 18)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "white").save(output, format="JPEG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_media_resource_context_reuses_image_bytes_for_size_and_save(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        return _FakeResponse(url, _jpeg_bytes()), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://example.test/cover.jpg"

        assert await context.get_size(url) == (12, 18)
        assert await context.save_image(url, tmp_path / "cover.jpg", tmp_path) is True
    finally:
        context.close()

    assert calls == ["https://example.test/cover.jpg"]


@pytest.mark.asyncio
async def test_media_resource_context_reuses_image_bytes_for_open_and_save(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        return _FakeResponse(url, _jpeg_bytes()), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://example.test/poster.jpg"
        img = await context.open_rgb_image(url)
        assert img is not None
        img.close()

        assert await context.save_image(url, tmp_path / "poster.jpg", tmp_path) is True
    finally:
        context.close()

    assert calls == ["https://example.test/poster.jpg"]


@pytest.mark.asyncio
async def test_media_resource_context_does_not_cache_failed_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        return None, "network error"

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://example.test/missing.jpg"

        assert await context.fetch_bytes(url) is None
        assert await context.save_image(url, tmp_path / "missing.jpg", tmp_path) is False
    finally:
        context.close()

    assert calls == ["https://example.test/missing.jpg", "https://example.test/missing.jpg"]
    assert not (tmp_path / "missing.jpg").exists()


@pytest.mark.asyncio
async def test_media_resource_context_rejects_invalid_dmm_redirect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        return _FakeResponse("https://pics.dmm.co.jp/digital/video/pred00816/now_printing.jpg", b"fake"), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://awsimgsrc.dmm.co.jp/digital/video/pred00816/pred00816pl.jpg"

        assert await context.fetch_bytes(url) is None
        assert await context.save_image(url, tmp_path / "poster.jpg", tmp_path) is False
    finally:
        context.close()

    assert calls == [
        "https://awsimgsrc.dmm.co.jp/digital/video/pred00816/pred00816pl.jpg?w=120&h=90",
        "https://awsimgsrc.dmm.co.jp/digital/video/pred00816/pred00816pl.jpg?w=120&h=90",
    ]
    assert not (tmp_path / "poster.jpg").exists()


@pytest.mark.asyncio
async def test_media_resource_context_adds_probe_params_for_dmm_aws_image(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        return _FakeResponse(f"{url}&&", _jpeg_bytes()), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg"

        assert await context.fetch_bytes(url)
    finally:
        context.close()

    assert calls == ["https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg?w=120&h=90"]


@pytest.mark.asyncio
async def test_media_resource_context_probe_size_does_not_cache_full_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    calls: list[tuple[str, bool]] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append((url, bool(kwargs.get("stream"))))
        return _FakeResponse(url, _jpeg_bytes()), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://example.test/probe.jpg"

        assert await context.probe_size(url) == (12, 18)
        assert await context.save_image(url, tmp_path / "probe.jpg", tmp_path) is True
    finally:
        context.close()

    assert calls == [
        ("https://example.test/probe.jpg", True),
        ("https://example.test/probe.jpg", False),
    ]
