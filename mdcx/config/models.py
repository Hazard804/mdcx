import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from pydantic.fields import FieldInfo

from ..gen.field_enums import CrawlerResultFields
from ..manual import ManualConfig
from .enums import (
    CDChar,
    CleanAction,
    DownloadableFile,
    EmbyAction,
    FieldRule,
    FixedScrapingType,
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
from .migrations import migrate_config_data


def str_to_list(v: str | list[Any] | None, sep: Literal[",", "|"] = ",", unique: bool = True) -> list[str]:
    """
    将字符串转换为列表.
    支持全/半角逗号或竖线作为分隔符, 将去除每项首尾的空白符, 去空, 去重.
    """
    if v is None:
        return []
    if isinstance(v, list):
        return [str(item) for item in v]
    if isinstance(v, str):
        if sep == ",":
            v = v.replace("，", ",")
        elif sep == "|":
            v = v.replace("｜", "|")
        if unique:
            return list(dict.fromkeys([item.strip() for item in v.strip(sep).split(sep) if item.strip()]))
        return [item.strip() for item in v.strip(sep).split(sep) if item.strip()]
    return []


class TranslateConfig(BaseModel):
    translate_by: list[Translator] = Field(
        default_factory=lambda: [
            Translator.GOOGLE,
            Translator.BAIDU,
            Translator.DEEPL,
            Translator.DEEPLX,
            Translator.LLM,
        ],
        title="翻译服务",
    )
    baidu_appid: str = Field(default="", title="百度 APP ID")
    baidu_key: str = Field(default="", title="百度密钥")
    deepl_key: str = Field(default="", title="DeepL API Key")
    deeplx_url: str = Field(default="", title="DeepLX URL")
    llm_url: HttpUrl = Field(default=HttpUrl("https://api.llm.com/v1"), title="LLM API Host")
    llm_model: str = Field(default="gpt-3.5-turbo", title="模型 ID")
    llm_key: str = Field(default="", title="LLM API Key")
    llm_prompt_title: str = Field(
        default="Please translate the following text to {lang}. Output only the translation without any explanation.\n{content}",
        title="LLM 标题提示词",
    )
    llm_prompt_outline: str = Field(
        default="Please translate the following text to {lang}. Output only the translation without any explanation.\n{content}",
        title="LLM 简介提示词",
    )
    llm_read_timeout: int = Field(default=60, title="LLM 读取超时 (秒)", description="LLM 生成耗时较长, 建议设置较大值")
    llm_max_req_sec: float = Field(default=1, title="LLM 每秒最大请求数")
    llm_max_try: int = Field(default=5, title="LLM 最大尝试次数")
    llm_temperature: float = Field(default=0.2, title="LLM 温度")

    def model_post_init(self, context) -> None:
        if self.llm_max_req_sec <= 0:
            self.llm_max_req_sec = 1


class SiteConfig(BaseModel):
    custom_url: HttpUrl | None = Field(default=None, title="自定义网址")


class FieldConfig(BaseModel):
    site_prority: list[Website] = Field(default_factory=list, title="来源网站优先级")
    language: Language = Field(default=Language.UNDEFINED, title="语言偏好")
    translate: bool = Field(
        default=True,
        title="翻译此字段",
        description="若启用则使用首个来源的数据并翻译为指定语言; 否则使用第一个指定语言的数据, 如果所有来源都没有指定语言数据则视为失败.",
    )


class FieldPriorityConfig(BaseModel):
    site_prority: list[Website] = Field(default_factory=list, title="来源网站优先级")


CONFIGURABLE_SCRAPING_TYPES = (
    FixedScrapingType.YOUMA,
    FixedScrapingType.WUMA,
    FixedScrapingType.SUREN,
    FixedScrapingType.FC2,
    FixedScrapingType.OUMEI,
    FixedScrapingType.GUOCHAN,
)

SCRAPING_TYPE_SITE_FIELDS = {
    FixedScrapingType.YOUMA: "website_youma",
    FixedScrapingType.WUMA: "website_wuma",
    FixedScrapingType.SUREN: "website_suren",
    FixedScrapingType.FC2: "website_fc2",
    FixedScrapingType.OUMEI: "website_oumei",
    FixedScrapingType.GUOCHAN: "website_guochan",
}

DEFAULT_FIELD_SITE_PRIORITY = [
    Website.THEPORNDB,
    Website.DMM,
    Website.OFFICIAL,
    Website.MGSTAGE,
    Website.PRESTIGE,
    Website.AVBASE,
    Website.JAV321,
    Website.MMTV,
    Website.JAVDB,
    Website.JAVBUS,
    Website.IQQTV,
    Website.FREEJAVBT,
    Website.MISSAV,
    Website.AVSOX,
    Website.FC2HUB,
    Website.FC2,
    Website.FC2PPVDB,
]


def default_field_config(language: Language = Language.UNDEFINED, translate: bool = True) -> FieldConfig:
    return FieldConfig(site_prority=list(DEFAULT_FIELD_SITE_PRIORITY), language=language, translate=translate)


class Config(BaseModel):
    model_config = ConfigDict()
    # region: General Settings
    config_version: int = Field(default=2, title="配置版本")
    media_path: str = Field(default="./media", title="媒体路径")
    softlink_path: str = Field(default="softlink", title="软链接路径")
    success_output_folder: str = Field(default="JAV_output", title="成功输出目录")
    failed_output_folder: str = Field(default="failed", title="失败输出目录")
    extrafanart_folder: str = Field(default="extrafanart_copy", title="额外剧照目录")
    media_type: list[str] = Field(
        default_factory=lambda: [
            ".mp4",
            ".avi",
            ".rmvb",
            ".wmv",
            ".mov",
            ".mkv",
            ".flv",
            ".ts",
            ".webm",
            ".iso",
            ".mpg",
        ],
        title="媒体类型",
    )
    sub_type: list[str] = Field(
        default_factory=lambda: [
            ".smi",
            ".srt",
            ".idx",
            ".sub",
            ".sup",
            ".psb",
            ".ssa",
            ".ass",
            ".usf",
            ".xss",
            ".ssf",
            ".rt",
            ".lrc",
            ".sbv",
            ".vtt",
            ".ttml",
        ],
        title="字幕类型",
    )
    scrape_softlink_path: bool = Field(default=False, title="刮削软链接路径")
    auto_link: bool = Field(default=False, title="自动创建软链接")
    # endregion

    # region: Cleaning Settings
    folders: list[str] = Field(default_factory=lambda: ["JAV_output", "examples"], title="排除的目录")
    string: list[str] = Field(
        default_factory=lambda: [
            "h_720",
            "2048论坛@fun2048.com",
            "1080p",
            "720p",
            "22-sht.me",
            "-HD",
            "bbs2048.org@",
            "hhd800.com@",
            "icao.me@",
            "hhb_000",
            "[456k.me]",
            "[ThZu.Cc]",
        ],
        title="要从文件名中删除的字符串",
    )
    file_size: float = Field(default=100.0, title="要处理的最小文件大小（MB）")
    no_escape: list[NoEscape] = Field(
        default_factory=lambda: [NoEscape.RECORD_SUCCESS_FILE],
        title="不转义的字符串",
    )
    clean_ext: list[str] = Field(
        default_factory=lambda: [".html", ".url"],
        title="清理规则: 扩展名",
    )
    clean_name: list[str] = Field(
        default_factory=lambda: ["uur76.mp4", "uur93.com.mp4"],
        title="清理规则: 文件名(完全匹配)",
    )
    clean_contains: list[str] = Field(
        default_factory=lambda: [
            "直播盒子",
            "最新情报",
            "最新位址",
            "注册免费送",
            "房间火爆",
            "美女荷官",
            "妹妹直播",
            "精彩直播",
        ],
        title="清理规则: 文件名包含",
    )
    clean_size: float = Field(default=0.0, title="清理小于此大小的文件（KB）")
    clean_ignore_ext: list[str] = Field(
        default_factory=list,
        title="清理规则: 排除扩展名",
    )
    clean_ignore_contains: list[str] = Field(
        default_factory=lambda: ["skip", "ignore"],
        title="清理规则: 排除文件名包含",
    )
    clean_enable: list[CleanAction] = Field(
        default_factory=lambda: [
            CleanAction.CLEAN_EXT,
            CleanAction.CLEAN_NAME,
            CleanAction.CLEAN_CONTAINS,
            CleanAction.CLEAN_SIZE,
            CleanAction.CLEAN_IGNORE_EXT,
            CleanAction.CLEAN_IGNORE_CONTAINS,
        ],
        title="启用的清理规则",
    )
    # endregion

    # region: Scraping Settings
    thread_number: int = Field(default=50, title="并发数")
    thread_time: int = Field(default=0, title="线程时间")
    javdb_time: int = Field(default=10, title="Javdb时间")
    main_mode: int = Field(default=1, title="主模式")
    read_mode: list[ReadMode] = Field(default_factory=list, title="读取模式")
    update_mode: str = Field(default="c", title="更新模式")
    update_a_folder: str = Field(default="actor", title="更新A目录")
    update_b_folder: str = Field(default="number actor", title="更新B目录")
    update_c_filetemplate: str = Field(default="number", title="更新C文件模板")
    update_d_folder: str = Field(default="number actor", title="更新D目录")
    update_titletemplate: str = Field(default="number title", title="更新标题模板")
    soft_link: int = Field(default=0, title="软链接")
    success_file_move: bool = Field(default=True, title="成功后移动文件")
    failed_file_move: bool = Field(default=True, title="失败后移动文件")
    success_file_rename: bool = Field(default=True, title="成功后重命名文件")
    del_empty_folder: bool = Field(default=True, title="删除空目录")
    show_poster: bool = Field(default=True, title="显示海报")
    download_files: list[DownloadableFile] = Field(
        default_factory=lambda: [
            DownloadableFile.POSTER,
            DownloadableFile.THUMB,
            DownloadableFile.FANART,
            DownloadableFile.EXTRAFANART,
            DownloadableFile.TRAILER,
            DownloadableFile.NFO,
            DownloadableFile.EXTRAFANART_EXTRAS,
            DownloadableFile.EXTRAFANART_COPY,
            DownloadableFile.THEME_VIDEOS,
            DownloadableFile.IGNORE_PIC_FAIL,
            DownloadableFile.IGNORE_YOUMA,
            DownloadableFile.IGNORE_WUMA,
            DownloadableFile.IGNORE_FC2,
            DownloadableFile.IGNORE_GUOCHAN,
            DownloadableFile.IGNORE_SIZE,
        ],
        title="下载文件类型",
    )
    keep_files: list[KeepableFile] = Field(
        default_factory=lambda: [
            KeepableFile.POSTER,
            KeepableFile.THUMB,
            KeepableFile.FANART,
            KeepableFile.EXTRAFANART,
            KeepableFile.TRAILER,
            KeepableFile.NFO,
            KeepableFile.EXTRAFANART_COPY,
            KeepableFile.THEME_VIDEOS,
        ],
        title="保留文件类型",
    )
    download_hd_pics: list[HDPicSource] = Field(
        default_factory=lambda: [HDPicSource.AMAZON],
        title="Amazon 高清封面图",
    )
    amazon_strict_pic_verify: bool = Field(default=False, title="严格校验 Amazon 图片")
    scrape_like: Literal["info", "speed", "single"] = Field(default="info", title="刮削模式")  # speed, info, single
    field_priority_try_all_images: bool = Field(default=False, title="字段优先时尝试所有图片")
    # endregion

    @field_validator("download_hd_pics", mode="before")
    @classmethod
    def filter_removed_hd_pic_sources(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            items = str_to_list(v)
        elif isinstance(v, list):
            items = v
        else:
            return v

        valid_values = {HDPicSource.AMAZON.value}
        return [item for item in items if (item.value if isinstance(item, HDPicSource) else str(item)) in valid_values]

    # region: Website Settings
    website_single: Website = Field(default=Website.AIRAV_CC, title="单个网站")  # todo 移除
    website_youma: list[Website] = Field(
        default_factory=lambda: [
            Website.MGSTAGE,
            Website.OFFICIAL,
            Website.MISSAV,
            Website.JAVBUS,
            Website.JAVDBAPI,
            Website.JAV321,
            Website.DMM,
            Website.AVBASE,
        ],
        title="有码网站源",
    )
    website_wuma: list[Website] = Field(
        default_factory=lambda: [
            Website.MISSAV,
            Website.MMTV,
            Website.AVSOX,
        ],
        title="无码网站源",
    )
    website_suren: list[Website] = Field(
        default_factory=lambda: [
            Website.MGSTAGE,
            Website.JAVBUS,
            Website.JAV321,
            Website.DMM,
            Website.AVBASE,
            Website.MMTV,
        ],
        title="素人网站源",
    )
    website_fc2: list[Website] = Field(
        default_factory=lambda: [
            Website.FC2,
            Website.MMTV,
            Website.FC2HUB,
            Website.FC2CLUB,
        ],
        title="FC2网站源",
    )
    website_oumei: list[Website] = Field(
        default_factory=lambda: [Website.THEPORNDB],
        title="欧美网站源",
    )
    website_guochan: list[Website] = Field(
        default_factory=lambda: [Website.CNMDB, Website.HDOUBAN, Website.MADOUQU, Website.JAVDAY, Website.MDTV],
        title="国产网站源",
    )
    fixed_scraping_type: FixedScrapingType = Field(
        default=FixedScrapingType.AUTO,
        title="锁定刮削类型",
        description="选择后将跳过自动类型判断，直接使用指定类型的网站列表进行刮削",
    )

    actor_realname: bool = Field(default=True, title="演员真名")
    outline_format: list[OutlineShow] = Field(default_factory=list, title="简介格式")
    # endregion

    field_configs: dict[CrawlerResultFields, FieldConfig] = Field(
        default_factory=lambda: {
            CrawlerResultFields.TITLE: default_field_config(language=Language.ZH_CN),
            CrawlerResultFields.ORIGINALTITLE: default_field_config(),
            CrawlerResultFields.OUTLINE: default_field_config(language=Language.ZH_CN),
            CrawlerResultFields.ORIGINALPLOT: default_field_config(),
            CrawlerResultFields.ACTORS: default_field_config(language=Language.ZH_CN),
            CrawlerResultFields.ALL_ACTORS: default_field_config(language=Language.ZH_CN),
            CrawlerResultFields.TAGS: default_field_config(language=Language.ZH_CN),
            CrawlerResultFields.DIRECTORS: default_field_config(language=Language.ZH_CN),
            CrawlerResultFields.SERIES: default_field_config(language=Language.ZH_CN),
            CrawlerResultFields.STUDIO: default_field_config(language=Language.ZH_CN),
            CrawlerResultFields.PUBLISHER: default_field_config(language=Language.ZH_CN),
            CrawlerResultFields.THUMB: default_field_config(),
            CrawlerResultFields.POSTER: default_field_config(),
            CrawlerResultFields.EXTRAFANART: default_field_config(),
            CrawlerResultFields.TRAILER: default_field_config(),
            CrawlerResultFields.RELEASE: default_field_config(),
            CrawlerResultFields.RUNTIME: default_field_config(),
            CrawlerResultFields.SCORE: default_field_config(),
            CrawlerResultFields.WANTED: default_field_config(),
        },
        title="字段配置",
    )
    type_field_configs: dict[FixedScrapingType, dict[CrawlerResultFields, FieldPriorityConfig]] = Field(
        default_factory=dict,
        title="按类型字段优先级",
    )

    site_configs: dict[Website, SiteConfig] = Field(default_factory=dict, title="网站配置")

    translate_config: TranslateConfig = Field(default_factory=TranslateConfig, title="翻译配置")

    # region: Naming and Formatting
    nfo_include_new: list[NfoInclude] = Field(
        default_factory=lambda: [
            NfoInclude.SORTTITLE,
            NfoInclude.ORIGINALTITLE,
            NfoInclude.TITLE_CD,
            NfoInclude.OUTLINE,
            NfoInclude.PLOT_,
            NfoInclude.ORIGINALPLOT,
            NfoInclude.OUTLINE_NO_CDATA,
            NfoInclude.RELEASE_,
            NfoInclude.RELEASEDATE,
            NfoInclude.PREMIERED,
            NfoInclude.COUNTRY,
            NfoInclude.MPAA,
            NfoInclude.CUSTOMRATING,
            NfoInclude.YEAR,
            NfoInclude.RUNTIME,
            NfoInclude.WANTED,
            NfoInclude.SCORE,
            NfoInclude.CRITICRATING,
            NfoInclude.ACTOR,
            NfoInclude.ACTOR_ALL,
            NfoInclude.DIRECTOR,
            NfoInclude.SERIES,
            NfoInclude.TAG,
            NfoInclude.GENRE,
            NfoInclude.ACTOR_SET,
            NfoInclude.SERIES_SET,
            NfoInclude.STUDIO,
            NfoInclude.MAKER,
            NfoInclude.PUBLISHER,
            NfoInclude.LABEL,
            NfoInclude.POSTER,
            NfoInclude.COVER,
            NfoInclude.TRAILER,
            NfoInclude.WEBSITE,
        ],
        title="NFO包含内容",
    )
    nfo_tagline: str = Field(default="发行日期 release", title="NFO标语")
    nfo_tag_include: list[TagInclude] = Field(
        default_factory=lambda: [
            TagInclude.ACTOR,
            TagInclude.LETTERS,
            TagInclude.SERIES,
            TagInclude.STUDIO,
            TagInclude.PUBLISHER,
            TagInclude.CNWORD,
            TagInclude.MOSAIC,
            TagInclude.DEFINITION,
        ],
        title="包含标签",
    )
    nfo_tag_series: str = Field(default="系列: series", title="NFO系列标签")
    nfo_tag_studio: str = Field(default="片商: studio", title="NFO工作室标签")
    nfo_tag_publisher: str = Field(default="发行: publisher", title="NFO发行商标签")
    nfo_tag_actor: str = Field(default="actor", title="NFO演员标签")
    nfo_tag_actor_contains: list[str] = Field(default_factory=list, title="NFO 演员名白名单")
    folder_name: str = Field(default="actor/number actor", title="目录名称")
    naming_file: str = Field(default="number", title="文件命名")
    naming_media: str = Field(default="number title", title="媒体命名")
    prevent_char: str = Field(default="", title="禁止字符")
    fields_rule: list[FieldRule] = Field(
        default_factory=lambda: [FieldRule.DEL_ACTOR, FieldRule.DEL_CHAR, FieldRule.FC2_SELLER, FieldRule.DEL_NUM],
        title="字段规则",
    )
    suffix_sort: list[SuffixSort] = Field(
        default_factory=lambda: [SuffixSort.MOWORD, SuffixSort.CNWORD, SuffixSort.DEFINITION],
        title="后缀排序",
    )
    actor_no_name: str = Field(default="未知演员", title="未知演员名称")
    release_rule: str = Field(default="YYYY-MM-DD", title="发布规则")
    folder_name_max: int = Field(default=60, title="目录名称最大长度")
    file_name_max: int = Field(default=60, title="文件名称最大长度")
    actor_name_max: int = Field(default=3, title="演员名称最大数量")
    actor_name_more: str = Field(default="等演员", title="更多演员名称")
    umr_style: str = Field(default="-破解", title="UMR样式")
    leak_style: str = Field(default="-流出", title="泄露样式")
    wuma_style: str = Field(default="", title="无码样式")
    youma_style: str = Field(default="", title="有码样式")
    cd_name: int = Field(default=0, title="CD名称")
    cd_char: list[CDChar] = Field(
        default_factory=lambda: [
            CDChar.LETTER,
            CDChar.ENDC,
            CDChar.DIGITAL,
            CDChar.MIDDLE_NUMBER,
            CDChar.UNDERLINE,
            CDChar.SPACE,
            CDChar.POINT,
        ],
        title="分集规则",
    )
    pic_simple_name: bool = Field(default=False, title="图片简化命名")
    trailer_simple_name: bool = Field(default=True, title="预告片简化命名")
    hd_name: Literal["height", "hd"] = Field(default="height", title="高清名称")
    hd_get: Literal["video", "path", "none"] = Field(default="video", title="获取高清")
    folder_moword: bool = Field(default=True, title="目录版本字符")
    file_moword: bool = Field(default=True, title="文件版本字符")
    folder_hd: bool = Field(default=True, title="目录画质字符")
    file_hd: bool = Field(default=True, title="文件画质字符")
    cnword_char: list[str] = Field(default_factory=lambda: ["-C.", "-C-", "ch.", "字幕"], title="中文字符")
    cnword_style: str = Field(default="-C", title="中文样式")
    folder_cnword: bool = Field(default=True, title="目录中文")
    file_cnword: bool = Field(default=True, title="文件中文")
    subtitle_folder: str = Field(default="", title="字幕目录")
    subtitle_add: bool = Field(default=False, title="添加字幕")
    subtitle_add_chs: bool = Field(default=True, title="添加中文字幕")
    subtitle_add_rescrape: bool = Field(default=True, title="重新刮削时添加字幕")
    # endregion

    # region: Server Settings
    server_type: Literal["emby", "jellyfin"] = Field(default="emby", title="服务器类型")
    emby_url: HttpUrl = Field(default=HttpUrl("http://127.0.0.1:8096"), title="Emby网址")
    api_key: str = Field(default="", title="API密钥")
    user_id: str = Field(default="", title="用户ID")
    emby_on: list[EmbyAction] = Field(
        default_factory=lambda: [
            EmbyAction.ACTOR_INFO_ZH_CN,
            EmbyAction.ACTOR_INFO_MISS,
            EmbyAction.ACTOR_PHOTO_NET,
            EmbyAction.ACTOR_PHOTO_MISS,
            EmbyAction.ACTOR_INFO_TRANSLATE,
            EmbyAction.ACTOR_INFO_PHOTO,
            EmbyAction.GRAPHIS_BACKDROP,
            EmbyAction.GRAPHIS_FACE,
            EmbyAction.GRAPHIS_NEW,
            EmbyAction.ACTOR_PHOTO_AUTO,
            EmbyAction.ACTOR_REPLACE,
        ],
        title="Emby功能开关",
    )
    use_database: bool = Field(default=False, title="使用数据库")
    info_database_path: str = Field(default="", title="信息数据库路径")
    gfriends_github: HttpUrl = Field(default=HttpUrl("https://github.com/gfriends/gfriends"), title="Gfriends Github")
    actor_photo_folder: str = Field(default="", title="演员照片目录")
    actor_photo_kodi_auto: bool = Field(default=False, title="演员照片Kodi自动")
    # endregion

    # region: Watermark Settings
    poster_mark: int = Field(default=1, title="海报水印")
    thumb_mark: int = Field(default=1, title="缩略图水印")
    fanart_mark: int = Field(default=0, title="Fanart水印")
    mark_size: int = Field(default=5, title="水印大小")
    mark_type: list[MarkType] = Field(
        default_factory=lambda: [
            MarkType.SUB,
            MarkType.YOUMA,
            MarkType.UMR,
            MarkType.LEAK,
            MarkType.UNCENSORED,
            MarkType.HD,
        ],
        title="水印类型",
    )
    mark_fixed: Literal["not_fixed", "fixed", "corner"] = Field(
        default="not_fixed",
        title="水印添加规则",
        description="not_fixed: 不固定位置. 将从首个位置开始顺时针方向依次添加; fixed: 固定一个位置, 水印在此依次横向添加; corner: 分别设置不同种类水印的位置.",
    )
    mark_pos: str = Field(default="top_left", title="水印规则为不固定时首个水印的位置")
    mark_pos_corner: str = Field(default="top_left", title="水印规则为固定时的位置")
    mark_pos_sub: str = Field(default="top_left", title="中文字幕水印位置")
    mark_pos_mosaic: str = Field(default="top_right", title="马赛克类型水印位置")
    mark_pos_hd: str = Field(default="bottom_right", title="清晰度水印位置")
    # endregion

    # region: Network Settings
    use_proxy: bool = Field(default=False, title="代理类型")
    proxy: str = Field(default="http://127.0.0.1:7890", title="代理地址")
    cf_bypass_url: str = Field(default="", title="Cloudflare Bypass地址")
    cf_bypass_proxy: str = Field(default="", title="Cloudflare Bypass代理地址")
    timeout: int = Field(default=10, title="超时")
    retry: int = Field(default=3, title="重试")
    theporndb_api_token: str = Field(default="", title="Theporndb API令牌")
    javdb: str = Field(default="", title="Javdb")
    fc2ppvdb: str = Field(default="", title="FC2PPVDB")
    javbus: str = Field(default="", title="Javbus")
    # endregion

    # region: Log Settings
    show_web_log: bool = Field(default=False, title="显示网页日志")
    show_from_log: bool = Field(default=True, title="显示来源日志")
    show_data_log: bool = Field(default=True, title="显示数据日志")
    save_log: bool = Field(default=True, title="保存日志")
    # endregion

    # region: Misc Settings
    update_check: bool = Field(default=True, title="检查更新")
    local_library: list[str] = Field(default_factory=list, title="本地库")
    actors_name: str = Field(default="", title="演员名称")
    netdisk_path: str = Field(default="", title="网盘路径")
    localdisk_path: str = Field(default="", title="本地磁盘路径")
    window_title: str = Field(default="hide", title="窗口标题")
    switch_on: list[Switch] = Field(
        default_factory=lambda: [
            Switch.AUTO_EXIT,
            Switch.REST_SCRAPE,
            Switch.TIMED_SCRAPE,
            Switch.REMAIN_TASK,
            Switch.SHOW_DIALOG_STOP_SCRAPE,
            Switch.SORT_DEL,
            Switch.THEPORNDB_NO_HASH,
            Switch.HIDE_DOCK,
            Switch.PASSTHROUGH,
            Switch.HIDE_MENU,
            Switch.DARK_MODE,
            Switch.COPY_NETDISK_NFO,
            Switch.SHOW_LOGS,
            Switch.HIDE_NONE,
        ],
        title="功能开关",
    )
    timed_interval: timedelta = Field(default=timedelta(minutes=30), title="定时器间隔")
    rest_count: int = Field(default=20, title="休息计数")
    rest_time: timedelta = Field(default=timedelta(), title="休息时间")
    # statement: int = Field(default=3, title="声明")
    # endregion

    # region: deperated
    # website_set: list[WebsiteSet] = Field(default_factory=list, title="网站设置")
    # whole_fields: list[WholeField] = Field(default_factory=list, title="完整字段")
    # none_fields: list[NoneField] = Field(default_factory=list, title="空字段")
    # title_website: list[Website] = Field(default_factory=list, title="标题网站源")
    # title_zh_website: list[Website] = Field(default_factory=list, title="中文标题网站源")
    # title_website_exclude: list[Website] = Field(default_factory=list, title="排除的标题网站源")
    # outline_website: list[Website] = Field(default_factory=list, title="简介网站源")
    # outline_zh_website: list[Website] = Field(default_factory=list, title="中文简介网站源")
    # outline_website_exclude: list[Website] = Field(default_factory=list, title="排除的简介网站源")
    # actor_website: list[Website] = Field(default_factory=list, title="演员网站源")
    # actor_website_exclude: list[Website] = Field(default_factory=list, title="排除的演员网站源")
    # thumb_website: list[Website] = Field(default_factory=list, title="缩略图网站源")
    # thumb_website_exclude: list[Website] = Field(default_factory=list, title="排除的缩略图网站源")
    # poster_website: list[Website] = Field(default_factory=list, title="海报网站源")
    # poster_website_exclude: list[Website] = Field(default_factory=list, title="排除的海报网站源")
    # extrafanart_website: list[Website] = Field(default_factory=list, title="剧照网站源")
    # extrafanart_website_exclude: list[Website] = Field(default_factory=list, title="排除的剧照网站源")
    # trailer_website: list[Website] = Field(default_factory=list, title="预告片网站源")
    # trailer_website_exclude: list[Website] = Field(default_factory=list, title="排除的预告片网站源")
    # tag_website: list[Website] = Field(default_factory=list, title="标签网站源")
    # tag_website_exclude: list[Website] = Field(default_factory=list, title="排除的标签网站源")
    # release_website: list[Website] = Field(default_factory=list, title="发布日期网站源")
    # release_website_exclude: list[Website] = Field(default_factory=list, title="排除的发布日期网站源")
    # runtime_website: list[Website] = Field(default_factory=list, title="时长网站源")
    # runtime_website_exclude: list[Website] = Field(default_factory=list, title="排除的时长网站源")
    # score_website: list[Website] = Field(default_factory=list, title="评分网站源")
    # score_website_exclude: list[Website] = Field(default_factory=list, title="排除的评分网站源")
    # director_website: list[Website] = Field(default_factory=list, title="导演网站源")
    # director_website_exclude: list[Website] = Field(default_factory=list, title="排除的导演网站源")
    # series_website: list[Website] = Field(default_factory=list, title="系列网站源")
    # series_website_exclude: list[Website] = Field(default_factory=list, title="排除的系列网站源")
    # studio_website: list[Website] = Field(default_factory=list, title="工作室网站源")
    # studio_website_exclude: list[Website] = Field(default_factory=list, title="排除的工作室网站源")
    # publisher_website: list[Website] = Field(default_factory=list, title="发行商网站源")
    # publisher_website_exclude: list[Website] = Field(default_factory=list, title="排除的发行商网站源")
    # wanted_website: list[Website] = Field(default_factory=list, title="想看网站源")
    # title_language: Language = Field(default=Language.ZH_CN, title="标题语言")
    # title_translate: bool = Field(default=True, title="翻译标题")
    # outline_language: Language = Field(default=Language.ZH_CN, title="简介语言")
    # outline_translate: bool = Field(default=True, title="翻译简介")
    # actor_language: Language = Field(default=Language.ZH_CN, title="演员语言")
    # actor_translate: bool = Field(default=True, title="翻译演员")
    # tag_language: Language = Field(default=Language.ZH_CN, title="标签语言")
    # tag_translate: bool = Field(default=True, title="翻译标签")
    # director_language: Language = Field(default=Language.ZH_CN, title="导演语言")
    # director_translate: bool = Field(default=True, title="翻译导演")
    # series_language: Language = Field(default=Language.ZH_CN, title="系列语言")
    # series_translate: bool = Field(default=True, title="翻译系列")
    # studio_language: Language = Field(default=Language.ZH_CN, title="工作室语言")
    # studio_translate: bool = Field(default=True, title="翻译工作室")
    # publisher_language: Language = Field(default=Language.ZH_CN, title="发行商语言")
    # publisher_translate: bool = Field(default=True, title="翻译发行商")
    # endregion

    def model_post_init(self, context) -> None:
        self.ensure_type_field_configs()

    def get_site_config(self, site: Website) -> SiteConfig:
        return self.site_configs.get(site, SiteConfig())

    def get_site_url(self, site: Website, default: str = "") -> str:
        """获取指定网站的用户自定义 URL, 结尾无斜杠."""
        return str(self.get_site_config(site).custom_url or default).rstrip("/")

    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        return self.field_configs.get(field, FieldConfig())

    def get_type_sites(self, scraping_type: FixedScrapingType) -> list[Website]:
        field_name = SCRAPING_TYPE_SITE_FIELDS.get(scraping_type)
        if not field_name:
            return []
        return self.parse_sites(getattr(self, field_name, []))

    def get_type_field_config(
        self, scraping_type: FixedScrapingType, field: CrawlerResultFields
    ) -> FieldPriorityConfig:
        self.ensure_type_field_configs()
        return self.type_field_configs.get(scraping_type, {}).get(field, FieldPriorityConfig())

    def set_type_field_sites(
        self, scraping_type: FixedScrapingType, field: CrawlerResultFields, sites: list[Website] | str
    ) -> None:
        self.type_field_configs.setdefault(scraping_type, {})[field] = FieldPriorityConfig(
            site_prority=self.parse_sites(sites)
        )

    def build_type_field_configs(
        self, scraping_type: FixedScrapingType
    ) -> dict[CrawlerResultFields, FieldPriorityConfig]:
        type_sites = self.get_type_sites(scraping_type)
        type_site_set = set(type_sites)
        configs: dict[CrawlerResultFields, FieldPriorityConfig] = {}
        for crawler_field in ManualConfig.REDUCED_FIELDS:
            field_sites = self.get_field_config(crawler_field).site_prority
            sites = [site for site in field_sites if site in type_site_set]
            if not sites:
                sites = list(type_sites)
            configs[crawler_field] = FieldPriorityConfig(site_prority=sites)
        return configs

    def _normalize_type_field_config(
        self,
        scraping_type: FixedScrapingType,
        current: dict[CrawlerResultFields, FieldPriorityConfig],
    ) -> dict[CrawlerResultFields, FieldPriorityConfig]:
        type_site_set = set(self.get_type_sites(scraping_type))
        default = self.build_type_field_configs(scraping_type)
        normalized: dict[CrawlerResultFields, FieldPriorityConfig] = {}
        for crawler_field in ManualConfig.REDUCED_FIELDS:
            if crawler_field in current:
                old_sites = current[crawler_field].site_prority
                sites = [site for site in self.parse_sites(old_sites) if site in type_site_set]
            else:
                sites = default[crawler_field].site_prority
            normalized[crawler_field] = FieldPriorityConfig(site_prority=sites)
        return normalized

    def fill_missing_type_field_configs(self) -> None:
        normalized: dict[FixedScrapingType, dict[CrawlerResultFields, FieldPriorityConfig]] = {}
        for scraping_type in CONFIGURABLE_SCRAPING_TYPES:
            current = self.type_field_configs.get(scraping_type)
            if current is None:
                normalized[scraping_type] = self.build_type_field_configs(scraping_type)
            else:
                normalized[scraping_type] = self._normalize_type_field_config(scraping_type, current)
        self.type_field_configs = normalized

    def ensure_type_field_configs(self) -> None:
        normalized: dict[FixedScrapingType, dict[CrawlerResultFields, FieldPriorityConfig]] = {}
        for scraping_type in CONFIGURABLE_SCRAPING_TYPES:
            current = self.type_field_configs.get(scraping_type)
            if not current:
                normalized[scraping_type] = self.build_type_field_configs(scraping_type)
                continue
            normalized[scraping_type] = self._normalize_type_field_config(scraping_type, current)
        self.type_field_configs = normalized

    def set_field_sites(self, field: CrawlerResultFields, sites: list[Website] | str):
        sites = self.parse_sites(sites)
        self.field_configs.setdefault(field, FieldConfig()).site_prority = sites

    def set_field_language(self, field: CrawlerResultFields, language: Language):
        self.field_configs.setdefault(field, FieldConfig()).language = language

    def set_field_translate(self, field: CrawlerResultFields, translate: bool):
        self.field_configs.setdefault(field, FieldConfig()).translate = translate

    @staticmethod
    def parse_sites(sites: list | set | str) -> list[Website]:
        if isinstance(sites, str):
            sites = str_to_list(sites, ",")
        return list(dict.fromkeys(Website(s) for s in sites if s in Website))

    @staticmethod
    def update(d: dict[str, Any]) -> list[str]:
        """
        处理字段变更.
        """
        warnings = migrate_config_data(d)
        # 处理旧版字段设置
        if "field_configs" not in d:
            Config._convert_field_configs(d)

        return warnings

    @staticmethod
    def _convert_field_configs(d):
        field_configs: dict[CrawlerResultFields, FieldConfig] = {}
        whole_fields: list[str] = d.get("whole_fields", [])
        none_fields: list[str] = d.get("none_fields", [])
        website_youma = Config.parse_sites(d.get("website_youma", []))
        if len(d.get("website_set", [])) > 0:
            website_youma.insert(0, Website.OFFICIAL)
            d["website_youma"] = website_youma
        website_wuma = Config.parse_sites(d.get("website_wuma", []))
        website_suren = Config.parse_sites(d.get("website_suren", []))
        website_fc2 = Config.parse_sites(d.get("website_fc2", []))
        website_oumei = Config.parse_sites(d.get("website_oumei", []))
        website_guochan = Config.parse_sites(d.get("website_guochan", []))
        all_enabled_sites = list(
            dict.fromkeys(website_youma + website_wuma + website_suren + website_fc2 + website_oumei + website_guochan)
        )
        for field_name in ManualConfig.CONFIG_DATA_FIELDS:
            if field_name in ("outline_zh", "title_zh"):
                continue
            if field_name in ManualConfig.RENAME_MAP:
                new_key = ManualConfig.RENAME_MAP[field_name]
            else:
                new_key = field_name
            assert new_key in CrawlerResultFields, f"Field {new_key} is not a valid CrawlerResultFields"
            new_key = cast(CrawlerResultFields, new_key)

            field_site = Config.parse_sites(d.get(f"{field_name}_website", []))
            if field_name in ("outline", "title"):
                field_site += Config.parse_sites(d.get(f"{field_name}_zh_website", []))
            if len(d.get("website_set", [])) > 0:
                field_site.insert(0, Website.OFFICIAL)
            field_site_exclude = Config.parse_sites(d.get(f"{field_name}_website_exclude", []))
            field_lang = Language(d.get(f"{field_name}_language", Language.UNDEFINED))
            field_translate: bool = d.get(f"{field_name}_translate", False)

            if field_name in none_fields:  # 不单独刮削
                field_configs[new_key] = FieldConfig(language=field_lang, translate=field_translate)
                continue
            if field_name in whole_fields:
                sites = list(dict.fromkeys(s for s in field_site + all_enabled_sites if s not in field_site_exclude))
            else:
                sites = list(dict.fromkeys(s for s in field_site if s not in field_site_exclude))
            field_configs[new_key] = FieldConfig(site_prority=sites, language=field_lang, translate=field_translate)
            # 处理旧版无配置项的字段
        field_configs[CrawlerResultFields.ALL_ACTORS] = field_configs.get(
            CrawlerResultFields.ACTORS,
            FieldConfig(site_prority=[Website.JAVDB], language=Language.JP),
        )
        field_configs[CrawlerResultFields.ORIGINALPLOT] = field_configs.get(
            CrawlerResultFields.OUTLINE,
            FieldConfig(site_prority=[Website.THEPORNDB, Website.DMM, Website.JAV321], language=Language.ZH_CN),
        )
        field_configs[CrawlerResultFields.ORIGINALTITLE] = field_configs.get(
            CrawlerResultFields.TITLE,
            FieldConfig(site_prority=[Website.THEPORNDB, Website.DMM, Website.JAV321], language=Language.ZH_CN),
        )
        d["field_configs"] = field_configs

    @field_validator("timed_interval", "rest_time", mode="before")
    def convert_time_str_to_timedelta(cls, v):
        if isinstance(v, timedelta):
            return v
        if isinstance(v, str) and re.match(r"^\d{2}:\d{2}:\d{2}$", v):
            h, m, s = map(int, v.split(":"))
            return timedelta(hours=h, minutes=m, seconds=s)
        return v

    @classmethod
    def from_legacy(cls, data: dict[str, Any]) -> "Config":
        """
        从 ConfigV1 创建 Config 实例. 此方法仅用于转换旧版配置文件.
        """
        # 应用兼容规则
        for rule in COMPAT_RULES:
            if isinstance(rule, Rename):
                if rule.old_name in data:
                    data[rule.new_name] = rule.to_new(data[rule.old_name]) if rule.to_new else data[rule.old_name]
                    data.pop(rule.old_name, None)
            elif isinstance(rule, Remove):
                data.pop(rule.name, None)

        # 处理 site_configs
        site_configs: dict[Website, SiteConfig] = {}
        for key, value in data.items():
            # custom url
            if key.endswith("_website") and key[:-8] in Website:
                site_name = key.replace("_website", "")
                site_configs[Website(site_name)] = SiteConfig(custom_url=value)
        data["site_configs"] = site_configs

        # 格式转换
        def handle_dict(model_fields: dict[str, FieldInfo], data: dict[str, Any]) -> dict[str, Any]:
            for name, info in model_fields.items():
                assert info.annotation is not None, f"Field {name} has no annotation"
                # 处理嵌套
                if isinstance(info.annotation, type) and issubclass(info.annotation, BaseModel):
                    sub_dict = handle_dict(info.annotation.model_fields, data)
                    data[name] = sub_dict
                    continue
                if name not in data:
                    continue
                if "list" in str(info.annotation) or "set" in str(info.annotation):
                    if name in (
                        "media_type",
                        "sub_type",
                        "clean_ext",
                        "clean_name",
                        "clean_contains",
                        "clean_ignore_ext",
                        "clean_ignore_contains",
                        "nfo_tag_actor_contains",
                    ):
                        data[name] = str_to_list(data[name], "|")
                    else:
                        data[name] = str_to_list(data[name], ",")
                if info.annotation is type(timedelta) and re.match(r"^\d{2}:\d{2}:\d{2}$", data[name]):
                    h, m, s = map(int, data[name].split(":"))
                    data[name] = timedelta(hours=h, minutes=m, seconds=s)
            return data

        data = handle_dict(cls.model_fields, data)
        cls.update(data)
        return cls.model_validate(data)

    @classmethod
    @lru_cache
    def json_schema(cls) -> dict[str, Any]:
        schema = cls.model_json_schema()
        try:
            from mdcx.crawlers import get_registered_crawler_site_values

            registered_sites = get_registered_crawler_site_values()
        except Exception:
            registered_sites = []
        if registered_sites and (website_schema := schema.get("$defs", {}).get("Website")):
            website_schema["enum"] = registered_sites
            website_schema["showNames"] = registered_sites
        return schema


@dataclass
class CompatRule:
    # 添加必要注释
    notes: list = field(kw_only=True, default_factory=list)


@dataclass
class Rename[TRaw = str, TNew = TRaw](CompatRule):
    old_name: str
    new_name: str
    to_new: Callable[[TRaw], TNew] | None = None
    to_old: Callable[[TNew], TRaw] | None = None


@dataclass
class Remove(CompatRule):
    name: str


# 描述 Config 相比于 ConfigV1 的变更并添加相应的兼容规则
COMPAT_RULES: list[CompatRule] = [
    Remove("version"),
    Remove("unknown_fields"),
    Rename[str, bool](
        "type",
        "use_proxy",
        to_new=lambda x: x != "no",
        to_old=lambda x: "no" if not x else "yes",
        notes=["ConfigV1.type", Config().use_proxy, "与关键词冲突"],
    ),
    Rename("outline_show", "outline_format", notes=["ConfigV1.outline_show", Config().outline_format, "澄清语义"]),
    Rename("tag_include", "nfo_tag_include", notes=["ConfigV1.tag_include", Config().nfo_tag_include, "澄清语义"]),
    Remove("show_4k", notes=["ConfigV1.show_4k", "功能与命名模板冲突"]),
    Remove("show_moword", notes=["ConfigV1.show_moword", "功能与命名模板冲突"]),
]
if TYPE_CHECKING:
    from .v1 import ConfigV1

    # 方便快速查看 ConfigV1 的字段
    _ = [
        ConfigV1.type,
        ConfigV1.outline_show,
        ConfigV1.tag_include,
        ConfigV1.show_4k,
        ConfigV1.show_moword,
    ]
