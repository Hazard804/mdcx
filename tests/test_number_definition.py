from pathlib import Path

import pytest

from mdcx.config.manager import manager
from mdcx.core.utils import get_video_size
from mdcx.number import get_file_number


def test_get_file_number_prefers_longer_escape_strings():
    escape_strings = ["4k2", ".com@", "489155.com@"]

    assert get_file_number(r"D:/test/489155.com@MXGS-992.mp4", escape_strings) == "MXGS-992"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_path", "file_number", "custom_strings", "expected_definition"),
    [
        (Path("D:/test/4k2.com@MXGS-993.mp4"), "MXGS-993", ["4k2", ".com@"], ""),
        (Path("D:/test/HUHD-111.mp4"), "HUHD-111", [], ""),
        (Path("D:/test/4k2.com@MXGS-993-4K.mp4"), "MXGS-993", ["4k2", ".com@"], "4K"),
        (Path("D:/test/HUHD-111-UHD.mp4"), "HUHD-111", [], "4K"),
    ],
)
async def test_get_video_size_path_strips_noise_and_number_tokens(
    monkeypatch: pytest.MonkeyPatch,
    file_path: Path,
    file_number: str,
    custom_strings: list[str],
    expected_definition: str,
):
    monkeypatch.setattr(manager.config, "hd_get", "path")
    monkeypatch.setattr(manager.config, "hd_name", "height")
    monkeypatch.setattr(manager.config, "string", custom_strings)
    monkeypatch.setattr(manager.config, "no_escape", [])

    definition, codec = await get_video_size(file_path, file_number)

    assert definition == expected_definition
    assert codec == ""
