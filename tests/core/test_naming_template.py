from pathlib import Path

import pytest

from mdcx.config.manager import manager
from mdcx.core.file import _generate_file_name, _get_folder_path
from mdcx.core.naming import NameRenderOptions, NamingTarget, render_name
from mdcx.models.types import CrawlersResult, FileInfo


def _build_file_info() -> FileInfo:
    file_info = FileInfo.empty()
    file_info.number = "ABC-123"
    file_info.file_path = Path("D:/Media/Input/ABC-123.mp4")
    file_info.folder_path = file_info.file_path.parent
    file_info.file_name = "ABC-123"
    file_info.definition = "1080P"
    return file_info


def _build_result() -> CrawlersResult:
    result = CrawlersResult.empty()
    result.number = "ABC-123"
    result.title = "中文标题"
    result.originaltitle = "Original Title"
    result.release = "2024-01-02"
    result.letters = "ABC"
    return result


def test_empty_field_does_not_remove_user_written_wrappers():
    file_info = _build_file_info()
    result = _build_result()
    result.studio = ""

    rendered = render_name(
        "{{ number }} ({{ filename }}) [{{ studio }}], {{ originaltitle }}, {{ definition }}",
        file_info,
        result,
        NameRenderOptions(target=NamingTarget.FILE),
    )

    assert rendered.text == "ABC-123 (ABC-123) [], Original Title, 1080P"


def test_jinja_if_segment_is_rendered_only_when_field_has_value():
    file_info = _build_file_info()
    result = _build_result()

    rendered_empty = render_name(
        "{{ number }}{% if studio %} [{{ studio }}]{% endif %}",
        file_info,
        result,
        NameRenderOptions(target=NamingTarget.FILE),
    )
    result.studio = "Studio A"
    rendered_present = render_name(
        "{{ number }}{% if studio %} [{{ studio }}]{% endif %}",
        file_info,
        result,
        NameRenderOptions(target=NamingTarget.FILE),
    )

    assert rendered_empty.text == "ABC-123"
    assert rendered_present.text == "ABC-123 [Studio A]"


def test_unknown_template_field_raises_clear_error():
    file_info = _build_file_info()
    result = _build_result()

    with pytest.raises(Exception, match="studioo"):
        render_name(
            "{{ number }} {{ studioo }}",
            file_info,
            result,
            NameRenderOptions(target=NamingTarget.FILE),
        )


def test_number_title_duplicate_is_collapsed_for_media_title():
    file_info = _build_file_info()
    result = _build_result()
    result.title = "ABC-123"

    rendered = render_name(
        "[{{ number }}]{% if title and title != number %}{{ title }}{% endif %}",
        file_info,
        result,
        NameRenderOptions(target=NamingTarget.NFO_TITLE),
    )

    assert rendered.text == "[ABC-123]"


def test_plain_legacy_text_is_not_interpreted_as_fields(monkeypatch):
    file_info = _build_file_info()
    result = _build_result()
    file_info.c_word = "-中字"

    monkeypatch.setattr(manager.config, "suffix_sort", [])
    rendered = render_name(
        "numbercnword originaltitle",
        file_info,
        result,
        NameRenderOptions(target=NamingTarget.FILE),
    )

    assert rendered.text == "numbercnword originaltitle"


def test_folder_template_keeps_template_separator_and_escapes_field_separator(monkeypatch):
    file_info = _build_file_info()
    result = _build_result()
    result.title = "A/B"

    monkeypatch.setattr(manager.config, "folder_name", "{{ letters }}/{{ title }}")
    monkeypatch.setattr(manager.config, "folder_name_max", 60)
    monkeypatch.setattr(manager.config, "folder_moword", False)
    monkeypatch.setattr(manager.config, "folder_hd", False)
    monkeypatch.setattr(manager.config, "folder_cnword", False)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "main_mode", 1)
    monkeypatch.setattr(manager.config, "soft_link", 0)

    _, folder_name = _get_folder_path(Path("D:/Media/Output"), file_info, result)

    assert folder_name == "ABC/A-B"


def test_long_originaltitle_is_truncated_but_number_is_kept(monkeypatch):
    file_info = _build_file_info()
    result = _build_result()
    result.originaltitle = "很长的原标题" * 20

    monkeypatch.setattr(manager.config, "folder_name", "{{ number }} {{ originaltitle }}")
    monkeypatch.setattr(manager.config, "folder_name_max", 32)
    monkeypatch.setattr(manager.config, "folder_moword", False)
    monkeypatch.setattr(manager.config, "folder_hd", False)
    monkeypatch.setattr(manager.config, "folder_cnword", False)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "main_mode", 1)
    monkeypatch.setattr(manager.config, "soft_link", 0)

    _, folder_name = _get_folder_path(Path("D:/Media/Output"), file_info, result)

    assert folder_name.startswith("ABC-123 ")
    assert len(folder_name) <= 32


def test_generate_file_name_uses_new_template(monkeypatch):
    file_info = _build_file_info()
    result = _build_result()
    result.studio = ""

    monkeypatch.setattr(
        manager.config,
        "naming_file",
        "{{ number }}{% if studio %} [{{ studio }}]{% endif %} {{ definition }}",
    )
    monkeypatch.setattr(manager.config, "file_name_max", 60)
    monkeypatch.setattr(manager.config, "file_moword", False)
    monkeypatch.setattr(manager.config, "file_hd", False)
    monkeypatch.setattr(manager.config, "file_cnword", False)
    monkeypatch.setattr(manager.config, "prevent_char", "")
    monkeypatch.setattr(manager.config, "success_file_rename", True)
    monkeypatch.setattr(manager.config, "main_mode", 1)

    assert _generate_file_name("", file_info, result) == "ABC-123 1080P"
