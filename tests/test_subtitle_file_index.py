import pytest

from mdcx.tools.subtitle import _dedupe_existing_paths
from mdcx.utils.file import build_file_name_index, find_file_from_index


@pytest.mark.asyncio
async def test_build_file_name_index_finds_subtitle_in_nested_folder(tmp_path):
    subtitle_folder = tmp_path / "字幕包"
    nested_folder = subtitle_folder / "maker" / "series"
    nested_folder.mkdir(parents=True)
    subtitle_path = nested_folder / "ABC-123.srt"
    subtitle_path.write_text("1\n", encoding="utf-8")

    file_name_index = await build_file_name_index(subtitle_folder)

    assert find_file_from_index(file_name_index, ("ABC-123.srt",)) == subtitle_path
    assert find_file_from_index(file_name_index, ("abc-123.srt",)) == subtitle_path


def test_dedupe_existing_paths_keeps_path_order(tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"

    assert _dedupe_existing_paths([first, second, first]) == [first, second]
