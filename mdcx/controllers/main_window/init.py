import re
import traceback
import webbrowser
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QMenu, QSystemTrayIcon, QTreeWidgetItem

from mdcx.config.enums import Website
from mdcx.config.extend import get_movie_path_setting
from mdcx.config.resources import resources
from mdcx.consts import GITHUB_RELEASES_URL, IS_WINDOWS
from mdcx.manual import ManualConfig
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt

if TYPE_CHECKING:
    from .main_window import MyMAinWindow


def Init_Ui(self: "MyMAinWindow"):
    self.setWindowTitle("MDCx")  # 设置任务栏标题
    self.setWindowIcon(QIcon(resources.icon_ico))  # 设置任务栏图标
    self.setWindowOpacity(1.0)  # 设置窗口透明度
    if IS_WINDOWS:
        self.setFixedSize(
            self.width(), self.height()
        )  # 禁止调整窗口大小(mac 平台禁止后最小化没反应，恢复时顶部会残留标题栏)
    self.setAttribute(Qt.WA_TranslucentBackground)  # 设置窗口背景透明
    self.Ui.progressBar_scrape.setValue(0)  # 进度条清0
    self.Ui.progressBar_scrape.setTextVisible(False)  # 不显示进度条文字
    self.Ui.pushButton_start_cap.setCheckable(True)  # 主界面开始按钮可点状态
    self.init_QTreeWidget()  # 初始化树状图
    self.Ui.label_poster.setScaledContents(True)  # 图片自适应窗口
    self.Ui.label_thumb.setScaledContents(True)  # 图片自适应窗口
    self.Ui.pushButton_right_menu.setIcon(QIcon(resources.right_menu))
    self.Ui.pushButton_right_menu.setToolTip(" 右键菜单 ")
    self.Ui.pushButton_play.setIcon(QIcon(resources.play_icon))
    self.Ui.pushButton_play.setToolTip(" 播放 ")
    self.Ui.pushButton_open_folder.setIcon(QIcon(resources.open_folder_icon))
    self.Ui.pushButton_open_folder.setToolTip(" 打开文件夹 ")
    self.Ui.pushButton_open_nfo.setIcon(QIcon(resources.open_nfo_icon))
    self.Ui.pushButton_open_nfo.setToolTip(" 编辑 NFO ")
    self.Ui.pushButton_tree_clear.setIcon(QIcon(resources.clear_tree_icon))
    self.Ui.pushButton_tree_clear.setToolTip(" 清空结果列表 ")
    self.Ui.pushButton_close.setToolTip(" 关闭 ")
    self.Ui.pushButton_min.setToolTip(" 最小化 ")
    self.Ui.pushButton_main.setIcon(QIcon(resources.home_icon))
    self.Ui.pushButton_log.setIcon(QIcon(resources.log_icon))
    self.Ui.pushButton_tool.setIcon(QIcon(resources.tool_icon))
    self.Ui.pushButton_setting.setIcon(QIcon(resources.setting_icon))
    self.Ui.pushButton_net.setIcon(QIcon(resources.net_icon))
    help_icon = QIcon(resources.help_icon)
    self.Ui.pushButton_about.setIcon(help_icon)
    self.Ui.pushButton_tips_normal_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_normal_mode.setToolTip("""<html><head/><body><p><b>正常模式：</b><br/>1）适合海报墙用户。正常模式将联网刮削视频字段信息，并执行翻译字段信息，移动和重命名视频文件及文件夹，下载图片、剧照、预告片，添加字幕、4K水印等一系列自动化操作<br/>2）刮削目录请在「设置」-「刮削目录」-「待刮削目录」中设置<br/>3）刮削网站请在「设置」-「刮削网站」中设置。部分网站需要代理访问，可在「设置」-「代理」中设置代理和免翻网址。你可以点击左侧的「检测网络」查看网络连通性<br/>\
        4）字段翻译请在「设置」-「翻译」中设置<br/>5）图片、剧照、预告片请在「设置」-「下载」中设置<br/>6）视频文件命名请在「设置」-「命名」中设置<br/>7）如果刮削后不需要重命名，请在下面的「刮削成功后重命名文件」设置为「关」<br/>8）如果刮削后不需要移动文件，请在下面的「刮削成功后移动文件」设置为「关」<br/>9）如果想自动刮削，请在「设置」-「高级」中勾选「自动刮削」<br/>10）其他设置项和功能玩法可自行研究</p></body></html>""")
    self.Ui.pushButton_tips_sort_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_sort_mode.setToolTip(
        """<html><head/><body><p><b>视频模式：</b><br/>1，适合不需要图片墙的情况。视频模式将联网刮削视频相关字段信息，然后根据「设置」-「命名」中设置的命名规则重命名、移动视频文件<br/>2，仅整理视频，不会下载和重命名图片、nfo 文件<br/>3，如果是海报墙用户，请不要使用视频模式。</p></body></html>"""
    )
    self.Ui.pushButton_tips_update_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_update_mode.setToolTip("""<html><head/><body><p><b>更新模式：</b><br/>1，适合视频已经归类好的情况。更新模式将在不改动文件位置结构的前提下重新刮削更新一些信息<br/>2，更新规则在下面的「更新模式规则中」定义：<br/>-1）如果只更新视频文件名，请选择「只更新C」，视频文件名命名规则请到「设置-」「命名规则」中设置<br/>-2）如果要更新视频所在的目录名，请选择「更新B和C」；如果要更新视频目录的上层目录，请勾选「同时更新A目录」<br/>-3），如果要在视频目录为视频再创建一级目录，请选择「创建D目录」<br/>\
        3，更新模式将会对「待刮削目录」下的所有视频进行联网刮削和更新。<br/>4，当有部分内容没有更新成功，下次想只刮削这些内容时，请选择「读取模式」，同时勾选「不存在 nfo 时，刮削并执行更新模式规则」，它将查询并读取所有视频本地的 nfo 文件（不联网），当没有 nfo 文件时，则会自动进行联网刮削<br/>5，当部分内容确实无法刮削时，你可以到「日志」页面，点击「失败」按钮，点击左下角的保存按钮，就可以把失败列表保存到本地，然后可以手动查看和处理这些视频信息。</p></body></html>""")
    self.Ui.pushButton_tips_read_mode.setIcon(help_icon)
    self.Ui.pushButton_tips_read_mode.setToolTip("""<html><head/><body><p><b>读取模式：</b><br/>\
        1，读取模式通过读取本地的 nfo 文件中的字段信息，可以无需联网，实现查看或更新视频命名等操作<br/>\
        2，如果仅想查看和检查已刮削的视频信息和图片是否存在问题，可以：<br/>\
        -1）不勾选「本地已刮削成功的文件，重新整理分类」；<br/>\
        -2）不勾选「本地自取刮削失败的文件，重新刮削」。<br/>\
        3，如果想要快速重新整理分类(不联网)，可以：<br/>\
        -1）勾选「本地已刮削成功的文件，重新整理分类」；<br/>\
        -2）在下面的「更新模式规则」中自定义更新规则。<br/>\
        软件将按照「更新模式规则」，和「设置」-「命名」中的设置项，进行重命名等操作。<br/>\
        4，如果想要使用本地nfo信息再次更新nfo文件（包括emby标题、tag、翻译等），可以：<br/>\
        -1）勾选「本地已刮削成功的文件，重新整理分类」；<br/>\
        -2）勾选「允许更新 nfo 文件」。<br/>\
        软件将按照「设置」-「刮削模式」-「Emby视频标题命名规则」、「设置」-「翻译」、「设置」-「NFO」等的设置项，利用本地 nfo 更新 nfo 信息。<br/>\
        6，如果想要重新下载图片等文件（需联网），可以：<br/>\
        -1）勾选「本地已刮削成功的文件，重新整理分类」；<br/>\
        -2）勾选「重新下载图片等文件」。<br/>\
        软件将按照「设置」-「下载」中的设置项，进行下载、保留等操作。</p></body></html>""")
    self.Ui.pushButton_tips_soft.setIcon(help_icon)
    self.Ui.pushButton_tips_soft.setToolTip("""<html><head/><body><p><b>创建软链接：</b><br/>\
        1，软链接适合网盘用户。软链接类似快捷方式，是指向真实文件的一个符号链接。它体积小，支持跨盘指向，删除后不影响原文件（当原文件删除后，软链接会失效）。<br/>\
        <span style=" font-weight:700; color:red;">注意：\
        <br/>Windows版：软链接保存位置必须是本地磁盘（平台限制），真实文件则网盘或本地盘都可以。<br/>\
        macOS版：没有问题。<br/>\
        Docker版：挂载目录的完整路径需要和实际目录完整路径一样，这样软链接才能指向实际位置，Emby 才能播放。</span><br/>\

        2，网盘受网络等因素影响，读写慢，限制多。选择创建软链接时，将在本地盘创建指向网盘视频文件的软链接文件，同时刮削下载的图片同样放在本地磁盘，使用 Emby、Jellyfin 加载速度快！<br/>\
        3，刮削不会移动、修改、重命名原文件，仅读取原文件的路径位置，用来创建软链接<br/>\
        4，刮削成功后，将按照刮削设置创建和重命名软链接文件<br/>\
        5，刮削失败时，不会创建软链接，如果你想要把全部文件都创建软链接，可以到 【工具】-【软链接助手】-【一键创建软链接】）<br/>\
        6，如果网盘里已经有刮削好的内容，想要把刮削信息转移到本地磁盘，同样使用上述工具，勾选【复制已刮削的图片和NFO文件】即可<br/>\
        7，网盘挂载和刮削方法：<br/>\
        -1）使用 CloudDriver、Alist、RaiDrive 等第三方工具挂载网盘<br/>\
        -2）MDCx 设置待刮削目录为网盘视频目录，输出目录为本地磁盘文件夹<br/>\
        -3）设置中选择「创建软链接」，其他配置设置好后保存配置，点击开始刮削<br/>\
        -4）Emby、Jellyfin 媒体库路径设置为本地刮削后保存的磁盘文件夹扫描即可</p></body></html>""")
    self.Ui.pushButton_tips_hard.setIcon(help_icon)
    self.Ui.pushButton_tips_hard.setToolTip(
        """<html><head/><body><p><b>创建硬链接：</b><br/>1，硬链接适合 PT 用户。PT 用户视频文件一般存放在 NAS 中，为保证上传分享率，不能修改原文件信息。<br/>2，硬链接指向和原文件相同的硬盘索引，和原文件必须同盘。使用硬链接，可以在同盘单独存放刮削资料，不影响原文件信息。<br/>3，删除硬链接，原文件还在；删除原文件，硬链接还在。两个都删除，文件才会被删除。<br/><span style=" font-weight:700; color:#ff2600;">注意：Mac 平台仅支持本地磁盘创建硬链接（权限问题），非本地磁盘请选择创建软链接。Windows 平台没有这个问题。</span></p></body></html>"""
    )
    self.Ui.textBrowser_log_main_3.hide()  # 失败列表隐藏
    self.Ui.pushButton_scraper_failed_list.hide()
    self.Ui.pushButton_save_failed_list.hide()
    supported_websites = list(ManualConfig.SUPPORTED_WEBSITES)
    if Website.AVBASE.value not in supported_websites:
        supported_websites.append(Website.AVBASE.value)
    self.Ui.comboBox_custom_website.addItems(supported_websites)
    self.Ui.textBrowser_log_main.document().setMaximumBlockCount(6000)
    self.Ui.textBrowser_log_main_2.document().setMaximumBlockCount(3000)
    self.Ui.textBrowser_log_main.viewport().installEventFilter(self)  # 注册事件用于识别点击控件时隐藏失败列表面板
    self.Ui.textBrowser_log_main_2.viewport().installEventFilter(self)
    self.Ui.pushButton_save_failed_list.setIcon(QIcon(resources.save_failed_list_icon))
    self.Ui.widget_show_success.resize(811, 511)
    self.Ui.widget_show_success.hide()
    self.Ui.widget_show_tips.resize(811, 511)
    self.Ui.widget_show_tips.hide()
    self.Ui.widget_nfo.resize(791, 681)
    self.Ui.widget_nfo.hide()


def Init_Singal(self: "MyMAinWindow"):
    # region 外部信号量连接
    signal_qt.log_text.connect(self.show_log_text)  # 可视化日志输出
    signal_qt.scrape_info.connect(self.show_scrape_info)  # 可视化日志输出
    signal_qt.net_info.connect(self.show_net_info)  # 可视化日志输出
    signal_qt.exec_set_main_info.connect(self.set_main_info)
    signal_qt.change_buttons_status.connect(self.change_buttons_status)
    signal_qt.reset_buttons_status.connect(self.reset_buttons_status)
    signal_qt.logs_failed_settext.connect(self.Ui.textBrowser_log_main_3.setText)
    signal_qt.label_result.connect(self.Ui.label_result.setText)
    signal_qt.set_label_file_path.connect(self.Ui.label_file_path.setText)
    signal_qt.view_success_file_settext.connect(self.Ui.pushButton_view_success_file.setText)
    signal_qt.exec_set_processbar.connect(self.set_processbar)
    signal_qt.view_failed_list_settext.connect(self.Ui.pushButton_view_failed_list.setText)
    signal_qt.exec_show_list_name.connect(self.show_list_name)
    signal_qt.exec_exit_app.connect(self.exit_app)
    signal_qt.logs_failed_show.connect(self.Ui.textBrowser_log_main_3.append)
    # endregion

    # region 控件点击
    # self.Ui.treeWidget_number.clicked.connect(self.treeWidget_number_clicked)
    self.Ui.treeWidget_number.selectionModel().selectionChanged.connect(self.treeWidget_number_clicked)
    self.Ui.pushButton_close.clicked.connect(self.pushButton_close_clicked)
    self.Ui.pushButton_min.clicked.connect(self.pushButton_min_clicked)
    self.Ui.pushButton_main.clicked.connect(self.pushButton_main_clicked)
    self.Ui.pushButton_log.clicked.connect(self.pushButton_show_log_clicked)
    self.Ui.pushButton_net.clicked.connect(self.pushButton_show_net_clicked)
    self.Ui.pushButton_tool.clicked.connect(self.pushButton_tool_clicked)
    self.Ui.pushButton_setting.clicked.connect(self.pushButton_setting_clicked)
    self.Ui.pushButton_about.clicked.connect(self.pushButton_about_clicked)
    self.Ui.pushButton_select_local_library.clicked.connect(self.pushButton_select_local_library_clicked)
    self.Ui.pushButton_select_netdisk_path.clicked.connect(self.pushButton_select_netdisk_path_clicked)
    self.Ui.pushButton_select_localdisk_path.clicked.connect(self.pushButton_select_localdisk_path_clicked)
    self.Ui.pushButton_select_media_folder.clicked.connect(self.pushButton_select_media_folder_clicked)
    self.Ui.pushButton_select_media_folder_setting_page.clicked.connect(self.pushButton_select_media_folder_clicked)
    self.Ui.pushButton_select_softlink_folder.clicked.connect(self.pushButton_select_softlink_folder_clicked)
    self.Ui.pushButton_select_sucess_folder.clicked.connect(self.pushButton_select_sucess_folder_clicked)
    self.Ui.pushButton_select_failed_folder.clicked.connect(self.pushButton_select_failed_folder_clicked)
    self.Ui.pushButton_view_success_file.clicked.connect(self.pushButton_view_success_file_clicked)
    self.Ui.pushButton_select_subtitle_folder.clicked.connect(self.pushButton_select_subtitle_folder_clicked)
    self.Ui.pushButton_select_actor_photo_folder.clicked.connect(self.pushButton_select_actor_photo_folder_clicked)
    self.Ui.pushButton_select_config_folder.clicked.connect(self.pushButton_select_config_folder_clicked)
    self.Ui.pushButton_select_actor_info_db.clicked.connect(self.pushButton_select_actor_info_db_clicked)
    self.Ui.pushButton_select_file.clicked.connect(self.pushButton_select_file_clicked)
    self.Ui.pushButton_start_cap.clicked.connect(self.pushButton_start_scrape_clicked)
    self.Ui.pushButton_start_cap2.clicked.connect(self.pushButton_start_scrape_clicked)
    self.Ui.pushButton_show_hide_logs.clicked.connect(self.pushButton_show_hide_logs_clicked)
    self.Ui.pushButton_view_failed_list.clicked.connect(self.pushButton_show_hide_failed_list_clicked)
    self.Ui.pushButton_save_new_config.clicked.connect(self.pushButton_save_new_config_clicked)
    self.Ui.pushButton_save_config.clicked.connect(self.pushButton_save_config_clicked)
    self.Ui.pushButton_init_config.clicked.connect(self.pushButton_init_config_clicked)
    self.Ui.pushButton_move_mp4.clicked.connect(self.pushButton_move_mp4_clicked)
    self.Ui.pushButton_check_net.clicked.connect(self.pushButton_check_net_clicked)
    self.Ui.pushButton_check_javdb_cookie.clicked.connect(self.pushButton_check_javdb_cookie_clicked)
    self.Ui.pushButton_check_fc2ppvdb_cookie.clicked.connect(self.pushButton_check_fc2ppvdb_cookie_clicked)
    self.Ui.pushButton_check_javbus_cookie.clicked.connect(self.pushButton_check_javbus_cookie_clicked)
    self.Ui.pushButton_check_and_clean_files.clicked.connect(self.pushButton_check_and_clean_files_clicked)
    self.Ui.pushButton_add_all_extras.clicked.connect(self.pushButton_add_all_extras_clicked)
    self.Ui.pushButton_del_all_extras.clicked.connect(self.pushButton_del_all_extras_clicked)
    self.Ui.pushButton_add_all_extrafanart_copy.clicked.connect(self.pushButton_add_all_extrafanart_copy_clicked)
    self.Ui.pushButton_del_all_extrafanart_copy.clicked.connect(self.pushButton_del_all_extrafanart_copy_clicked)
    self.Ui.pushButton_add_all_theme_videos.clicked.connect(self.pushButton_add_all_theme_videos_clicked)
    self.Ui.pushButton_del_all_theme_videos.clicked.connect(self.pushButton_del_all_theme_videos_clicked)
    self.Ui.pushButton_add_sub_for_all_video.clicked.connect(self.pushButton_add_sub_for_all_video_clicked)
    self.Ui.pushButton_add_actor_info.clicked.connect(self.pushButton_add_actor_info_clicked)
    self.Ui.pushButton_add_actor_pic.clicked.connect(self.pushButton_add_actor_pic_clicked)
    self.Ui.pushButton_add_actor_pic_kodi.clicked.connect(self.pushButton_add_actor_pic_kodi_clicked)
    self.Ui.pushButton_del_actor_folder.clicked.connect(self.pushButton_del_actor_folder_clicked)
    self.Ui.pushButton_show_pic_actor.clicked.connect(self.pushButton_show_pic_actor_clicked)
    self.Ui.pushButton_select_thumb.clicked.connect(self.pushButton_select_thumb_clicked)
    self.Ui.pushButton_find_missing_number.clicked.connect(self.pushButton_find_missing_number_clicked)
    self.Ui.pushButton_creat_symlink.clicked.connect(self.pushButton_creat_symlink_clicked)
    self.Ui.pushButton_start_single_file.clicked.connect(self.pushButton_start_single_file_clicked)
    self.Ui.pushButton_select_file_clear_info.clicked.connect(self.pushButton_select_file_clear_info_clicked)
    self.Ui.pushButton_scrape_note.clicked.connect(self.pushButton_scrape_note_clicked)
    self.Ui.pushButton_field_tips_nfo.clicked.connect(self.pushButton_field_tips_nfo_clicked)
    self.Ui.pushButton_tips_normal_mode.clicked.connect(self.pushButton_tips_normal_mode_clicked)
    self.Ui.pushButton_tips_sort_mode.clicked.connect(self.pushButton_tips_sort_mode_clicked)
    self.Ui.pushButton_tips_update_mode.clicked.connect(self.pushButton_tips_update_mode_clicked)
    self.Ui.pushButton_tips_read_mode.clicked.connect(self.pushButton_tips_read_mode_clicked)
    self.Ui.pushButton_tips_soft.clicked.connect(self.pushButton_tips_soft_clicked)
    self.Ui.pushButton_tips_hard.clicked.connect(self.pushButton_tips_hard_clicked)
    self.Ui.checkBox_cover.stateChanged.connect(self.checkBox_cover_clicked)
    self.Ui.checkBox_i_agree_clean.stateChanged.connect(self.checkBox_i_agree_clean_clicked)
    self.Ui.checkBox_cd_part_a.stateChanged.connect(self.checkBox_cd_part_a_clicked)
    self.Ui.checkBox_i_understand_clean.stateChanged.connect(self.checkBox_i_agree_clean_clicked)
    self.Ui.horizontalSlider_timeout.valueChanged.connect(self.lcdNumber_timeout_change)
    self.Ui.horizontalSlider_retry.valueChanged.connect(self.lcdNumber_retry_change)
    self.Ui.horizontalSlider_mark_size.valueChanged.connect(self.lcdNumber_mark_size_change)
    self.Ui.horizontalSlider_thread.valueChanged.connect(self.lcdNumber_thread_change)
    self.Ui.horizontalSlider_javdb_time.valueChanged.connect(self.lcdNumber_javdb_time_change)
    self.Ui.horizontalSlider_thread_time.valueChanged.connect(self.lcdNumber_thread_time_change)
    self.Ui.comboBox_change_config.activated[str].connect(self.config_file_change)
    self.Ui.comboBox_custom_website.activated[str].connect(self.switch_custom_website_change)
    self.Ui.pushButton_right_menu.clicked.connect(self.main_open_right_menu)
    self.Ui.pushButton_play.clicked.connect(self.main_play_click)
    self.Ui.pushButton_open_folder.clicked.connect(self.main_open_folder_click)
    self.Ui.pushButton_open_nfo.clicked.connect(self.main_open_nfo_click)
    self.Ui.pushButton_tree_clear.clicked.connect(self.init_QTreeWidget)
    self.Ui.pushButton_scraper_failed_list.clicked.connect(self.pushButton_scraper_failed_list_clicked)
    self.Ui.pushButton_save_failed_list.clicked.connect(self.pushButton_save_failed_list_clicked)
    self.Ui.pushButton_success_list_close.clicked.connect(self.Ui.widget_show_success.hide)
    self.Ui.pushButton_success_list_save.clicked.connect(self.pushButton_success_list_save_clicked)
    self.Ui.pushButton_success_list_clear.clicked.connect(self.pushButton_success_list_clear_clicked)
    self.Ui.pushButton_show_tips_close.clicked.connect(self.Ui.widget_show_tips.hide)
    self.Ui.pushButton_nfo_close.clicked.connect(self.Ui.widget_nfo.hide)
    self.Ui.pushButton_nfo_save.clicked.connect(self.save_nfo_info)
    # endregion

    # region 鼠标点击
    self.Ui.label_show_version.mousePressEvent = self.label_version_clicked
    self.Ui.label_local_number.mousePressEvent = self.label_local_number_clicked

    def n(a): ...  # mousePressEvent 的返回值必须是 None, 用这个包装一下

    self.Ui.label_download_actor_zip.mousePressEvent = lambda ev: n(
        webbrowser.open("https://github.com/moyy996/AVDC/releases/tag/%E5%A4%B4%E5%83%8F%E5%8C%85-2")
    )
    self.Ui.label_download_sub_zip.mousePressEvent = lambda ev: n(
        webbrowser.open("https://www.dropbox.com/sh/vkbxawm6mwmwswr/AADqZiF8aUHmK6qIc7JSlURIa")
    )
    self.Ui.label_download_mark_zip.mousePressEvent = lambda ev: n(
        webbrowser.open("https://www.dropbox.com/sh/vkbxawm6mwmwswr/AADqZiF8aUHmK6qIc7JSlURIa")
    )
    self.Ui.label_get_cookie_url.mousePressEvent = lambda ev: n(webbrowser.open("https://tieba.baidu.com/p/5492736764"))
    self.Ui.label_download_actor_db.mousePressEvent = lambda ev: n(
        webbrowser.open(f"{GITHUB_RELEASES_URL}/tag/actor_info_database")
    )

    # 日志窗口链接仅外部打开，避免 QTextBrowser 内部跳转导致日志页变空
    self.Ui.textBrowser_log_main.setOpenLinks(False)
    self.Ui.textBrowser_log_main_2.setOpenLinks(False)
    self.Ui.textBrowser_net_main.setOpenLinks(False)

    def _open_safe_url(url):
        raw = url.toString()
        m = re.match(r"^(https?://[^\s\"'<>]+)", raw)
        target = m.group(1) if m else raw
        webbrowser.open(target)

    self.Ui.textBrowser_log_main.anchorClicked.connect(lambda url: n(_open_safe_url(url)))
    self.Ui.textBrowser_log_main_2.anchorClicked.connect(lambda url: n(_open_safe_url(url)))
    self.Ui.textBrowser_net_main.anchorClicked.connect(lambda url: n(_open_safe_url(url)))
    # endregion

    # region 控件更新
    self.main_logs_show.connect(self.Ui.textBrowser_log_main.append)
    self.main_logs_clear.connect(self.Ui.textBrowser_log_main.clear)
    self.req_logs_clear.connect(self.Ui.textBrowser_log_main_2.clear)
    self.main_req_logs_show.connect(self.Ui.textBrowser_log_main_2.append)
    self.net_logs_show.connect(self.Ui.textBrowser_net_main.append)
    self.set_javdb_cookie.connect(self.Ui.plainTextEdit_cookie_javdb.setPlainText)
    self.set_javbus_cookie.connect(self.Ui.plainTextEdit_cookie_javbus.setPlainText)
    self.set_javbus_status.connect(self.Ui.label_javbus_cookie_result.setText)
    self.set_pic_pixmap.connect(self.resize_label_and_setpixmap)
    self.set_pic_text.connect(self.Ui.label_poster_size.setText)
    self.change_to_mainpage.connect(self.change_mainpage)
    # endregion

    # region 文本更新
    self.set_label_file_path.connect(self.Ui.label_file_path.setText)
    self.pushButton_start_cap.connect(self.Ui.pushButton_start_cap.setText)
    self.pushButton_start_cap2.connect(self.Ui.pushButton_start_cap2.setText)
    self.pushButton_start_single_file.connect(self.Ui.pushButton_start_single_file.setText)
    self.pushButton_add_sub_for_all_video.connect(self.Ui.pushButton_add_sub_for_all_video.setText)
    self.pushButton_show_pic_actor.connect(self.Ui.pushButton_show_pic_actor.setText)
    self.pushButton_add_actor_info.connect(self.Ui.pushButton_add_actor_info.setText)
    self.pushButton_add_actor_pic.connect(self.Ui.pushButton_add_actor_pic.setText)
    self.pushButton_add_actor_pic_kodi.connect(self.Ui.pushButton_add_actor_pic_kodi.setText)
    self.pushButton_del_actor_folder.connect(self.Ui.pushButton_del_actor_folder.setText)
    self.pushButton_check_and_clean_files.connect(self.Ui.pushButton_check_and_clean_files.setText)
    self.pushButton_move_mp4.connect(self.Ui.pushButton_move_mp4.setText)
    self.pushButton_find_missing_number.connect(self.Ui.pushButton_find_missing_number.setText)
    self.label_result.connect(self.Ui.label_result.setText)
    self.label_show_version.connect(self.Ui.label_show_version.setText)  # endregion


def Init_QSystemTrayIcon(self: "MyMAinWindow"):
    self.tray_icon = QSystemTrayIcon(self)
    self.tray_icon.setIcon(QIcon(resources.icon_ico))
    self.tray_icon.activated.connect(self.tray_icon_click)
    self.tray_icon.setToolTip(f"MDCx {self.localversion}（左键显示/隐藏 | 右键退出）")
    show_action = QAction("显示", self)
    hide_action = QAction("隐藏\tQ", self)
    quit_action = QAction("退出 MDCx", self)
    show_action.triggered.connect(self.tray_icon_show)
    hide_action.triggered.connect(self.hide)
    quit_action.triggered.connect(self.ready_to_exit)
    tray_menu = QMenu()
    tray_menu.addAction(show_action)
    tray_menu.addAction(hide_action)
    tray_menu.addSeparator()
    tray_menu.addAction(quit_action)
    self.tray_icon.setContextMenu(tray_menu)
    self.tray_icon.show()
    # self.tray_icon.showMessage(f"MDCx {self.localversion}", u'已启动！欢迎使用!', QIcon(self.icon_ico), 3000)
    # icon的值  0没有图标  1是提示  2是警告  3是错误


def init_QTreeWidget(self: "MyMAinWindow"):
    # 初始化树状控件
    try:
        self.set_label_file_path.emit(
            f"🎈 当前刮削路径: \n {get_movie_path_setting().movie_path}"
        )  # 主界面右上角显示提示信息
    except Exception:
        signal_qt.show_traceback_log(traceback.format_exc())
    signal_qt.set_main_info()
    Flags.count_claw = 0  # 批量刮削次数
    if self.Ui.pushButton_start_cap.text() != "开始":
        Flags.count_claw = 1  # 批量刮削次数
    else:
        self.label_result.emit(" 刮削中：0 成功：0 失败：0")
    self.Ui.treeWidget_number.clear()
    self.item_succ = QTreeWidgetItem(self.Ui.treeWidget_number)
    self.item_succ.setText(0, "成功")
    self.item_fail = QTreeWidgetItem(self.Ui.treeWidget_number)
    self.item_fail.setText(0, "失败")
    self.Ui.treeWidget_number.expandAll()  # 展开主界面树状内容
