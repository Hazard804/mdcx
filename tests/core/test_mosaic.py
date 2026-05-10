from pathlib import Path

import pytest

from mdcx.config.enums import DownloadableFile, MarkType
from mdcx.config.manager import manager
from mdcx.core import image as image_core
from mdcx.core.mosaic import (
    has_leak_mark,
    has_uncensored_mark,
    normalize_mosaic,
)
from mdcx.models.types import FileInfo, OtherInfo


@pytest.mark.parametrize(
    ("raw", "expected", "leak", "uncensored"),
    [
        ("有碼", "有码", False, False),
        ("無碼", "无码", False, True),
        ("無修正", "无码", False, True),
        ("流出", "流出", True, False),
        ("無碼流出", "无码流出", True, True),
        ("无码流出", "无码流出", True, True),
        ("無碼破解", "无码破解", False, True),
    ],
)
def test_mosaic_normalization_keeps_postprocess_attributes(raw: str, expected: str, leak: bool, uncensored: bool):
    assert normalize_mosaic(raw) == expected
    assert has_leak_mark(raw) is leak
    assert has_uncensored_mark(raw) is uncensored


@pytest.mark.asyncio
async def test_add_mark_handles_plain_leak(monkeypatch: pytest.MonkeyPatch):
    records: list[list[str]] = []

    async def fake_add_mark_thread(_path: Path, mark_list: list[str]):
        records.append(mark_list)

    monkeypatch.setattr(image_core, "add_mark_thread", fake_add_mark_thread)
    monkeypatch.setattr(manager.config, "mark_type", [MarkType.LEAK, MarkType.UNCENSORED])
    monkeypatch.setattr(manager.config, "download_files", [DownloadableFile.POSTER])
    monkeypatch.setattr(manager.config, "poster_mark", 1)
    monkeypatch.setattr(manager.config, "thumb_mark", 0)
    monkeypatch.setattr(manager.config, "fanart_mark", 0)

    other = OtherInfo.empty()
    other.poster_marked = False
    other.poster_path = Path("poster.jpg")

    await image_core.add_mark(other, FileInfo.empty(), "流出")

    assert records == [["流出"]]


@pytest.mark.asyncio
async def test_add_mark_falls_back_to_uncensored_for_uncensored_leak(
    monkeypatch: pytest.MonkeyPatch,
):
    records: list[list[str]] = []

    async def fake_add_mark_thread(_path: Path, mark_list: list[str]):
        records.append(mark_list)

    monkeypatch.setattr(image_core, "add_mark_thread", fake_add_mark_thread)
    monkeypatch.setattr(manager.config, "mark_type", [MarkType.UNCENSORED])
    monkeypatch.setattr(manager.config, "download_files", [DownloadableFile.POSTER])
    monkeypatch.setattr(manager.config, "poster_mark", 1)
    monkeypatch.setattr(manager.config, "thumb_mark", 0)
    monkeypatch.setattr(manager.config, "fanart_mark", 0)

    other = OtherInfo.empty()
    other.poster_marked = False
    other.poster_path = Path("poster.jpg")

    await image_core.add_mark(other, FileInfo.empty(), "无码流出")

    assert records == [["无码"]]
