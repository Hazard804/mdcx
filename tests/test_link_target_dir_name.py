from pathlib import Path

from mdcx.config.manager import manager
from mdcx.controllers.main_window.main_window import MyMAinWindow


class _DisplayPath:
    def __init__(self, name: str):
        self.name = name


def _make_window() -> MyMAinWindow:
    return MyMAinWindow.__new__(MyMAinWindow)


def test_sanitize_link_dir_name_removes_cross_platform_invalid_chars(monkeypatch):
    monkeypatch.setattr(manager.config, "folder_name_max", 60)
    window = _make_window()

    sanitized, notes = window._sanitize_link_dir_name('bad<>:"/\\\\|?*\r\nname. ')

    assert sanitized == "bad_name"
    assert any("链接目录名已清洗" in note for note in notes)


def test_sanitize_link_dir_name_fallbacks_for_empty_name(monkeypatch):
    monkeypatch.setattr(manager.config, "folder_name_max", 60)
    window = _make_window()

    sanitized, notes = window._sanitize_link_dir_name(' .<>:"/\\\\|?*\r\n')

    assert sanitized == "unnamed"
    assert any("清洗后为空" in note for note in notes)


def test_sanitize_link_dir_name_avoids_windows_reserved_names(monkeypatch):
    monkeypatch.setattr(manager.config, "folder_name_max", 60)
    window = _make_window()

    sanitized, notes = window._sanitize_link_dir_name("CON")

    assert sanitized == "CON_"
    assert any("Windows 保留名" in note for note in notes)


def test_sanitize_link_dir_name_respects_length_limit(monkeypatch):
    monkeypatch.setattr(manager.config, "folder_name_max", 10)
    window = _make_window()

    sanitized, notes = window._sanitize_link_dir_name("abcdefghijklmno")

    assert sanitized == "abcdefghij"
    assert any("已按最大长度截断" in note for note in notes)


def test_build_link_target_path_dedupes_non_empty_conflicting_dirs(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(manager.config, "folder_name_max", 60)
    window = _make_window()
    output_dir = tmp_path / "links"
    existing_dir = output_dir / "a_b"
    existing_dir.mkdir(parents=True)
    (existing_dir / "other.mp4").write_text("existing", encoding="utf-8")

    target_path, notes = window._build_link_target_path(
        source_path=tmp_path / "source.mp4",
        output_dir=output_dir,
        display_path=_DisplayPath("a:b.mp4"),
        group_in_named_dir=True,
    )

    assert target_path == output_dir / "a_b_2" / "a:b.mp4"
    assert any("自动避让冲突" in note for note in notes)


def test_build_link_target_path_reuses_existing_target_dir_when_same_file_exists(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(manager.config, "folder_name_max", 60)
    window = _make_window()
    output_dir = tmp_path / "links"
    existing_dir = output_dir / "movie"
    existing_dir.mkdir(parents=True)
    (existing_dir / "movie.mp4").write_text("existing", encoding="utf-8")

    target_path, notes = window._build_link_target_path(
        source_path=tmp_path / "source.mp4",
        output_dir=output_dir,
        display_path=tmp_path / "movie.mp4",
        group_in_named_dir=True,
    )

    assert target_path == output_dir / "movie" / "movie.mp4"
    assert not any("自动避让冲突" in note for note in notes)
