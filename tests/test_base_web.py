from pathlib import Path

import pytest

import mdcx.base.web as base_web
import mdcx.core.web as core_web
from mdcx.config.enums import DownloadableFile
from mdcx.config.manager import manager


class _FakeResponse:
    def __init__(self, url: str, headers: dict[str, str] | None = None, content: bytes = b"", status_code: int = 200):
        self.url = url
        self.headers = headers or {}
        self.content = content
        self.status_code = status_code


def test_normalize_media_url_removes_empty_query_and_probe_params():
    assert (
        base_web.normalize_media_url(
            "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg?&&&",
        )
        == "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg"
    )
    assert (
        base_web.normalize_media_url(
            "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg?&w=120&h=90&&",
            strip_dmm_probe_params=True,
        )
        == "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg"
    )


def test_normalize_media_url_collapses_duplicate_slashes_for_dmm_hosts():
    assert (
        base_web.normalize_media_url(
            "https://awsimgsrc.dmm.co.jp/pics_dig//digital/video/ssis00100/ssis00100pl.jpg",
        )
        == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00100/ssis00100pl.jpg"
    )
    assert (
        base_web.normalize_media_url(
            "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00100/ssis00100pl.jpg",
        )
        == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00100/ssis00100pl.jpg"
    )


@pytest.mark.asyncio
async def test_check_url_cleans_dmm_probe_params_from_final_url(monkeypatch: pytest.MonkeyPatch):
    async def fake_request(method: str, url: str, **kwargs):
        assert method == "GET"
        assert "w=120" in url
        assert "h=90" in url
        return (
            _FakeResponse(
                "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg?w=120&h=90&&",
                headers={"Content-Length": "4096"},
            ),
            "",
        )

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    result = await base_web.check_url("https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg?&&&")

    assert result == "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg"


@pytest.mark.asyncio
async def test_check_url_uses_config_retry_for_dmm_images(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []

    async def fake_request(method: str, url: str, **kwargs):
        calls.append(kwargs)
        return None, "连接超时"

    async def fake_sleep(delay: float):
        return None

    monkeypatch.setattr(manager.config, "retry", 4)
    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)
    monkeypatch.setattr(base_web.asyncio, "sleep", fake_sleep)

    result = await base_web.check_url("https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg")

    assert result is None
    assert len(calls) == 4
    assert all(call["retry_count"] == 1 for call in calls)


@pytest.mark.asyncio
async def test_get_url_content_length_uses_get_for_dmm_images(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    async def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url))
        return (_FakeResponse(url, headers={"Content-Length": "12345"}), "")

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)

    length = await base_web.get_url_content_length(
        "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg?&&"
    )

    assert length == 12345
    assert calls == [
        ("GET", "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/cjod499/cjod499ps.jpg"),
    ]


@pytest.mark.asyncio
async def test_download_extrafanart_task_uses_direct_get_for_non_dmm_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    calls: list[tuple[str, str]] = []

    async def fake_get_content(url: str, **kwargs):
        calls.append(("get_content", url))
        return b"fake-image", ""

    async def fake_download(url: str, file_path: Path):
        calls.append(("download", url))
        return False

    async def fake_check_pic_async(path: Path):
        return (800, 1200)

    monkeypatch.setattr(manager.computed.async_client, "get_content", fake_get_content)
    monkeypatch.setattr(manager.computed.async_client, "download", fake_download)
    monkeypatch.setattr(base_web, "check_pic_async", fake_check_pic_async)

    result = await base_web.download_extrafanart_task(
        (
            "https://example.test/images/fanart1.jpg",
            tmp_path / "fanart1.jpg",
            tmp_path,
            "fanart1.jpg",
        )
    )

    assert result is True
    assert calls == [
        ("get_content", "https://example.test/images/fanart1.jpg"),
    ]


@pytest.mark.asyncio
async def test_download_extrafanart_task_uses_single_get_for_dmm_image(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    calls: list[tuple[str, str]] = []

    async def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url))
        return _FakeResponse(url, content=b"fake-image"), ""

    async def fake_check_pic_async(path: Path):
        return (800, 1200)

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)
    monkeypatch.setattr(base_web, "check_pic_async", fake_check_pic_async)

    result = await base_web.download_extrafanart_task(
        (
            "https://pics.dmm.co.jp/digital/video/pred00816/pred00816jp-1.jpg",
            tmp_path / "fanart1.jpg",
            tmp_path,
            "fanart1.jpg",
        )
    )

    assert result is True
    assert calls == [
        ("GET", "https://pics.dmm.co.jp/digital/video/pred00816/pred00816jp-1.jpg"),
    ]


@pytest.mark.asyncio
async def test_download_extrafanart_task_skips_invalid_dmm_placeholder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    calls: list[tuple[str, str]] = []

    async def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url))
        return _FakeResponse("https://pics.dmm.co.jp/digital/video/pred00816/now_printing.jpg", content=b"fake"), ""

    async def fake_check_pic_async(path: Path):
        raise AssertionError("无效 DMM 图片不应写入后再验图")

    monkeypatch.setattr(manager.computed.async_client, "request", fake_request)
    monkeypatch.setattr(base_web, "check_pic_async", fake_check_pic_async)

    result = await base_web.download_extrafanart_task(
        (
            "https://pics.dmm.co.jp/digital/video/pred00816/pred00816jp-1.jpg",
            tmp_path / "fanart1.jpg",
            tmp_path,
            "fanart1.jpg",
        )
    )

    assert result is False
    assert calls == [("GET", "https://pics.dmm.co.jp/digital/video/pred00816/pred00816jp-1.jpg")]


@pytest.mark.asyncio
async def test_extrafanart_download_does_not_gate_batch_on_first_image_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    calls: list[str] = []

    async def fake_download_extrafanart_task(task):
        calls.append(task[0])
        return task[0].endswith("fanart2.jpg")

    monkeypatch.setattr(manager.config, "download_files", [DownloadableFile.EXTRAFANART])
    monkeypatch.setattr(manager.config, "keep_files", [])
    monkeypatch.setattr(core_web, "download_extrafanart_task", fake_download_extrafanart_task)

    result = await core_web.extrafanart_download(
        ["https://example.test/fanart1.jpg", "https://example.test/fanart2.jpg"],
        "test",
        tmp_path,
    )

    assert result is False
    assert calls == ["https://example.test/fanart1.jpg", "https://example.test/fanart2.jpg"]
