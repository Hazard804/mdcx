import platform
import re
import traceback
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import HttpUrl, ValidationError
from PyQt5.QtCore import Qt

from mdcx.config.enums import (
    CDChar,
    CleanAction,
    DownloadableFile,
    EmbyAction,
    FieldRule,
    HDPicSource,
    KeepableFile,
    Language,
    MarkType,
    NfoInclude,
    NoEscape,
    OutlineShow,
    ReadMode,
    SuffixSort,
    Switch,
    TagInclude,
    Translator,
    Website,
)
from mdcx.config.extend import get_movie_path_setting
from mdcx.config.manager import manager
from mdcx.config.models import SiteConfig, str_to_list
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt
from mdcx.tools.actress_db import ActressDB

from .bind_utils import get_checkbox, get_checkboxes, get_radio_buttons

if TYPE_CHECKING:
    from .main_window import MyMAinWindow


def save_config(self: "MyMAinWindow"):
    """
    从 UI 获取配置并保存到 config 对象中, 并更新配置文件
    """
    field_mapping = {
        "title": CrawlerResultFields.TITLE,
        "outline": CrawlerResultFields.OUTLINE,
        "actor": CrawlerResultFields.ACTORS,
        "tag": CrawlerResultFields.TAGS,
        "series": CrawlerResultFields.SERIES,
        "studio": CrawlerResultFields.STUDIO,
        "publisher": CrawlerResultFields.PUBLISHER,
        "director": CrawlerResultFields.DIRECTORS,
        "poster": CrawlerResultFields.POSTER,
        "thumb": CrawlerResultFields.THUMB,
        "extrafanart": CrawlerResultFields.EXTRAFANART,
        "score": CrawlerResultFields.SCORE,
        "release": CrawlerResultFields.RELEASE,
        "runtime": CrawlerResultFields.RUNTIME,
        "trailer": CrawlerResultFields.TRAILER,
        "wanted": CrawlerResultFields.WANTED,
    }

    # region media & escape
    manager.config.media_path = self.Ui.lineEdit_movie_path.text()  # 待刮削目录
    manager.config.softlink_path = self.Ui.lineEdit_movie_softlink_path.text()  # 软链接目录目录
    manager.config.success_output_folder = self.Ui.lineEdit_success.text()  # 成功输出目录
    manager.config.failed_output_folder = self.Ui.lineEdit_fail.text()  # 失败输出目录
    manager.config.extrafanart_folder = self.Ui.lineEdit_extrafanart_dir.text().strip()  # 剧照目录

    media_type_text = self.Ui.lineEdit_movie_type.text().lower()
    manager.config.media_type = str_to_list(media_type_text, "|")
    sub_type_text = self.Ui.lineEdit_sub_type.text()
    manager.config.sub_type = str_to_list(sub_type_text, "|")

    folders_text = self.Ui.lineEdit_escape_dir.text()
    manager.config.folders = str_to_list(folders_text, ",")
    string_text = self.Ui.lineEdit_escape_string.text()
    manager.config.string = str_to_list(string_text, ",")
    manager.config.scrape_softlink_path = get_checkbox(self.Ui.checkBox_scrape_softlink_path)

    try:  # 过滤小文件大小
        manager.config.file_size = float(self.Ui.lineEdit_escape_size.text())
    except Exception:
        manager.config.file_size = 0.0
    manager.config.no_escape = get_checkboxes(
        (self.Ui.checkBox_no_escape_file, NoEscape.NO_SKIP_SMALL_FILE),
        (self.Ui.checkBox_no_escape_dir, NoEscape.FOLDER),
        (self.Ui.checkBox_skip_success_file, NoEscape.SKIP_SUCCESS_FILE),
        (self.Ui.checkBox_record_success_file, NoEscape.RECORD_SUCCESS_FILE),
        (self.Ui.checkBox_check_symlink, NoEscape.CHECK_SYMLINK),
        (self.Ui.checkBox_check_symlink_definition, NoEscape.SYMLINK_DEFINITION),
    )
    # endregion

    # region clean
    clean_ext_text = self.Ui.lineEdit_clean_file_ext.text()
    manager.config.clean_ext = str_to_list(clean_ext_text, "|")
    clean_name_text = self.Ui.lineEdit_clean_file_name.text()
    manager.config.clean_name = str_to_list(clean_name_text, "|")
    clean_contains_text = self.Ui.lineEdit_clean_file_contains.text()
    manager.config.clean_contains = str_to_list(clean_contains_text, "|")
    try:
        manager.config.clean_size = float(self.Ui.lineEdit_clean_file_size.text())  # 清理文件大小小于等于
    except Exception:
        manager.config.clean_size = 0.0
    clean_ignore_ext_text = self.Ui.lineEdit_clean_excluded_file_ext.text()
    manager.config.clean_ignore_ext = str_to_list(clean_ignore_ext_text, "|")
    clean_ignore_contains_text = self.Ui.lineEdit_clean_excluded_file_contains.text()
    manager.config.clean_ignore_contains = str_to_list(clean_ignore_contains_text, "|")
    manager.config.clean_enable = get_checkboxes(
        (self.Ui.checkBox_clean_file_ext, CleanAction.CLEAN_EXT),
        (self.Ui.checkBox_clean_file_name, CleanAction.CLEAN_NAME),
        (self.Ui.checkBox_clean_file_contains, CleanAction.CLEAN_CONTAINS),
        (self.Ui.checkBox_clean_file_size, CleanAction.CLEAN_SIZE),
        (self.Ui.checkBox_clean_excluded_file_ext, CleanAction.CLEAN_IGNORE_EXT),
        (self.Ui.checkBox_clean_excluded_file_contains, CleanAction.CLEAN_IGNORE_CONTAINS),
        (self.Ui.checkBox_i_understand_clean, CleanAction.I_KNOW),
        (self.Ui.checkBox_i_agree_clean, CleanAction.I_AGREE),
        (self.Ui.checkBox_auto_clean, CleanAction.AUTO_CLEAN),
    )
    # endregion

    # region website
    # 网站相关字段需要转换为枚举或列表
    website_single_text = self.Ui.comboBox_website_all.currentText()
    try:
        manager.config.website_single = Website(website_single_text)
    except ValueError:
        manager.config.website_single = Website.AIRAV_CC  # 默认值

    def get_sites(text: str) -> set[Website]:
        return {Website(site) for site in str_to_list(text, ",")}

    manager.config.website_youma = get_sites(self.Ui.lineEdit_website_youma.text())
    manager.config.website_wuma = get_sites(self.Ui.lineEdit_website_wuma.text())
    manager.config.website_suren = get_sites(self.Ui.lineEdit_website_suren.text())
    manager.config.website_fc2 = get_sites(self.Ui.lineEdit_website_fc2.text())
    manager.config.website_oumei = get_sites(self.Ui.lineEdit_website_oumei.text())
    manager.config.website_guochan = get_sites(self.Ui.lineEdit_website_guochan.text())

    manager.config.scrape_like = get_radio_buttons(
        (self.Ui.radioButton_scrape_speed, "speed"), (self.Ui.radioButton_scrape_info, "info"), default="single"
    )

    # 标题字段配置
    manager.config.set_field_sites(field_mapping["title"], self.Ui.lineEdit_title_website.text())
    title_language = get_radio_buttons(
        (self.Ui.radioButton_title_zh_cn, Language.ZH_CN),
        (self.Ui.radioButton_title_zh_tw, Language.ZH_TW),
        default=Language.JP,
    )
    manager.config.set_field_language(field_mapping["title"], title_language)
    manager.config.set_field_translate(field_mapping["title"], get_checkbox(self.Ui.checkBox_title_translate))
    # originaltitle
    manager.config.set_field_sites(CrawlerResultFields.ORIGINALTITLE, self.Ui.lineEdit_originaltitle_website.text())

    manager.config.title_sehua = get_checkbox(self.Ui.checkBox_title_sehua)
    manager.config.title_yesjav = get_checkbox(self.Ui.checkBox_title_yesjav)
    manager.config.title_sehua_zh = get_checkbox(self.Ui.checkBox_title_sehua_2)

    # 简介字段配置
    manager.config.set_field_sites(field_mapping["outline"], self.Ui.lineEdit_outline_website.text())
    outline_language = get_radio_buttons(
        (self.Ui.radioButton_outline_zh_cn, Language.ZH_CN),
        (self.Ui.radioButton_outline_zh_tw, Language.ZH_TW),
        default=Language.JP,
    )
    manager.config.set_field_language(field_mapping["outline"], outline_language)
    manager.config.set_field_translate(field_mapping["outline"], get_checkbox(self.Ui.checkBox_outline_translate))
    manager.config.outline_format = get_checkboxes(
        (self.Ui.checkBox_show_translate_from, OutlineShow.SHOW_FROM),
        (self.Ui.radioButton_trans_show_zh_jp, OutlineShow.SHOW_ZH_JP),
        (self.Ui.radioButton_trans_show_jp_zh, OutlineShow.SHOW_JP_ZH),
    )
    # originalplot
    manager.config.set_field_sites(CrawlerResultFields.ORIGINALPLOT, self.Ui.lineEdit_originalplot_website.text())

    # 演员字段配置
    manager.config.set_field_sites(field_mapping["actor"], self.Ui.lineEdit_actors_website.text())
    actor_language = get_radio_buttons(
        (self.Ui.radioButton_actor_zh_cn, Language.ZH_CN),
        (self.Ui.radioButton_actor_zh_tw, Language.ZH_TW),
        default=Language.JP,
    )
    manager.config.set_field_language(field_mapping["actor"], actor_language)
    manager.config.set_field_translate(field_mapping["actor"], get_checkbox(self.Ui.checkBox_actor_translate))
    manager.config.actor_realname = get_checkbox(self.Ui.checkBox_actor_realname)
    # all_actors
    manager.config.set_field_sites(CrawlerResultFields.ALL_ACTORS, self.Ui.lineEdit_all_actors_website.text())
    manager.config.set_field_language(CrawlerResultFields.ALL_ACTORS, actor_language)
    manager.config.set_field_translate(CrawlerResultFields.ALL_ACTORS, get_checkbox(self.Ui.checkBox_actor_translate))

    # 标签字段配置
    manager.config.set_field_sites(field_mapping["tag"], self.Ui.lineEdit_tags_website.text())
    tag_language = get_radio_buttons(
        (self.Ui.radioButton_tag_zh_cn, Language.ZH_CN),
        (self.Ui.radioButton_tag_zh_tw, Language.ZH_TW),
        default=Language.JP,
    )
    manager.config.set_field_language(field_mapping["tag"], tag_language)
    manager.config.set_field_translate(field_mapping["tag"], get_checkbox(self.Ui.checkBox_tag_translate))

    manager.config.nfo_tag_include = get_checkboxes(
        (self.Ui.checkBox_tag_actor, TagInclude.ACTOR),
        (self.Ui.checkBox_tag_letters, TagInclude.LETTERS),
        (self.Ui.checkBox_tag_series, TagInclude.SERIES),
        (self.Ui.checkBox_tag_studio, TagInclude.STUDIO),
        (self.Ui.checkBox_tag_publisher, TagInclude.PUBLISHER),
        (self.Ui.checkBox_tag_cnword, TagInclude.CNWORD),
        (self.Ui.checkBox_tag_mosaic, TagInclude.MOSAIC),
        (self.Ui.checkBox_tag_definition, TagInclude.DEFINITION),
    )

    # 系列字段配置
    manager.config.set_field_sites(field_mapping["series"], self.Ui.lineEdit_series_website.text())
    series_language = get_radio_buttons(
        (self.Ui.radioButton_series_zh_cn, Language.ZH_CN),
        (self.Ui.radioButton_series_zh_tw, Language.ZH_TW),
        default=Language.JP,
    )
    manager.config.set_field_language(field_mapping["series"], series_language)
    manager.config.set_field_translate(field_mapping["series"], get_checkbox(self.Ui.checkBox_series_translate))

    # 工作室字段配置
    manager.config.set_field_sites(field_mapping["studio"], self.Ui.lineEdit_studio_website.text())
    studio_language = get_radio_buttons(
        (self.Ui.radioButton_studio_zh_cn, Language.ZH_CN),
        (self.Ui.radioButton_studio_zh_tw, Language.ZH_TW),
        default=Language.JP,
    )
    manager.config.set_field_language(field_mapping["studio"], studio_language)
    manager.config.set_field_translate(field_mapping["studio"], get_checkbox(self.Ui.checkBox_studio_translate))

    # 发行商字段配置
    manager.config.set_field_sites(field_mapping["publisher"], self.Ui.lineEdit_publisher_website.text())
    publisher_language = get_radio_buttons(
        (self.Ui.radioButton_publisher_zh_cn, Language.ZH_CN),
        (self.Ui.radioButton_publisher_zh_tw, Language.ZH_TW),
        default=Language.JP,
    )
    manager.config.set_field_language(field_mapping["publisher"], publisher_language)
    manager.config.set_field_translate(field_mapping["publisher"], get_checkbox(self.Ui.checkBox_publisher_translate))

    # 导演字段配置
    manager.config.set_field_sites(field_mapping["director"], self.Ui.lineEdit_directors_website.text())
    director_language = get_radio_buttons(
        (self.Ui.radioButton_director_zh_cn, Language.ZH_CN),
        (self.Ui.radioButton_director_zh_tw, Language.ZH_TW),
        default=Language.JP,
    )
    manager.config.set_field_language(field_mapping["director"], director_language)
    manager.config.set_field_translate(field_mapping["director"], get_checkbox(self.Ui.checkBox_director_translate))

    # 其他图片和媒体字段配置
    manager.config.set_field_sites(field_mapping["poster"], self.Ui.lineEdit_poster_website.text())
    manager.config.set_field_sites(field_mapping["thumb"], self.Ui.lineEdit_thumb_website.text())
    manager.config.set_field_sites(field_mapping["extrafanart"], self.Ui.lineEdit_extrafanart_website.text())
    manager.config.set_field_sites(field_mapping["score"], self.Ui.lineEdit_score_website.text())
    manager.config.set_field_sites(field_mapping["release"], self.Ui.lineEdit_release_website.text())
    manager.config.set_field_sites(field_mapping["runtime"], self.Ui.lineEdit_runtime_website.text())
    manager.config.set_field_sites(field_mapping["trailer"], self.Ui.lineEdit_trailer_website.text())
    manager.config.set_field_sites(field_mapping["wanted"], self.Ui.lineEdit_wanted_website.text())
    manager.config.nfo_tagline = self.Ui.lineEdit_nfo_tagline.text()  # tagline格式
    manager.config.nfo_tag_series = self.Ui.lineEdit_nfo_tag_series.text()  # nfo_tag_series 格式
    manager.config.nfo_tag_studio = self.Ui.lineEdit_nfo_tag_studio.text()  # nfo_tag_studio 格式
    manager.config.nfo_tag_publisher = self.Ui.lineEdit_nfo_tag_publisher.text()  # nfo_tag_publisher 格式
    manager.config.nfo_tag_actor = self.Ui.lineEdit_nfo_tag_actor.text()  # nfo_tag_actor 格式
    nfo_tag_actor_contains_text = self.Ui.lineEdit_nfo_tag_actor_contains.text()
    manager.config.nfo_tag_actor_contains = str_to_list(nfo_tag_actor_contains_text, "|")

    # 注意：whole_fields 和 none_fields 已弃用，不再设置这些字段
    # 它们的功能已经通过新的字段配置API来实现

    # region nfo
    manager.config.nfo_include_new = get_checkboxes(
        (self.Ui.checkBox_nfo_sorttitle, NfoInclude.SORTTITLE),
        (self.Ui.checkBox_nfo_originaltitle, NfoInclude.ORIGINALTITLE),
        (self.Ui.checkBox_nfo_title_cd, NfoInclude.TITLE_CD),
        (self.Ui.checkBox_nfo_outline, NfoInclude.OUTLINE),
        (self.Ui.checkBox_nfo_plot, NfoInclude.PLOT_),
        (self.Ui.checkBox_nfo_originalplot, NfoInclude.ORIGINALPLOT),
        (self.Ui.checkBox_outline_cdata, NfoInclude.OUTLINE_NO_CDATA),
        (self.Ui.checkBox_nfo_release, NfoInclude.RELEASE_),
        (self.Ui.checkBox_nfo_relasedate, NfoInclude.RELEASEDATE),
        (self.Ui.checkBox_nfo_premiered, NfoInclude.PREMIERED),
        (self.Ui.checkBox_nfo_country, NfoInclude.COUNTRY),
        (self.Ui.checkBox_nfo_mpaa, NfoInclude.MPAA),
        (self.Ui.checkBox_nfo_customrating, NfoInclude.CUSTOMRATING),
        (self.Ui.checkBox_nfo_year, NfoInclude.YEAR),
        (self.Ui.checkBox_nfo_runtime, NfoInclude.RUNTIME),
        (self.Ui.checkBox_nfo_wanted, NfoInclude.WANTED),
        (self.Ui.checkBox_nfo_score, NfoInclude.SCORE),
        (self.Ui.checkBox_nfo_criticrating, NfoInclude.CRITICRATING),
        (self.Ui.checkBox_nfo_actor, NfoInclude.ACTOR),
        (self.Ui.checkBox_nfo_all_actor, NfoInclude.ACTOR_ALL),
        (self.Ui.checkBox_nfo_director, NfoInclude.DIRECTOR),
        (self.Ui.checkBox_nfo_series, NfoInclude.SERIES),
        (self.Ui.checkBox_nfo_tag, NfoInclude.TAG),
        (self.Ui.checkBox_nfo_genre, NfoInclude.GENRE),
        (self.Ui.checkBox_nfo_actor_set, NfoInclude.ACTOR_SET),
        (self.Ui.checkBox_nfo_set, NfoInclude.SERIES_SET),
        (self.Ui.checkBox_nfo_studio, NfoInclude.STUDIO),
        (self.Ui.checkBox_nfo_maker, NfoInclude.MAKER),
        (self.Ui.checkBox_nfo_publisher, NfoInclude.PUBLISHER),
        (self.Ui.checkBox_nfo_label, NfoInclude.LABEL),
        (self.Ui.checkBox_nfo_poster, NfoInclude.POSTER),
        (self.Ui.checkBox_nfo_cover, NfoInclude.COVER),
        (self.Ui.checkBox_nfo_trailer, NfoInclude.TRAILER),
        (self.Ui.checkBox_nfo_website, NfoInclude.WEBSITE),
    )
    # endregion
    manager.config.translate_config.translate_by = get_checkboxes(
        (self.Ui.checkBox_google, Translator.GOOGLE),
        (self.Ui.checkBox_baidu, Translator.BAIDU),
        (self.Ui.checkBox_deepl, Translator.DEEPL),
        (self.Ui.checkBox_deeplx, Translator.DEEPLX),
        (self.Ui.checkBox_llm, Translator.LLM),
    )
    manager.config.translate_config.baidu_appid = self.Ui.lineEdit_baidu_appid.text()
    manager.config.translate_config.baidu_key = self.Ui.lineEdit_baidu_key.text()
    manager.config.translate_config.deepl_key = self.Ui.lineEdit_deepl_key.text().strip()  # deepl api key
    manager.config.translate_config.deeplx_url = self.Ui.lineEdit_deeplx_url.text().strip()  # deeplx url

    llm_url_text = self.Ui.lineEdit_llm_url.text()
    if llm_url_text:
        manager.config.translate_config.llm_url = HttpUrl(llm_url_text)
    manager.config.translate_config.llm_model = self.Ui.lineEdit_llm_model.text()
    manager.config.translate_config.llm_key = self.Ui.lineEdit_llm_key.text()
    manager.config.translate_config.llm_prompt_title = self.Ui.textEdit_llm_prompt_title.toPlainText()
    manager.config.translate_config.llm_prompt_outline = self.Ui.textEdit_llm_prompt_outline.toPlainText()
    manager.config.translate_config.llm_max_req_sec = self.Ui.doubleSpinBox_llm_max_req_sec.value()
    manager.config.translate_config.llm_max_try = self.Ui.spinBox_llm_max_try.value()
    manager.config.translate_config.llm_temperature = self.Ui.doubleSpinBox_llm_temperature.value()
    # endregion

    # region common
    manager.config.thread_number = self.Ui.horizontalSlider_thread.value()  # 线程数量
    manager.config.thread_time = self.Ui.horizontalSlider_thread_time.value()  # 线程延时
    manager.config.javdb_time = self.Ui.horizontalSlider_javdb_time.value()  # javdb 延时
    # 主模式设置
    manager.config.main_mode = get_radio_buttons(
        (self.Ui.radioButton_mode_common, 1),
        (self.Ui.radioButton_mode_sort, 2),
        (self.Ui.radioButton_mode_update, 3),
        (self.Ui.radioButton_mode_read, 4),
        default=1,
    )

    manager.config.read_mode = get_checkboxes(
        (self.Ui.checkBox_read_has_nfo_update, ReadMode.HAS_NFO_UPDATE),
        (self.Ui.checkBox_read_no_nfo_scrape, ReadMode.NO_NFO_SCRAPE),
        (self.Ui.checkBox_read_download_file_again, ReadMode.READ_DOWNLOAD_AGAIN),
        (self.Ui.checkBox_read_update_nfo, ReadMode.READ_UPDATE_NFO),
    )
    # update 模式设置
    if self.Ui.radioButton_update_c.isChecked():
        manager.config.update_mode = "c"
    elif self.Ui.radioButton_update_b_c.isChecked():
        manager.config.update_mode = "abc" if self.Ui.checkBox_update_a.isChecked() else "bc"
    elif self.Ui.radioButton_update_d_c.isChecked():
        manager.config.update_mode = "d"
    else:
        manager.config.update_mode = "c"
    manager.config.update_a_folder = self.Ui.lineEdit_update_a_folder.text()  # 更新模式 - a 目录
    manager.config.update_b_folder = self.Ui.lineEdit_update_b_folder.text()  # 更新模式 - b 目录
    manager.config.update_c_filetemplate = self.Ui.lineEdit_update_c_filetemplate.text()  # 更新模式 - c 文件命名规则
    manager.config.update_d_folder = self.Ui.lineEdit_update_d_folder.text()  # 更新模式 - d 目录
    manager.config.update_titletemplate = self.Ui.lineEdit_update_titletemplate.text()  # 更新模式 - emby视频标题
    # 链接模式设置
    if self.Ui.radioButton_soft_on.isChecked():  # 软链接开
        manager.config.soft_link = 1
    elif self.Ui.radioButton_hard_on.isChecked():  # 硬链接开
        manager.config.soft_link = 2
    else:  # 软链接关
        manager.config.soft_link = 0

    # 文件操作设置
    manager.config.success_file_move = self.Ui.radioButton_succ_move_on.isChecked()
    manager.config.failed_file_move = self.Ui.radioButton_fail_move_on.isChecked()
    manager.config.success_file_rename = self.Ui.radioButton_succ_rename_on.isChecked()
    manager.config.del_empty_folder = self.Ui.radioButton_del_empty_folder_on.isChecked()
    manager.config.show_poster = self.Ui.checkBox_cover.isChecked()
    # endregion

    # region download
    manager.config.download_files = get_checkboxes(
        (self.Ui.checkBox_download_poster, DownloadableFile.POSTER),
        (self.Ui.checkBox_download_thumb, DownloadableFile.THUMB),
        (self.Ui.checkBox_download_fanart, DownloadableFile.FANART),
        (self.Ui.checkBox_download_extrafanart, DownloadableFile.EXTRAFANART),
        (self.Ui.checkBox_download_trailer, DownloadableFile.TRAILER),
        (self.Ui.checkBox_download_nfo, DownloadableFile.NFO),
        (self.Ui.checkBox_extras, DownloadableFile.EXTRAFANART_EXTRAS),
        (self.Ui.checkBox_download_extrafanart_copy, DownloadableFile.EXTRAFANART_COPY),
        (self.Ui.checkBox_theme_videos, DownloadableFile.THEME_VIDEOS),
        (self.Ui.checkBox_ignore_pic_fail, DownloadableFile.IGNORE_PIC_FAIL),
        (self.Ui.checkBox_ignore_youma, DownloadableFile.IGNORE_YOUMA),
        (self.Ui.checkBox_youma_use_poster, DownloadableFile.YOUMA_USE_POSTER),
        (self.Ui.checkBox_ignore_wuma, DownloadableFile.IGNORE_WUMA),
        (self.Ui.checkBox_ignore_fc2, DownloadableFile.IGNORE_FC2),
        (self.Ui.checkBox_ignore_guochan, DownloadableFile.IGNORE_GUOCHAN),
        (self.Ui.checkBox_ignore_size, DownloadableFile.IGNORE_SIZE),
    )

    manager.config.keep_files = get_checkboxes(
        (self.Ui.checkBox_old_poster, KeepableFile.POSTER),
        (self.Ui.checkBox_old_thumb, KeepableFile.THUMB),
        (self.Ui.checkBox_old_fanart, KeepableFile.FANART),
        (self.Ui.checkBox_old_extrafanart, KeepableFile.EXTRAFANART),
        (self.Ui.checkBox_old_trailer, KeepableFile.TRAILER),
        (self.Ui.checkBox_old_nfo, KeepableFile.NFO),
        (self.Ui.checkBox_old_extrafanart_copy, KeepableFile.EXTRAFANART_COPY),
        (self.Ui.checkBox_old_theme_videos, KeepableFile.THEME_VIDEOS),
    )

    manager.config.download_hd_pics = get_checkboxes(
        (self.Ui.checkBox_hd_poster, HDPicSource.POSTER),
        (self.Ui.checkBox_hd_thumb, HDPicSource.THUMB),
        (self.Ui.checkBox_amazon_big_pic, HDPicSource.AMAZON),
        (self.Ui.checkBox_official_big_pic, HDPicSource.OFFICIAL),
        (self.Ui.checkBox_google_big_pic, HDPicSource.GOOGLE),
        (self.Ui.radioButton_google_only, HDPicSource.GOO_ONLY),
    )

    google_used_text = self.Ui.lineEdit_google_used.text()
    manager.config.google_used = str_to_list(google_used_text)
    google_exclude_text = self.Ui.lineEdit_google_exclude.text()
    manager.config.google_exclude = str_to_list(google_exclude_text)
    # endregion

    # region name
    manager.config.folder_name = self.Ui.lineEdit_dir_name.text()  # 视频文件夹命名
    manager.config.naming_file = self.Ui.lineEdit_local_name.text()  # 视频文件名命名
    manager.config.naming_media = self.Ui.lineEdit_media_name.text()  # nfo标题命名
    manager.config.prevent_char = self.Ui.lineEdit_prevent_char.text()  # 防屏蔽字符

    manager.config.fields_rule = get_checkboxes(
        (self.Ui.checkBox_title_del_actor, FieldRule.DEL_ACTOR),
        (self.Ui.checkBox_actor_del_char, FieldRule.DEL_CHAR),
        (self.Ui.checkBox_actor_fc2_seller, FieldRule.FC2_SELLER),
        (self.Ui.checkBox_number_del_num, FieldRule.DEL_NUM),
    )

    suffix_sort_text = self.Ui.lineEdit_suffix_sort.text()
    suffix_sort_list = []
    for item in str_to_list(suffix_sort_text):
        if item == "moword":
            suffix_sort_list.append(SuffixSort.MOWORD)
        elif item == "cnword":
            suffix_sort_list.append(SuffixSort.CNWORD)
        elif item == "definition":
            suffix_sort_list.append(SuffixSort.DEFINITION)
    manager.config.suffix_sort = suffix_sort_list

    manager.config.actor_no_name = self.Ui.lineEdit_actor_no_name.text()  # 未知演员
    manager.config.actor_name_more = self.Ui.lineEdit_actor_name_more.text()  # 等演员
    release_rule = self.Ui.lineEdit_release_rule.text()  # 发行日期
    manager.config.release_rule = re.sub(r'[\\/:*?"<>|\r\n]+', "-", release_rule).strip()

    manager.config.folder_name_max = int(self.Ui.lineEdit_folder_name_max.text())  # 长度命名规则-目录
    manager.config.file_name_max = int(self.Ui.lineEdit_file_name_max.text())  # 长度命名规则-文件名
    manager.config.actor_name_max = int(self.Ui.lineEdit_actor_name_max.text())  # 长度命名规则-演员数量

    manager.config.umr_style = self.Ui.lineEdit_umr_style.text()  # 无码破解版本命名
    manager.config.leak_style = self.Ui.lineEdit_leak_style.text()  # 无码流出版本命名
    manager.config.wuma_style = self.Ui.lineEdit_wuma_style.text()  # 无码版本命名
    manager.config.youma_style = self.Ui.lineEdit_youma_style.text()  # 有码版本命名

    # 分集命名规则
    manager.config.cd_name = get_radio_buttons(
        (self.Ui.radioButton_cd_part_lower, 0),
        (self.Ui.radioButton_cd_part_upper, 1),
        default=2,
    )

    manager.config.cd_char = get_checkboxes(
        (self.Ui.checkBox_cd_part_a, CDChar.LETTER),
        (self.Ui.checkBox_cd_part_c, CDChar.ENDC),
        (self.Ui.checkBox_cd_part_01, CDChar.DIGITAL),
        (self.Ui.checkBox_cd_part_1_xxx, CDChar.MIDDLE_NUMBER),
        (self.Ui.checkBox_cd_part_underline, CDChar.UNDERLINE),
        (self.Ui.checkBox_cd_part_space, CDChar.SPACE),
        (self.Ui.checkBox_cd_part_point, CDChar.POINT),
    )

    # 图片和预告片命名规则
    manager.config.pic_simple_name = not self.Ui.radioButton_pic_with_filename.isChecked()
    manager.config.trailer_simple_name = not self.Ui.radioButton_trailer_with_filename.isChecked()
    manager.config.hd_name = "height" if self.Ui.radioButton_definition_height.isChecked() else "hd"

    # 分辨率获取方式
    manager.config.hd_get = get_radio_buttons(
        (self.Ui.radioButton_videosize_video, "video"),
        (self.Ui.radioButton_videosize_path, "path"),
        default="none",
    )
    manager.config.folder_moword = get_checkbox(self.Ui.checkBox_foldername_mosaic)
    manager.config.file_moword = get_checkbox(self.Ui.checkBox_filename_mosaic)
    manager.config.folder_hd = get_checkbox(self.Ui.checkBox_foldername_4k)
    manager.config.file_hd = get_checkbox(self.Ui.checkBox_filename_4k)
    # endregion

    # region subtitle
    cnword_char_text = self.Ui.lineEdit_cnword_char.text()
    manager.config.cnword_char = str_to_list(cnword_char_text)
    manager.config.cnword_style = self.Ui.lineEdit_cnword_style.text()  # 中文字幕字符样式
    manager.config.folder_cnword = get_checkbox(self.Ui.checkBox_foldername)
    manager.config.file_cnword = get_checkbox(self.Ui.checkBox_filename)
    manager.config.subtitle_folder = self.Ui.lineEdit_sub_folder.text()  # 字幕文件目录
    manager.config.subtitle_add = get_checkbox(self.Ui.radioButton_add_sub_on)
    manager.config.subtitle_add_chs = get_checkbox(self.Ui.checkBox_sub_add_chs)
    manager.config.subtitle_add_rescrape = get_checkbox(self.Ui.checkBox_sub_rescrape)
    # endregion

    # region emby
    manager.config.server_type = "emby" if self.Ui.radioButton_server_emby.isChecked() else "jellyfin"
    emby_url = self.Ui.lineEdit_emby_url.text()  # emby地址
    emby_url = emby_url.replace("：", ":").strip("/ ")
    if emby_url and "://" not in emby_url:
        emby_url = "http://" + emby_url
    if emby_url:
        manager.config.emby_url = HttpUrl(emby_url)
    manager.config.api_key = self.Ui.lineEdit_api_key.text()  # emby密钥
    manager.config.user_id = self.Ui.lineEdit_user_id.text()  # emby用户ID
    manager.config.actor_photo_folder = self.Ui.lineEdit_actor_photo_folder.text()  # 头像图片目录
    gfriends_github = self.Ui.lineEdit_net_actor_photo.text().strip(" /")  # gfriends github 项目地址
    if not gfriends_github:
        gfriends_github = "https://github.com/gfriends/gfriends"
    elif "://" not in gfriends_github:
        gfriends_github = "https://" + gfriends_github
    manager.config.gfriends_github = HttpUrl(gfriends_github)
    manager.config.info_database_path = self.Ui.lineEdit_actor_db_path.text()  # 信息数据库
    manager.config.use_database = self.Ui.checkBox_actor_db.isChecked()
    if manager.config.use_database:
        ActressDB.init_db()

    # 构建 emby_on 配置
    actor_info_lang = get_radio_buttons(
        (self.Ui.radioButton_actor_info_zh_cn, EmbyAction.ACTOR_INFO_ZH_CN),
        (self.Ui.radioButton_actor_info_zh_tw, EmbyAction.ACTOR_INFO_ZH_TW),
        default=EmbyAction.ACTOR_INFO_JA,
    )
    actor_info_mode = get_radio_buttons(
        (self.Ui.radioButton_actor_info_all, EmbyAction.ACTOR_INFO_ALL), default=EmbyAction.ACTOR_INFO_MISS
    )
    actor_photo_source = get_radio_buttons(
        (self.Ui.radioButton_actor_photo_net, EmbyAction.ACTOR_PHOTO_NET), default=EmbyAction.ACTOR_PHOTO_LOCAL
    )
    actor_photo_mode = get_radio_buttons(
        (self.Ui.radioButton_actor_photo_all, EmbyAction.ACTOR_PHOTO_ALL), default=EmbyAction.ACTOR_PHOTO_MISS
    )
    emby_actions = [actor_info_lang, actor_info_mode, actor_photo_source, actor_photo_mode]

    # 添加其他emby选项
    emby_actions.extend(
        get_checkboxes(
            (self.Ui.checkBox_actor_info_translate, EmbyAction.ACTOR_INFO_TRANSLATE),
            (self.Ui.checkBox_actor_info_photo, EmbyAction.ACTOR_INFO_PHOTO),
            (self.Ui.checkBox_actor_photo_ne_backdrop, EmbyAction.GRAPHIS_BACKDROP),
            (self.Ui.checkBox_actor_photo_ne_face, EmbyAction.GRAPHIS_FACE),
            (self.Ui.checkBox_actor_photo_ne_new, EmbyAction.GRAPHIS_NEW),
            (self.Ui.checkBox_actor_photo_auto, EmbyAction.ACTOR_PHOTO_AUTO),
            (self.Ui.checkBox_actor_pic_replace, EmbyAction.ACTOR_REPLACE),
        )
    )

    manager.config.emby_on = emby_actions
    manager.config.actor_photo_kodi_auto = get_checkbox(self.Ui.checkBox_actor_photo_kodi)
    # endregion

    # region mark
    manager.config.poster_mark = 1 if self.Ui.checkBox_poster_mark.isChecked() else 0
    manager.config.thumb_mark = 1 if self.Ui.checkBox_thumb_mark.isChecked() else 0
    manager.config.fanart_mark = 1 if self.Ui.checkBox_fanart_mark.isChecked() else 0
    manager.config.mark_size = self.Ui.horizontalSlider_mark_size.value()  # 水印大小

    manager.config.mark_type = get_checkboxes(
        (self.Ui.checkBox_sub, MarkType.SUB),
        (self.Ui.checkBox_censored, MarkType.YOUMA),
        (self.Ui.checkBox_umr, MarkType.UMR),
        (self.Ui.checkBox_leak, MarkType.LEAK),
        (self.Ui.checkBox_uncensored, MarkType.UNCENSORED),
        (self.Ui.checkBox_hd, MarkType.HD),
    )

    # 水印位置设置
    manager.config.mark_fixed = get_radio_buttons(
        (self.Ui.radioButton_not_fixed_position, "not_fixed"),
        (self.Ui.radioButton_fixed_corner, "corner"),
        default="fixed",
    )
    manager.config.mark_pos = get_radio_buttons(
        (self.Ui.radioButton_top_left, "top_left"),
        (self.Ui.radioButton_top_right, "top_right"),
        (self.Ui.radioButton_bottom_left, "bottom_left"),
        (self.Ui.radioButton_bottom_right, "bottom_right"),
        default="top_left",
    )
    manager.config.mark_pos_corner = get_radio_buttons(
        (self.Ui.radioButton_top_left_corner, "top_left"),
        (self.Ui.radioButton_top_right_corner, "top_right"),
        (self.Ui.radioButton_bottom_left_corner, "bottom_left"),
        (self.Ui.radioButton_bottom_right_corner, "bottom_right"),
        default="top_left",
    )
    manager.config.mark_pos_hd = get_radio_buttons(
        (self.Ui.radioButton_top_left_hd, "top_left"),
        (self.Ui.radioButton_top_right_hd, "top_right"),
        (self.Ui.radioButton_bottom_left_hd, "bottom_left"),
        (self.Ui.radioButton_bottom_right_hd, "bottom_right"),
        default="top_left",
    )
    manager.config.mark_pos_sub = get_radio_buttons(
        (self.Ui.radioButton_top_left_sub, "top_left"),
        (self.Ui.radioButton_top_right_sub, "top_right"),
        (self.Ui.radioButton_bottom_left_sub, "bottom_left"),
        (self.Ui.radioButton_bottom_right_sub, "bottom_right"),
        default="top_left",
    )
    manager.config.mark_pos_mosaic = get_radio_buttons(
        (self.Ui.radioButton_top_left_mosaic, "top_left"),
        (self.Ui.radioButton_top_right_mosaic, "top_right"),
        (self.Ui.radioButton_bottom_left_mosaic, "bottom_left"),
        (self.Ui.radioButton_bottom_right_mosaic, "bottom_right"),
        default="top_left",
    )
    # endregion

    # region network
    manager.config.use_proxy = self.Ui.checkBox_use_proxy.isChecked()
    proxy = self.Ui.lineEdit_proxy.text()  # 代理地址
    manager.config.proxy = proxy
    manager.config.cf_bypass_url = self.Ui.lineEdit_cf_bypass_url.text().strip()  # Cloudflare bypass 地址
    manager.config.cf_bypass_proxy = self.Ui.lineEdit_cf_bypass_proxy.text().strip()  # Cloudflare bypass 独立代理
    manager.config.timeout = self.Ui.horizontalSlider_timeout.value()  # 超时时间
    manager.config.retry = self.Ui.horizontalSlider_retry.value()  # 重试次数

    site = self.Ui.comboBox_custom_website.currentText()
    if site in Website:
        site = Website(site)
        url = self.Ui.lineEdit_site_custom_url.text().strip("/ ")
        if url:
            with suppress(ValidationError):
                manager.config.site_configs.setdefault(site, SiteConfig()).custom_url = HttpUrl(url)
        elif site in manager.config.site_configs:
            manager.config.site_configs[site].custom_url = None

    manager.config.javdb = self.Ui.plainTextEdit_cookie_javdb.toPlainText()  # javdb cookie
    manager.config.fc2ppvdb = self.Ui.plainTextEdit_cookie_fc2ppvdb.toPlainText()  # fc2ppvdb cookie
    manager.config.javbus = self.Ui.plainTextEdit_cookie_javbus.toPlainText()  # javbus cookie
    manager.config.theporndb_api_token = self.Ui.lineEdit_api_token_theporndb.text()  # api token
    if manager.config.javdb:
        manager.config.javdb = manager.config.javdb.replace("locale=en", "locale=zh")
    # endregion

    # region other
    manager.config.rest_count = int(self.Ui.lineEdit_rest_count.text())  # 间歇刮削文件数量

    rest_time_text = self.Ui.lineEdit_rest_time.text()  # 格式: HH:MM:SS
    if re.match(r"^\d{2}:\d{2}:\d{2}$", rest_time_text):
        h, m, s = map(int, rest_time_text.split(":"))
        manager.config.rest_time = timedelta(hours=h, minutes=m, seconds=s)
    else:
        manager.config.rest_time = timedelta(minutes=1, seconds=2)  # 默认值

    timed_interval_text = self.Ui.lineEdit_timed_interval.text()  # 格式: HH:MM:SS
    if re.match(r"^\d{2}:\d{2}:\d{2}$", timed_interval_text):
        h, m, s = map(int, timed_interval_text.split(":"))
        manager.config.timed_interval = timedelta(hours=h, minutes=m, seconds=s)
    else:
        manager.config.timed_interval = timedelta(minutes=30)  # 默认值

    # 开关汇总和其他设置
    show_logs_value = not self.Ui.textBrowser_log_main_2.isHidden()
    switch_actions = get_checkboxes(
        (self.Ui.checkBox_auto_start, Switch.AUTO_START),
        (self.Ui.checkBox_auto_exit, Switch.AUTO_EXIT),
        (self.Ui.checkBox_rest_scrape, Switch.REST_SCRAPE),
        (self.Ui.checkBox_timed_scrape, Switch.TIMED_SCRAPE),
        (self.Ui.checkBox_remain_task, Switch.REMAIN_TASK),
        (self.Ui.checkBox_show_dialog_exit, Switch.SHOW_DIALOG_EXIT),
        (self.Ui.checkBox_show_dialog_stop_scrape, Switch.SHOW_DIALOG_STOP_SCRAPE),
        (self.Ui.checkBox_sortmode_delpic, Switch.SORT_DEL),
        (self.Ui.checkBox_dialog_qt, Switch.QT_DIALOG),
        (self.Ui.checkBox_theporndb_hash, Switch.THEPORNDB_NO_HASH),
        (self.Ui.checkBox_hide_dock_icon, Switch.HIDE_DOCK),
        (self.Ui.checkBox_highdpi_passthrough, Switch.PASSTHROUGH),
        (self.Ui.checkBox_hide_menu_icon, Switch.HIDE_MENU),
        (self.Ui.checkBox_dark_mode, Switch.DARK_MODE),
        (self.Ui.checkBox_copy_netdisk_nfo, Switch.COPY_NETDISK_NFO),
    )

    # 手动添加 show_logs 设置
    if show_logs_value:
        switch_actions.append(Switch.SHOW_LOGS)

    # 添加隐藏设置
    switch_actions.append(
        get_radio_buttons(
            (self.Ui.radioButton_hide_close, Switch.HIDE_CLOSE),
            (self.Ui.radioButton_hide_mini, Switch.HIDE_MINI),
            default=Switch.HIDE_NONE,
        )
    )

    manager.config.switch_on = switch_actions

    # 日志设置
    manager.config.show_web_log = get_checkbox(self.Ui.checkBox_show_web_log)
    manager.config.show_from_log = get_checkbox(self.Ui.checkBox_show_from_log)
    manager.config.show_data_log = get_checkbox(self.Ui.checkBox_show_data_log)
    manager.config.save_log = get_radio_buttons(
        (self.Ui.radioButton_log_on, True),
        (self.Ui.radioButton_log_off, False),
        default=True,
    )
    manager.config.update_check = get_radio_buttons(
        (self.Ui.radioButton_update_on, True),
        (self.Ui.radioButton_update_off, False),
        default=True,
    )
    manager.config.local_library = str_to_list(self.Ui.lineEdit_local_library_path.text())  # 本地资源库
    manager.config.actors_name = self.Ui.lineEdit_actors_name.text().replace("\n", "")  # 演员名
    manager.config.netdisk_path = self.Ui.lineEdit_netdisk_path.text()  # 网盘路径
    manager.config.localdisk_path = self.Ui.lineEdit_localdisk_path.text()  # 本地磁盘路径
    manager.config.window_title = "hide" if self.Ui.checkBox_hide_window_title.isChecked() else "show"
    # endregion
    manager.config.auto_link = get_checkbox(self.Ui.checkBox_create_link)  # 刮削中自动创建软链接

    # 保存
    manager.save()

    # 根据配置更新界面显示
    scrape_like = manager.config.scrape_like
    if "speed" == scrape_like:
        Flags.scrape_like_text = "速度优先"
    elif "single" == scrape_like:
        Flags.scrape_like_text = "指定网站"
    else:
        Flags.scrape_like_text = "字段优先"

    main_mode = int(manager.config.main_mode)  # 刮削模式
    mode_mapping = {
        1: ("common", "正常模式"),
        2: ("sort", "整理模式"),
        3: ("update", "更新模式"),
        4: ("read", "读取模式"),
    }

    mode_key, mode_text = mode_mapping.get(main_mode, ("common", "正常模式"))
    Flags.main_mode_text = mode_text

    try:
        scrape_like_text = Flags.scrape_like_text
        if manager.config.scrape_like == "single":
            scrape_like_text += f" · {manager.config.website_single.value}"
        if manager.config.soft_link == 1:
            scrape_like_text += " · 软连接开"
        elif manager.config.soft_link == 2:
            scrape_like_text += " · 硬连接开"
        signal_qt.show_log_text(
            f" 🛠 当前配置：{manager.path} 保存完成！\n "
            f"📂 程序目录：{manager.data_folder} \n "
            f"📂 刮削目录：{get_movie_path_setting().movie_path} \n "
            f"💠 刮削模式：{Flags.main_mode_text} · {scrape_like_text} \n "
            f"🖥️ 系统信息：{platform.platform()} \n "
            f"🐰 软件版本：{self.localversion} \n"
        )
    except Exception:
        signal_qt.show_traceback_log(traceback.format_exc())
    try:
        self._windows_auto_adjust()  # 界面自动调整
    except Exception:
        signal_qt.show_traceback_log(traceback.format_exc())
    self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)  # type: ignore
    self.activateWindow()
    try:
        self.set_label_file_path.emit(
            f"🎈 当前刮削路径: \n {get_movie_path_setting().movie_path}"
        )  # 主界面右上角显示提示信息
    except Exception:
        signal_qt.show_traceback_log(traceback.format_exc())
