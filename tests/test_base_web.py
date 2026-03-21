from pathlib import Path

import pytest

import mdcx.base.web as base_web
from mdcx.config.manager import manager


@pytest.mark.asyncio
async def test_download_extrafanart_task_uses_direct_get_without_head(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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
            "https://pics.dmm.co.jp/digital/video/pred00816/pred00816jp-1.jpg",
            tmp_path / "fanart1.jpg",
            tmp_path,
            "fanart1.jpg",
        )
    )

    assert result is True
    assert calls == [("get_content", "https://pics.dmm.co.jp/digital/video/pred00816/pred00816jp-1.jpg")]
