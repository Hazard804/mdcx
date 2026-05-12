import importlib.util
import sys
import types

import pytest

if importlib.util.find_spec("PyQt6") is None:
    pyqt6 = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")

    class QObject:
        pass

    class _Signal:
        def connect(self, *_args, **_kwargs):
            return None

        def emit(self, *_args, **_kwargs):
            return None

    def pyqtSignal(*_args, **_kwargs):
        return _Signal()

    qtcore.QObject = QObject
    qtcore.pyqtSignal = pyqtSignal
    sys.modules["PyQt6"] = pyqt6
    sys.modules["PyQt6.QtCore"] = qtcore


pytestmark = pytest.mark.skipif(sys.version_info < (3, 13), reason="项目配置模型需要 Python 3.13+")


def test_parse_media_paths_supports_english_and_chinese_semicolons(tmp_path):
    from mdcx.config.extend import parse_media_paths

    first = tmp_path / "first"
    second = tmp_path / "second"
    third = tmp_path / "third"

    paths = parse_media_paths(f' "{first}" ; {second} ； {third} ; {second} ')

    assert paths == [first, second, third]


def test_get_movie_path_setting_uses_file_owner_root_for_multi_paths(monkeypatch, tmp_path):
    from mdcx.config.extend import get_movie_path_setting
    from mdcx.config.manager import manager

    first = tmp_path / "first"
    second = tmp_path / "second"
    file_path = second / "sub" / "MIAA-001.mp4"

    monkeypatch.setattr(manager.config, "media_path", f"{first};{second}")
    monkeypatch.setattr(manager.config, "softlink_path", "softlink_end_folder_name")
    monkeypatch.setattr(manager.config, "success_output_folder", "JAV_output/end_folder_name")
    monkeypatch.setattr(manager.config, "failed_output_folder", "failed/end_folder_name")
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart")
    monkeypatch.setattr(manager.config, "folders", ["failed", "JAV_output"])
    monkeypatch.setattr(manager.config, "scrape_softlink_path", False)

    setting = get_movie_path_setting(file_path)

    assert setting.movie_path == second
    assert setting.movie_paths == [first, second]
    assert setting.success_folder == second / "JAV_output" / second.name
    assert setting.failed_folder == second / "failed" / second.name
    assert setting.ignore_dirs == [second / "failed", second / "JAV_output"]


def test_get_movie_path_setting_ignores_unrelated_first_folder_name_file(monkeypatch, tmp_path):
    from mdcx.config.extend import get_movie_path_setting
    from mdcx.config.manager import manager

    movie_path = tmp_path / "movie"
    file_path = tmp_path / "other" / "MIAA-001.mp4"

    monkeypatch.setattr(manager.config, "media_path", str(movie_path))
    monkeypatch.setattr(manager.config, "softlink_path", "softlink")
    monkeypatch.setattr(manager.config, "success_output_folder", "JAV_output/first_folder_name")
    monkeypatch.setattr(manager.config, "failed_output_folder", "failed/first_folder_name")
    monkeypatch.setattr(manager.config, "extrafanart_folder", "extrafanart")
    monkeypatch.setattr(manager.config, "folders", [])
    monkeypatch.setattr(manager.config, "scrape_softlink_path", False)

    setting = get_movie_path_setting(file_path)

    assert setting.success_folder == movie_path / "JAV_output"
    assert setting.failed_folder == movie_path / "failed"
