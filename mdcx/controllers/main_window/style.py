from typing import TYPE_CHECKING

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

if TYPE_CHECKING:
    from .main_window import MyMAinWindow


LIGHT_TOKENS = {
    "window": "#FFFFFF",
    "surface": "#F8FAFC",
    "surface_muted": "#F5F7FF",
    "text": "#111827",
    "text_muted": "#4B5563",
    "text_disabled": "#9AA3AF",
    "placeholder": "#6B7280",
    "border": "#D8DEE9",
    "accent": "#4C6EFF",
    "accent_hover": "#6684FF",
    "accent_pressed": "#3F5FE6",
    "link": "#0B63CE",
    "link_hover": "#084A9C",
    "selection_bg": "rgba(76, 110, 255, 42)",
    "selection_bg_inactive": "rgba(76, 110, 255, 34)",
    "selection_text": "#111827",
    "tree_hover": "rgba(76, 110, 255, 18)",
    "tree_border": "rgba(76, 110, 255, 170)",
}

DARK_TOKENS = {
    "window": "#121A24",
    "surface": "#18222D",
    "surface_muted": "#1D2834",
    "text": "#E5E7EB",
    "text_muted": "#B6C2D0",
    "text_disabled": "#6B7280",
    "placeholder": "#94A3B8",
    "border": "#2F3A46",
    "accent": "#6684FF",
    "accent_hover": "#8EA3FF",
    "accent_pressed": "#4C6EE0",
    "link": "#9DB7FF",
    "link_hover": "#C3D2FF",
    "selection_bg": "rgba(102, 132, 255, 80)",
    "selection_bg_inactive": "rgba(102, 132, 255, 58)",
    "selection_text": "#FFFFFF",
    "tree_hover": "rgba(102, 132, 255, 34)",
    "tree_border": "rgba(142, 163, 255, 190)",
}


def _tokens(dark: bool) -> dict[str, str]:
    return DARK_TOKENS if dark else LIGHT_TOKENS


def get_theme_tokens(dark: bool) -> dict[str, str]:
    return _tokens(dark)


def apply_application_palette(dark: bool) -> None:
    app = QApplication.instance()
    if app is None:
        return

    t = _tokens(dark)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(t["window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(t["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(t["surface"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(t["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Link, QColor(t["link"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["placeholder"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t["text_disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(t["surface"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t["text_disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t["text_disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor(t["text_disabled"]))
    try:
        palette.setColor(QPalette.ColorRole.Accent, QColor(t["accent"]))
    except AttributeError:
        pass
    app.setPalette(palette)


def build_tree_widget_style(dark: bool) -> str:
    t = _tokens(dark)
    return f"""
        QTreeWidget {{
            outline: 0;
            border: 0;
            color: {t["text"]};
            background: transparent;
            alternate-background-color: transparent;
            selection-background-color: transparent;
            selection-color: {t["selection_text"]};
        }}
        QTreeWidget::item {{
            color: {t["text"]};
            border: 1px solid transparent;
            border-radius: 4px;
            padding: 2px 4px;
        }}
        QTreeWidget::item:hover {{
            color: {t["text"]};
            background: {t["tree_hover"]};
            border: 1px solid {t["tree_border"]};
        }}
        QTreeWidget::item:selected,
        QTreeWidget::item:selected:active {{
            color: {t["selection_text"]};
            background: {t["selection_bg"]};
            border: 1px solid {t["tree_border"]};
        }}
        QTreeWidget::item:selected:!active {{
            color: {t["selection_text"]};
            background: {t["selection_bg_inactive"]};
            border: 1px solid {t["tree_border"]};
        }}
        QTreeWidget::branch {{
            background: transparent;
            border: 0;
            image: none;
        }}
        QTreeWidget::branch:selected {{
            background: transparent;
            image: none;
        }}
    """


def build_menu_style(dark: bool) -> str:
    t = _tokens(dark)
    return f"""
        QMenu {{
            color: {t["text"]};
            background: {t["surface"]};
            border: 1px solid {t["border"]};
            padding: 4px;
        }}
        QMenu::item {{
            color: {t["text"]};
            padding: 5px 28px 5px 24px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            color: #FFFFFF;
            background: {t["accent"]};
        }}
        QMenu::item:disabled {{
            color: {t["text_disabled"]};
        }}
        QMenu::separator {{
            height: 1px;
            background: {t["border"]};
            margin: 4px 8px;
        }}
    """


def _apply_log_document_style(self: "MyMAinWindow", dark: bool) -> None:
    t = _tokens(dark)
    document_style = f"""
        a {{
            color: {t["link"]};
            text-decoration: none;
            font-weight: 500;
        }}
        a:hover {{
            color: {t["link_hover"]};
            text-decoration: underline;
        }}
    """
    for text_browser in (
        self.Ui.textBrowser_log_main,
        self.Ui.textBrowser_log_main_2,
        self.Ui.textBrowser_log_main_3,
        self.Ui.textBrowser_net_main,
        self.Ui.textBrowser_show_success_list,
        self.Ui.textBrowser_show_tips,
    ):
        text_browser.document().setDefaultStyleSheet(document_style)


def set_style(self: "MyMAinWindow"):
    if self.dark_mode:
        self.set_dark_style()
        return

    apply_application_palette(False)
    _apply_log_document_style(self, False)
    self.Ui.treeWidget_number.setStyleSheet(build_tree_widget_style(False))

    # 控件美化 左侧栏样式
    self.Ui.widget_setting.setStyleSheet(f"""
        QWidget#widget_setting{{
            background: #F5F5F6;
            border-top-left-radius: {self.window_radius}px;
            border-bottom-left-radius: {self.window_radius}px;
        }}
        QPushButton#pushButton_main,#pushButton_log,#pushButton_tool,#pushButton_setting,#pushButton_net,#pushButton_about{{
            font-size: 14px;
            color: black;
            border-width: 9px;
            border-color: gray;
            border-radius: 10px;
            text-align : left;
            qproperty-iconSize: 20px 20px;
            padding-left: 20px;
        }}
        QLabel#label_show_version{{
            font-size: 13px;
            color: rgba(20, 20, 20, 250);
            border: 0px solid rgba(255, 255, 255, 80);
        }}
        """)
    # 主界面
    self.Ui.page_main.setStyleSheet("""
        QLabel#label_number1,#label_actor1,#label_title1,#label_poster1,#label_number,#label_actor,#label_title,#label_poster1{
            font-size: 16px;
            font-weight: bold;
            background-color: rgba(246, 246, 246, 0);
            border: 0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_file_path{
            font-size: 16px;
            color: black;
            background-color: rgba(246, 246, 246, 0);
            font-weight: bold;
            border: 0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_poster_size{
            color: rgba(0, 0, 0, 200);
        }
        QLabel#label_poster,#label_thumb{
            border: 1px solid rgba(60, 60, 60, 100);
        }
        QGroupBox{
            background-color: rgba(246, 246, 246, 0);
        }
        """)
    # 工具页
    self.Ui.page_tool.setStyleSheet("""
        * {
            font-size: 13px;
        }
        QScrollArea{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 0);
        }
        QWidget#scrollAreaWidgetContents_gongju{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 255);
        }

        QLabel{
            font-size:13px;
            border: 0px solid rgba(0, 0, 0, 80);
        }
        QLineEdit{
            font-size:13px;
            border:0px solid rgba(130, 30, 30, 20);
            border-radius: 15px;
        }
        QComboBox{
            combobox-popup: 0;
            font-size: 13px;
            color: black;
        }
        QGroupBox{
            background-color: rgba(245,245,246,220);
            border-radius: 10px;
        }
        """)
    # 使用帮助页
    self.Ui.page_about.setStyleSheet("""
        * {
            font-size: 13px;
        }
        QTextBrowser{
            font-family: Consolas, 'PingFang SC', 'Microsoft YaHei UI', 'Noto Color Emoji', 'Segoe UI Emoji';
            font-size: 13px;
            border: 0px solid #BEBEBE;
            background-color: rgba(246,246,246,0);
            padding: 2px, 2px;
        }
        """)
    # 设置页
    self.Ui.page_setting.setStyleSheet("""
        * {
            font-size:13px;
        }
        QScrollArea{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 255);
        }
        QTabWidget{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 255);
        }
        QTabWidget::tab-bar {
            alignment: center;
        }
        QTabBar::tab{
            color: black;
            border:1px solid #E8E8E8;
            min-height: 3ex;
            min-width: 6ex;
            padding: 2px;
            background-color:#FFFFFF;
            border-radius: 1px;
        }
        QTabBar::tab:selected{
            color: white;
            font-weight:bold;
            border-bottom: 2px solid #2080F7;
            background-color:#2080F7;
            border-radius: 1px;
        }
        QWidget#tab1,#tab2,#tab3,#tab4,#tab5,#tab,#tab_2,#tab_3,#tab_4,#tab_5,#tab_6,#tab_7,#scrollAreaWidgetContents_guaxiaomulu,#scrollAreaWidgetContents_guaxiaomoshi,#scrollAreaWidgetContents_guaxiaowangzhan,#scrollAreaWidgetContents_xiazai,#scrollAreaWidgetContents_mingming,#scrollAreaWidgetContents_fanyi,#scrollAreaWidgetContents_zimu,#scrollAreaWidgetContents_shuiyin,#scrollAreaWidgetContents_nfo,#scrollAreaWidgetContents_yanyuan,#scrollAreaWidgetContents_wangluo,#scrollAreaWidgetContents_gaoji{
            background-color: rgba(255, 255, 255, 255);
            border-color: rgba(246, 246, 246, 255);
        }
        QLabel{
            font-size:13px;
            border:0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_config{
            font-size:13px;
            border:0px solid rgba(230, 230, 230, 80);
            background: rgba(246, 246, 246, 220);
        }

        QLineEdit{
            font-size:13px;
            border:0px solid rgba(130, 30, 30, 20);
            border-radius: 15px;
        }
        QRadioButton{
            font-size:13px;
        }
        QComboBox{
            combobox-popup: 0;
            font-size:13px;
        }
        QCheckBox{
            font-size:13px;
        }
        QCheckBox::indicator, QRadioButton::indicator{
            width: 14px;
            height: 14px;
            border: 1px solid #B8C0CC;
            background: #FFFFFF;
        }
        QCheckBox::indicator{
            border-radius: 3px;
        }
        QRadioButton::indicator{
            border-radius: 7px;
        }
        QCheckBox::indicator:checked{
            background: #4C6EFF;
            border: 1px solid #4C6EFF;
            image: url(resources/Img/check_indicator.svg);
        }
        QRadioButton::indicator:checked{
            background: #4C6EFF;
            border: 1px solid #4C6EFF;
            image: url(resources/Img/radio_indicator.svg);
        }
        QCheckBox::indicator:hover, QRadioButton::indicator:hover{
            border: 1px solid #4C6EFF;
        }
        QPlainTextEdit{
            font-size:13px;
        }
        QGroupBox{
            background-color: rgba(245,245,246,220);
            border-radius: 10px;
        }
        """)
    # 整个页面
    self.Ui.centralwidget.setStyleSheet(f"""
        * {{
            font-family: Consolas, 'PingFang SC', 'Microsoft YaHei UI', 'Noto Color Emoji', 'Segoe UI Emoji';
            font-size:13px;
            color: black;
        }}
        QTreeWidget
        {{
            background-color: rgba(246, 246, 246, 0);
            font-size: 12px;
            border:0px solid rgb(120,120,120);
        }}
        QWidget#centralwidget{{
            background: #FFFFFF;
            border: {self.window_border}px solid rgba(20,20,20,50);
            border-radius: {self.window_radius}px;
       }}
        QTextBrowser#textBrowser_log_main,#textBrowser_net_main{{
            font-size:13px;
            border: 0px solid #BEBEBE;
            background-color: rgba(246,246,246,0);
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_log_main_2{{
            font-size:13px;
            border-radius: 0px;
            border-top: 1px solid #BEBEBE;
            background-color: rgba(238,245,245,60);
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_log_main_3{{
            font-size:13px;
            border-radius: 0px;
            border-right: 1px solid #EDEDED;
            background-color: rgba(239,255,252,240);
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_show_success_list,#textBrowser_show_tips{{
            font-size: 13px;
            background-color: rgba(240, 245, 240, 240);
            border: 1px solid #BEBEBE;
            padding: 2px;
        }}
        QWidget#widget_show_success,#widget_show_tips,#widget_nfo{{
            background-color: rgba(246,246,246,255);
            border: 1px solid rgba(20,20,20,50);
            border-radius: 10px;
       }}
        QWidget#scrollAreaWidgetContents_nfo_editor{{
            background-color: rgba(240, 245, 240, 240);
            border: 0px solid rgba(0,0,0,150);
        }}
        QLineEdit, QPlainTextEdit, QTextEdit, QDoubleSpinBox, QSpinBox{{
            font-size:14px;
            background:white;
            border-radius:10px;
            border: 1px solid #D8DEE9;
            padding: 4px 8px;
            selection-background-color: #4C6EFF;
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus{{
            border: 1px solid #4C6EFF;
            background: #FFFFFF;
        }}
        QTextEdit#textEdit_nfo_outline,#textEdit_nfo_originalplot,#textEdit_nfo_tag{{
            font-size:14px;
            background:white;
            border: 1px solid #D8DEE9;
            padding: 4px 8px;
        }}
        QComboBox{{
            combobox-popup: 0;
            background: #FFFFFF;
            border: 1px solid #D8DEE9;
            border-radius: 8px;
            padding: 3px 30px 3px 8px;
            selection-background-color: #4C6EFF;
        }}
        QComboBox::drop-down{{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 26px;
            border-left: 1px solid #D8DEE9;
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
            background: #F8FAFC;
        }}
        QComboBox::drop-down:hover{{
            background: #EEF2FF;
        }}
        QComboBox::down-arrow{{
            image: url(resources/Img/chevron_down_light.svg);
            width: 14px;
            height: 14px;
        }}
        QComboBox:focus{{
            border: 1px solid #4C6EFF;
        }}
        QComboBox QAbstractItemView{{
            background: #FFFFFF;
            border: 1px solid #D8DEE9;
            selection-background-color: #4C6EFF;
            selection-color: white;
            outline: 0;
        }}
        QComboBox QAbstractItemView::item{{
            min-height: 24px;
            padding: 4px 8px;
            color: #111827;
        }}
        QComboBox QAbstractItemView::item:selected{{
            color: #FFFFFF;
            background: #4C6EFF;
        }}
        QCheckBox::indicator, QRadioButton::indicator{{
            width: 14px;
            height: 14px;
            border: 1px solid #B8C0CC;
            background: #FFFFFF;
        }}
        QCheckBox::indicator{{
            border-radius: 3px;
        }}
        QRadioButton::indicator{{
            border-radius: 7px;
        }}
        QCheckBox::indicator:checked{{
            background: #4C6EFF;
            border: 1px solid #4C6EFF;
            image: url(resources/Img/check_indicator.svg);
        }}
        QRadioButton::indicator:checked{{
            background: #4C6EFF;
            border: 1px solid #4C6EFF;
            image: url(resources/Img/radio_indicator.svg);
        }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover{{
            border: 1px solid #4C6EFF;
        }}
        QToolTip{{
            border: 1px solid #D8DEE9;
            border-radius: 8px;
            background: #FFFFFF;
            color: #111827;
            padding: 6px 10px;
        }}
        QPushButton#pushButton_right_menu,#pushButton_play,#pushButton_open_folder,#pushButton_open_nfo,#pushButton_show_hide_logs,#pushButton_save_failed_list,#pushButton_tree_clear{{
            background-color: rgba(181, 181, 181, 0);
            border-radius:10px;
            border: 0px solid rgba(0, 0, 0, 80);
        }}
        QPushButton:hover#pushButton_right_menu,:hover#pushButton_play,:hover#pushButton_open_folder,:hover#pushButton_open_nfo,:hover#pushButton_show_hide_logs,:hover#pushButton_save_failed_list,:hover#pushButton_tree_clear{{
            background-color: rgba(181, 181, 181, 120);
        }}
        QPushButton:pressed#pushButton_right_menu,:pressed#pushButton_play,:pressed#pushButton_open_folder,:pressed#pushButton_open_nfo,:pressed#pushButton_show_hide_logs,:pressed#pushButton_save_failed_list,:pressed#pushButton_tree_clear{{
            background-color: rgba(150, 150, 150, 120);
        }}
        QPushButton#pushButton_scrape_note,#pushButton_field_tips_website,#pushButton_field_tips_nfo{{
            color: #111827;
            background: #FFFFFF;
            border: 1px solid #CBD5E1;
            border-radius: 6px;
            padding: 3px 10px;
        }}
        QPushButton:hover#pushButton_scrape_note,:hover#pushButton_field_tips_website,:hover#pushButton_field_tips_nfo{{
            color: #FFFFFF;
            background: #4C6EFF;
            border: 1px solid #4C6EFF;
        }}
        QPushButton:pressed#pushButton_scrape_note,:pressed#pushButton_field_tips_website,:pressed#pushButton_field_tips_nfo{{
            color: #FFFFFF;
            background: #3F5FE6;
            border: 1px solid #3F5FE6;
        }}
        QPushButton#pushButton_save_new_config,#pushButton_init_config,#pushButton_success_list_close,#pushButton_success_list_save,#pushButton_success_list_clear,#pushButton_show_tips_close,#pushButton_nfo_close,#pushButton_nfo_save,#pushButton_show_pic_actor,#pushButton_add_actor_pic,#pushButton_add_actor_info,#pushButton_add_actor_pic_kodi,#pushButton_del_actor_folder,#pushButton_move_mp4,#pushButton_select_file,#pushButton_select_local_library,#pushButton_select_netdisk_path,#pushButton_select_localdisk_path,#pushButton_creat_symlink,#pushButton_find_missing_number,#pushButton_select_thumb,#pushButton_start_single_file,#pushButton_select_file_clear_info,#pushButton_add_sub_for_all_video,#pushButton_view_failed_list,#pushButton_select_media_folder,#pushButton_select_media_folder_setting_page,#pushButton_select_softlink_folder,#pushButton_select_sucess_folder,#pushButton_select_failed_folder,#pushButton_view_success_file,#pushButton_select_subtitle_folder,#pushButton_select_actor_photo_folder,#pushButton_select_actor_info_db,#pushButton_select_config_folder,#pushButton_add_all_extrafanart_copy,#pushButton_del_all_extrafanart_copy,#pushButton_add_all_extras,#pushButton_del_all_extras,#pushButton_add_all_theme_videos,#pushButton_del_all_theme_videos,#pushButton_check_and_clean_files,#pushButton_search_by_number,#pushButton_search_by_url{{
            font-size:14px;
            background-color: rgba(220, 220,220, 255);
            border-color:black;
            border-width:8px;
            border-radius:20px;
            padding: 2px, 2px;
        }}
        QPushButton:hover#pushButton_show_pic_actor,:hover#pushButton_add_actor_pic,:hover#pushButton_add_actor_info,:hover#pushButton_add_actor_pic_kodi,:hover#pushButton_del_actor_folder,:hover#pushButton_add_sub_for_all_video,:hover#pushButton_view_failed_list,:hover#pushButton_select_media_folder,:hover#pushButton_select_media_folder_setting_page,:hover#pushButton_select_softlink_folder,:hover#pushButton_select_sucess_folder,:hover#pushButton_select_failed_folder,:hover#pushButton_view_success_file,:hover#pushButton_select_subtitle_folder,:hover#pushButton_select_actor_photo_folder,:hover#pushButton_select_actor_info_db,:hover#pushButton_select_config_folder,:hover#pushButton_add_all_extrafanart_copy,:hover#pushButton_del_all_extrafanart_copy,:hover#pushButton_add_all_extras,:hover#pushButton_del_all_extras,:hover#pushButton_add_all_theme_videos,:hover#pushButton_del_all_theme_videos,:hover#pushButton_check_and_clean_files,:hover#pushButton_search_by_number,:hover#pushButton_search_by_url{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
        }}
        QPushButton:pressed#pushButton_show_pic_actor,:pressed#pushButton_add_actor_pic,:pressed#pushButton_add_actor_info,:pressed#pushButton_add_actor_pic_kodi,:pressed#pushButton_del_actor_folder,:pressed#pushButton_add_sub_for_all_video,:pressed#pushButton_view_failed_list,:pressed#pushButton_select_media_folder,:pressed#pushButton_select_media_folder_setting_page,:pressed#pushButton_select_softlink_folder,:pressed#pushButton_select_sucess_folder,:pressed#pushButton_select_failed_folder,:pressed#pushButton_view_success_file,:pressed#pushButton_select_subtitle_folder,:pressed#pushButton_select_actor_photo_folder,:pressed#pushButton_select_actor_info_db,:pressed#pushButton_select_config_folder,:pressed#pushButton_add_all_extrafanart_copy,:pressed#pushButton_del_all_extrafanart_copy,:pressed#pushButton_add_all_extras,:pressed#pushButton_del_all_extras,:pressed#pushButton_add_all_theme_videos,:pressed#pushButton_del_all_theme_videos,:pressed#pushButton_check_and_clean_files,:pressed#pushButton_search_by_number,:pressed#pushButton_search_by_url{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:14px;
            font-weight:bold;
        }}
        QPushButton#pushButton_save_config{{
            color: white;
            font-size:14px;
            background-color:#4C6EFF;
            border-radius:25px;
            padding: 2px, 2px;
        }}
        QPushButton:hover#pushButton_save_config,:hover#pushButton_save_new_config,:hover#pushButton_init_config,:hover#pushButton_success_list_close,:hover#pushButton_success_list_save,:hover#pushButton_success_list_clear,:hover#pushButton_show_tips_close,:hover#pushButton_nfo_close,:hover#pushButton_nfo_save,:hover#pushButton_scraper_failed_list{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
            }}
        QPushButton:pressed#pushButton_save_config,:pressed#pushButton_save_new_config,:pressed#pushButton_init_config,:pressed#pushButton_success_list_close,:pressed#pushButton_success_list_save,:pressed#pushButton_success_list_clear,:pressed#pushButton_show_tips_close,:pressed#pushButton_nfo_close,:pressed#pushButton_nfo_save,:pressed#pushButton_scraper_failed_list{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:14px;
            font-weight:bold;
        }}
        QPushButton#pushButton_start_cap,#pushButton_start_cap2,#pushButton_check_net,#pushButton_scraper_failed_list{{
            color: white;
            font-size:14px;
            background-color:#4C6EFF;
            border-radius:20px;
            padding: 2px, 2px;
            font-weight:bold;
        }}
        QPushButton:hover#pushButton_start_cap,:hover#pushButton_start_cap2,:hover#pushButton_check_net,:hover#pushButton_move_mp4,:hover#pushButton_select_file,:hover#pushButton_select_local_library,:hover#pushButton_select_netdisk_path,:hover#pushButton_select_localdisk_path,:hover#pushButton_creat_symlink,:hover#pushButton_find_missing_number,:hover#pushButton_select_thumb,:hover#pushButton_start_single_file,:hover#pushButton_select_file_clear_info{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
            }}
        QPushButton:pressed#pushButton_start_cap,:pressed#pushButton_start_cap2,:pressed#pushButton_check_net,:pressed#pushButton_move_mp4,:pressed#pushButton_select_file,:pressed#pushButton_select_local_library,:pressed#pushButton_select_netdisk_path,:pressed#pushButton_select_localdisk_path,:pressed#pushButton_creat_symlink,:pressed#pushButton_find_missing_number,:pressed#pushButton_select_thumb,:pressed#pushButton_start_single_file,:press#pushButton_select_file_clear_info{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:12px;
            font-weight:bold;
        }}
        QSlider::groove:horizontal{{
            height: 6px;
            border-radius: 3px;
            background: #D7DDE8;
        }}
        QSlider::sub-page:horizontal{{
            border-radius: 3px;
            background: #4C6EFF;
        }}
        QSlider::add-page:horizontal{{
            border-radius: 3px;
            background: #D7DDE8;
        }}
        QSlider::handle:horizontal{{
            width: 16px;
            height: 16px;
            margin: -5px 0;
            border-radius: 8px;
            border: 2px solid #4C6EFF;
            background: #FFFFFF;
        }}
        QSlider::handle:horizontal:hover{{
            border: 2px solid #2F55EA;
            background: #F8FAFF;
        }}
        QScrollBar:vertical{{
            width: 10px;
            margin: 0;
            background: transparent;
        }}
        QScrollBar::handle:vertical{{
            min-height: 32px;
            border-radius: 5px;
            background: #CBD5E1;
        }}
        QScrollBar::handle:vertical:hover{{
            background: #94A3B8;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{{
            height: 0;
            background: transparent;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{{
            background: transparent;
        }}
        QScrollBar:horizontal{{
            height: 10px;
            margin: 0;
            background: transparent;
        }}
        QScrollBar::handle:horizontal{{
            min-width: 32px;
            border-radius: 5px;
            background: #CBD5E1;
        }}
        QScrollBar::handle:horizontal:hover{{
            background: #94A3B8;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal{{
            width: 0;
            background: transparent;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal{{
            background: transparent;
        }}
        QProgressBar::chunk{{
            background-color: #5777FF;
            width: 3px; /*区块宽度*/
            margin: 0px;
        }}
        """)
    self.Ui.treeWidget_number.setStyleSheet(build_tree_widget_style(False))


def set_dark_style(self: "MyMAinWindow"):
    apply_application_palette(True)
    _apply_log_document_style(self, True)
    self.Ui.treeWidget_number.setStyleSheet(build_tree_widget_style(True))

    # 控件美化 左侧栏样式 暗黑模式
    self.Ui.widget_setting.setStyleSheet(f"""
        QWidget#widget_setting{{
            background: #1F272F;
            border-top-left-radius: {self.window_radius}px;
            border-bottom-left-radius: {self.window_radius}px;
        }}
        QPushButton#pushButton_main,#pushButton_log,#pushButton_tool,#pushButton_setting,#pushButton_net,#pushButton_about{{
            font-size: 14px;
            color: white;
            border-width: 9px;
            border-color: gray;
            border-radius: 10px;
            text-align : left;
            qproperty-iconSize: 20px 20px;
            padding-left: 20px;
        }}
        QLabel#label_show_version{{
            font-size: 13px;
            color: rgba(210, 210, 210, 250);
            border: 0px solid rgba(255, 255, 255, 80);
        }}
        """)
    # 主界面
    self.Ui.page_main.setStyleSheet("""
        QLabel#label_number1,#label_actor1,#label_title1,#label_poster1,#label_number,#label_actor,#label_title,#label_poster1{
            font-size: 16px;
            font-weight: bold;
            background-color: rgba(246, 246, 246, 0);
            border: 0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_file_path{
            font-size: 16px;
            color: white;
            background-color: rgba(246, 246, 246, 0);
            font-weight: bold;
            border: 0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_poster_size{
            color: rgba(255, 255, 255, 200);
        }
        QLabel#label_poster,#label_thumb{
            border: 1px solid rgba(255, 255, 255, 200);
        }
        QGroupBox{
            background-color: rgba(246, 246, 246, 0);
        }
        """)
    # 工具页
    self.Ui.page_tool.setStyleSheet("""
        * {
            font-size: 13px;
        }
        QScrollArea{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 0);
        }
        QWidget#scrollAreaWidgetContents_gongju{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 255);
        }

        QLabel{
            font-size:13px;
            border: 0px solid rgba(0, 0, 0, 80);
        }

        QGroupBox{
            background-color: rgba(180, 180, 180, 20);
            border-radius: 10px;
        }
        """)
    # 使用帮助页
    self.Ui.page_about.setStyleSheet("""
        * {
            font-size: 13px;
        }
        QTextBrowser{
            font-family: Consolas, 'PingFang SC', 'Microsoft YaHei UI', 'Noto Color Emoji', 'Segoe UI Emoji';
            font-size: 13px;
            border: 0px solid #BEBEBE;
            background-color: rgba(246,246,246,0);
            padding: 2px, 2px;
        }
        """)
    # 设置页
    self.Ui.page_setting.setStyleSheet("""
        * {
            font-size:13px;
        }
        QScrollArea{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 0);
        }
        QTabWidget{
            background-color: rgba(246, 246, 246, 0);
            border-color: rgba(246, 246, 246, 0);
        }
        QTabWidget::tab-bar {
            alignment: center;
        }
        QTabBar::tab{
            border:1px solid #1F272F;
            min-height: 3ex;
            min-width: 6ex;
            padding: 2px;
            background-color:#242D37;
            border-radius: 2px;
        }
        QTabBar::tab:selected{
            font-weight:bold;
            border-bottom: 2px solid #2080F7;
            background-color:#2080F7;
            border-radius: 1px;
        }
        QWidget#tab1,#tab2,#tab3,#tab4,#tab5,#tab,#tab_2,#tab_3,#tab_4,#tab_5,#tab_6,#tab_7,#scrollAreaWidgetContents_guaxiaomulu,#scrollAreaWidgetContents_guaxiaomoshi,#scrollAreaWidgetContents_guaxiaowangzhan,#scrollAreaWidgetContents_xiazai,#scrollAreaWidgetContents_mingming,#scrollAreaWidgetContents_fanyi,#scrollAreaWidgetContents_zimu,#scrollAreaWidgetContents_shuiyin,#scrollAreaWidgetContents_nfo,#scrollAreaWidgetContents_yanyuan,#scrollAreaWidgetContents_wangluo,#scrollAreaWidgetContents_gaoji{
            background-color: #18222D;
            border-color: rgba(246, 246, 246, 0);
        }
        QLabel{
            font-size:13px;
            border:0px solid rgba(0, 0, 0, 80);
        }
        QLabel#label_config{
            font-size:13px;
            border:0px solid rgba(0, 0, 0, 80);
            background: rgba(31,39,47,230);
        }
        QLineEdit{
            font-size:13px;
            border:0px solid rgba(130, 30, 30, 20);
            border-radius: 15px;
        }
        QRadioButton{
            font-size:13px;
        }
        QCheckBox{
            font-size:13px;
        }
        QCheckBox::indicator, QRadioButton::indicator{
            width: 14px;
            height: 14px;
            border: 1px solid #5B6673;
            background: #18222D;
        }
        QCheckBox::indicator{
            border-radius: 3px;
        }
        QRadioButton::indicator{
            border-radius: 7px;
        }
        QCheckBox::indicator:checked{
            background: #6684FF;
            border: 1px solid #6684FF;
            image: url(resources/Img/check_indicator.svg);
        }
        QRadioButton::indicator:checked{
            background: #6684FF;
            border: 1px solid #6684FF;
            image: url(resources/Img/radio_indicator.svg);
        }
        QCheckBox::indicator:hover, QRadioButton::indicator:hover{
            border: 1px solid #8EA3FF;
        }
        QPlainTextEdit{
            font-size:13px;
            background:#18222D;
            border-radius: 4px;
        }
        QGroupBox{
            background-color: rgba(180, 180, 180, 20);
            border-radius: 10px;
        }
        QPushButton{
            color: #E5E7EB;
        }
        QPushButton#pushButton_scrape_note,#pushButton_field_tips_website,#pushButton_field_tips_nfo{
            color: #E5E7EB;
            background: #1D2834;
            border: 1px solid #3B4654;
            border-radius: 6px;
            padding: 3px 10px;
        }
        QPushButton:hover#pushButton_scrape_note,:hover#pushButton_field_tips_website,:hover#pushButton_field_tips_nfo{
            color: #FFFFFF;
            background: #6684FF;
            border: 1px solid #6684FF;
        }
        QPushButton:pressed#pushButton_scrape_note,:pressed#pushButton_field_tips_website,:pressed#pushButton_field_tips_nfo{
            color: #FFFFFF;
            background: #4C6EE0;
            border: 1px solid #4C6EE0;
        }
        """)
    # 整个页面
    self.Ui.centralwidget.setStyleSheet(f"""
        * {{
            font-family: Consolas, 'PingFang SC', 'Microsoft YaHei UI', 'Noto Color Emoji', 'Segoe UI Emoji';
            font-size:13px;
            color: white;
        }}
        QTreeWidget
        {{
            background-color: rgba(246, 246, 246, 0);
            font-size: 12px;
            border:0px solid rgb(120,120,120);
        }}
        QWidget#centralwidget{{
            background: #18222D;
            border: {self.window_border}px solid rgba(20,20,20,50);
            border-radius: {self.window_radius}px;
       }}
        QTextBrowser#textBrowser_log_main,#textBrowser_net_main{{
            font-size:13px;
            border: 0px solid #BEBEBE;
            background-color: rgba(246,246,246,0);
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_log_main_2{{
            font-size:13px;
            border-radius: 0px;
            border-top: 1px solid #BEBEBE;
            background-color: #18222D;
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_log_main_3{{
            font-size:13px;
            border-radius: 0px;
            border-right: 1px solid #20303F;
            background-color: #1F272F;
            padding: 2px, 2px;
        }}
        QTextBrowser#textBrowser_show_success_list,#textBrowser_show_tips{{
            font-size: 13px;
            border: 1px solid #BEBEBE;
            background-color: #18222D;
            padding: 2px;
        }}
        QWidget#widget_show_success,#widget_show_tips,#widget_nfo{{
            background-color: #1F272F;
            border: 1px solid rgba(240,240,240,150);
            border-radius: 10px;
       }}
        QWidget#scrollAreaWidgetContents_nfo_editor{{
            background-color: #18222D;
            border: 0px solid rgba(0,0,0,150);
        }}
        QLineEdit, QPlainTextEdit, QTextEdit, QDoubleSpinBox, QSpinBox{{
            font-size:13px;
            background:#18222D;
            border-radius:20px;
            border: 1px solid #2F3A46;
            padding: 4px 8px;
            selection-background-color: #4C6EFF;
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus{{
            border: 1px solid #6684FF;
            background: #1D2834;
        }}
        QTextEdit#textEdit_nfo_outline,#textEdit_nfo_originalplot,#textEdit_nfo_tag{{
            font-size:13px;
            background:#18222D;
            border: 1px solid #2F3A46;
            padding: 4px 8px;
        }}
        QToolTip{{
            border: 1px solid #2F3A46;
            border-radius: 8px;
            background: #F9FAFB;
            color: #111827;
            padding: 6px 10px;
        }}
        QCheckBox::indicator, QRadioButton::indicator{{
            width: 14px;
            height: 14px;
            border: 1px solid #5B6673;
            background: #18222D;
        }}
        QCheckBox::indicator{{
            border-radius: 3px;
        }}
        QRadioButton::indicator{{
            border-radius: 7px;
        }}
        QCheckBox::indicator:checked{{
            background: #6684FF;
            border: 1px solid #6684FF;
            image: url(resources/Img/check_indicator.svg);
        }}
        QRadioButton::indicator:checked{{
            background: #6684FF;
            border: 1px solid #6684FF;
            image: url(resources/Img/radio_indicator.svg);
        }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover{{
            border: 1px solid #8EA3FF;
        }}
        QPushButton#pushButton_right_menu,#pushButton_play,#pushButton_open_folder,#pushButton_open_nfo,#pushButton_show_hide_logs,#pushButton_save_failed_list,#pushButton_tree_clear{{
            background-color: rgba(181, 181, 181, 0);
            border-radius:10px;
            border: 0px solid rgba(0, 0, 0, 80);
        }}
        QPushButton:hover#pushButton_right_menu,:hover#pushButton_play,:hover#pushButton_open_folder,:hover#pushButton_open_nfo,:hover#pushButton_show_hide_logs,:hover#pushButton_save_failed_list,:hover#pushButton_tree_clear{{
            background-color: rgba(181, 181, 181, 120);
        }}
        QPushButton:pressed#pushButton_right_menu,:pressed#pushButton_play,:pressed#pushButton_open_folder,:pressed#pushButton_open_nfo,:pressed#pushButton_show_hide_logs,:pressed#pushButton_save_failed_list,:pressed#pushButton_tree_clear{{
            background-color: rgba(150, 150, 150, 120);
        }}
        QPushButton#pushButton_scrape_note,#pushButton_field_tips_website,#pushButton_field_tips_nfo{{
            color: #E5E7EB;
            background: #1D2834;
            border: 1px solid #3B4654;
            border-radius: 6px;
            padding: 3px 10px;
        }}
        QPushButton:hover#pushButton_scrape_note,:hover#pushButton_field_tips_website,:hover#pushButton_field_tips_nfo{{
            color: #FFFFFF;
            background: #6684FF;
            border: 1px solid #6684FF;
        }}
        QPushButton:pressed#pushButton_scrape_note,:pressed#pushButton_field_tips_website,:pressed#pushButton_field_tips_nfo{{
            color: #FFFFFF;
            background: #4C6EE0;
            border: 1px solid #4C6EE0;
        }}
        QPushButton#pushButton_save_new_config,#pushButton_init_config,#pushButton_success_list_close,#pushButton_success_list_save,#pushButton_success_list_clear,#pushButton_show_tips_close,#pushButton_nfo_close,#pushButton_nfo_save,#pushButton_show_pic_actor,#pushButton_add_actor_pic,#pushButton_add_actor_info,#pushButton_add_actor_pic_kodi,#pushButton_del_actor_folder,#pushButton_move_mp4,#pushButton_select_file,#pushButton_select_local_library,#pushButton_select_netdisk_path,#pushButton_select_localdisk_path,#pushButton_creat_symlink,#pushButton_find_missing_number,#pushButton_select_thumb,#pushButton_start_single_file,#pushButton_select_file_clear_info,#pushButton_add_sub_for_all_video,#pushButton_view_failed_list,#pushButton_select_media_folder,#pushButton_select_media_folder_setting_page,#pushButton_select_softlink_folder,#pushButton_select_sucess_folder,#pushButton_select_failed_folder,#pushButton_view_success_file,#pushButton_select_subtitle_folder,#pushButton_select_actor_photo_folder,#pushButton_select_actor_info_db,#pushButton_select_config_folder,#pushButton_add_all_extrafanart_copy,#pushButton_del_all_extrafanart_copy,#pushButton_add_all_extras,#pushButton_del_all_extras,#pushButton_add_all_theme_videos,#pushButton_del_all_theme_videos,#pushButton_check_and_clean_files,#pushButton_search_by_number,#pushButton_search_by_url{{
            font-size:14px;
            background-color: rgba(220, 220,220, 50);
            border-color:black;
            border-width:8px;
            border-radius:20px;
            padding: 2px, 2px;
        }}
        QPushButton:hover#pushButton_show_pic_actor,:hover#pushButton_add_actor_pic,:hover#pushButton_add_actor_info,:hover#pushButton_add_actor_pic_kodi,:hover#pushButton_del_actor_folder,:hover#pushButton_add_sub_for_all_video,:hover#pushButton_view_failed_list,:hover#pushButton_scraper_failed_list,:hover#pushButton_select_media_folder,:hover#pushButton_select_media_folder_setting_page,:hover#pushButton_select_softlink_folder,:hover#pushButton_select_sucess_folder,:hover#pushButton_select_failed_folder,:hover#pushButton_view_success_file,:hover#pushButton_select_subtitle_folder,:hover#pushButton_select_actor_photo_folder,:hover#pushButton_select_actor_info_db,:hover#pushButton_select_config_folder,:hover#pushButton_add_all_extrafanart_copy,:hover#pushButton_del_all_extrafanart_copy,:hover#pushButton_add_all_extras,:hover#pushButton_del_all_extras,:hover#pushButton_add_all_theme_videos,:hover#pushButton_del_all_theme_videos,:hover#pushButton_check_and_clean_files,:hover#pushButton_search_by_number,:hover#pushButton_search_by_url{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
        }}
        QPushButton:pressed#pushButton_show_pic_actor,:pressed#pushButton_add_actor_pic,:pressed#pushButton_add_actor_info,:pressed#pushButton_add_actor_pic_kodi,:pressed#pushButton_del_actor_folder,:pressed#pushButton_add_sub_for_all_video,:pressed#pushButton_view_failed_list,:pressed#pushButton_scraper_failed_list,:pressed#pushButton_select_media_folder,:pressed#pushButton_select_media_folder_setting_page,:pressed#pushButton_select_softlink_folder,:pressed#pushButton_select_sucess_folder,:pressed#pushButton_select_failed_folder,:pressed#pushButton_view_success_file,:pressed#pushButton_select_subtitle_folder,:pressed#pushButton_select_actor_photo_folder,:pressed#pushButton_select_actor_info_db,:pressed#pushButton_select_config_folder,:pressed#pushButton_add_all_extrafanart_copy,:pressed#pushButton_del_all_extrafanart_copy,:pressed#pushButton_add_all_extras,:pressed#pushButton_del_all_extras,:pressed#pushButton_add_all_theme_videos,:pressed#pushButton_del_all_theme_videos,:pressed#pushButton_check_and_clean_files,:pressed#pushButton_search_by_number,:pressed#pushButton_search_by_url{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:14px;
            font-weight:bold;
        }}
        QPushButton#pushButton_save_config{{
            color: white;
            font-size:14px;
            background-color:#4C6EFF;
            border-radius:25px;
            padding: 2px, 2px;
        }}
        QPushButton:hover#pushButton_save_config,:hover#pushButton_save_new_config,:hover#pushButton_init_config,:hover#pushButton_success_list_close,:hover#pushButton_success_list_save,:hover#pushButton_success_list_clear,:hover#pushButton_show_tips_close,:hover#pushButton_nfo_close,:hover#pushButton_nfo_save{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
        }}
        QPushButton:pressed#pushButton_save_config,:pressed#pushButton_save_new_config,:pressed#pushButton_init_config,:pressed#pushButton_success_list_close,:pressed#pushButton_success_list_save,:pressed#pushButton_success_list_clear,pressed#pushButton_show_tips_close,:pressed#pushButton_nfo_close,:pressed#pushButton_nfo_save{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:14px;
            font-weight:bold;
        }}
        QPushButton#pushButton_start_cap,#pushButton_start_cap2,#pushButton_check_net,#pushButton_scraper_failed_list{{
            color: white;
            font-size:14px;
            background-color:#4C6EFF;
            border-radius:20px;
            padding: 2px, 2px;
            font-weight:bold;
        }}
        QPushButton:hover#pushButton_start_cap,:hover#pushButton_start_cap2,:hover#pushButton_check_net,:hover#pushButton_move_mp4,:hover#pushButton_select_file,:hover#pushButton_select_local_library,:hover#pushButton_select_netdisk_path,:hover#pushButton_select_localdisk_path,:hover#pushButton_creat_symlink,:hover#pushButton_find_missing_number,:hover#pushButton_select_thumb,:hover#pushButton_start_single_file,:hover#pushButton_select_file_clear_info{{
            color: white;
            background-color: rgba(76,110,255,240);
            font-weight:bold;
            }}
        QPushButton:pressed#pushButton_start_cap,:pressed#pushButton_start_cap2,:pressed#pushButton_check_net,:pressed#pushButton_move_mp4,:pressed#pushButton_select_file,:pressed#pushButton_select_local_library,:pressed#pushButton_select_netdisk_path,:pressed#pushButton_select_localdisk_path,:pressed#pushButton_creat_symlink,:pressed#pushButton_find_missing_number,:pressed#pushButton_select_thumb,:pressed#pushButton_start_single_file,:press#pushButton_select_file_clear_info{{
            background-color:#4C6EE0;
            border-color:black;
            border-width:12px;
            font-weight:bold;
        }}
        QSlider::groove:horizontal{{
            height: 6px;
            border-radius: 3px;
            background: #2F3A46;
        }}
        QSlider::sub-page:horizontal{{
            border-radius: 3px;
            background: #6684FF;
        }}
        QSlider::add-page:horizontal{{
            border-radius: 3px;
            background: #2F3A46;
        }}
        QSlider::handle:horizontal{{
            width: 16px;
            height: 16px;
            margin: -5px 0;
            border-radius: 8px;
            border: 2px solid #6684FF;
            background: #F8FAFC;
        }}
        QSlider::handle:horizontal:hover{{
            border: 2px solid #8EA3FF;
            background: #FFFFFF;
        }}
        QComboBox{{
            combobox-popup: 0;
            font-size:13px;
            color: white;
            background:#18222D;
            border: 1px solid #2F3A46;
            border-radius: 8px;
            padding: 3px 30px 3px 8px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: right;
            width: 26px;
            border-left: 1px solid #2F3A46;
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
            background: #1D2834;
        }}
        QComboBox::drop-down:hover {{
            background: #243244;
        }}
        QComboBox::down-arrow {{
            image: url(resources/Img/chevron_down_dark.svg);
            width: 14px;
            height: 14px;
        }}

        QComboBox QAbstractItemView {{
            color:white;
            background: #1F272F;
            border: 1px solid #2F3A46;
            selection-color:white;
            selection-background-color: #6684FF;
            outline: 0;
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 24px;
            padding: 4px 8px;
            color: #E5E7EB;
        }}
        QComboBox QAbstractItemView::item:selected {{
            color: #FFFFFF;
            background: #6684FF;
        }}
        QScrollBar:vertical{{
            width: 10px;
            margin: 0;
            background: transparent;
        }}
        QScrollBar::handle:vertical{{
            min-height: 32px;
            border-radius: 5px;
            background: #4B5563;
        }}
        QScrollBar::handle:vertical:hover{{
            background: #64748B;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{{
            height: 0;
            background: transparent;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{{
            background: transparent;
        }}
        QScrollBar:horizontal{{
            height: 10px;
            margin: 0;
            background: transparent;
        }}
        QScrollBar::handle:horizontal{{
            min-width: 32px;
            border-radius: 5px;
            background: #4B5563;
        }}
        QScrollBar::handle:horizontal:hover{{
            background: #64748B;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal{{
            width: 0;
            background: transparent;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal{{
            background: transparent;
        }}
        QProgressBar::chunk{{
            background-color: #5777FF;
            width: 3px; /*区块宽度*/
            margin: 0px;
        }}
        """)
    self.Ui.treeWidget_number.setStyleSheet(build_tree_widget_style(True))
