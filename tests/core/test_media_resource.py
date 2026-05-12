from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from mdcx.config.manager import manager
from mdcx.core.media_resource import MediaResourceContext


class _FakeResponse:
    def __init__(self, url: str, content: bytes = b"", headers: dict[str, str] | None = None):
        self.url = url
        self.content = content
        self.headers = headers or {}
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
async def test_media_resource_context_close_clears_cached_image_bytes(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        return _FakeResponse(url, _jpeg_bytes()), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    url = "https://example.test/poster.jpg"

    assert await context.fetch_bytes(url)
    context.close()
    assert await context.fetch_bytes(url)
    context.close()

    assert calls == [
        "https://example.test/poster.jpg",
        "https://example.test/poster.jpg",
    ]


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
        "https://awsimgsrc.dmm.co.jp/digital/video/pred00816/pred00816pl.jpg",
        "https://awsimgsrc.dmm.co.jp/digital/video/pred00816/pred00816pl.jpg",
    ]
    assert not (tmp_path / "poster.jpg").exists()


@pytest.mark.asyncio
async def test_media_resource_context_adds_probe_params_for_dmm_aws_image_probe(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        return _FakeResponse(f"{url}&&", _jpeg_bytes()), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg"

        assert await context.probe_size(url) == (12, 18)
    finally:
        context.close()

    assert calls == ["https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg?w=120&h=90"]


@pytest.mark.asyncio
async def test_media_resource_context_can_probe_original_dmm_aws_image_size(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        if "w=120" in url:
            return _FakeResponse(url, _jpeg_bytes((63, 90))), ""
        return _FakeResponse(url, _jpeg_bytes((1518, 2149))), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/1sdjs00093/1sdjs00093ps.jpg"

        assert await context.probe_original_size(url) == (1518, 2149)
    finally:
        context.close()

    assert calls == ["https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/1sdjs00093/1sdjs00093ps.jpg"]


@pytest.mark.asyncio
async def test_media_resource_context_saves_original_dmm_image_after_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    calls: list[tuple[str, bool]] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append((url, bool(kwargs.get("stream"))))
        if "w=120" in url:
            return _FakeResponse(url, _jpeg_bytes((12, 18))), ""
        return _FakeResponse(url, _jpeg_bytes((80, 120))), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg"
        file_path = tmp_path / "cover.jpg"

        assert await context.probe_size(url) == (12, 18)
        assert await context.save_image(url, file_path, tmp_path) is True

        with Image.open(file_path) as img:
            assert img.size == (80, 120)
    finally:
        context.close()

    assert calls == [
        ("https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg?w=120&h=90", True),
        ("https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg", False),
    ]


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


@pytest.mark.asyncio
async def test_media_resource_context_reuses_probe_size(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, bool]] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append((url, bool(kwargs.get("stream"))))
        return _FakeResponse(url, _jpeg_bytes((120, 180))), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://example.test/poster.jpg"

        assert await context.probe_original_size(url) == (120, 180)
        assert await context.probe_original_size(url) == (120, 180)
    finally:
        context.close()

    assert calls == [("https://example.test/poster.jpg", True)]


@pytest.mark.asyncio
async def test_media_resource_context_reuses_probe_content_length(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str, bool]] = []

    async def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, bool(kwargs.get("stream"))))
        return _FakeResponse(url, _jpeg_bytes((120, 180)), headers={"Content-Length": "23456"}), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://example.test/poster.jpg"

        assert await context.probe_original_size(url) == (120, 180)
        assert await context.get_content_length(url) == 23456
    finally:
        context.close()

    assert calls == [("GET", "https://example.test/poster.jpg", True)]


@pytest.mark.asyncio
async def test_media_resource_context_does_not_reuse_dmm_thumbnail_probe_content_length(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[str, str, bool]] = []

    async def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, bool(kwargs.get("stream"))))
        if "w=120" in url:
            return _FakeResponse(url, _jpeg_bytes((120, 90)), headers={"Content-Length": "1234"}), ""
        return _FakeResponse(url, headers={"Content-Length": "23456"}), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg"

        assert await context.probe_size(url) == (120, 90)
        assert await context.get_content_length(url) == 23456
    finally:
        context.close()

    assert calls == [
        ("GET", "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg?w=120&h=90", True),
        ("GET", "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg", False),
    ]


@pytest.mark.asyncio
async def test_media_resource_context_reuses_full_image_for_content_length(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []
    content = _jpeg_bytes((16, 24))

    async def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url))
        return _FakeResponse(url, content), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://example.test/cover.jpg"

        assert await context.fetch_bytes(url) == content
        assert await context.get_content_length(url) == len(content)
    finally:
        context.close()

    assert calls == [("GET", "https://example.test/cover.jpg")]


@pytest.mark.asyncio
async def test_media_resource_context_reuses_content_length_probe(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    async def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url))
        return _FakeResponse(url, headers={"Content-Length": "12345"}), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://example.test/cover.jpg"

        assert await context.get_content_length(url) == 12345
        assert await context.get_content_length(url) == 12345
    finally:
        context.close()

    assert calls == [("HEAD", "https://example.test/cover.jpg")]


@pytest.mark.asyncio
async def test_media_resource_context_does_not_cache_failed_content_length_probe(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    async def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url))
        return None, "HTTP 503"

    async def fake_sleep(_delay: float):
        return None

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)
    monkeypatch.setattr("mdcx.core.media_resource.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(manager.config, "retry", 1)

    context = MediaResourceContext()
    try:
        url = "https://example.test/cover.jpg"

        assert await context.get_content_length(url) is None
        assert await context.get_content_length(url) is None
    finally:
        context.close()

    assert calls == [("HEAD", "https://example.test/cover.jpg"), ("HEAD", "https://example.test/cover.jpg")]


@pytest.mark.asyncio
async def test_media_resource_context_reuses_dmm_image_validation_without_caching_probe_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    calls: list[tuple[str, bool]] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append((url, bool(kwargs.get("stream"))))
        if "w=120" in url:
            return _FakeResponse(url, _jpeg_bytes((12, 18))), ""
        return _FakeResponse(url, _jpeg_bytes((80, 120))), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg"
        file_path = tmp_path / "cover.jpg"

        assert await context.check_image_url(url) == url
        assert await context.check_image_url(url) == url
        assert await context.save_image(url, file_path, tmp_path) is True

        with Image.open(file_path) as img:
            assert img.size == (80, 120)
    finally:
        context.close()

    assert calls == [
        ("https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg?w=120&h=90", False),
        ("https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg", False),
    ]


@pytest.mark.asyncio
async def test_media_resource_context_rejects_and_caches_dmm_login_redirect(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        return _FakeResponse(
            "https://www.dmm.co.jp/login/",
            b"<html>login</html>",
            headers={"Content-Length": "18", "content-type": "text/html"},
        ), ""

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    context = MediaResourceContext()
    try:
        url = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/1sdjs00093/1sdjs00093ps.jpg"

        assert await context.check_image_url(url) is None
        assert await context.check_image_url(url) is None
    finally:
        context.close()

    assert calls == ["https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/1sdjs00093/1sdjs00093ps.jpg?w=120&h=90"]


@pytest.mark.asyncio
async def test_media_resource_context_does_not_cache_transient_dmm_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        return None, "HTTP 503"

    async def fake_sleep(_delay: float):
        return None

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)
    monkeypatch.setattr("mdcx.core.media_resource.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(manager.config, "retry", 3)

    context = MediaResourceContext()
    try:
        url = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/1sdjs00093/1sdjs00093ps.jpg"

        assert await context.check_image_url(url) is None
        assert await context.check_image_url(url) is None
    finally:
        context.close()

    request_url = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/1sdjs00093/1sdjs00093ps.jpg?w=120&h=90"
    assert calls == [request_url, request_url, request_url, request_url, request_url, request_url]


@pytest.mark.asyncio
async def test_media_resource_context_dmm_validation_uses_configured_retry_count(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []

    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        calls.append(url)
        return None, "HTTP 503"

    async def fake_sleep(_delay: float):
        return None

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)
    monkeypatch.setattr("mdcx.core.media_resource.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(manager.config, "retry", 1)

    context = MediaResourceContext()
    try:
        url = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/1sdjs00093/1sdjs00093ps.jpg"

        assert await context.check_image_url(url) is None
        assert await context.check_image_url(url) is None
    finally:
        context.close()

    request_url = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/1sdjs00093/1sdjs00093ps.jpg?w=120&h=90"
    assert calls == [request_url, request_url]
