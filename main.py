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

# --------------------------
# Qt6 禁用系统DPI缩放（必须在 QApplication 实例化前设置）
# --------------------------
# 1. 禁用 Qt 自动高 DPI 缩放
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
# 2. 强制缩放因子为 1.0
os.environ["QT_SCALE_FACTOR"] = "1"
# 3. 禁用自动屏幕缩放因子
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
# 4. 强制字体 DPI 为 96（标准屏幕）
os.environ["QT_FONT_DPI"] = "96"
# 5. 设置缩放策略为 PassThrough（避免取整）
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

# --------------------------
# 创建QApplication实例及后续逻辑
# --------------------------
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
