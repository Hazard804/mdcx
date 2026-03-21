from pathlib import Path

import pytest

from mdcx.config.manager import manager
from mdcx.core.file import _generate_file_name, _get_folder_path
from mdcx.models.types import CrawlersResult, FileInfo


def _build_file_info() -> FileInfo:
    file_info = FileInfo.empty()
    file_info.number = "ABC-123"
    file_info.file_path = Path("D:/Media/Input/ABC-123.mp4")
    file_info.folder_path = file_info.file_path.parent
    file_info.file_name = "ABC-123"
    file_info.definition = "4K"
    file_info.wuma = "-无码"
    return file_info


def _build_result() -> CrawlersResult:
    result = CrawlersResult.empty()
    result.number = "ABC-123"
    result.release = "2024-01-01"
    return result


@pytest.mark.parametrize(
    ("folder_moword", "file_moword", "folder_hd", "file_hd", "expected_folder_name", "expected_file_name"),
    [
        (False, True, False, True, "ABC-123", "ABC-123-无码-4K"),
        (True, False, True, False, "ABC-123-无码-4K", "ABC-123"),
    ],
)
def test_name_flags_control_folder_and_file_independently(
    monkeypatch: pytest.MonkeyPatch,
    folder_moword: bool,
    file_moword: bool,
    folder_hd: bool,
    file_hd: bool,
    expected_folder_name: str,
    expected_file_name: str,
):
    file_info = _build_file_info()
    result = _build_result()

    monkeypatch.setattr(manager.config, "folder_name", "number")
    monkeypatch.setattr(manager.config, "naming_file", "number")
    monkeypatch.setattr(manager.config, "folder_moword", folder_moword)
    monkeypatch.setattr(manager.config, "file_moword", file_moword)
    monkeypatch.setattr(manager.config, "folder_hd", folder_hd)
    monkeypatch.setattr(manager.config, "file_hd", file_hd)
    monkeypatch.setattr(manager.config, "folder_cnword", False)
    monkeypatch.setattr(manager.config, "file_cnword", False)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "success_file_rename", True)
    monkeypatch.setattr(manager.config, "main_mode", 1)
    monkeypatch.setattr(manager.config, "soft_link", 0)

    _, folder_name = _get_folder_path(Path("D:/Media/Output"), file_info, result)
    file_name = _generate_file_name("", file_info, result)

    assert folder_name == expected_folder_name
    assert file_name == expected_file_name
