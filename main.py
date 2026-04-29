#!/usr/bin/env python3
import os
import platform
import sys

from PIL import ImageFile
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from mdcx.consts import IS_DOCKER, IS_MAC, IS_NFC, IS_PYINSTALLER, IS_WINDOWS, MAIN_PATH
from mdcx.controllers.main_window.main_window import MyMAinWindow
from mdcx.controllers.main_window.style import apply_application_palette
from mdcx.utils.video import VIDEO_BACKEND

ImageFile.LOAD_TRUNCATED_IMAGES = True


def show_constants():
    """显示所有运行时常量"""
    constants = {
        "MAIN_PATH": MAIN_PATH,
        "IS_WINDOWS": IS_WINDOWS,
        "IS_MAC": IS_MAC,
        "IS_DOCKER": IS_DOCKER,
        "IS_NFC": IS_NFC,
        "IS_PYINSTALLER": IS_PYINSTALLER,
        "VIDEO_BACKEND": VIDEO_BACKEND,
    }
    print("Run time constants:")
    for key, value in constants.items():
        print(f"\t{key}: {value}")


show_constants()


if os.path.isfile("highdpi_passthrough"):
    # Qt6 默认启用高 DPI，这里仅保留非整数缩放策略开关，避免 150% 缩放被取整。
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

app = QApplication(sys.argv)
app.setStyle("Fusion")
apply_application_palette(False)
if platform.system() != "Windows":
    app.setWindowIcon(QIcon("resources/Img/MDCx.ico"))  # 设置任务栏图标
ui = MyMAinWindow()
ui.show()
app.installEventFilter(ui)
# newWin2 = CutWindow()
try:
    sys.exit(app.exec())
except Exception as e:
    print(e)
