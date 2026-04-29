from pathlib import Path

import pytest

from mdcx.config.manager import manager
from mdcx.core.file import get_file_info_v2
from mdcx.core.utils import get_video_size
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.number import get_file_number, is_uncensored


def test_get_file_number_prefers_longer_escape_strings():
    escape_strings = ["4k2", ".com@", "489155.com@"]

    assert get_file_number(r"D:/test/489155.com@MXGS-992.mp4", escape_strings) == "MXGS-992"


@pytest.mark.parametrize(
    ("raw_number", "expected_number"),
    [
        (r"D:/test/100225_100.mp4", "100225_100"),
        (r"D:/test/111111_111.mp4", "111111_111"),
        (r"D:/test/111111-111.mp4", "111111-111"),
        (r"D:/test/1pondo_031926_001.mp4", "031926_001"),
        (r"D:/test/caribbeancom-031426-001.mp4", "031426-001"),
        (r"D:/test/pacopacomama_031726_100.mp4", "031726_100"),
        (r"D:/test/10musume_031426_01.mp4", "031426_01"),
    ],
)
def test_get_file_number_normalizes_uncensored_digit_numbers(raw_number: str, expected_number: str):
    assert get_file_number(raw_number, []) == expected_number
    assert is_uncensored(expected_number) is True


@pytest.mark.parametrize(
    ("raw_number", "expected_number"),
    [
        (r"D:/test/LUXU-1488.mp4", "259LUXU-1488"),
        (r"D:/test/SCUTE-953.mp4", "229SCUTE-953"),
        (r"D:/test/MAAN-673.mp4", "300MAAN-673"),
    ],
)
def test_get_file_number_normalizes_suren_numbers(raw_number: str, expected_number: str):
    assert get_file_number(raw_number, []) == expected_number


@pytest.mark.parametrize(
    ("raw_number", "expected_number"),
    [
        (r"D:/test/DANDY-818.mp4", "DANDY-818"),
        (r"D:/test/KIWVR-254.mp4", "KIWVR-254"),
    ],
)
def test_get_file_number_keeps_non_suren_prefixes(raw_number: str, expected_number: str):
    assert get_file_number(raw_number, []) == expected_number


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_path", "file_number", "custom_strings", "expected_definition"),
    [
        (Path("D:/test/4k2.com@MXGS-993.mp4"), "MXGS-993", ["4k2", ".com@"], ""),
        (Path("D:/test/4k3.com@SSNI-1000.mp4"), "SSNI-1000", ["4k3.com@"], ""),
        (Path("D:/test/HUHD-111.mp4"), "HUHD-111", [], ""),
        (Path("D:/test/SSNI-100-1080P.mp4"), "SSNI-100", ["1080p", "720p"], "1080P"),
        (Path("D:/test/1080PSSNI-100.mp4"), "SSNI-100", ["1080p", "720p"], "1080P"),
        (Path("D:/test/SSNI-1001080P.mp4"), "SSNI-100", ["1080p", "720p"], "1080P"),
        (Path("D:/test/SSNI-100-720P.mp4"), "SSNI-100", ["1080p", "720p"], "720P"),
        (Path("D:/test/SSNI-100-HD.mp4"), "SSNI-100", ["-HD"], "720P"),
        (Path("D:/test/SSNI-100-FHD.mp4"), "SSNI-100", ["fhd"], "1080P"),
        (Path("D:/test/SSNI-100-QHD.mp4"), "SSNI-100", ["qhd"], "1440P"),
        (Path("D:/test/SSNI-100-UHD.mp4"), "SSNI-100", ["uhd"], "4K"),
        (Path("D:/test/SSNI-100-8K.mp4"), "SSNI-100", ["8k"], "8K"),
        (Path("D:/test/4k2.com@MXGS-993-4K.mp4"), "MXGS-993", ["4k2", ".com@"], "4K"),
        (Path("D:/test/4k3.com@SSNI-1000-4K.mp4"), "SSNI-1000", ["4k3.com@"], "4K"),
        (Path("D:/test/HUHD-111-UHD.mp4"), "HUHD-111", [], "4K"),
        (Path("D:/test/IPZZ-841_4K60FPS.mp4"), "IPZZ-841", [], "4K"),
        (Path("D:/test/IPZZ-841_4KS.mp4"), "IPZZ-841", [], "4K"),
        (Path("D:/test/IPZZ-841_4k60fps.mp4"), "IPZZ-841", [], "4K"),
        (Path("D:/test/IPZZ-841_4ks.mp4"), "IPZZ-841", [], "4K"),
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_path", "expected_number"),
    [
        (Path("D:/test/100225_100.mp4"), "100225_100"),
        (Path("D:/test/1pondo_031926_001.mp4"), "031926_001"),
        (Path("D:/test/10musume_031426_01.mp4"), "031426_01"),
    ],
)
async def test_get_file_info_marks_uncensored_digit_numbers(file_path: Path, expected_number: str):
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(file_path, copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == expected_number
    assert file_info.mosaic == "无码"


@pytest.mark.asyncio
async def test_get_file_info_marks_restored_as_umr_case_insensitive():
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(Path("D:/test/ABF-131.RESTORED.mp4"), copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == "ABF-131"
    assert file_info.destroyed == manager.config.umr_style
    assert file_info.mosaic == "无码破解"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_path", "expected_number", "expected_short_number"),
    [
        (Path("D:/test/LUXU-1488.mp4"), "259LUXU-1488", "LUXU-1488"),
        (Path("D:/test/SCUTE-953.mp4"), "229SCUTE-953", "SCUTE-953"),
        (Path("D:/test/259LUXU-1488.mp4"), "259LUXU-1488", "LUXU-1488"),
    ],
)
async def test_get_file_info_extracts_suren_short_number(
    file_path: Path, expected_number: str, expected_short_number: str
):
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(file_path, copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == expected_number
    assert file_info.short_number == expected_short_number


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_path", "expected_number"),
    [
        (Path("D:/test/DANDY-818.mp4"), "DANDY-818"),
        (Path("D:/test/KIWVR-254.mp4"), "KIWVR-254"),
    ],
)
async def test_get_file_info_does_not_extract_short_number_for_non_suren_prefixes(
    file_path: Path, expected_number: str
):
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(file_path, copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == expected_number
    assert file_info.short_number == ""
