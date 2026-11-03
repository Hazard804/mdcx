"""裁剪窗口水印选项的回归测试。

LTX 破解必须回显为专属「LTX」选项，不能被退化成「破解」，否则重新裁剪会把
封面上的 LTX 水印覆盖成普通破解水印。
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6", reason="裁剪窗口依赖 PyQt6")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from mdcx.config.enums import MarkType  # noqa: E402
from mdcx.config.manager import manager  # noqa: E402
from mdcx.controllers.cut_window import CutWindow  # noqa: E402
from mdcx.models.types import FileInfo  # noqa: E402

POSTER_PATH = Path(__file__).resolve().parent.parent / "resources" / "Img" / "default-poster.jpg"

# QApplication 必须在整个测试会话内保持存活：mdcx.signals 里的 QObject 绑定在它上面，
# 一旦被回收，后续测试访问 signal 会抛 "wrapped C/C++ object has been deleted"。
_APP = None


@pytest.fixture(scope="session")
def qapp():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    yield _APP


@pytest.fixture
def cut_window(qapp, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "poster_mark", 1)
    monkeypatch.setattr(
        manager.config,
        "mark_type",
        [MarkType.SUB, MarkType.UMR, MarkType.LEAK, MarkType.UNCENSORED, MarkType.HD],
    )
    return CutWindow(_FakeMainWindow())


class _FakeMainWindow(QWidget):
    """裁剪窗口只用到父窗口的 dark_mode 与文件对话框 options。"""

    def __init__(self):
        super().__init__()
        self.dark_mode = False
        self.options = None


def _file_info(destroyed: str, mosaic: str) -> FileInfo:
    file_info = FileInfo.empty()
    file_info.number = "MIDV-999"
    file_info.mosaic = mosaic
    file_info.destroyed = destroyed
    return file_info


@pytest.mark.parametrize(
    ("destroyed", "mosaic", "expected"),
    [
        ("-LTX", "无码破解", "radioButton_add_ltx"),
        ("-破解", "无码破解", "radioButton_add_umr"),
        ("", "无码", "radioButton_add_uncensored"),
    ],
)
def test_cut_window_preselects_matching_watermark(cut_window, destroyed: str, mosaic: str, expected: str):
    cut_window.showimage(POSTER_PATH, _file_info(destroyed, mosaic))

    selected = [
        name
        for name in ("radioButton_add_ltx", "radioButton_add_umr", "radioButton_add_uncensored")
        if getattr(cut_window.Ui, name).isChecked()
    ]
    assert selected == [expected]


def test_ltx_and_umr_options_are_mutually_exclusive(cut_window):
    cut_window.Ui.radioButton_add_ltx.setChecked(True)

    assert cut_window.Ui.radioButton_add_umr.isChecked() is False
