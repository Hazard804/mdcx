import os
import re
import shutil
import threading
import time
import traceback
import webbrowser
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from PyQt6.QtCore import QEvent, QItemSelectionModel, QPoint, QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCursor, QGuiApplication, QHoverEvent, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QTreeWidgetItem,
    QWidget,
)

from mdcx.base.file import (
    check_and_clean_files,
    get_success_list,
    movie_lists,
    newtdisk_creat_symlink,
    save_remain_list,
    save_success_list,
)
from mdcx.base.image import add_del_extrafanart_copy
from mdcx.base.video import add_del_extras, add_del_theme_videos
from mdcx.base.web import check_theporndb_api_token, check_version
from mdcx.base.web_sync import get_text_sync
from mdcx.config.enums import NfoInclude, Switch, Website
from mdcx.config.extend import deal_url, get_movie_path_setting
from mdcx.config.manager import manager
from mdcx.config.resources import resources
from mdcx.consts import GITHUB_ISSUES_URL, GITHUB_RELEASES_URL, IS_WINDOWS, LOCAL_VERSION
from mdcx.core.network_check import run_network_check
from mdcx.core.nfo import write_nfo
from mdcx.core.scraper import again_search, get_remain_list, start_new_scrape
from mdcx.crawlers.fc2ppvdb import cookie_str_to_dict, fetch_article_info_with_warmup
from mdcx.image import get_pixmap
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.models.log_buffer import LogBuffer
from mdcx.models.types import CrawlersResult, FileInfo, OtherInfo, ShowData
from mdcx.signals import signal_qt
from mdcx.tools.actress_db import ActressDB
from mdcx.tools.emby_actor_image import update_emby_actor_photo
from mdcx.tools.emby_actor_info import creat_kodi_actors, show_emby_actor_list, update_emby_actor_info
from mdcx.tools.missing import check_missing_number
from mdcx.tools.subtitle import add_sub_for_all_video
from mdcx.utils import (
    add_html,
    add_html_plain_text,
    executor,
    get_current_time,
    get_used_time,
    kill_a_thread,
    split_path,
)
from mdcx.utils.file import (
    create_hardlink_sync,
    create_symlink_sync,
    delete_file_sync,
    open_file_thread,
    resolve_link_source_sync,
    resolve_success_record_source_sync,
)
from mdcx.views.MDCx import Ui_MDCx

from ..cut_window import CutWindow
from .handlers import show_netstatus
from .init import Init_QSystemTrayIcon, Init_Singal, Init_Ui, init_QTreeWidget
from .load_config import load_config
from .save_config import save_config
from .style import apply_application_palette, build_menu_style, set_dark_style, set_style

if TYPE_CHECKING:
    from PyQt6.QtGui import QMouseEvent


LINK_DIR_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
WINDOWS_RESERVED_DIR_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
DEFAULT_LINK_DIR_NAME = "unnamed"


class MyMAinWindow(QMainWindow):
    # region 信号量
    main_logs_show = pyqtSignal(str)  # 显示刮削日志信号
    main_logs_clear = pyqtSignal(str)  # 清空刮削日志信号
    req_logs_clear = pyqtSignal(str)  # 清空请求日志信号
    main_req_logs_show = pyqtSignal(str)  # 显示刮削后台日志信号
    net_logs_show = pyqtSignal(str)  # 显示网络检测日志信号
    set_javdb_cookie = pyqtSignal(str)  # 加载javdb cookie文本内容到设置页面
    set_javdb_status = pyqtSignal(str)  # javdb 检查状态更新
    set_fc2ppvdb_status = pyqtSignal(str)  # fc2ppvdb 检查状态更新
    set_javbus_cookie = pyqtSignal(str)  # 加载javbus cookie文本内容到设置页面
    set_javbus_status = pyqtSignal(str)  # javbus 检查状态更新
    exec_save_config = pyqtSignal()  # 主线程执行保存配置
    set_label_file_path = pyqtSignal(str)  # 主界面更新路径信息显示
    set_pic_pixmap = pyqtSignal(list, list)  # 主界面显示封面、缩略图
    set_pic_text = pyqtSignal(str)  # 主界面显示封面信息
    change_to_mainpage = pyqtSignal(str)  # 切换到主界面
    label_result = pyqtSignal(str)
    pushButton_start_cap = pyqtSignal(str)
    pushButton_start_cap2 = pyqtSignal(str)
    pushButton_start_single_file = pyqtSignal(str)
    pushButton_add_sub_for_all_video = pyqtSignal(str)
    pushButton_show_pic_actor = pyqtSignal(str)
    pushButton_add_actor_info = pyqtSignal(str)
    pushButton_add_actor_pic = pyqtSignal(str)
    pushButton_add_actor_pic_kodi = pyqtSignal(str)
    pushButton_del_actor_folder = pyqtSignal(str)
    pushButton_check_and_clean_files = pyqtSignal(str)
    pushButton_move_mp4 = pyqtSignal(str)
    pushButton_find_missing_number = pyqtSignal(str)
    label_show_version = pyqtSignal(str)

    # endregion

    def __init__(self, parent=None):
        super().__init__(parent)

        # region 初始化需要的变量
        self.localversion = LOCAL_VERSION  # 当前版本号
        self.new_version = "\n🔍 点击检查最新版本"  # 有版本更新时在左下角显示的新版本信息
        self.show_data: ShowData | None = None  # 当前树状图选中文件的数据
        self.img_path = None  # 当前树状图选中文件的图片地址
        self.m_drag = False  # 允许鼠标拖动的标识
        self.m_DragPosition: QPoint | None = None  # 鼠标拖动位置
        self.logs_counts = 0  # 日志次数（每1w次清屏）
        self.req_logs_counts = 0  # 日志次数（每1w次清屏）
        self.main_log_queue: deque[str] = deque()
        self.main_log_batch_size = 80
        self.main_log_max_count = 10000
        self.network_check_cancel_event: threading.Event | None = None
        self.network_check_future = None
        self.file_main_open_path = Path()  # 主界面打开的文件路径
        self.json_array: dict[str, ShowData] = {}  # 主界面右侧结果树状数据

        self.window_radius = 0  # 窗口四角弧度，为0时表示显示窗口标题栏
        self.window_border = 0  # 窗口描边，为0时表示显示窗口标题栏
        self.dark_mode = False  # 暗黑模式标识
        self.check_mac = True  # 检测配置目录
        # self.window_marjin = 0 窗口外边距，为0时不往里缩
        self.show_flag = True  # 是否加载刷新样式

        self.timer = QTimer()  # 初始化一个定时器，用于显示日志
        self.timer.timeout.connect(self.show_detail_log)
        self.timer.timeout.connect(self._flush_main_log_queue)
        self.timer.start(100)  # 设置间隔100毫秒
        self.timer_scrape = QTimer()  # 初始化一个定时器，用于间隔刮削
        self.timer_scrape.timeout.connect(self.auto_scrape)
        self.timer_update = QTimer()  # 初始化一个定时器，用于检查更新
        self.timer_update.timeout.connect(check_version)
        self.timer_update.start(43200000)  # 设置检查间隔12小时
        self.timer_remain_task = QTimer()  # 初始化一个定时器，用于显示保存剩余任务
        self.timer_remain_task.timeout.connect(save_remain_list)
        self.timer_remain_task.start(1500)  # 设置间隔1.5秒
        self.atuo_scrape_count = 0  # 循环刮削次数
        # endregion

        # region 其它属性声明
        self.threads_list: list[threading.Thread] = []  # 启动的线程列表
        self.start_click_time = 0
        self.start_click_pos: QPoint
        self.window_marjin = None
        self.now_show_name = None
        self.show_name = None
        self.t_net = None
        self.options: QFileDialog.Option
        self.tray_icon: QSystemTrayIcon
        self.item_succ: QTreeWidgetItem
        self.item_fail: QTreeWidgetItem
        # endregion

        # region 初始化 UI
        resources.get_fonts()
        self.Ui = Ui_MDCx()  # 实例化 Ui
        self.Ui.setupUi(self)  # 初始化 Ui
        self._bind_system_theme_refresh()
        self._setup_fc2ppvdb_cookie_ui()
        self._setup_baidu_translate_ui()
        self.cutwindow = CutWindow(self)
        self.Init_Singal()  # 信号连接
        self.Init_Ui()  # 设置Ui初始状态
        self.load_config()  # 加载配置
        get_success_list()  # 获取历史成功刮削列表
        # endregion

        # region 启动显示信息和后台检查更新
        self.show_scrape_info()  # 主界面左下角显示一些配置信息
        self.show_net_info("\n🏠 代理设置在:【设置】 - 【网络】 - 【代理设置】。")
        show_netstatus()  # 检查网络界面显示当前网络代理信息
        self.show_net_info(
            "\n💡 Cloudflare Bypass：在【设置】-【网络】-【CF Bypass】填写本地服务地址后生效，"
            "例如 http://127.0.0.1:8000。\n"
            "▶️ 点击右上角 【开始检测】按钮以测试网络连通性。"
        )
        signal_qt.add_log("🍯 你可以点击左下角的图标来 显示 / 隐藏 请求信息面板！")
        self.show_version()  # 日志页面显示版本信息
        self.creat_right_menu()  # 加载右键菜单
        self.pushButton_main_clicked()  # 切换到主界面
        self.auto_start()  # 自动开始刮削
        # endregion

    # region Init
    def _setup_fc2ppvdb_cookie_ui(self):
        # 扩展 cookie 设置区域，并把下面分组整体下移，避免重叠
        delta_y = 140
        group_geo = self.Ui.groupBox_10.geometry()
        old_group_bottom = group_geo.y() + group_geo.height()
        self.Ui.groupBox_10.setGeometry(group_geo.x(), group_geo.y(), group_geo.width(), group_geo.height() + delta_y)
        content_geo = self.Ui.scrollAreaWidgetContents_wangluo.geometry()
        self.Ui.scrollAreaWidgetContents_wangluo.setGeometry(
            content_geo.x(),
            content_geo.y(),
            content_geo.width(),
            content_geo.height() + delta_y,
        )
        for child in self.Ui.scrollAreaWidgetContents_wangluo.children():
            if not isinstance(child, QWidget) or child is self.Ui.groupBox_10:
                continue
            child_geo = child.geometry()
            if child_geo.y() >= old_group_bottom:
                child.setGeometry(
                    child_geo.x(),
                    child_geo.y() + delta_y,
                    child_geo.width(),
                    child_geo.height(),
                )
        grid_geo = self.Ui.gridLayoutWidget_10.geometry()
        self.Ui.gridLayoutWidget_10.setGeometry(grid_geo.x(), grid_geo.y(), grid_geo.width(), 400)
        self.Ui.label_75.setGeometry(60, 450, 611, 141)
        self.Ui.label_get_cookie_url.setGeometry(130, 600, 430, 21)
        self.Ui.label_7.setGeometry(60, 600, 71, 21)

        self.Ui.label_fc2ppvdb_cookie = QLabel(self.Ui.gridLayoutWidget_10)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.Ui.label_fc2ppvdb_cookie.sizePolicy().hasHeightForWidth())
        self.Ui.label_fc2ppvdb_cookie.setSizePolicy(sizePolicy)
        self.Ui.label_fc2ppvdb_cookie.setMinimumSize(130, 30)
        self.Ui.label_fc2ppvdb_cookie.setMaximumSize(130, 16777215)
        self.Ui.label_fc2ppvdb_cookie.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.Ui.label_fc2ppvdb_cookie.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter
        )
        self.Ui.label_fc2ppvdb_cookie.setText("fc2ppvdb：\n（登录状态）")
        self.Ui.label_fc2ppvdb_cookie.setObjectName("label_fc2ppvdb_cookie")
        self.Ui.gridLayout_10.addWidget(self.Ui.label_fc2ppvdb_cookie, 4, 0, 1, 1)

        self.Ui.plainTextEdit_cookie_fc2ppvdb = QPlainTextEdit(self.Ui.gridLayoutWidget_10)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.Ui.plainTextEdit_cookie_fc2ppvdb.sizePolicy().hasHeightForWidth())
        self.Ui.plainTextEdit_cookie_fc2ppvdb.setSizePolicy(sizePolicy)
        self.Ui.plainTextEdit_cookie_fc2ppvdb.setMinimumSize(400, 80)
        self.Ui.plainTextEdit_cookie_fc2ppvdb.setStyleSheet(
            " border: 1px solid rgba(0,0,0, 50);\n"
            "                                border-radius: 1px;\n"
            '                                font: "Courier";'
        )
        self.Ui.plainTextEdit_cookie_fc2ppvdb.setPlaceholderText("FC2 独立刮削请填写 fc2ppvdb cookie")
        self.Ui.plainTextEdit_cookie_fc2ppvdb.setObjectName("plainTextEdit_cookie_fc2ppvdb")
        self.Ui.gridLayout_10.addWidget(self.Ui.plainTextEdit_cookie_fc2ppvdb, 4, 1, 1, 1)

        self.Ui.horizontalLayout_fc2ppvdb_cookie = QHBoxLayout()
        self.Ui.horizontalLayout_fc2ppvdb_cookie.setObjectName("horizontalLayout_fc2ppvdb_cookie")
        self.Ui.pushButton_check_fc2ppvdb_cookie = QPushButton(self.Ui.gridLayoutWidget_10)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.Ui.pushButton_check_fc2ppvdb_cookie.sizePolicy().hasHeightForWidth())
        self.Ui.pushButton_check_fc2ppvdb_cookie.setSizePolicy(sizePolicy)
        self.Ui.pushButton_check_fc2ppvdb_cookie.setText("检查cookie")
        self.Ui.pushButton_check_fc2ppvdb_cookie.setObjectName("pushButton_check_fc2ppvdb_cookie")
        self.Ui.horizontalLayout_fc2ppvdb_cookie.addWidget(self.Ui.pushButton_check_fc2ppvdb_cookie)

        self.Ui.label_fc2ppvdb_cookie_result = QLabel(self.Ui.gridLayoutWidget_10)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.Ui.label_fc2ppvdb_cookie_result.sizePolicy().hasHeightForWidth())
        self.Ui.label_fc2ppvdb_cookie_result.setSizePolicy(sizePolicy)
        self.Ui.label_fc2ppvdb_cookie_result.setMinimumSize(0, 0)
        self.Ui.label_fc2ppvdb_cookie_result.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.Ui.label_fc2ppvdb_cookie_result.setText("")
        self.Ui.label_fc2ppvdb_cookie_result.setAlignment(
            Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.Ui.label_fc2ppvdb_cookie_result.setObjectName("label_fc2ppvdb_cookie_result")
        self.Ui.horizontalLayout_fc2ppvdb_cookie.addWidget(self.Ui.label_fc2ppvdb_cookie_result)
        self.Ui.gridLayout_10.addLayout(self.Ui.horizontalLayout_fc2ppvdb_cookie, 5, 1, 1, 1)

    def _setup_baidu_translate_ui(self):
        delta_y = 70

        trans_geo = self.Ui.groupBox_trans.geometry()
        self.Ui.groupBox_trans.setGeometry(
            trans_geo.x(), trans_geo.y(), trans_geo.width(), trans_geo.height() + delta_y
        )

        layout_geo = self.Ui.layoutWidget_2.geometry()
        self.Ui.layoutWidget_2.setGeometry(
            layout_geo.x(), layout_geo.y(), layout_geo.width(), layout_geo.height() + delta_y
        )

        content_geo = self.Ui.scrollAreaWidgetContents_fanyi.geometry()
        self.Ui.scrollAreaWidgetContents_fanyi.setGeometry(
            content_geo.x(), content_geo.y(), content_geo.width(), content_geo.height() + delta_y
        )

        for child in self.Ui.scrollAreaWidgetContents_fanyi.children():
            if not isinstance(child, QWidget) or child is self.Ui.groupBox_trans:
                continue
            child_geo = child.geometry()
            if child_geo.y() > trans_geo.y():
                child.setGeometry(
                    child_geo.x(),
                    child_geo.y() + delta_y,
                    child_geo.width(),
                    child_geo.height(),
                )

        self.Ui.label_60.setText("填写 DeepL API / DeepLX URL / 百度 API 凭据后，才会生效；未填写时会自动跳过。")
        self.Ui.label_601.setText("填写 DeepL API / DeepLX URL / 百度 API 凭据后，才会生效；未填写时会自动跳过。")

        self.Ui.checkBox_baidu = QCheckBox(self.Ui.layoutWidget_2)
        self.Ui.checkBox_baidu.setMinimumSize(self.Ui.checkBox_google.minimumSize())
        self.Ui.checkBox_baidu.setObjectName("checkBox_baidu")
        self.Ui.checkBox_baidu.setText("百度")
        self.Ui.horizontalLayout_20.addWidget(self.Ui.checkBox_baidu)

        self.Ui.label_baidu_appid = QLabel(self.Ui.layoutWidget_2)
        self.Ui.label_baidu_appid.setMinimumSize(self.Ui.label_80.minimumSize())
        self.Ui.label_baidu_appid.setLayoutDirection(self.Ui.label_80.layoutDirection())
        self.Ui.label_baidu_appid.setFrameShape(self.Ui.label_80.frameShape())
        self.Ui.label_baidu_appid.setAlignment(self.Ui.label_80.alignment())
        self.Ui.label_baidu_appid.setObjectName("label_baidu_appid")
        self.Ui.label_baidu_appid.setText("百度 APP ID：")
        self.Ui.gridLayout_32.addWidget(self.Ui.label_baidu_appid, 5, 0, 1, 1)

        self.Ui.lineEdit_baidu_appid = QLineEdit(self.Ui.layoutWidget_2)
        self.Ui.lineEdit_baidu_appid.setMinimumSize(self.Ui.lineEdit_deepl_key.minimumSize())
        self.Ui.lineEdit_baidu_appid.setStyleSheet(self.Ui.lineEdit_deepl_key.styleSheet())
        self.Ui.lineEdit_baidu_appid.setObjectName("lineEdit_baidu_appid")
        self.Ui.gridLayout_32.addWidget(self.Ui.lineEdit_baidu_appid, 5, 1, 1, 1)

        self.Ui.label_baidu_key = QLabel(self.Ui.layoutWidget_2)
        self.Ui.label_baidu_key.setMinimumSize(self.Ui.label_80.minimumSize())
        self.Ui.label_baidu_key.setLayoutDirection(self.Ui.label_80.layoutDirection())
        self.Ui.label_baidu_key.setFrameShape(self.Ui.label_80.frameShape())
        self.Ui.label_baidu_key.setAlignment(self.Ui.label_80.alignment())
        self.Ui.label_baidu_key.setObjectName("label_baidu_key")
        self.Ui.label_baidu_key.setText("百度密钥：")
        self.Ui.gridLayout_32.addWidget(self.Ui.label_baidu_key, 6, 0, 1, 1)

        self.Ui.lineEdit_baidu_key = QLineEdit(self.Ui.layoutWidget_2)
        self.Ui.lineEdit_baidu_key.setMinimumSize(self.Ui.lineEdit_deepl_key.minimumSize())
        self.Ui.lineEdit_baidu_key.setStyleSheet(self.Ui.lineEdit_deepl_key.styleSheet())
        self.Ui.lineEdit_baidu_key.setObjectName("lineEdit_baidu_key")
        self.Ui.gridLayout_32.addWidget(self.Ui.lineEdit_baidu_key, 6, 1, 1, 1)

    def Init_Ui(self): ...

    def Init_Singal(self): ...

    def Init_QSystemTrayIcon(self): ...

    def init_QTreeWidget(self): ...

    def load_config(self): ...

    def creat_right_menu(self):
        self.menu_start = QAction(QIcon(resources.start_icon), "  开始刮削\tS", self)
        self.menu_stop = QAction(QIcon(resources.stop_icon), "  停止刮削\tS", self)
        self.menu_number = QAction(QIcon(resources.input_number_icon), "  重新刮削\tN", self)
        self.menu_website = QAction(QIcon(resources.input_website_icon), "  输入网址重新刮削\tU", self)
        self.menu_del_file = QAction(QIcon(resources.del_file_icon), "  删除文件\tD", self)
        self.menu_del_folder = QAction(QIcon(resources.del_folder_icon), "  删除文件和文件夹\tA", self)
        self.menu_make_symlink = QAction(QIcon(resources.open_folder_icon), "  在指定位置创建软链接", self)
        self.menu_make_symlink_in_dir = QAction(
            QIcon(resources.open_folder_icon), "  在指定位置创建软链接（按文件名建目录）", self
        )
        self.menu_make_hardlink = QAction(QIcon(resources.open_folder_icon), "  在指定位置创建硬链接", self)
        self.menu_make_hardlink_in_dir = QAction(
            QIcon(resources.open_folder_icon), "  在指定位置创建硬链接（按文件名建目录）", self
        )
        self.menu_folder = QAction(QIcon(resources.open_folder_icon), "  打开文件夹\tF", self)
        self.menu_nfo = QAction(QIcon(resources.open_nfo_icon), "  编辑 NFO\tE", self)
        self.menu_play = QAction(QIcon(resources.play_icon), "  播放\tP", self)
        self.menu_hide = QAction(QIcon(resources.hide_boss_icon), "  隐藏\tQ", self)

        self.menu_start.triggered.connect(self.pushButton_start_scrape_clicked)
        self.menu_stop.triggered.connect(self.pushButton_start_scrape_clicked)
        self.menu_number.triggered.connect(self.search_by_number_clicked)
        self.menu_website.triggered.connect(self.search_by_url_clicked)
        self.menu_del_file.triggered.connect(self.main_del_file_click)
        self.menu_del_folder.triggered.connect(self.main_del_folder_click)
        self.menu_make_symlink.triggered.connect(self.main_make_symlink_click)
        self.menu_make_symlink_in_dir.triggered.connect(self.main_make_symlink_in_dir_click)
        self.menu_make_hardlink.triggered.connect(self.main_make_hardlink_click)
        self.menu_make_hardlink_in_dir.triggered.connect(self.main_make_hardlink_in_dir_click)
        self.menu_folder.triggered.connect(self.main_open_folder_click)
        self.menu_nfo.triggered.connect(self.main_open_nfo_click)
        self.menu_play.triggered.connect(self.main_play_click)
        self.menu_hide.triggered.connect(self.hide)

        QShortcut(QKeySequence(self.tr("N")), self, self.search_by_number_clicked)
        QShortcut(QKeySequence(self.tr("U")), self, self.search_by_url_clicked)
        QShortcut(QKeySequence(self.tr("D")), self, self.main_del_file_click)
        QShortcut(QKeySequence(self.tr("A")), self, self.main_del_folder_click)
        QShortcut(QKeySequence(self.tr("F")), self, self.main_open_folder_click)
        QShortcut(QKeySequence(self.tr("E")), self, self.main_open_nfo_click)
        QShortcut(QKeySequence(self.tr("P")), self, self.main_play_click)
        QShortcut(QKeySequence(self.tr("S")), self, self.pushButton_start_scrape_clicked)
        QShortcut(QKeySequence(self.tr("Q")), self, self.hide)
        # QShortcut(QKeySequence(self.tr("Esc")), self, self.hide)
        QShortcut(QKeySequence(self.tr("Ctrl+M")), self, self.pushButton_min_clicked2)
        QShortcut(QKeySequence(self.tr("Ctrl+W")), self, self.ready_to_exit)

        self.Ui.page_main.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.Ui.page_main.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos=None):
        if not pos:
            pos = self.Ui.pushButton_right_menu.pos() + QPoint(40, 10)
            # pos = QCursor().pos()
        menu = QMenu()
        menu.setStyleSheet(build_menu_style(self.dark_mode))
        selected_entries = self._get_selected_entries()
        selected_entry = selected_entries[0] if len(selected_entries) == 1 else None
        if len(selected_entries) > 1:
            menu.addAction(QAction(f"已选择 {len(selected_entries)} 项", self))
            menu.addSeparator()
            menu.addAction(self.menu_del_file)
            menu.addAction(self.menu_del_folder)
            menu.addAction(self.menu_make_symlink)
            menu.addAction(self.menu_make_symlink_in_dir)
            menu.addAction(self.menu_make_hardlink)
            menu.addAction(self.menu_make_hardlink_in_dir)
            menu.exec(self.Ui.page_main.mapToGlobal(pos))
            return

        if selected_entry is not None:
            _, _, _, file_path = selected_entry
            file_name = split_path(file_path)[1]
            menu.addAction(QAction(file_name, self))
            menu.addSeparator()
        elif self.file_main_open_path:
            file_name = split_path(self.file_main_open_path)[1]
            menu.addAction(QAction(file_name, self))
            menu.addSeparator()
        else:
            menu.addAction(QAction("请刮削后使用！", self))
            menu.addSeparator()
            if self.Ui.pushButton_start_cap.text() != "开始":
                menu.addAction(self.menu_stop)
            else:
                menu.addAction(self.menu_start)
        menu.addAction(self.menu_number)
        menu.addAction(self.menu_website)
        menu.addSeparator()
        menu.addAction(self.menu_del_file)
        menu.addAction(self.menu_del_folder)
        menu.addAction(self.menu_make_symlink)
        menu.addAction(self.menu_make_symlink_in_dir)
        menu.addAction(self.menu_make_hardlink)
        menu.addAction(self.menu_make_hardlink_in_dir)
        menu.addSeparator()
        menu.addAction(self.menu_folder)
        menu.addAction(self.menu_nfo)
        menu.addAction(self.menu_play)
        menu.addAction(self.menu_hide)
        menu.exec(self.Ui.page_main.mapToGlobal(pos))
        # menu.move(pos)
        # menu.show()

    def _tree_result_context_menu(self, pos: QPoint):
        item = self.Ui.treeWidget_number.itemAt(pos)
        if item is not None and item.text(0) not in {"成功", "失败"}:
            self._set_result_item_as_current_selection(item)
        global_pos = self.Ui.treeWidget_number.viewport().mapToGlobal(pos)
        self._menu(self.Ui.page_main.mapFromGlobal(global_pos))

    # endregion

    # region 窗口操作
    def tray_icon_click(self, e):
        if e == QSystemTrayIcon.ActivationReason.Trigger and IS_WINDOWS:
            if self.isVisible():
                self.hide()
            else:
                self.activateWindow()
                self.raise_()
                self.show()

    def tray_icon_show(self):
        if self.windowState() & Qt.WindowState.WindowMinimized:  # 最小化时恢复
            self.showNormal()
        self.recover_windowflags()  # 恢复焦点
        self.activateWindow()
        self.raise_()
        self.show()

    def change_mainpage(self, t):
        self.pushButton_main_clicked()

    def eventFilter(self, a0, a1):
        # print(event.type())

        if a1.type() == QEvent.Type.MouseButtonRelease:  # 松开鼠标，检查是否在前台
            self.recover_windowflags()
        if a1.type() == QEvent.Type.ApplicationActivate and not self.isVisible():
            self.show()
        if a0.objectName() == "label_poster" or a0.objectName() == "label_thumb":
            if a1.type() == QEvent.Type.MouseButtonPress:
                a1 = cast("QMouseEvent", a1)
                if a1.button() == Qt.MouseButton.LeftButton:
                    self.start_click_time = time.time()
                    self.start_click_pos = a1.globalPosition().toPoint()
            elif a1.type() == QEvent.Type.MouseButtonRelease:
                a1 = cast("QMouseEvent", a1)
                if a1.button() == Qt.MouseButton.LeftButton:
                    if not bool(a1.globalPosition().toPoint() - self.start_click_pos) or (
                        time.time() - self.start_click_time < 0.05
                    ):
                        self._pic_main_clicked()
        if a0 is self.Ui.textBrowser_log_main.viewport() or a0 is self.Ui.textBrowser_log_main_2.viewport():
            if not self.Ui.textBrowser_log_main_3.isHidden() and a1.type() == QEvent.Type.MouseButtonPress:
                self.Ui.textBrowser_log_main_3.hide()
                self.Ui.pushButton_scraper_failed_list.hide()
                self.Ui.pushButton_save_failed_list.hide()
        return super().eventFilter(a0, a1)

    def showEvent(self, a0):
        self.resize(1030, 700)  # 调整窗口大小

    # 当隐藏边框时，最小化后，点击任务栏时，需要监听事件，在恢复窗口时隐藏边框
    def changeEvent(self, a0):
        # self.show_traceback_log(QEvent.WindowStateChange)
        # WindowState （WindowNoState=0 正常窗口; WindowMinimized= 1 最小化;
        # WindowMaximized= 2 最大化; WindowFullScreen= 3 全屏;WindowActive= 8 可编辑。）
        # windows平台无问题，仅mac平台python版有问题
        if (
            not IS_WINDOWS
            and self.window_radius
            and a0.type() == QEvent.Type.WindowStateChange
            and self.windowState() == Qt.WindowState.WindowNoState
        ):
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)  # 隐藏边框
            self.show()

        # activeAppName = AppKit.NSWorkspace.sharedWorkspace().activeApplication()['NSApplicationName'] # 活动窗口的标题

    def closeEvent(self, a0):
        self.ready_to_exit()
        if a0:
            a0.ignore()

    # 显示与隐藏窗口标题栏
    def _windows_auto_adjust(self):
        if manager.config.window_title == "hide":  # 隐藏标题栏
            if self.window_radius == 0:
                self.show_flag = True
            self.window_radius = 5
            if IS_WINDOWS:
                self.window_border = 1
            else:
                self.window_border = 0
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)  # 隐藏标题栏
            self.Ui.pushButton_close.setVisible(True)
            self.Ui.pushButton_min.setVisible(True)
            self.Ui.widget_buttons.move(0, 50)

        else:  # 显示标题栏
            if self.window_radius == 5:
                self.show_flag = True
            self.window_radius = 0
            self.window_border = 0
            self.window_marjin = 0
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)  # 显示标题栏
            self.Ui.pushButton_close.setVisible(False)
            self.Ui.pushButton_min.setVisible(False)
            self.Ui.widget_buttons.move(0, 20)

        if bool(self.dark_mode != self.Ui.checkBox_dark_mode.isChecked()):
            self.show_flag = True
            self.dark_mode = self.Ui.checkBox_dark_mode.isChecked()

        if self.show_flag:
            self.show_flag = False
            self.set_style()  # 样式美化

            # self.setWindowState(Qt.WindowNoState)                               # 恢复正常窗口
            self.show()
            self._change_page()

    def _change_page(self):
        page = int(self.Ui.stackedWidget.currentIndex())
        if page == 0:
            self.pushButton_main_clicked()
        elif page == 1:
            self.pushButton_show_log_clicked()
        elif page == 2:
            self.pushButton_show_net_clicked()
        elif page == 3:
            self.pushButton_tool_clicked()
        elif page == 4:
            self.pushButton_setting_clicked()
        elif page == 5:
            self.pushButton_about_clicked()

    def set_style(self): ...

    def set_dark_style(self): ...

    def _bind_system_theme_refresh(self) -> None:
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(
                lambda *_args: apply_application_palette(self.dark_mode)
            )
        except Exception:
            pass

    # region 拖动窗口
    # 按下鼠标
    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.m_drag = True
            self.m_DragPosition = a0.globalPosition().toPoint() - self.pos()
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))  # 按下左键改变鼠标指针样式为手掌

    # 松开鼠标
    def mouseReleaseEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.m_drag = False
            self.m_DragPosition = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))  # 释放左键改变鼠标指针样式为箭头

    # 拖动鼠标
    def mouseMoveEvent(self, a0):
        if a0 and self.m_drag and self.m_DragPosition is not None and a0.buttons() & Qt.MouseButton.LeftButton:
            self.move(a0.globalPosition().toPoint() - self.m_DragPosition)
            a0.accept()
        else:
            self.m_drag = False
            self.m_DragPosition = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    # endregion

    # region 关闭
    # 关闭按钮点击事件响应函数
    def pushButton_close_clicked(self):
        if Switch.HIDE_CLOSE in manager.config.switch_on:
            self.hide()
        else:
            self.ready_to_exit()

    def ready_to_exit(self):
        if Switch.SHOW_DIALOG_EXIT in manager.config.switch_on:
            if not self.isVisible():
                self.show()
            if self.windowState() & Qt.WindowState.WindowMinimized:
                self.showNormal()

            # print(self.window().isActiveWindow()) # 是否为活动窗口
            self.raise_()
            box = QMessageBox(QMessageBox.Icon.Warning, "退出", "确定要退出吗？")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.button(QMessageBox.StandardButton.Yes).setText("退出 MDCx")
            box.button(QMessageBox.StandardButton.No).setText("取消")
            box.setDefaultButton(QMessageBox.StandardButton.No)
            reply = box.exec()
            if reply != QMessageBox.StandardButton.Yes:
                self.raise_()
                self.show()
                return
        self.exit_app()

    # 关闭窗口
    def exit_app(self):
        show_poster = manager.config.show_poster
        switch_on = manager.config.switch_on
        need_save_config = False

        if self.Ui.checkBox_cover.isChecked() != show_poster:
            manager.config.show_poster = self.Ui.checkBox_cover.isChecked()
            need_save_config = True
        if self.Ui.textBrowser_log_main_2.isHidden() == (Switch.SHOW_LOGS in switch_on):
            if self.Ui.textBrowser_log_main_2.isHidden():
                manager.config.switch_on.remove(Switch.SHOW_LOGS)
            else:
                manager.config.switch_on.append(Switch.SHOW_LOGS)
            need_save_config = True
        if need_save_config:
            try:
                manager.save()
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        signal_qt.show_traceback_log("\n\n\n\n************ 程序正常退出！************\n")
        os._exit(0)

    # endregion

    # 最小化窗口
    def pushButton_min_clicked(self):
        if Switch.HIDE_MINI in manager.config.switch_on:
            self.hide()
            return
        # mac 平台 python 版本 最小化有问题，此处就是为了兼容它，需要先设置为显示窗口标题栏才能最小化
        if not IS_WINDOWS:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)  # 不隐藏边框

        # self.setWindowState(Qt.WindowState.WindowMinimized)
        # self.show_traceback_log(self.isMinimized())
        self.showMinimized()

    def pushButton_min_clicked2(self):
        if not IS_WINDOWS:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)  # 不隐藏边框
            # self.show()  # 加上后可以显示缩小动画
        self.showMinimized()

    # 重置左侧按钮样式
    def set_left_button_style(self):
        try:
            if self.dark_mode:
                self.Ui.left_backgroud_widget.setStyleSheet(
                    f"background: #1F272F;border-right: 1px solid #20303F;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
                )
                self.Ui.pushButton_main.setStyleSheet(
                    "QPushButton:hover#pushButton_main{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_log.setStyleSheet(
                    "QPushButton:hover#pushButton_log{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_net.setStyleSheet(
                    "QPushButton:hover#pushButton_net{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_tool.setStyleSheet(
                    "QPushButton:hover#pushButton_tool{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_setting.setStyleSheet(
                    "QPushButton:hover#pushButton_setting{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_about.setStyleSheet(
                    "QPushButton:hover#pushButton_about{color: white;background-color: rgba(160,160,165,40);}"
                )
            else:
                self.Ui.pushButton_main.setStyleSheet(
                    "QPushButton:hover#pushButton_main{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_log.setStyleSheet(
                    "QPushButton:hover#pushButton_log{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_net.setStyleSheet(
                    "QPushButton:hover#pushButton_net{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_tool.setStyleSheet(
                    "QPushButton:hover#pushButton_tool{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_setting.setStyleSheet(
                    "QPushButton:hover#pushButton_setting{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_about.setStyleSheet(
                    "QPushButton:hover#pushButton_about{color: black;background-color: rgba(160,160,165,40);}"
                )
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # endregion

    # region 显示版本号
    def show_version(self):
        try:
            t = threading.Thread(target=self._show_version_thread)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _show_version_thread(self):
        version_info = f"基于 MDC-GUI 修改 当前版本: {self.localversion}"
        download_link = ""
        latest_version = check_version()
        if latest_version:
            if int(self.localversion) < int(latest_version):
                self.new_version = f"\n🍉 有新版本了！（{latest_version}）"
                signal_qt.show_scrape_info()
                self.Ui.label_show_version.setCursor(Qt.CursorShape.OpenHandCursor)  # 设置鼠标形状为十字形
                version_info = f'基于 MDC-GUI 修改 · 当前版本: {self.localversion} （ <font color="red" >最新版本是: {latest_version}，请及时更新！🚀 </font>）'
                download_link = f' ⬇️ <a href="{GITHUB_RELEASES_URL}">下载新版本</a>'
            else:
                version_info = f'基于 MDC-GUI 修改 · 当前版本: {self.localversion} （ <font color="green">你使用的是最新版本！🎉 </font>）'

        feedback = f' 💌 问题反馈: <a href="{GITHUB_ISSUES_URL}">GitHub Issues</a>'

        # 显示版本信息和反馈入口
        signal_qt.show_log_text(version_info)
        if feedback or download_link:
            self.main_logs_show.emit(f"{feedback}{download_link}")
        signal_qt.show_log_text("================================================================================")
        self.pushButton_check_javdb_cookie_clicked()  # 检测javdb cookie
        self.pushButton_check_javbus_cookie_clicked()  # 检测javbus cookie
        if manager.config.use_database:
            ActressDB.init_db()
        try:
            t = threading.Thread(target=check_theporndb_api_token)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    # endregion

    # region 各种点击跳转浏览器
    def label_version_clicked(self, ev):
        try:
            webbrowser.open(GITHUB_RELEASES_URL)
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # endregion

    # region 左侧切换页面
    # 点左侧的主界面按钮
    def pushButton_main_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F5F6;border-right: 1px solid #EDEDED;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(0)
        self.set_left_button_style()
        self.Ui.pushButton_main.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # 点左侧的日志按钮
    def pushButton_show_log_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(1)
        self.set_left_button_style()
        self.Ui.pushButton_log.setStyleSheet(
            "font-weight: bold; background-color: rgba(160,160,165,60);"
        )  # self.Ui.textBrowser_log_main.verticalScrollBar().setValue(  #     self.Ui.textBrowser_log_main.verticalScrollBar().maximum())  # self.Ui.textBrowser_log_main_2.verticalScrollBar().setValue(  #     self.Ui.textBrowser_log_main_2.verticalScrollBar().maximum())

    # 点左侧的工具按钮
    def pushButton_tool_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(3)
        self.set_left_button_style()
        self.Ui.pushButton_tool.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # 点左侧的设置按钮
    def pushButton_setting_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #EEF3FF;border-right: 1px solid #D8E2FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(4)
        self.set_left_button_style()
        try:
            if self.dark_mode:
                self.Ui.pushButton_setting.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")
            else:
                self.Ui.pushButton_setting.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,100);")
            self._check_mac_config_folder()
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # 点击左侧【检测网络】按钮，切换到检测网络页面
    def pushButton_show_net_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(2)
        self.set_left_button_style()
        self.Ui.pushButton_net.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # 点左侧的关于按钮
    def pushButton_about_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(5)
        self.set_left_button_style()
        self.Ui.pushButton_about.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # endregion

    # region 主界面
    # 开始刮削按钮
    def pushButton_start_scrape_clicked(self):
        if self.Ui.pushButton_start_cap.text() == "开始":
            if not get_remain_list():
                start_new_scrape(FileMode.Default)
        elif self.Ui.pushButton_start_cap.text() == "■ 停止":
            self.pushButton_stop_scrape_clicked()

    # 停止确认弹窗
    def pushButton_stop_scrape_clicked(self):
        if Switch.SHOW_DIALOG_STOP_SCRAPE in manager.config.switch_on:
            box = QMessageBox(QMessageBox.Icon.Warning, "停止刮削", "确定要停止刮削吗？")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.button(QMessageBox.StandardButton.Yes).setText("停止刮削")
            box.button(QMessageBox.StandardButton.No).setText("取消")
            box.setDefaultButton(QMessageBox.StandardButton.No)
            reply = box.exec()
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self.Ui.pushButton_start_cap.text() == "■ 停止":
            Flags.stop_requested = True
            signal_qt.stop = True
            executor.run(save_success_list())
            Flags.rest_time_convert_ = Flags.rest_time_convert
            Flags.rest_time_convert = 0
            self.Ui.pushButton_start_cap.setText(" ■ 停止中 ")
            self.Ui.pushButton_start_cap2.setText(" ■ 停止中 ")
            signal_qt.show_scrape_info("⛔️ 刮削停止中...")
            executor.cancel_async()  # 取消异步任务
            if not self.threads_list:
                self.stop_used_time = 0.0
                self.show_stop_info_thread()
                return
            t = threading.Thread(target=self._kill_threads)  # 关闭线程池
            t.start()

    # 显示停止信息
    def _show_stop_info(self):
        signal_qt.reset_buttons_status.emit()
        try:
            Flags.rest_time_convert = Flags.rest_time_convert_
            if Flags.stop_other:
                signal_qt.show_scrape_info("⛔️ 已手动停止！")
                signal_qt.show_log_text(
                    "⛔️ 已手动停止！\n================================================================================"
                )
                self.set_label_file_path.emit("⛔️ 已手动停止！")
                return
            signal_qt.exec_set_processbar.emit(0)
            end_time = time.time()
            used_time = str(round((end_time - Flags.start_time), 2))
            if Flags.scrape_done:
                average_time = str(round((end_time - Flags.start_time) / Flags.scrape_done, 2))
            else:
                average_time = used_time
            signal_qt.show_scrape_info("⛔️ 刮削已手动停止！")
            self.set_label_file_path.emit(
                f"⛔️ 刮削已手动停止！\n   已刮削 {Flags.scrape_done} 个视频, 还剩余 {Flags.total_count - Flags.scrape_done} 个! 刮削用时 {used_time} 秒"
            )
            signal_qt.show_log_text(
                f"\n ⛔️ 刮削已手动停止！\n 😊 已刮削 {Flags.scrape_done} 个视频, 还剩余 {Flags.total_count - Flags.scrape_done} 个! 刮削用时 {used_time} 秒, 停止用时 {self.stop_used_time} 秒"
            )
            signal_qt.show_log_text("================================================================================")
            signal_qt.show_log_text(
                " ⏰ Start time".ljust(13) + ": " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(Flags.start_time))
            )
            signal_qt.show_log_text(
                " 🏁 End time".ljust(13) + ": " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
            )
            signal_qt.show_log_text(f"{' ⏱ Used time'.ljust(13)}: {used_time}S")
            signal_qt.show_log_text(f"{' 🍕 Per time'.ljust(13)}: {average_time}S")
            signal_qt.show_log_text("================================================================================")
            Flags.again_dic.clear()
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())
        finally:
            signal_qt.stop = False
        print(threading.enumerate())

    def show_stop_info_thread(
        self,
    ):
        t = threading.Thread(target=self._show_stop_info)
        t.start()

    # 关闭线程池和扫描线程
    def _kill_threads(self):
        Flags.total_kills = len(self.threads_list)
        Flags.now_kill = 0
        start_time = time.time()
        self.set_label_file_path.emit(f"⛔️ 正在停止刮削...\n   正在停止已在运行的任务线程（1/{Flags.total_kills}）...")
        signal_qt.show_log_text(
            f"\n ⛔️ {get_current_time()} 已停止添加新的刮削任务，正在停止已在运行的任务线程（{Flags.total_kills}）..."
        )
        signal_qt.show_traceback_log(f"⛔️ 正在停止正在运行的任务线程 ({Flags.total_kills}) ...")
        i = 0
        for each in self.threads_list:
            i += 1
            signal_qt.show_traceback_log(f"正在停止线程: {i}/{Flags.total_kills} {each.name} ...")
        signal_qt.show_traceback_log(
            "线程正在停止中，请稍后...\n 🍯 停止时间与线程数量及线程正在执行的任务有关，比如正在执行网络请求、文件下载等IO操作时，需要等待其释放资源。。。\n"
        )
        signal_qt.stop = True
        for each in self.threads_list:  # 线程池的线程
            kill_a_thread(each)
            while each.is_alive():
                pass

        self.stop_used_time = get_used_time(start_time)
        signal_qt.show_log_text(f" 🕷 {get_current_time()} 已停止线程：{Flags.total_kills}/{Flags.total_kills}")
        signal_qt.show_traceback_log(f"所有线程已停止！！！({self.stop_used_time}s)\n ⛔️ 刮削已手动停止！\n")
        signal_qt.show_log_text(f" ⛔️ {get_current_time()} 所有线程已停止！({self.stop_used_time}s)")
        thread_remain_list = []
        [thread_remain_list.append(t.name) for t in threading.enumerate()]  # 剩余线程名字列表
        thread_remain = ", ".join(thread_remain_list)
        print(f"✅ 剩余线程 ({len(thread_remain_list)}): {thread_remain}")
        self.show_stop_info_thread()

    # 进度条
    def set_processbar(self, value):
        self.Ui.progressBar_scrape.setProperty("value", value)

    # region 刮削结果显示
    def _addTreeChild(self, result, filename):
        node = QTreeWidgetItem()
        node.setText(0, filename)
        if result == "succ":
            self.item_succ.addChild(node)
        else:
            self.item_fail.addChild(node)
        # self.Ui.treeWidget_number.verticalScrollBar().setValue(self.Ui.treeWidget_number.verticalScrollBar().maximum())
        # self.Ui.treeWidget_number.setCurrentItem(node)
        # self.Ui.treeWidget_number.scrollToItem(node)

    def _get_single_selected_entry(self) -> tuple[QTreeWidgetItem, str, ShowData, Path] | None:
        selected_entries = self._get_selected_entries()
        if len(selected_entries) != 1:
            return None
        return selected_entries[0]

    def _has_single_selected_result_item(self) -> bool:
        return self._get_single_selected_entry() is not None

    def _set_result_item_as_current_selection(self, item: QTreeWidgetItem) -> None:
        if item.text(0) in {"成功", "失败"}:
            return

        tree = self.Ui.treeWidget_number
        selected_items = tree.selectedItems()
        if item not in selected_items:
            tree.clearSelection()
            item.setSelected(True)
        model_index = tree.indexFromItem(item)
        if model_index.isValid():
            tree.selectionModel().setCurrentIndex(model_index, QItemSelectionModel.SelectionFlag.NoUpdate)

    def show_list_name(self, status: Literal["succ", "fail"], show_data: ShowData, real_number=""):
        # 添加树状节点
        self._addTreeChild(status, show_data.show_name)

        if not show_data.data.title:
            show_data.data.title = LogBuffer.error().get()
            show_data.data.number = real_number
        self.json_array[show_data.show_name] = show_data
        if not self._has_single_selected_result_item():
            self.show_name = show_data.show_name
            self.set_main_info(show_data)

    def set_main_info(self, show_data: "ShowData | None"):
        if show_data is not None:
            self.show_data = show_data
            file_info = show_data.file_info
            data = show_data.data
            other = show_data.other
            self.show_name = show_data.show_name
        else:
            file_info = FileInfo.empty()
            data = CrawlersResult.empty()
            other = OtherInfo.empty()
            self.show_name = None
        try:
            number = data.number
            self.Ui.label_number.setToolTip(number)
            if len(number) > 11:
                number = number[:10] + "……"
            self.Ui.label_number.setText(number)
            actor = str(data.actor)
            if data.all_actor and NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
                actor = str(data.all_actor)
            self.Ui.label_actor.setToolTip(actor)
            if number and not actor:
                actor = manager.config.actor_no_name
            if len(actor) > 10:
                actor = actor[:9] + "……"
            self.Ui.label_actor.setText(actor)
            self.file_main_open_path = file_info.file_path  # 文件路径

            title = data.title.split("\n")[0].strip(" :")
            self.Ui.label_title.setToolTip(title)
            if len(title) > 27:
                title = title[:25] + "……"
            self.Ui.label_title.setText(title)
            outline = str(data.outline)
            self.Ui.label_outline.setToolTip(outline)
            if len(outline) > 38:
                outline = outline[:36] + "……"
            self.Ui.label_outline.setText(outline)
            tag = str(data.tag).strip(" [',']").replace("'", "")
            self.Ui.label_tag.setToolTip(tag)
            if len(tag) > 76:
                tag = tag[:75] + "……"
            self.Ui.label_tag.setText(tag)
            self.Ui.label_release.setText(str(data.release))
            self.Ui.label_release.setToolTip(str(data.release))
            if data.runtime:
                self.Ui.label_runtime.setText(str(data.runtime) + " 分钟")
                self.Ui.label_runtime.setToolTip(str(data.runtime) + " 分钟")
            else:
                self.Ui.label_runtime.setText("")
            self.Ui.label_director.setText(str(data.director))
            self.Ui.label_director.setToolTip(str(data.director))
            series = str(data.series)
            self.Ui.label_series.setToolTip(series)
            if len(series) > 32:
                series = series[:31] + "……"
            self.Ui.label_series.setText(series)
            self.Ui.label_studio.setText(data.studio)
            self.Ui.label_studio.setToolTip(data.studio)
            self.Ui.label_publish.setText(data.publisher)
            self.Ui.label_publish.setToolTip(data.publisher)
            self.Ui.label_poster.setToolTip("点击裁剪图片")
            self.Ui.label_thumb.setToolTip("点击裁剪图片")
            # 生成img_path，用来裁剪使用
            img_path = other.fanart_path if other.fanart_path and other.fanart_path.is_file() else other.thumb_path
            self.img_path = img_path
            if self.Ui.checkBox_cover.isChecked():  # 主界面显示封面和缩略图
                poster_path = other.poster_path
                thumb_path = other.thumb_path
                fanart_path = other.fanart_path
                if not (thumb_path and thumb_path.is_file()) and fanart_path and fanart_path.is_file():
                    thumb_path = fanart_path
                poster_from = data.poster_from
                cover_from = data.thumb_from
                if poster_path and thumb_path:
                    executor.submit(self._set_pixmap(poster_path, thumb_path, poster_from, cover_from))
        except Exception:
            if not signal_qt.stop:
                signal_qt.show_traceback_log(traceback.format_exc())

    async def _set_pixmap(
        self,
        poster_path: Path,
        thumb_path: Path,
        poster_from="",
        cover_from="",
    ):
        poster_pix = [False, "", "暂无封面图", 156, 220]
        thumb_pix = [False, "", "暂无缩略图", 328, 220]
        if os.path.exists(poster_path):
            poster_pix = await get_pixmap(poster_path, poster=True, pic_from=poster_from)
        if os.path.exists(thumb_path):
            thumb_pix = await get_pixmap(thumb_path, poster=False, pic_from=cover_from)

        # self.Ui.label_poster_size.setText(poster_pix[2] + '  ' + thumb_pix[2])
        poster_text = poster_pix[2] if poster_pix[2] != "暂无封面图" else ""
        thumb_text = thumb_pix[2] if thumb_pix[2] != "暂无缩略图" else ""
        self.set_pic_text.emit((poster_text + " " + thumb_text).strip())
        self.set_pic_pixmap.emit(poster_pix, thumb_pix)

    def resize_label_and_setpixmap(self, poster_pix, thumb_pix):
        self.Ui.label_poster.resize(poster_pix[3], poster_pix[4])
        self.Ui.label_thumb.resize(thumb_pix[3], thumb_pix[4])

        if poster_pix[0]:
            self.Ui.label_poster.setPixmap(poster_pix[1])
        else:
            self.Ui.label_poster.setText(poster_pix[2])

        if thumb_pix[0]:
            self.Ui.label_thumb.setPixmap(thumb_pix[1])
        else:
            self.Ui.label_thumb.setText(thumb_pix[2])

    # endregion

    def _get_selected_result_items(self) -> list[QTreeWidgetItem]:
        """
        获取当前树状图中有效的结果项（不包含成功/失败根节点）。
        """
        selected_items = []
        for item in self.Ui.treeWidget_number.selectedItems():
            if not item or item.text(0) in {"成功", "失败"}:
                continue
            if item.text(0) not in self.json_array:
                continue
            selected_items.append(item)
        return selected_items

    def _get_selected_entries(self) -> list[tuple[QTreeWidgetItem, str, ShowData, Path]]:
        result = []
        for item in self._get_selected_result_items():
            show_name = item.text(0)
            show_data = self.json_array.get(show_name)
            if show_data is None or not show_data.file_info.file_path:
                continue
            result.append((item, show_name, show_data, show_data.file_info.file_path))
        return result

    def _build_delete_preview(self, paths: list[Path], limit: int = 8) -> str:
        preview = "\n".join(str(path) for path in paths[:limit])
        if len(paths) > limit:
            preview += f"\n... 其余 {len(paths) - limit} 项省略"
        return preview

    def _shorten_text(self, text: str, limit: int) -> str:
        text = str(text).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    def _normalize_delete_error_reason(self, error_text: str) -> str:
        if not error_text:
            return "未知错误"

        lines = [line.strip() for line in str(error_text).splitlines() if line.strip()]
        full_text = "\n".join(lines).lower()

        if "symbolic link privilege not held" in full_text or "winerror 1314" in full_text:
            return "当前没有创建软链接权限，请尝试以管理员身份运行或开启开发者模式"

        if (
            "winerror 17" in full_text
            or "different disk drive" in full_text
            or "cross-device link" in full_text
            or "not same device" in full_text
        ):
            return "硬链接要求源文件与目标路径位于同一磁盘，请改用软链接"

        if "目标已存在:" in str(error_text):
            for line in lines:
                if "目标已存在:" in line:
                    return line.strip()

        for line in lines:
            if line.startswith("错误:"):
                return line.removeprefix("错误:").strip()

        for line in reversed(lines):
            if "PermissionError:" in line:
                return line.split("PermissionError:", 1)[1].strip()
            if "FileNotFoundError:" in line:
                return line.split("FileNotFoundError:", 1)[1].strip()
            if "OSError:" in line:
                return line.split("OSError:", 1)[1].strip()

        return lines[-1]

    def _build_action_result_text(self, success_count: int, failure_count: int, skipped_count: int = 0) -> str:
        parts = [f"成功 {success_count} 个"]
        if skipped_count:
            parts.append(f"跳过 {skipped_count} 个")
        parts.append(f"失败 {failure_count} 个")
        return "，".join(parts)

    def _show_action_failure_feedback(
        self,
        action_name: str,
        success_count: int,
        failure_details: list[tuple[Path, str]],
        skipped_count: int = 0,
    ) -> None:
        if not failure_details:
            return

        preview_limit = 3
        preview_lines = [
            f"- {self._shorten_text(str(path), 90)}\n  原因：{self._shorten_text(reason, 70)}"
            for path, reason in failure_details[:preview_limit]
        ]
        if len(failure_details) > preview_limit:
            preview_lines.append(f"... 其余 {len(failure_details) - preview_limit} 条请展开“显示详情”或查看日志")

        detail_limit = 20
        detail_lines = [
            f"{index}. {path}\n   原因：{reason}"
            for index, (path, reason) in enumerate(failure_details[:detail_limit], start=1)
        ]
        if len(failure_details) > detail_limit:
            detail_lines.append(f"... 其余 {len(failure_details) - detail_limit} 条请查看日志")
        detail_text = "\n\n".join(detail_lines)

        box = QMessageBox(QMessageBox.Icon.Warning, f"{action_name}结果", f"{action_name}完成")
        box.setInformativeText(
            f"{self._build_action_result_text(success_count, len(failure_details), skipped_count)}\n\n"
            f"{'\n'.join(preview_lines)}"
        )
        box.setDetailedText(detail_text)
        view_log_button = box.addButton("查看日志", QMessageBox.ButtonRole.ActionRole)
        box.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
        self._bind_localized_message_box_detail_buttons(box)
        box.exec()

        if box.clickedButton() == view_log_button:
            self.pushButton_show_log_clicked()
            self.show_hide_logs(True)

    def _localize_message_box_detail_buttons(self, box: QMessageBox) -> None:
        for button in box.findChildren(QPushButton):
            text = button.text().strip()
            if text == "Show Details...":
                button.setText("显示详情")
            elif text == "Hide Details...":
                button.setText("隐藏详情")

    def _bind_localized_message_box_detail_buttons(self, box: QMessageBox) -> None:
        def relocalize() -> None:
            self._localize_message_box_detail_buttons(box)

        relocalize()
        QTimer.singleShot(0, relocalize)
        for button in box.findChildren(QPushButton):
            button.clicked.connect(lambda _checked=False: QTimer.singleShot(0, relocalize))

    def _select_link_output_dir(self, link_name: str) -> Path | None:
        default_dir = str(get_movie_path_setting().softlink_path)
        selected_dir = QFileDialog.getExistingDirectory(
            None,
            f"选择{link_name}目标目录",
            default_dir,
            options=self.options,
        )
        return Path(selected_dir) if selected_dir else None

    def _confirm_record_link_paths(self, link_name: str) -> bool | None:
        box = QMessageBox(
            QMessageBox.Icon.Question,
            f"创建{link_name}",
            f"是否将本次成功创建的{link_name}路径写入程序的刮削成功列表？",
        )
        box.setInformativeText("已存在的同源链接会自动去重；取消则中止本次创建。")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
        )
        box.button(QMessageBox.StandardButton.Yes).setText("写入并继续")
        box.button(QMessageBox.StandardButton.No).setText("仅创建")
        box.button(QMessageBox.StandardButton.Cancel).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Cancel:
            return None
        return reply == QMessageBox.StandardButton.Yes

    def _build_link_target_path(
        self,
        source_path: Path,
        output_dir: Path,
        display_path: Path | None = None,
        group_in_named_dir: bool = False,
    ) -> tuple[Path, list[str]]:
        file_name = display_path.name if display_path is not None else source_path.name
        if not group_in_named_dir:
            return output_dir / file_name, []

        raw_dir_name = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
        raw_dir_name = raw_dir_name or file_name
        dir_name, dir_notes = self._sanitize_link_dir_name(raw_dir_name)
        target_dir, collision_note = self._get_available_link_target_dir(output_dir, dir_name, file_name)
        if collision_note:
            dir_notes.append(f"链接目录名已自动避让冲突: {dir_name} -> {target_dir.name}")
        return target_dir / file_name, dir_notes

    def _get_link_dir_name_max(self) -> int:
        folder_name_max = int(manager.config.folder_name_max)
        if folder_name_max <= 0 or folder_name_max > 255:
            return 60
        return folder_name_max

    def _fit_link_dir_name_length(self, dir_name: str, suffix: str = "") -> str:
        max_length = self._get_link_dir_name_max()
        if len(dir_name) + len(suffix) <= max_length:
            return dir_name + suffix

        base_length = max(max_length - len(suffix), 1)
        trimmed = dir_name[:base_length].rstrip(". ").rstrip()
        if not trimmed:
            trimmed = DEFAULT_LINK_DIR_NAME[:base_length].rstrip(". ").rstrip() or DEFAULT_LINK_DIR_NAME[:1]
        return trimmed + suffix

    def _is_windows_reserved_dir_name(self, dir_name: str) -> bool:
        return dir_name.rstrip(". ").upper() in WINDOWS_RESERVED_DIR_NAMES

    def _sanitize_link_dir_name(self, raw_name: str) -> tuple[str, list[str]]:
        sanitized = LINK_DIR_INVALID_CHARS_RE.sub("_", raw_name)
        sanitized = re.sub(r"\s+", " ", sanitized)
        sanitized = re.sub(r"_+", "_", sanitized)
        sanitized = sanitized.strip().strip(". ").rstrip(". ").strip()
        notes: list[str] = []

        if not sanitized or not sanitized.strip("._- "):
            sanitized = DEFAULT_LINK_DIR_NAME
            notes.append(f"链接目录名清洗后为空，已回退为默认目录名: {raw_name} -> {sanitized}")
        elif sanitized != raw_name:
            notes.append(f"链接目录名已清洗: {raw_name} -> {sanitized}")

        if self._is_windows_reserved_dir_name(sanitized):
            original_name = sanitized
            sanitized = f"{sanitized}_"
            notes.append(f"链接目录名命中 Windows 保留名，已自动调整: {original_name} -> {sanitized}")

        fitted_name = self._fit_link_dir_name_length(sanitized)
        if fitted_name != sanitized:
            notes.append(f"链接目录名过长，已按最大长度截断: {sanitized} -> {fitted_name}")
        return fitted_name, notes

    def _can_reuse_link_target_dir(self, target_dir: Path, file_name: str) -> bool:
        if not target_dir.exists():
            return True
        if not target_dir.is_dir():
            return False

        target_file = target_dir / file_name
        if target_file.exists() or target_file.is_symlink():
            return True

        try:
            return not any(target_dir.iterdir())
        except Exception:
            return False

    def _get_available_link_target_dir(self, output_dir: Path, dir_name: str, file_name: str) -> tuple[Path, str]:
        candidate_dir = output_dir / dir_name
        if self._can_reuse_link_target_dir(candidate_dir, file_name):
            return candidate_dir, ""

        suffix_index = 2
        while True:
            candidate_name = self._fit_link_dir_name_length(dir_name, f"_{suffix_index}")
            candidate_dir = output_dir / candidate_name
            if self._can_reuse_link_target_dir(candidate_dir, file_name):
                return candidate_dir, candidate_name
            suffix_index += 1

    def _prepare_link_target_dir(self, target_path: Path, group_in_named_dir: bool) -> tuple[bool, str, bool]:
        if not group_in_named_dir:
            return True, "", False

        target_dir = target_path.parent
        if target_dir == target_path:
            return False, "目标目录无效", False
        if target_dir.exists():
            if target_dir.is_dir():
                return True, "", False
            return False, f"目标目录已存在同名文件: {target_dir}", False

        try:
            target_dir.mkdir(parents=True, exist_ok=False)
            return True, "", True
        except Exception as error:
            return False, self._normalize_delete_error_reason(str(error)), False

    def _cleanup_empty_link_target_dir(self, target_path: Path, created_dir: bool) -> None:
        if not created_dir:
            return

        target_dir = target_path.parent
        try:
            if target_dir.exists() and target_dir.is_dir() and not any(target_dir.iterdir()):
                target_dir.rmdir()
                signal_qt.show_log_text(f" ↩ 创建失败，已回滚空目录: {target_dir}")
        except Exception as error:
            signal_qt.show_log_text(
                f" ⚠ 回滚空目录失败: {target_dir}\n    原因: {self._normalize_delete_error_reason(str(error))}"
            )

    def _create_links_for_selected_files(
        self, link_type: Literal["soft", "hard"], group_in_named_dir: bool = False
    ) -> None:
        selected_entries = self._get_selected_entries()
        if selected_entries:
            link_targets = [(show_name, file_path) for _, show_name, _, file_path in selected_entries]
        else:
            if not self._check_main_file_path():
                return
            link_targets = [(self.show_name or "", self.file_main_open_path)]

        if not link_targets:
            return

        link_name = "软链接" if link_type == "soft" else "硬链接"
        if group_in_named_dir:
            link_name = f"{link_name}（按文件名建目录）"
        should_record_success = self._confirm_record_link_paths(link_name)
        if should_record_success is None:
            return
        output_dir = self._select_link_output_dir(link_name)
        if output_dir is None:
            return

        signal_qt.show_log_text(f" 🔗 开始创建{link_name}")
        signal_qt.show_log_text(f" 📁 目标目录: {output_dir}")
        signal_qt.show_log_text(f" 📝 成功列表写入: {'是' if should_record_success else '否'}")

        success_count = 0
        skipped_count = 0
        success_paths_to_record: set[Path] = set()
        failure_details: list[tuple[Path, str]] = []
        for _show_name, file_path in link_targets:
            success, source_path, error_info = resolve_link_source_sync(file_path)
            if not success:
                failure_details.append((file_path, self._normalize_delete_error_reason(error_info)))
                signal_qt.show_log_text(
                    f" ❌ {link_name}失败: {file_path}\n    原因: {self._normalize_delete_error_reason(error_info)}"
                )
                continue

            target_path, target_notes = self._build_link_target_path(
                source_path, output_dir, file_path, group_in_named_dir
            )
            for note in target_notes:
                signal_qt.show_log_text(f" ℹ {note}")
            ok, dir_error, created_dir = self._prepare_link_target_dir(target_path, group_in_named_dir)
            if not ok:
                failure_details.append((target_path, dir_error))
                signal_qt.show_log_text(
                    f" ❌ {link_name}失败: {target_path}\n    源文件: {source_path}\n    原因: {dir_error}"
                )
                continue

            if link_type == "soft":
                result, info = create_symlink_sync(source_path, target_path)
            else:
                result, info = create_hardlink_sync(source_path, target_path)

            record_success, success_record_path, record_info = resolve_success_record_source_sync(file_path)
            if not record_success:
                success_record_path = file_path
                record_info = (
                    f"解析成功列表源路径失败，已回退记录当前路径: {self._normalize_delete_error_reason(record_info)}"
                )

            if result:
                if "已存在同源" in info:
                    skipped_count += 1
                    if should_record_success:
                        success_paths_to_record.add(success_record_path)
                    if record_info:
                        signal_qt.show_log_text(f" ℹ 成功列表记录路径: {success_record_path}\n    说明: {record_info}")
                    signal_qt.show_log_text(f" ⏭ 已跳过{link_name}: {target_path}\n    原因: {info}")
                else:
                    success_count += 1
                    if should_record_success:
                        success_paths_to_record.add(success_record_path)
                    if record_info:
                        signal_qt.show_log_text(f" ℹ 成功列表记录路径: {success_record_path}\n    说明: {record_info}")
                    signal_qt.show_log_text(f" ✅ 已创建{link_name}: {target_path}\n    源文件: {source_path}")
            else:
                self._cleanup_empty_link_target_dir(target_path, created_dir)
                failure_details.append((target_path, self._normalize_delete_error_reason(info)))
                signal_qt.show_log_text(
                    f" ❌ {link_name}失败: {target_path}\n    源文件: {source_path}\n    原因: {self._normalize_delete_error_reason(info)}"
                )

        if should_record_success and success_paths_to_record:
            Flags.success_list.update(success_paths_to_record)
            executor.run(save_success_list())
            signal_qt.show_log_text(f" 💾 已写入成功列表 {len(success_paths_to_record)} 项")

        fail_count = len(failure_details)
        signal_qt.show_log_text(
            f" 🎉 创建{link_name}完成：成功 {success_count} 个，跳过 {skipped_count} 个，失败 {fail_count} 个"
        )
        if fail_count:
            signal_qt.show_scrape_info(
                f"💡 创建{link_name}完成，成功 {success_count} 个，跳过 {skipped_count} 个，失败 {fail_count} 个！{get_current_time()}"
            )
            self._show_action_failure_feedback(f"创建{link_name}", success_count, failure_details, skipped_count)
        elif skipped_count and not success_count:
            signal_qt.show_scrape_info(
                f"💡 所选文件的{link_name}已存在，已跳过 {skipped_count} 个！{get_current_time()}"
            )
        elif skipped_count:
            signal_qt.show_scrape_info(
                f"💡 创建{link_name}完成，成功 {success_count} 个，跳过 {skipped_count} 个！{get_current_time()}"
            )
        elif success_count == 1:
            signal_qt.show_scrape_info(f"💡 已创建{link_name}！{get_current_time()}")
        else:
            signal_qt.show_scrape_info(f"💡 已创建 {success_count} 个{link_name}！{get_current_time()}")

    def _find_result_item_by_name(self, show_name: str) -> QTreeWidgetItem | None:
        for root_item in (self.item_succ, self.item_fail):
            for i in range(root_item.childCount()):
                child = root_item.child(i)
                if child.text(0) == show_name:
                    return child
        return None

    def _clear_main_info_panel(self) -> None:
        self.set_main_info(None)
        self.file_main_open_path = Path()
        self.show_name = None
        self.show_data = None
        if not self.Ui.widget_nfo.isHidden():
            self.Ui.widget_nfo.hide()

    def _remove_deleted_result_items(self, show_names: list[str]) -> None:
        if not show_names:
            return

        current_show_name = self.show_name
        for show_name in show_names:
            self.json_array.pop(show_name, None)

        for show_name in show_names:
            item = self._find_result_item_by_name(show_name)
            if item is None:
                continue
            parent = item.parent()
            if parent is not None:
                parent.removeChild(item)

        self.Ui.treeWidget_number.clearSelection()
        if current_show_name in show_names:
            self._clear_main_info_panel()

    # 主界面-点击树状条目
    def treeWidget_number_clicked(self, *_args):
        selected_items = self._get_selected_result_items()
        if len(selected_items) != 1:
            if len(selected_items) > 1:
                self._clear_main_info_panel()
            return

        item = selected_items[0]
        try:
            index_json = str(item.text(0))
            self.set_main_info(self.json_array[index_json])
            if not self.Ui.widget_nfo.isHidden():
                self._show_nfo_info()
        except Exception:
            signal_qt.show_traceback_log(item.text(0) + ": No info!")

    def _check_main_file_path(self):
        selected_entries = self._get_selected_entries()
        if len(selected_entries) > 1:
            QMessageBox.about(self, "选择过多", "请只选择一个项目后再使用！！")
            signal_qt.show_scrape_info(f"💡 请只选择一个项目后再使用！{get_current_time()}")
            return False
        if len(selected_entries) == 1:
            _, show_name, show_data, file_path = selected_entries[0]
            self.show_name = show_name
            self.set_main_info(show_data)
            self.file_main_open_path = file_path

        if self.file_main_open_path == Path() or not self.file_main_open_path.is_file():
            QMessageBox.about(self, "没有目标文件", "请刮削后再使用！！")
            signal_qt.show_scrape_info(f"💡 请刮削后使用！{get_current_time()}")
            return False
        return True

    def main_play_click(self):
        """
        主界面点播放
        """
        # 发送hover事件，清除hover状态（因为弹窗后，失去焦点，状态不会变化）
        self.Ui.pushButton_play.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_play, event)
        if self._check_main_file_path():
            # mac需要改为无焦点状态，不然弹窗失去焦点后，再切换回来会有找不到焦点的问题（windows无此问题）
            # if not self.is_windows:
            #     self.setWindowFlags(self.windowFlags() | Qt.WindowDoesNotAcceptFocus)
            #     self.show()
            # 启动线程打开文件
            t = threading.Thread(target=open_file_thread, args=(self.file_main_open_path, False))
            t.start()

    def main_open_folder_click(self):
        """
        主界面点打开文件夹
        """
        self.Ui.pushButton_open_folder.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_open_folder, event)
        if self._check_main_file_path():
            # mac需要改为无焦点状态，不然弹窗失去焦点后，再切换回来会有找不到焦点的问题（windows无此问题）
            # if not self.is_windows:
            #     self.setWindowFlags(self.windowFlags() | Qt.WindowDoesNotAcceptFocus)
            #     self.show()
            # 启动线程打开文件
            t = threading.Thread(target=open_file_thread, args=(self.file_main_open_path, True))
            t.start()

    def main_open_nfo_click(self):
        """
        主界面点打开nfo
        """
        self.Ui.pushButton_open_nfo.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_open_nfo, event)
        if self._check_main_file_path():
            self.Ui.widget_nfo.show()
            self._show_nfo_info()

    def main_open_right_menu(self):
        """
        主界面点打开右键菜单
        """
        # 发送hover事件，清除hover状态（因为弹窗后，失去焦点，状态不会变化）
        self.Ui.pushButton_right_menu.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_right_menu, event)
        self._menu()

    def search_by_number_clicked(self):
        """
        主界面点输入番号
        """
        if self._check_main_file_path():
            file_path = self.file_main_open_path
            main_file_name = split_path(file_path)[1]
            default_text = os.path.splitext(main_file_name)[0].upper()
            text, ok = QInputDialog.getText(
                self, "输入番号重新刮削", f"文件名: {main_file_name}\n请输入番号:", text=default_text
            )
            if ok and text:
                Flags.again_dic[file_path] = (text, "", "")
                signal_qt.show_scrape_info(f"💡 已添加刮削！{get_current_time()}")
                if self.Ui.pushButton_start_cap.text() == "开始":
                    again_search()

    def search_by_url_clicked(self):
        """
        主界面点输入网址
        """
        if self._check_main_file_path():
            file_path = self.file_main_open_path
            main_file_name = split_path(file_path)[1]
            text, ok = QInputDialog.getText(
                self,
                "输入网址重新刮削",
                f"文件名: {main_file_name}\n支持网站:airav_cc、avsex、avsox、dmm、getchu、fc2"
                f"、fc2club、fc2hub、iqqtv、jav321、javbus、javdb、freejavbt、javlibrary、mdtv"
                f"、madouqu、mgstage、7mmtv、xcity、mywife、giga、faleno、dahlia、fantastica、avbase"
                f"、prestige、hdouban、lulubar、love6、cnmdb、theporndb、kin8\n请输入番号对应的网址（不是网站首页地址！！！是番号页面地址！！！）:",
            )
            if ok and text:
                website, url = deal_url(text)
                if website:
                    Flags.again_dic[file_path] = ("", url, website)
                    signal_qt.show_scrape_info(f"💡 已添加刮削！{get_current_time()}")
                    if self.Ui.pushButton_start_cap.text() == "开始":
                        again_search()
                else:
                    signal_qt.show_scrape_info(f"💡 不支持的网站！{get_current_time()}")

    def main_del_file_click(self):
        """
        主界面点删除文件
        """
        selected_entries = self._get_selected_entries()
        if selected_entries:
            delete_targets = [(show_name, file_path) for _, show_name, _, file_path in selected_entries]
        else:
            if not self._check_main_file_path():
                return
            delete_targets = [(self.show_name or "", self.file_main_open_path)]

        if not delete_targets:
            return

        file_paths = [file_path for _, file_path in delete_targets]
        if len(file_paths) == 1:
            box_text = f"将要删除文件: \n{file_paths[0]}\n\n 你确定要删除吗？"
        else:
            box_text = (
                f"将要删除 {len(file_paths)} 个文件：\n{self._build_delete_preview(file_paths)}\n\n你确定要继续吗？"
            )

        box = QMessageBox(QMessageBox.Icon.Warning, "删除文件", box_text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("删除文件")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply != QMessageBox.StandardButton.Yes:
            return

        signal_qt.show_log_text(" 🗑 开始删除文件")
        signal_qt.show_log_text(f" 📦 本次待删除文件数: {len(file_paths)}")

        success_show_names = []
        failure_details: list[tuple[Path, str]] = []
        for show_name, file_path in delete_targets:
            result, error_info = delete_file_sync(file_path)
            if result:
                if show_name:
                    success_show_names.append(show_name)
                signal_qt.show_log_text(f" ✅ 已删除文件: {file_path}")
            else:
                reason = self._normalize_delete_error_reason(error_info)
                failure_details.append((file_path, reason))
                signal_qt.show_log_text(f" ❌ 删除文件失败: {file_path}\n    原因: {reason}")

        self._remove_deleted_result_items(success_show_names)
        fail_count = len(failure_details)
        success_count = len(file_paths) - fail_count
        signal_qt.show_log_text(f" 🎉 删除文件完成：成功 {success_count} 个，失败 {fail_count} 个")
        if fail_count:
            signal_qt.show_scrape_info(
                f"💡 文件删除完成，成功 {success_count} 个，失败 {fail_count} 个！{get_current_time()}"
            )
            self._show_action_failure_feedback("删除文件", success_count, failure_details)
        elif success_count == 1:
            signal_qt.show_scrape_info(f"💡 已删除文件！{get_current_time()}")
        else:
            signal_qt.show_scrape_info(f"💡 已删除 {success_count} 个文件！{get_current_time()}")

    def main_del_folder_click(self):
        """
        主界面点删除文件夹
        """
        selected_entries = self._get_selected_entries()
        if selected_entries:
            delete_targets = [(show_name, file_path) for _, show_name, _, file_path in selected_entries]
        else:
            if not self._check_main_file_path():
                return
            delete_targets = [(self.show_name or "", self.file_main_open_path)]

        if not delete_targets:
            return

        file_paths = [file_path for _, file_path in delete_targets]
        folder_to_show_names: dict[Path, list[str]] = {}
        for show_name, file_path in delete_targets:
            folder_path = Path(split_path(file_path)[0])
            folder_to_show_names.setdefault(folder_path, [])
            if show_name:
                folder_to_show_names[folder_path].append(show_name)

        folder_paths = sorted(folder_to_show_names, key=lambda p: len(p.parts), reverse=True)
        if len(folder_paths) == 1:
            box_text = f"将要删除文件夹: \n{folder_paths[0]}\n\n 你确定要删除吗？"
        else:
            box_text = (
                f"将要删除 {len(folder_paths)} 个文件夹（来源于 {len(file_paths)} 个选中项）：\n"
                f"{self._build_delete_preview(folder_paths)}\n\n你确定要继续吗？"
            )

        box = QMessageBox(QMessageBox.Icon.Warning, "删除文件", box_text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("删除文件和文件夹")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply != QMessageBox.StandardButton.Yes:
            return

        signal_qt.show_log_text(" 🗑 开始删除文件夹")
        signal_qt.show_log_text(f" 📦 本次待删除文件夹数: {len(folder_paths)}")

        success_folder_count = 0
        success_show_names: list[str] = []
        failure_details: list[tuple[Path, str]] = []
        for folder_path in folder_paths:
            try:
                shutil.rmtree(folder_path)
                success_folder_count += 1
                success_show_names.extend(folder_to_show_names.get(folder_path, []))
                signal_qt.show_log_text(f" ✅ 已删除文件夹: {folder_path}")
            except FileNotFoundError:
                success_folder_count += 1
                success_show_names.extend(folder_to_show_names.get(folder_path, []))
                signal_qt.show_log_text(f" ✅ 文件夹不存在，按已删除处理: {folder_path}")
            except Exception as error:
                reason = self._normalize_delete_error_reason(str(error))
                failure_details.append((folder_path, reason))
                signal_qt.show_log_text(f" ❌ 删除文件夹失败: {folder_path}\n    原因: {reason}")

        if success_show_names:
            self._remove_deleted_result_items(success_show_names)

        fail_count = len(failure_details)
        signal_qt.show_log_text(f" 🎉 删除文件夹完成：成功 {success_folder_count} 个，失败 {fail_count} 个")
        if fail_count:
            self.show_scrape_info(
                f"💡 文件夹删除完成，成功 {success_folder_count} 个，失败 {fail_count} 个！{get_current_time()}"
            )
            self._show_action_failure_feedback("删除文件夹", success_folder_count, failure_details)
        elif success_folder_count == 1:
            self.show_scrape_info(f"💡 已删除文件夹！{get_current_time()}")
        else:
            self.show_scrape_info(f"💡 已删除 {success_folder_count} 个文件夹！{get_current_time()}")

    def main_make_symlink_click(self):
        """
        主界面在指定位置创建软链接
        """
        self._create_links_for_selected_files("soft")

    def main_make_symlink_in_dir_click(self):
        """
        主界面在指定位置创建软链接，并按文件名创建目录
        """
        self._create_links_for_selected_files("soft", group_in_named_dir=True)

    def main_make_hardlink_click(self):
        """
        主界面在指定位置创建硬链接
        """
        self._create_links_for_selected_files("hard")

    def main_make_hardlink_in_dir_click(self):
        """
        主界面在指定位置创建硬链接，并按文件名创建目录
        """
        self._create_links_for_selected_files("hard", group_in_named_dir=True)

    def _pic_main_clicked(self):
        """
        主界面点图片
        """
        file_info = None if self.show_data is None else self.show_data.file_info
        self.cutwindow.showimage(self.img_path, file_info)
        self.cutwindow.show()

    # 主界面-开关封面显示
    def checkBox_cover_clicked(self):
        if not self.Ui.checkBox_cover.isChecked():
            self.Ui.label_poster.setText("封面图")
            self.Ui.label_thumb.setText("缩略图")
            self.Ui.label_poster.resize(156, 220)
            self.Ui.label_thumb.resize(328, 220)
            self.Ui.label_poster_size.setText("")
            self.Ui.label_thumb_size.setText("")
        else:
            self.set_main_info(self.show_data)

    # region 主界面编辑nfo
    def _show_nfo_info(self):
        try:
            if not self.show_name:
                return
            show_data = self.json_array[self.show_name]
            json_data = show_data.data
            file_info = show_data.file_info
            self.now_show_name = show_data.show_name
            actor = json_data.actor
            if json_data.all_actor and NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
                actor = json_data.all_actor
            self.Ui.label_nfo.setText(str(file_info.file_path))
            self.Ui.lineEdit_nfo_number.setText(json_data.number)
            self.Ui.lineEdit_nfo_actor.setText(actor)
            self.Ui.lineEdit_nfo_year.setText(json_data.year)
            self.Ui.lineEdit_nfo_title.setText(json_data.title)
            self.Ui.lineEdit_nfo_originaltitle.setText(json_data.originaltitle)
            self.Ui.textEdit_nfo_outline.setPlainText(json_data.outline)
            self.Ui.textEdit_nfo_originalplot.setPlainText(json_data.originalplot)
            self.Ui.textEdit_nfo_tag.setPlainText(json_data.tag)
            self.Ui.lineEdit_nfo_release.setText(json_data.release)
            self.Ui.lineEdit_nfo_runtime.setText(json_data.runtime)
            self.Ui.lineEdit_nfo_score.setText(json_data.score)
            self.Ui.lineEdit_nfo_wanted.setText(json_data.wanted)
            self.Ui.lineEdit_nfo_director.setText(json_data.director)
            self.Ui.lineEdit_nfo_series.setText(json_data.series)
            self.Ui.lineEdit_nfo_studio.setText(json_data.studio)
            self.Ui.lineEdit_nfo_publisher.setText(json_data.publisher)
            self.Ui.lineEdit_nfo_poster.setText(json_data.poster)
            self.Ui.lineEdit_nfo_cover.setText(json_data.thumb)
            self.Ui.lineEdit_nfo_trailer.setText(json_data.trailer)
            all_items = [self.Ui.comboBox_nfo.itemText(i) for i in range(self.Ui.comboBox_nfo.count())]
            self.Ui.comboBox_nfo.setCurrentIndex(all_items.index(json_data.country))
        except Exception:
            if not signal_qt.stop:
                signal_qt.show_traceback_log(traceback.format_exc())

    def save_nfo_info(self):
        try:
            if self.now_show_name is None:
                return
            show_data = self.json_array[self.now_show_name]
            json_data = show_data.data
            file_info = show_data.file_info
            nfo_path = file_info.file_path.with_suffix(".nfo")
            nfo_folder = nfo_path.parent
            json_data.number = self.Ui.lineEdit_nfo_number.text()
            if NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
                json_data.all_actor = self.Ui.lineEdit_nfo_actor.text()
            json_data.actor = self.Ui.lineEdit_nfo_actor.text()
            json_data.year = self.Ui.lineEdit_nfo_year.text()
            json_data.title = self.Ui.lineEdit_nfo_title.text()
            json_data.originaltitle = self.Ui.lineEdit_nfo_originaltitle.text()
            json_data.outline = self.Ui.textEdit_nfo_outline.toPlainText()
            json_data.originalplot = self.Ui.textEdit_nfo_originalplot.toPlainText()
            json_data.tag = self.Ui.textEdit_nfo_tag.toPlainText()
            json_data.release = self.Ui.lineEdit_nfo_release.text()
            json_data.runtime = self.Ui.lineEdit_nfo_runtime.text()
            json_data.score = self.Ui.lineEdit_nfo_score.text()
            json_data.wanted = self.Ui.lineEdit_nfo_wanted.text()
            json_data.director = self.Ui.lineEdit_nfo_director.text()
            json_data.series = self.Ui.lineEdit_nfo_series.text()
            json_data.studio = self.Ui.lineEdit_nfo_studio.text()
            json_data.publisher = self.Ui.lineEdit_nfo_publisher.text()
            json_data.poster = self.Ui.lineEdit_nfo_poster.text()
            json_data.thumb = self.Ui.lineEdit_nfo_cover.text()
            json_data.trailer = self.Ui.lineEdit_nfo_trailer.text()
            if executor.run(write_nfo(file_info, json_data, nfo_path, nfo_folder, update=True)):
                self.Ui.label_save_tips.setText(f"已保存! {get_current_time()}")
                self.set_main_info(show_data)
            else:
                self.Ui.label_save_tips.setText(f"保存失败! {get_current_time()}")
        except Exception:
            if not signal_qt.stop:
                signal_qt.show_traceback_log(traceback.format_exc())

    # endregion

    # 主界面左下角显示信息
    def show_scrape_info(self, before_info=""):
        try:
            if Flags.file_mode == FileMode.Single:
                scrape_info = f"💡 单文件刮削\n💠 {Flags.main_mode_text} · {self.Ui.comboBox_website_all.currentText()}"
            else:
                scrape_info = f"💠 {Flags.main_mode_text} · {Flags.scrape_like_text}"
                if manager.config.scrape_like == "single":
                    scrape_info = f"💡 {manager.config.website_single} 刮削\n" + scrape_info
            if manager.config.soft_link == 1:
                scrape_info = "🍯 软链接 · 开\n" + scrape_info
            elif manager.config.soft_link == 2:
                scrape_info = "🍯 硬链接 · 开\n" + scrape_info
            after_info = f"\n{scrape_info}\n🛠 {manager.file}\n🐰 MDCx {self.localversion}"
            self.label_show_version.emit(before_info + after_info + self.new_version)
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # region 获取/保存成功刮削列表
    def pushButton_success_list_save_clicked(self):
        box = QMessageBox(QMessageBox.Icon.Warning, "保存成功列表", "确定要将当前列表保存为已刮削成功文件列表吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("保存")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            success_text = self.Ui.textBrowser_show_success_list.toPlainText().replace("暂无成功刮削的文件", "").strip()
            Flags.success_list = {
                p for path in success_text.splitlines() if (line := path.strip()) and (p := Path(line)).suffix
            }
            executor.run(save_success_list())
            get_success_list()
            self.Ui.widget_show_success.hide()

    def pushButton_success_list_clear_clicked(self):
        box = QMessageBox(QMessageBox.Icon.Warning, "清空成功列表", "确定要清空当前已刮削成功文件列表吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("清空")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            Flags.success_list.clear()
            executor.run(save_success_list())
            self.Ui.widget_show_success.hide()

    def pushButton_view_success_file_clicked(self):
        self.Ui.widget_show_success.show()
        info = "暂无成功刮削的文件"
        if len(Flags.success_list):
            info = "\n".join(sorted(str(p) for p in Flags.success_list))
        self.Ui.textBrowser_show_success_list.setText(info)

    # endregion
    # endregion

    # region 日志页
    # 日志页点展开折叠日志
    def pushButton_show_hide_logs_clicked(self):
        if self.Ui.textBrowser_log_main_2.isHidden():
            self.show_hide_logs(True)
        else:
            self.show_hide_logs(False)

    # 日志页点展开折叠日志
    def show_hide_logs(self, show):
        if show:
            self.Ui.pushButton_show_hide_logs.setIcon(QIcon(resources.hide_logs_icon))
            self.Ui.textBrowser_log_main_2.show()
            self.Ui.textBrowser_log_main.resize(790, 418)
            self.Ui.textBrowser_log_main.verticalScrollBar().setValue(
                self.Ui.textBrowser_log_main.verticalScrollBar().maximum()
            )
            self.Ui.textBrowser_log_main_2.verticalScrollBar().setValue(
                self.Ui.textBrowser_log_main_2.verticalScrollBar().maximum()
            )

            # self.Ui.textBrowser_log_main_2.moveCursor(self.Ui.textBrowser_log_main_2.textCursor().End)

        else:
            self.Ui.pushButton_show_hide_logs.setIcon(QIcon(resources.show_logs_icon))
            self.Ui.textBrowser_log_main_2.hide()
            self.Ui.textBrowser_log_main.resize(790, 689)
            self.Ui.textBrowser_log_main.verticalScrollBar().setValue(
                self.Ui.textBrowser_log_main.verticalScrollBar().maximum()
            )

    # 日志页点展开折叠失败列表
    def pushButton_show_hide_failed_list_clicked(self):
        if self.Ui.textBrowser_log_main_3.isHidden():
            self.show_hide_failed_list(True)
        else:
            self.show_hide_failed_list(False)

    # 日志页点展开折叠失败列表
    def show_hide_failed_list(self, show):
        if show:
            self.Ui.textBrowser_log_main_3.show()
            self.Ui.pushButton_scraper_failed_list.show()
            self.Ui.pushButton_save_failed_list.show()
            self.Ui.textBrowser_log_main_3.verticalScrollBar().setValue(
                self.Ui.textBrowser_log_main_3.verticalScrollBar().maximum()
            )

        else:
            self.Ui.pushButton_save_failed_list.hide()
            self.Ui.textBrowser_log_main_3.hide()
            self.Ui.pushButton_scraper_failed_list.hide()

    # 日志页点一键刮削失败列表
    def pushButton_scraper_failed_list_clicked(self):
        if len(Flags.failed_list) and self.Ui.pushButton_start_cap.text() == "开始":
            start_new_scrape(FileMode.Default, movie_list=[s[0] for s in Flags.failed_list])
            self.show_hide_failed_list(False)

    # 日志页点另存失败列表
    def pushButton_save_failed_list_clicked(self):
        if len(Flags.failed_list):
            log_name = "failed_" + time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime()) + ".txt"
            log_name = get_movie_path_setting().movie_path / log_name
            filename, filetype = QFileDialog.getSaveFileName(
                None, "保存失败文件列表", log_name.as_posix(), "Text Files (*.txt)", options=self.options
            )
            if filename:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(self.Ui.textBrowser_log_main_3.toPlainText().strip())

    def _write_main_logs_to_file(self, logs: list[str]):
        if not logs:
            return
        text = "\n".join(logs) + "\n"
        try:
            Flags.log_txt.write(text.encode("utf-8"))
        except Exception:
            log_folder = manager.data_folder / "Log"
            if not os.path.exists(log_folder):
                os.makedirs(log_folder, exist_ok=True)
            log_name = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime()) + ".txt"
            log_name = log_folder / log_name
            try:
                Flags.log_txt = open(log_name, "wb", buffering=0)
                Flags.log_txt.write(text.encode("utf-8"))
                self.main_log_queue.appendleft(f"创建日志文件: {log_name}")
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())

    def _flush_main_log_queue(self):
        if not self.main_log_queue:
            return
        logs: list[str] = []
        while self.main_log_queue and len(logs) < self.main_log_batch_size:
            logs.append(self.main_log_queue.popleft())
        if manager.config.save_log:
            self._write_main_logs_to_file(logs)
        try:
            self.logs_counts += len(logs)
            if self.logs_counts >= self.main_log_max_count:
                self.logs_counts = len(logs)
                self.main_logs_clear.emit("")
                self.main_logs_show.emit(add_html(" 🗑️ 日志过多，已清屏！"))
            self.main_logs_show.emit(add_html("\n".join(logs)))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self.Ui.textBrowser_log_main.append(traceback.format_exc())

    # 显示详细日志
    def show_detail_log(self):
        text = signal_qt.get_log()
        if text and manager.config.show_web_log:
            self.main_req_logs_show.emit(add_html_plain_text(text))
            if self.req_logs_counts < 10000:
                self.req_logs_counts += 1
            else:
                self.req_logs_counts = 0
                self.req_logs_clear.emit("")
                self.main_req_logs_show.emit(add_html_plain_text(" 🗑️ 日志过多，已清屏！"))

    # 日志页面显示内容
    def show_log_text(self, text):
        if not text:
            return
        self.main_log_queue.append(str(text))

    # endregion

    # region 工具页
    # 工具页面点查看本地番号
    def label_local_number_clicked(self, ev):
        if self.Ui.pushButton_find_missing_number.isEnabled():
            self.pushButton_show_log_clicked()  # 点击按钮后跳转到日志页面
            if self.Ui.lineEdit_actors_name.text() != manager.config.actors_name:  # 保存配置
                self.pushButton_save_config_clicked()
            executor.submit(check_missing_number(False))

    # 工具页面本地资源库点选择目录
    def pushButton_select_local_library_clicked(self):
        media_folder_path = self._get_select_folder_path()
        if media_folder_path:
            self.Ui.lineEdit_local_library_path.setText(media_folder_path)
            self.pushButton_save_config_clicked()

    # 工具页面网盘目录点选择目录
    def pushButton_select_netdisk_path_clicked(self):
        media_folder_path = self._get_select_folder_path()
        if media_folder_path:
            self.Ui.lineEdit_netdisk_path.setText(media_folder_path)
            self.pushButton_save_config_clicked()

    # 工具页面本地目录点选择目录
    def pushButton_select_localdisk_path_clicked(self):
        media_folder_path = self._get_select_folder_path()
        if media_folder_path:
            self.Ui.lineEdit_localdisk_path.setText(media_folder_path)
            self.pushButton_save_config_clicked()

    # 工具/设置页面点选择目录
    def pushButton_select_media_folder_clicked(self):
        media_folder_path = self._get_select_folder_path()
        if media_folder_path:
            self.Ui.lineEdit_movie_path.setText(media_folder_path)
            self.pushButton_save_config_clicked()

    # 工具-软链接助手
    def pushButton_creat_symlink_clicked(self):
        """
        工具点一键创建软链接
        """
        self.pushButton_show_log_clicked()  # 点击按钮后跳转到日志页面

        if Switch.COPY_NETDISK_NFO in manager.config.switch_on != self.Ui.checkBox_copy_netdisk_nfo.isChecked():
            self.pushButton_save_config_clicked()

        try:
            executor.submit(newtdisk_creat_symlink(self.Ui.checkBox_copy_netdisk_nfo.isChecked()))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    # 工具-检查番号
    def pushButton_find_missing_number_clicked(self):
        """
        工具点检查缺失番号
        """
        self.pushButton_show_log_clicked()  # 点击按钮后跳转到日志页面

        # 如果本地资源库或演员与配置内容不同，则自动保存
        if (
            self.Ui.lineEdit_actors_name.text() != manager.config.actors_name
            or self.Ui.lineEdit_local_library_path.text() != manager.config.local_library
        ):
            self.pushButton_save_config_clicked()
        executor.submit(check_missing_number(True))

    # 工具-单文件刮削
    def pushButton_select_file_clicked(self):
        media_path = self.Ui.lineEdit_movie_path.text()  # 获取待刮削目录作为打开目录
        if not media_path:
            media_path = manager.data_folder
        else:
            media_path = Path(media_path)
        file_path, filetype = QFileDialog.getOpenFileName(
            None,
            "选取视频文件",
            media_path.as_posix(),
            "Movie Files(*.mp4 "
            "*.avi *.rmvb *.wmv "
            "*.mov *.mkv *.flv *.ts "
            "*.webm *.MP4 *.AVI "
            "*.RMVB *.WMV *.MOV "
            "*.MKV *.FLV *.TS "
            "*.WEBM);;All Files(*)",
            options=self.options,
        )
        if file_path:
            self.Ui.lineEdit_single_file_path.setText(file_path)

    def pushButton_start_single_file_clicked(self):  # 点刮削
        Flags.single_file_path = Path(self.Ui.lineEdit_single_file_path.text().strip())
        if not Flags.single_file_path:
            signal_qt.show_scrape_info("💡 请选择文件！")
            return

        if not os.path.isfile(Flags.single_file_path):
            signal_qt.show_scrape_info("💡 文件不存在！")  # 主界面左下角显示信息
            return

        if not self.Ui.lineEdit_appoint_url.text():
            signal_qt.show_scrape_info("💡 请填写番号网址！")  # 主界面左下角显示信息
            return

        self.pushButton_show_log_clicked()  # 点击刮削按钮后跳转到日志页面
        Flags.appoint_url = self.Ui.lineEdit_appoint_url.text().strip()
        # 单文件刮削从用户输入的网址中识别网址名，复用现成的逻辑=>主页面输入网址刮削
        website, url = deal_url(Flags.appoint_url)
        if website:
            Flags.website_name = website
        else:
            signal_qt.show_scrape_info(f"💡 不支持的网站！{get_current_time()}")
            return
        start_new_scrape(FileMode.Single)

    def pushButton_select_file_clear_info_clicked(self):  # 点清空信息
        self.Ui.lineEdit_single_file_path.setText("")
        self.Ui.lineEdit_appoint_url.setText("")

        # self.Ui.lineEdit_movie_number.setText('')

    # 工具-裁剪封面图
    def pushButton_select_thumb_clicked(self):
        path = self.Ui.lineEdit_movie_path.text()
        if not path:
            path = manager.data_folder.as_posix()
        file_path, fileType = QFileDialog.getOpenFileName(
            None, "选取缩略图", path, "Picture Files(*.jpg *.png);;All Files(*)", options=self.options
        )
        if file_path:
            self.cutwindow.showimage(Path(file_path))
            self.cutwindow.show()

    # 工具-视频移动
    def pushButton_move_mp4_clicked(self):
        box = QMessageBox(QMessageBox.Icon.Warning, "移动视频和字幕", "确定要移动视频和字幕吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("移动")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            self.pushButton_show_log_clicked()  # 点击开始移动按钮后跳转到日志页面
            try:
                t = threading.Thread(target=self._move_file_thread)
                self.threads_list.append(t)
                t.start()  # 启动线程,即让线程开始执行
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())
                signal_qt.show_log_text(traceback.format_exc())

    def _move_file_thread(self):
        signal_qt.change_buttons_status.emit()
        c = get_movie_path_setting()
        movie_path = c.movie_path
        ignore_dirs = c.ignore_dirs
        ignore_dirs.append(movie_path / "Movie_moved")
        movie_list = executor.run(
            movie_lists(ignore_dirs, manager.config.media_type + manager.config.sub_type, movie_path)
        )
        if not movie_list:
            signal_qt.show_log_text("No movie found!")
            signal_qt.show_log_text("================================================================================")
            signal_qt.reset_buttons_status.emit()
            return
        des_path = movie_path / "Movie_moved"
        if not des_path.exists():
            signal_qt.show_log_text("Created folder: Movie_moved")
            os.makedirs(des_path)
        signal_qt.show_log_text("Start move movies...")
        skip_list = []
        for file_path in movie_list:
            file_name = file_path.name
            file_ext = file_path.suffix.lower()
            try:
                shutil.move(file_path, des_path)
                if file_ext in manager.config.media_type:
                    signal_qt.show_log_text("   Move movie: " + file_name + " to Movie_moved Success!")
                else:
                    signal_qt.show_log_text("   Move sub: " + file_name + " to Movie_moved Success!")
            except Exception as e:
                skip_list.append([file_name, file_path, str(e)])
        if skip_list:
            signal_qt.show_log_text(f"\n{len(skip_list)} file(s) did not move!")
            i = 0
            for info in skip_list:
                i += 1
                signal_qt.show_log_text(f"[{i}] {info[0]}\n file path: {info[1]}\n {info[2]}\n")
        signal_qt.show_log_text("Move movies finished!")
        signal_qt.show_log_text("================================================================================")
        signal_qt.reset_buttons_status.emit()

    # endregion

    # region 设置页
    # region 选择目录
    # 设置-目录-软链接目录-点选择目录
    def pushButton_select_softlink_folder_clicked(self):
        media_folder_path = self._get_select_folder_path()
        if media_folder_path:
            self.Ui.lineEdit_movie_softlink_path.setText(media_folder_path)
            self.pushButton_save_config_clicked()

    # 设置-目录-成功输出目录-点选择目录
    def pushButton_select_sucess_folder_clicked(self):
        media_folder_path = self._get_select_folder_path()
        if media_folder_path:
            self.Ui.lineEdit_success.setText(media_folder_path)
            self.pushButton_save_config_clicked()

    # 设置-目录-失败输出目录-点选择目录
    def pushButton_select_failed_folder_clicked(self):
        media_folder_path = self._get_select_folder_path()
        if media_folder_path:
            self.Ui.lineEdit_fail.setText(media_folder_path)
            self.pushButton_save_config_clicked()

    # 设置-字幕-字幕文件目录-点选择目录
    def pushButton_select_subtitle_folder_clicked(self):
        media_folder_path = self._get_select_folder_path()
        if media_folder_path:
            self.Ui.lineEdit_sub_folder.setText(media_folder_path)
            self.pushButton_save_config_clicked()

    # 设置-头像-头像文件目录-点选择目录
    def pushButton_select_actor_photo_folder_clicked(self):
        media_folder_path = self._get_select_folder_path()
        if media_folder_path:
            self.Ui.lineEdit_actor_photo_folder.setText(media_folder_path)
            self.pushButton_save_config_clicked()

    # 设置-其他-配置文件目录-点选择目录
    def pushButton_select_config_folder_clicked(self):
        p = self._get_select_folder_path()
        if not p:
            return
        p = Path(p)
        if p.is_dir() and p != manager.data_folder:
            manager.list_configs()
            config_path = p / "config.json"
            manager.path = config_path
            if config_path.is_file():
                temp_dark = self.dark_mode
                temp_window_radius = self.window_radius
                self.load_config()
                if temp_dark != self.dark_mode and temp_window_radius == self.window_radius:
                    self.show_flag = True
                    self._windows_auto_adjust()
            else:
                self.Ui.lineEdit_config_folder.setText(str(p))
                self.pushButton_save_config_clicked()
            signal_qt.show_scrape_info(f"💡 目录已切换！{get_current_time()}")

    # endregion

    # 设置-演员-补全信息-演员信息数据库-选择文件按钮
    def pushButton_select_actor_info_db_clicked(self):
        database_path, _ = QFileDialog.getOpenFileName(
            None, "选择数据库文件", manager.data_folder.as_posix(), options=self.options
        )
        if database_path:
            self.Ui.lineEdit_actor_db_path.setText(database_path)
            self.pushButton_save_config_clicked()

    # region 设置-问号
    def pushButton_tips_normal_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_normal_mode.toolTip())

    def pushButton_tips_sort_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_sort_mode.toolTip())

    def pushButton_tips_update_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_update_mode.toolTip())

    def pushButton_tips_read_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_read_mode.toolTip())

    def pushButton_tips_soft_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_soft.toolTip())

    def pushButton_tips_hard_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_hard.toolTip())

    # 设置-显示说明信息
    def _show_tips(self, msg):
        self.Ui.textBrowser_show_tips.setText(msg)
        self.Ui.widget_show_tips.show()

    # 设置-刮削网站和字段中的详细说明弹窗
    def pushButton_scrape_note_clicked(self):
        self._show_tips("""<html>
<head/>
<body>
  <p><span style=" font-weight:700;">所有可用网站:</span></p>
  <li>airav_cc</li>
  <li>avbase</li>
  <li>avsex</li>
  <li>avsox</li>
  <li>cableav</li>
  <li>cnmdb</li>
  <li>dmm</li>
  <li>faleno</li>
  <li>fantastica</li>
  <li>fc2</li>
  <li>fc2club</li>
  <li>fc2hub</li>
  <li>fc2ppvdb</li>
  <li>freejavbt</li>
  <li>getchu</li>
  <li>giga</li>
  <li>hdouban</li>
  <li>hscangku</li>
  <li>iqqtv</li>
  <li>jav321</li>
  <li>javbus</li>
  <li>javday</li>
  <li>javdb</li>
  <li>javlibrary</li>
  <li>kin8</li>
  <li>love6</li>
  <li>lulubar</li>
  <li>madouqu</li>
  <li>mdtv</li>
  <li>missav</li>
  <li>mgstage</li>
  <li>7mmtv</li>
  <li>mywife</li>
  <li>prestige</li>
  <li>theporndb</li>
  <li>xcity</li>
  <li>dahlia</li>
  <li>getchu_dmm</li>
  <li>official</li>
  <p><span style=" font-weight:700;">指定类型影片可指定刮削网站:<span></p>
  <p>· 欧美：theporndb </p>
  <p>· 国产：mdtv、madouqu、hdouban、cnmdb、love6</p>
  <p>· 里番：getchu_dmm </p>
  <p>· Mywife：mywife </p>
  <p>· GIGA：giga </p>
  <p>· Kin8：Kin8 </p>
</body>
</html>""")

    def pushButton_field_tips_nfo_clicked(self):
        msg = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n\
<movie>\n\
    <plot><![CDATA[剧情简介]]></plot>\n\
    <outline><![CDATA[剧情简介]]></outline>\n\
    <originalplot><![CDATA[原始剧情简介]]></originalplot>\n\
    <tagline>发行日期 XXXX-XX-XX</tagline> \n\
    <premiered>发行日期</premiered>\n\
    <releasedate>发行日期</releasedate>\n\
    <release>发行日期</release>\n\
    <num>番号</num>\n\
    <title>标题</title>\n\
    <originaltitle>原始标题</originaltitle>\n\
    <sorttitle>类标题 </sorttitle>\n\
    <mpaa>家长分级</mpaa>\n\
    <customrating>自定义分级</customrating>\n\
    <actor>\n\
        <name>名字</name>\n\
        <type>类型：演员</type>\n\
    </actor>\n\
    <director>导演</director>\n\
    <rating>评分</rating>\n\
    <criticrating>影评人评分</criticrating>\n\
    <votes>想看人数</votes>\n\
    <year>年份</year>\n\
    <runtime>时长</runtime>\n\
    <series>系列</series>\n\
    <set>\n\
        <name>合集</name>\n\
    </set>\n\
    <studio>片商/制作商</studio> \n\
    <maker>片商/制作商</maker>\n\
    <publisher>厂牌/发行商</publisher>\n\
    <label>厂牌/发行商</label>\n\
    <tag>标签</tag>\n\
    <genre>风格</genre>\n\
    <cover>背景图地址</cover>\n\
    <poster>封面图地址</poster>\n\
    <trailer>预告片地址</trailer>\n\
    <website>刮削网址</website>\n\
</movie>\n\
        """
        self._show_tips(msg)

    # endregion

    # 设置-刮削目录 点击检查待刮削目录并清理文件
    def pushButton_check_and_clean_files_clicked(self):
        if not manager.computed.can_clean:
            self.pushButton_save_config_clicked()
        self.pushButton_show_log_clicked()
        try:
            executor.submit(check_and_clean_files())
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    # 设置-字幕 为所有视频中的无字幕视频添加字幕
    def pushButton_add_sub_for_all_video_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_sub_for_all_video())
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    # region 设置-下载
    # 为所有视频中的创建/删除剧照附加内容
    def pushButton_add_all_extras_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_extras("add"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    def pushButton_del_all_extras_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_extras("del"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # 为所有视频中的创建/删除剧照副本
    def pushButton_add_all_extrafanart_copy_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        self.pushButton_save_config_clicked()
        try:
            executor.submit(add_del_extrafanart_copy("add"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    def pushButton_del_all_extrafanart_copy_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        self.pushButton_save_config_clicked()
        try:
            executor.submit(add_del_extrafanart_copy("del"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # 为所有视频中的创建/删除主题视频
    def pushButton_add_all_theme_videos_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_theme_videos("add"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    def pushButton_del_all_theme_videos_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_theme_videos("del"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # endregion

    # region 设置-演员
    # 设置-演员 补全演员信息
    def pushButton_add_actor_info_clicked(self):
        self.pushButton_save_config_clicked()
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(update_emby_actor_info())
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # 设置-演员 补全演员头像按钮
    def pushButton_add_actor_pic_clicked(self):
        self.pushButton_save_config_clicked()
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(update_emby_actor_photo())
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # 设置-演员 补全演员头像按钮 kodi
    def pushButton_add_actor_pic_kodi_clicked(self):
        self.pushButton_save_config_clicked()
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(creat_kodi_actors(True))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # 设置-演员 清除演员头像按钮 kodi
    def pushButton_del_actor_folder_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(creat_kodi_actors(False))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # 设置-演员 查看演员列表按钮
    def pushButton_show_pic_actor_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(show_emby_actor_list(self.Ui.comboBox_pic_actor.currentIndex()))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # endregion

    # 设置-线程数量
    def lcdNumber_thread_change(self):
        thread_number = self.Ui.horizontalSlider_thread.value()
        self.Ui.lcdNumber_thread.display(thread_number)

    # 设置-javdb延时
    def lcdNumber_javdb_time_change(self):
        javdb_time = self.Ui.horizontalSlider_javdb_time.value()
        self.Ui.lcdNumber_javdb_time.display(javdb_time)

    # 设置-其他网站延时
    def lcdNumber_thread_time_change(self):
        thread_time = self.Ui.horizontalSlider_thread_time.value()
        self.Ui.lcdNumber_thread_time.display(thread_time)

    # 设置-超时时间
    def lcdNumber_timeout_change(self):
        timeout = self.Ui.horizontalSlider_timeout.value()
        self.Ui.lcdNumber_timeout.display(timeout)

    # 设置-重试次数
    def lcdNumber_retry_change(self):
        retry = self.Ui.horizontalSlider_retry.value()
        self.Ui.lcdNumber_retry.display(retry)

    # 设置-水印大小
    def lcdNumber_mark_size_change(self):
        mark_size = self.Ui.horizontalSlider_mark_size.value()
        self.Ui.lcdNumber_mark_size.display(mark_size)

    # 设置-网络-网址设置-下拉框切换
    def switch_custom_website_change(self, site):
        if site not in Website:
            return
        site = Website(site)
        self.Ui.lineEdit_site_custom_url.setText(manager.config.get_site_url(site))

    # 切换配置
    def config_file_change(self, new_config_file: str):
        if new_config_file != manager.file:
            new_config_path = manager.data_folder / new_config_file
            signal_qt.show_log_text(
                f"\n================================================================================\n切换配置：{new_config_path}"
            )
            manager.path = new_config_path
            temp_dark = self.dark_mode
            temp_window_radius = self.window_radius
            self.load_config()
            if temp_dark != self.dark_mode and temp_window_radius == self.window_radius:
                self.show_flag = True
                self._windows_auto_adjust()
            signal_qt.show_scrape_info(f"💡 配置已切换！{get_current_time()}")

    # 重置配置
    def pushButton_init_config_clicked(self):
        self.Ui.pushButton_init_config.setEnabled(False)
        manager.reset()
        temp_dark = self.dark_mode
        temp_window_radius = self.window_radius
        self.load_config()
        if temp_dark and temp_window_radius:
            self.show_flag = True
            self._windows_auto_adjust()
        self.Ui.pushButton_init_config.setEnabled(True)
        signal_qt.show_scrape_info(f"💡 配置已重置！{get_current_time()}")

    # 设置-命名-分集-字母
    def checkBox_cd_part_a_clicked(self):
        if self.Ui.checkBox_cd_part_a.isChecked():
            self.Ui.checkBox_cd_part_c.setEnabled(True)
        else:
            self.Ui.checkBox_cd_part_c.setEnabled(False)

    # 设置-刮削目录-同意清理(我已知晓/我已同意)
    def checkBox_i_agree_clean_clicked(self):
        if self.Ui.checkBox_i_understand_clean.isChecked() and self.Ui.checkBox_i_agree_clean.isChecked():
            self.Ui.pushButton_check_and_clean_files.setEnabled(True)
            self.Ui.checkBox_auto_clean.setEnabled(True)
        else:
            self.Ui.pushButton_check_and_clean_files.setEnabled(False)
            self.Ui.checkBox_auto_clean.setEnabled(False)

    # 读取设置页的设置, 保存config.ini，然后重新加载
    def _check_mac_config_folder(self):
        if self.check_mac and not IS_WINDOWS and ".app/Contents/Resources" in manager.data_folder.as_posix():
            self.check_mac = False
            box = QMessageBox(
                QMessageBox.Icon.Warning,
                "选择配置文件目录",
                f"检测到当前配置文件目录为：\n {manager.data_folder}\n\n由于 MacOS 平台在每次更新 APP 版本时会覆盖该目录的配置，因此请选择其他的配置目录！\n这样下次更新 APP 时，选择相同的配置目录即可读取你之前的配置！！！",
            )
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.button(QMessageBox.StandardButton.Yes).setText("选择目录")
            box.button(QMessageBox.StandardButton.No).setText("取消")
            box.setDefaultButton(QMessageBox.StandardButton.Yes)
            reply = box.exec()
            if reply == QMessageBox.StandardButton.Yes:
                self.pushButton_select_config_folder_clicked()

    # 设置-保存
    def pushButton_save_config_clicked(self):
        self.save_config()
        self.load_config()  # 确保界面显示和实际配置一致
        signal_qt.show_scrape_info(f"💡 配置已保存！{get_current_time()}")

    # 设置-另存为
    def pushButton_save_new_config_clicked(self):
        new_config_name, ok = QInputDialog.getText(self, "另存为新配置", "请输入新配置的文件名")
        if ok and new_config_name:
            new_config_name = new_config_name.replace("/", "").replace("\\", "")
            new_config_name = re.sub(r'[\\:*?"<>|\r\n]+', "", new_config_name)
            if os.path.splitext(new_config_name)[1] != ".json":
                new_config_name += ".json"
            if new_config_name != manager.file:
                manager.path = manager.data_folder / new_config_name
                self.pushButton_save_config_clicked()

    def save_config(self): ...

    # endregion

    # region 检测网络
    def network_check(self):
        try:
            signal_qt.show_net_info("\n⛑ 开始检测网络...")
            cancel_event = self.network_check_cancel_event or threading.Event()
            self.network_check_cancel_event = cancel_event
            self.network_check_future = executor.submit(
                run_network_check(progress=signal_qt.show_net_info, cancel_event=cancel_event)
            )
            self.network_check_future.result()
        except Exception as e:
            signal_qt.show_net_info(f"\n⛔️ 网络检测出现异常：{e}")
            signal_qt.show_net_info(
                "================================================================================\n"
            )
            signal_qt.show_traceback_log(str(e))
            signal_qt.show_traceback_log(traceback.format_exc())
        self.network_check_cancel_event = None
        self.network_check_future = None
        self.Ui.pushButton_check_net.setEnabled(True)
        self.Ui.pushButton_check_net.setText("开始检测")
        self.Ui.pushButton_check_net.setStyleSheet(
            "QPushButton#pushButton_check_net{background-color:#4C6EFF}QPushButton:hover#pushButton_check_net{background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_check_net{#4C6EE0}"
        )

    # 网络检查
    def pushButton_check_net_clicked(self):
        if self.Ui.pushButton_check_net.text() == "开始检测":
            self.Ui.pushButton_check_net.setText("停止检测")
            self.Ui.pushButton_check_net.setStyleSheet(
                "QPushButton#pushButton_check_net{color: white;background-color:#3758D8;}QPushButton:hover#pushButton_check_net{color: white;background-color:#4C6EFF;}QPushButton:pressed#pushButton_check_net{color: white;background-color:#2F49B8;}"
            )
            try:
                self.t_net = threading.Thread(target=self.network_check)
                self.t_net.start()  # 启动线程,即让线程开始执行
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())
                signal_qt.show_net_info(traceback.format_exc())
        elif self.Ui.pushButton_check_net.text() == "停止检测":
            self.Ui.pushButton_check_net.setText(" 停止检测 ")
            self.Ui.pushButton_check_net.setText(" 停止检测 ")
            if self.network_check_cancel_event:
                self.network_check_cancel_event.set()
            signal_qt.show_net_info("\n⛔️ 正在停止网络检测...")
            self.Ui.pushButton_check_net.setStyleSheet(
                "QPushButton#pushButton_check_net{color: white;background-color:#4C6EFF;}QPushButton:hover#pushButton_check_net{color: white;background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_check_net{color: white;background-color:#4C6EE0}"
            )
            self.Ui.pushButton_check_net.setText("开始检测")
        else:
            try:
                if self.network_check_cancel_event:
                    self.network_check_cancel_event.set()
            except Exception as e:
                signal_qt.show_traceback_log(str(e))
                signal_qt.show_traceback_log(traceback.format_exc())

    # 检测网络界面日志显示
    def show_net_info(self, text):
        try:
            self.net_logs_show.emit(add_html_plain_text(text))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self.Ui.textBrowser_net_main.append(traceback.format_exc())

    # 检查javdb cookie
    def pushButton_check_javdb_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_javdb.toPlainText()
        if not input_cookie:
            self.set_javdb_status.emit("❌ 未填写 Cookie")
            self.show_log_text(" ❌ JavDb 未填写 Cookie，可在「设置」-「网络」添加！")
            return
        self.set_javdb_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_javdb_cookie, args=(input_cookie,))
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _check_javdb_cookie(self, input_cookie: str):
        tips = "❌ 未填写 Cookie，影响 FC2 刮削！"
        if not input_cookie:
            self.set_javdb_status.emit(tips)
            return tips
        # self.Ui.pushButton_check_javdb_cookie.setEnabled(False)
        tips = "✅ 连接正常！"
        header = {"cookie": input_cookie}
        javdb_url = manager.config.get_site_url(Website.JAVDB, "https://javdb.com") + "/v/D16Q5?locale=zh"
        try:
            response, error = get_text_sync(javdb_url, headers=header)
            if response is None:
                if "Cookie" in error:
                    if manager.config.javdb != input_cookie:
                        tips = "❌ Cookie 已过期！"
                    else:
                        tips = "❌ Cookie 已过期！已清理！(不清理无法访问)"
                        self.set_javdb_cookie.emit("")
                        self.exec_save_config.emit()
                else:
                    tips = f"❌ 连接失败！请检查网络或代理设置！ {response}"
            else:
                if "The owner of this website has banned your access based on your browser's behaving" in response:
                    ip_adress = re.findall(r"(\d+\.\d+\.\d+\.\d+)", response)
                    ip_adress = ip_adress[0] + " " if ip_adress else ""
                    tips = f"❌ 你的 IP {ip_adress}被 JavDb 封了！"
                elif "Due to copyright restrictions" in response or "Access denied" in response:
                    tips = "❌ 当前 IP 被禁止访问！请使用非日本节点！"
                elif "ray-id" in response:
                    tips = "❌ 访问被 CloudFlare 拦截！"
                elif "/logout" in response:  # 已登录，有登出按钮
                    vip_info = "未开通 VIP"
                    tips = f"✅ 连接正常！（{vip_info}）"
                    if input_cookie:
                        if "icon-diamond" in response or "/v/D16Q5" in response:  # 有钻石图标或者跳到详情页表示已开通
                            vip_info = "已开通 VIP"
                        if manager.config.javdb != input_cookie:  # 保存cookie
                            tips = f"✅ 连接正常！（{vip_info}）Cookie 已保存！"
                            self.exec_save_config.emit()
                        else:
                            tips = f"✅ 连接正常！（{vip_info}）"
                else:
                    if manager.config.javdb != input_cookie:
                        tips = "❌ Cookie 无效！请重新填写！"
                    else:
                        tips = "❌ Cookie 无效！已清理！"
                        self.set_javdb_cookie.emit("")
                        self.exec_save_config.emit()
        except Exception as e:
            tips = f"❌ 连接失败！请检查网络或代理设置！ {e}"
            signal_qt.show_traceback_log(tips)
        if input_cookie:
            self.set_javdb_status.emit(tips)
            # self.Ui.pushButton_check_javdb_cookie.setEnabled(True)
        self.show_log_text(tips.replace("❌", " ❌ JavDb").replace("✅", " ✅ JavDb"))
        return tips

    # 检查 fc2ppvdb cookie
    def pushButton_check_fc2ppvdb_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_fc2ppvdb.toPlainText().strip()
        if not input_cookie:
            self.set_fc2ppvdb_status.emit("❌ 未填写 Cookie")
            self.show_log_text(" ❌ FC2PPVDB 未填写 Cookie，可在「设置」-「网络」添加！")
            return
        self.set_fc2ppvdb_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_fc2ppvdb_cookie, args=(input_cookie,))
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _check_fc2ppvdb_cookie(self, input_cookie: str):
        tips = "❌ 未填写 Cookie"
        if not input_cookie:
            self.set_fc2ppvdb_status.emit(tips)
            return tips

        if "fc2ppvdb_session" not in input_cookie:
            tips = "❌ Cookie 无效！缺少 fc2ppvdb_session"
        else:
            cookies = cookie_str_to_dict(input_cookie)
            response, error = executor.run(
                fetch_article_info_with_warmup(
                    manager.computed.async_client,
                    base_url="https://fc2ppvdb.com",
                    number="3259498",
                    cookies=cookies,
                    use_proxy=manager.config.use_proxy,
                )
            )
            if response is None:
                tips = f"❌ Cookie 检查失败：{error}"
            elif not response.get("article"):
                tips = "❌ Cookie 检查失败：返回数据异常"
            elif manager.config.fc2ppvdb != input_cookie:
                self.exec_save_config.emit()
                tips = "✅ 连接正常，Cookie 已保存！"
            else:
                tips = "✅ 连接正常！"

        self.set_fc2ppvdb_status.emit(tips)
        self.show_log_text(tips.replace("❌", " ❌ FC2PPVDB").replace("✅", " ✅ FC2PPVDB"))
        return tips

    # javbus cookie
    def pushButton_check_javbus_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_javbus.toPlainText()
        self.set_javbus_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_javbus_cookie, args=(input_cookie,))
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self.show_log_text(traceback.format_exc())

    def _check_javbus_cookie(self, input_cookie: str):
        # self.Ui.pushButton_check_javbus_cookie.setEnabled(False)
        tips = "✅ 连接正常！"
        headers = {"Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6", "cookie": input_cookie}
        javbus_url = manager.config.get_site_url(Website.JAVBUS, "https://javbus.com") + "/FSDSS-660"

        try:
            response, error = get_text_sync(javbus_url, headers=headers)

            if response is None:
                tips = f"❌ 连接失败！请检查网络或代理设置！ {error}"
            elif "lostpasswd" in response:
                if input_cookie:
                    tips = "❌ Cookie 无效！"
                else:
                    tips = "❌ 当前节点需要 Cookie 才能刮削！请填写 Cookie 或更换节点！"
            elif manager.config.javbus != input_cookie:
                self.exec_save_config.emit()
                tips = "✅ 连接正常！Cookie 已保存！  "

        except Exception as e:
            tips = f"❌ 连接失败！请检查网络或代理设置！ {e}"

        self.show_log_text(tips.replace("❌", " ❌ JavBus").replace("✅", " ✅ JavBus"))
        self.set_javbus_status.emit(tips)
        # self.Ui.pushButton_check_javbus_cookie.setEnabled(True)
        return tips

    # endregion

    # region 其它
    # 点选择目录弹窗
    def _get_select_folder_path(self):
        media_path = self.Ui.lineEdit_movie_path.text()  # 获取待刮削目录作为打开目录
        if not media_path:
            media_path = manager.data_folder.as_posix()
        media_folder_path = QFileDialog.getExistingDirectory(None, "选择目录", media_path, options=self.options)
        return media_folder_path

    # 改回接受焦点状态
    def recover_windowflags(self):
        return

    def change_buttons_status(self):
        Flags.stop_other = True
        self.Ui.pushButton_start_cap.setText("■ 停止")
        self.Ui.pushButton_start_cap2.setText("■ 停止")
        self.Ui.pushButton_select_media_folder.setVisible(False)
        self.Ui.pushButton_start_single_file.setEnabled(False)
        self.Ui.pushButton_start_single_file.setText("正在刮削中...")
        self.Ui.pushButton_add_sub_for_all_video.setEnabled(False)
        self.Ui.pushButton_add_sub_for_all_video.setText("正在刮削中...")
        self.Ui.pushButton_show_pic_actor.setEnabled(False)
        self.Ui.pushButton_show_pic_actor.setText("刮削中...")
        self.Ui.pushButton_add_actor_info.setEnabled(False)
        self.Ui.pushButton_add_actor_info.setText("正在刮削中...")
        self.Ui.pushButton_add_actor_pic.setEnabled(False)
        self.Ui.pushButton_add_actor_pic.setText("正在刮削中...")
        self.Ui.pushButton_add_actor_pic_kodi.setEnabled(False)
        self.Ui.pushButton_add_actor_pic_kodi.setText("正在刮削中...")
        self.Ui.pushButton_del_actor_folder.setEnabled(False)
        self.Ui.pushButton_del_actor_folder.setText("正在刮削中...")
        # self.Ui.pushButton_check_and_clean_files.setEnabled(False)
        self.Ui.pushButton_check_and_clean_files.setText("正在刮削中...")
        self.Ui.pushButton_move_mp4.setEnabled(False)
        self.Ui.pushButton_move_mp4.setText("正在刮削中...")
        self.Ui.pushButton_find_missing_number.setEnabled(False)
        self.Ui.pushButton_find_missing_number.setText("正在刮削中...")
        self.Ui.pushButton_start_cap.setStyleSheet(
            "QPushButton#pushButton_start_cap{color: white;background-color:#DC2626;}QPushButton:hover#pushButton_start_cap{color: white;background-color:#EF4444;}QPushButton:pressed#pushButton_start_cap{color: white;background-color:#B91C1C;}"
        )
        self.Ui.pushButton_start_cap2.setStyleSheet(
            "QPushButton#pushButton_start_cap2{color: white;background-color:#DC2626;}QPushButton:hover#pushButton_start_cap2{color: white;background-color:#EF4444;}QPushButton:pressed#pushButton_start_cap2{color: white;background-color:#B91C1C;}"
        )

    def reset_buttons_status(self):
        self.Ui.pushButton_start_cap.setEnabled(True)
        self.Ui.pushButton_start_cap2.setEnabled(True)
        self.pushButton_start_cap.emit("开始")
        self.pushButton_start_cap2.emit("开始")
        self.Ui.pushButton_select_media_folder.setVisible(True)
        self.Ui.pushButton_start_single_file.setEnabled(True)
        self.pushButton_start_single_file.emit("刮削")
        self.Ui.pushButton_add_sub_for_all_video.setEnabled(True)
        self.pushButton_add_sub_for_all_video.emit("点击检查所有视频的字幕情况并为无字幕视频添加字幕")

        self.Ui.pushButton_show_pic_actor.setEnabled(True)
        self.pushButton_show_pic_actor.emit("查看")
        self.Ui.pushButton_add_actor_info.setEnabled(True)
        self.pushButton_add_actor_info.emit("开始补全")
        self.Ui.pushButton_add_actor_pic.setEnabled(True)
        self.pushButton_add_actor_pic.emit("开始补全")
        self.Ui.pushButton_add_actor_pic_kodi.setEnabled(True)
        self.pushButton_add_actor_pic_kodi.emit("开始补全")
        self.Ui.pushButton_del_actor_folder.setEnabled(True)
        self.pushButton_del_actor_folder.emit("清除所有.actors文件夹")
        self.Ui.pushButton_check_and_clean_files.setEnabled(True)
        self.pushButton_check_and_clean_files.emit("点击检查待刮削目录并清理文件")
        self.Ui.pushButton_move_mp4.setEnabled(True)
        self.pushButton_move_mp4.emit("开始移动")
        self.Ui.pushButton_find_missing_number.setEnabled(True)
        self.pushButton_find_missing_number.emit("检查缺失番号")

        self.Ui.pushButton_start_cap.setStyleSheet(
            "QPushButton#pushButton_start_cap{color: white;background-color:#4C6EFF;}QPushButton:hover#pushButton_start_cap{color: white;background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_start_cap{color: white;background-color:#4C6EE0}"
        )
        self.Ui.pushButton_start_cap2.setStyleSheet(
            "QPushButton#pushButton_start_cap2{color: white;background-color:#4C6EFF;}QPushButton:hover#pushButton_start_cap2{color: white;background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_start_cap2{color: white;background-color:#4C6EE0}"
        )
        Flags.file_mode = FileMode.Default
        self.threads_list = []
        if len(Flags.failed_list):
            self.Ui.pushButton_scraper_failed_list.setText(f"一键重新刮削当前 {len(Flags.failed_list)} 个失败文件")
        else:
            self.Ui.pushButton_scraper_failed_list.setText("当有失败任务时，点击可以一键刮削当前失败列表")

    # endregion

    # region 自动刮削
    def auto_scrape(self):
        if Switch.TIMED_SCRAPE in manager.config.switch_on and self.Ui.pushButton_start_cap.text() == "开始":
            time.sleep(0.1)
            timed_interval = manager.config.timed_interval
            self.atuo_scrape_count += 1
            signal_qt.show_log_text(
                f"\n\n 🍔 已启用「循环刮削」！间隔时间：{timed_interval}！即将开始第 {self.atuo_scrape_count} 次循环刮削！"
            )
            if Flags.scrape_start_time:
                signal_qt.show_log_text(
                    " ⏰ 上次刮削时间: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(Flags.scrape_start_time))
                )
            start_new_scrape(FileMode.Default)

    def auto_start(self):
        if Switch.AUTO_START in manager.config.switch_on:
            signal_qt.show_log_text("\n\n 🍔 已启用「软件启动后自动刮削」！即将开始自动刮削！")
            self.pushButton_start_scrape_clicked()

    # endregion


# region 外部方法定义
MyMAinWindow.load_config = load_config
MyMAinWindow.save_config = save_config
MyMAinWindow.Init_QSystemTrayIcon = Init_QSystemTrayIcon
MyMAinWindow.Init_Ui = Init_Ui
MyMAinWindow.Init_Singal = Init_Singal
MyMAinWindow.init_QTreeWidget = init_QTreeWidget
MyMAinWindow.set_style = set_style
MyMAinWindow.set_dark_style = set_dark_style
# endregion
