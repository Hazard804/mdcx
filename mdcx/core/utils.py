import asyncio
import re
from pathlib import Path

import aiofiles.os

from ..config.enums import FieldRule, Language, NfoInclude, NoEscape, TagInclude
from ..config.manager import manager
from ..config.resources import resources
from ..gen.field_enums import CrawlerResultFields
from ..manual import ManualConfig
from ..models.log_buffer import LogBuffer
from ..models.types import BaseCrawlerResult, CrawlersResult, FileInfo
from ..number import get_number_letters, strip_escape_strings
from ..signals import signal
from ..utils import get_used_time
from ..utils.video import get_video_metadata
from .naming import NameRenderOptions, NamingTarget, render_name


def replace_word(json_data: BaseCrawlerResult):
    # 常见字段替换的字符
    for key, value in ManualConfig.ALL_REP_WORD.items():
        for each in ManualConfig.ALL_KEY_WORD:
            setattr(json_data, each, getattr(json_data, each).replace(key, value))

    # 简体时替换的字符
    key_word = []
    if manager.config.get_field_config(CrawlerResultFields.TITLE).language == Language.ZH_CN:
        key_word.append("title")
    if manager.config.get_field_config(CrawlerResultFields.OUTLINE).language == Language.ZH_CN:
        key_word.append("outline")

    for key, value in ManualConfig.CHINESE_REP_WORD.items():
        for each in key_word:
            setattr(json_data, each, getattr(json_data, each).replace(key, value))

    # 替换标题的上下集信息
    for field in (CrawlerResultFields.TITLE, CrawlerResultFields.ORIGINALTITLE):
        for each in ManualConfig.TITLE_REP:
            setattr(json_data, field, getattr(json_data, field).replace(each, "").strip(":， ").strip())


def replace_special_word(json_data: BaseCrawlerResult):
    # 常见字段替换的字符
    all_key_word = [
        "title",
        "originaltitle",
        "outline",
        "originalplot",
        "series",
        "director",
        "studio",
        "publisher",
        "tag",
    ]
    for key, value in ManualConfig.SPECIAL_WORD.items():
        for each in all_key_word:
            # json_data[each] = json_data[each].replace(key, value)
            setattr(json_data, each, getattr(json_data, each).replace(key, value))


def deal_some_field(json_data: CrawlersResult):
    fields_rule = manager.config.fields_rule
    title = json_data.title
    originaltitle = json_data.originaltitle
    number = json_data.number

    # 演员处理
    if json_data.actors:
        # 去除演员名中的括号
        temp_actor_list = []
        actors = json_data.actors.copy()
        json_data.actors = []
        for raw_name in actors:
            if not raw_name:
                continue
            cleaned = re.findall(r"[^\(\)\（\）]+", raw_name)
            temp_actor_list.extend(cleaned)
            if FieldRule.DEL_CHAR in fields_rule:
                json_data.actors.append(cleaned[0])
            else:
                json_data.actors.append(raw_name)

        # 去除 all_actors 中的括号
        all_actors = json_data.all_actors.copy()
        json_data.all_actors = []
        for raw_name in all_actors:
            if not raw_name:
                continue
            cleaned = re.findall(r"[^\(\)\（\）]+", raw_name)
            if FieldRule.DEL_CHAR in fields_rule:
                json_data.all_actors.append(cleaned[0])
            else:
                json_data.all_actors.append(raw_name)

        # 去除标题后的演员名
        if FieldRule.DEL_ACTOR in fields_rule:
            new_all_actor_name_list = []
            for each_actor in json_data.actor_amazon + temp_actor_list:
                # 获取演员映射表的所有演员别名进行替换
                actor_keyword_list: list[str] = resources.get_actor_data(each_actor).get("keyword", [])
                new_all_actor_name_list.extend(actor_keyword_list)
            for each_actor in set(new_all_actor_name_list):
                title = title.removesuffix(f" {each_actor}")
                originaltitle = originaltitle.removesuffix(f" {each_actor}")
        json_data.title = title.strip()
        json_data.originaltitle = originaltitle.strip()

    # 去除标题中的番号
    if number != title and title.startswith(number):
        title = title.replace(number, "").strip()
        json_data.title = title
    if number != originaltitle and originaltitle.startswith(number):
        originaltitle = originaltitle.replace(number, "").strip()
        json_data.originaltitle = originaltitle

    # 去除标题中的/
    json_data.title = json_data.title.replace("/", "#").strip(" -")
    json_data.originaltitle = json_data.originaltitle.replace("/", "#").strip(" -")

    # 去除素人番号前缀数字
    if FieldRule.DEL_NUM in fields_rule:
        temp_n = re.findall(r"\d{3,}([a-zA-Z]+-\d+)", number)
        if temp_n:
            json_data.number = temp_n[0]
            json_data.letters = get_number_letters(json_data.number)

    if number.endswith("Z"):
        json_data.number = json_data.number[:-1] + "z"
    return json_data


def show_movie_info(file_info: FileInfo, result: CrawlersResult):
    if not manager.config.show_data_log:  # 调试模式打开时显示详细日志
        return
    for key in ManualConfig.SHOW_KEY:  # 大部分来自 CrawlersResultDataClass, 少部分来自 FileInfo
        value = getattr(result, key, getattr(file_info, key, ""))
        if not value:
            continue
        if key == CrawlerResultFields.OUTLINE or key == CrawlerResultFields.ORIGINALPLOT and len(value) > 100:
            value = str(value)[:98] + "……（略）"
        elif key == "has_sub":
            value = "中文字幕"
        elif key == CrawlerResultFields.ACTORS and NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
            value = result.all_actor
        LogBuffer.log().write(f"\n     {key:<13}: {value}")


def _normalize_path_for_definition(file_path: Path, file_number: str = "") -> str:
    definition_markers = {
        "8K",
        "4K",
        "4KS",
        "4K60FPS",
        "UHD",
        "UHD8",
        "QHD",
        "FHD",
        "HD",
        "1440P",
        "1080P",
        "960P",
        "720P",
        "540P",
        "480P",
        "360P",
        "144P",
    }
    escape_strings = [
        each for each in manager.config.string if re.sub(r"[^A-Z0-9]", "", each.upper()) not in definition_markers
    ]
    normalized = strip_escape_strings(file_path.as_posix(), escape_strings)
    number_candidates = {file_number.upper()} if file_number else set()

    if file_number:
        short_number = re.findall(r"\d{3,}([A-Z]+-\d+)", file_number.upper())
        number_candidates.update(short_number)

    for each in sorted((candidate for candidate in number_candidates if candidate), key=len, reverse=True):
        normalized = normalized.replace(each, "-")

    return normalized


def _detect_height_from_path(file_path: Path, file_number: str = "") -> int:
    normalized = _normalize_path_for_definition(file_path, file_number)
    normalized_name = normalized.rsplit("/", 1)[-1]
    pattern_height_map = (
        ((r"(?<![A-Z0-9])8K(?![A-Z0-9])",), 4000),
        ((r"(?<![A-Z0-9])4K(?![A-Z0-9])", r"(?<![A-Z0-9])UHD(?![A-Z0-9])"), 2000),
        ((r"(?<![A-Z0-9])1440P(?![A-Z0-9])", r"(?<![A-Z0-9])QHD(?![A-Z0-9])"), 1440),
        ((r"(?<![A-Z0-9])1080P(?![A-Z0-9])", r"(?<![A-Z0-9])FHD(?![A-Z0-9])"), 1080),
        ((r"(?<![A-Z0-9])960P(?![A-Z0-9])",), 960),
        ((r"(?<![A-Z0-9])720P(?![A-Z0-9])", r"(?<![A-Z0-9])HD(?![A-Z0-9])"), 720),
    )
    for patterns, height in pattern_height_map:
        if any(re.search(pattern, normalized) for pattern in patterns):
            return height
    # 文件名尾部的 4K 扩展标记单独处理，如 IPZZ-841_4K60FPS / IPZZ-841_4KS。
    if re.search(r"(?:^|[-_ .\[])(?:4K60FPS|4KS)(?=\.[^.\\/]+$)", normalized_name):
        return 2000
    # 无码破解标记和 4K 紧贴时也保留 4K 识别，如 JUR-615-U4K / JUR-615-UC4K。
    if re.search(r"(?:^|[-_ .\[])U(?:C)?-?4K(?=\.[^.\\/]+$)", normalized_name):
        return 2000
    return 0


async def get_video_size(file_path: Path, file_number: str = ""):
    """
    获取视频分辨率和编码格式

    Args:
        file_path (Path): 视频文件的完整路径

    Returns:
        definition,codec (tuple[str, str]): 视频分辨率, 编码格式
    """
    # 获取本地分辨率 同时获取视频编码格式
    definition = ""
    height = 0
    hd_get = manager.config.hd_get
    if await aiofiles.os.path.islink(file_path):
        if NoEscape.SYMLINK_DEFINITION in manager.config.no_escape:
            file_path = file_path.resolve()
        else:
            hd_get = "path"
    codec = ""
    if hd_get == "video":
        try:
            height, codec = await asyncio.to_thread(get_video_metadata, file_path)
        except Exception as e:
            signal.show_log_text(f" 🔴 无法获取视频分辨率! 文件地址: {file_path}  错误信息: {e}")
    elif hd_get == "path":
        height = _detect_height_from_path(file_path, file_number)

    hd_name = manager.config.hd_name
    if not height:
        pass
    elif height >= 4000:
        definition = "8K" if hd_name == "height" else "UHD8"
    elif height >= 2000:
        definition = "4K" if hd_name == "height" else "UHD"
    elif height >= 1400:
        definition = "1440P" if hd_name == "height" else "QHD"
    elif height >= 1000:
        definition = "1080P" if hd_name == "height" else "FHD"
    elif height >= 900:
        definition = "960P" if hd_name == "height" else "HD"
    elif height >= 700:
        definition = "720P" if hd_name == "height" else "HD"
    elif height >= 500:
        definition = "540P" if hd_name == "height" else "qHD"
    elif height >= 400:
        definition = "480P"
    elif height >= 300:
        definition = "360P"
    elif height >= 100:
        definition = "144P"

    return definition, codec


def add_definition_tag(res: BaseCrawlerResult, definition, codec):
    remove_key = ["144P", "360P", "480P", "540P", "720P", "960P", "1080P", "1440P", "2160P", "4K", "8K"]
    tag = res.tag
    for each_key in remove_key:
        tag = tag.replace(each_key, "").replace(each_key.lower(), "")
    tag_list = re.split(r"[,，]", tag)
    new_tag_list = []
    [new_tag_list.append(i) for i in tag_list if i]
    if definition and TagInclude.DEFINITION in manager.config.nfo_tag_include:
        new_tag_list.insert(0, definition)
        if manager.config.hd_get == "video" and codec and codec not in new_tag_list:
            new_tag_list.insert(0, codec)  # 插入编码格式
    res.tag = ",".join(new_tag_list)


def show_result(res: CrawlersResult, start_time: float):
    LogBuffer.log().write(res.site_log)
    if manager.config.show_from_log and res.field_log:  # 字段来源信息
        LogBuffer.log().write("\n\n 📒 字段来源\n\n" + res.field_log.strip(" ").strip("\n"))
    LogBuffer.log().write(f"\n 🍀 Data done!({get_used_time(start_time)}s)")


def render_name_template(
    template: str,
    file_info: FileInfo,
    json_data: CrawlersResult,
    show_4k: bool,
    show_cnword: bool,
    show_moword: bool,
    should_escape_result: bool,
) -> tuple[str, str, str, str, str, str]:
    """
    将命名模板渲染成实际值。

    旧调用点仍使用这个函数，内部已切换到 mdcx.core.naming 的统一渲染器。
    """
    target = NamingTarget.FILE if should_escape_result else NamingTarget.NFO_TITLE
    result = render_name(
        template,
        file_info,
        json_data,
        NameRenderOptions(
            target=target,
            show_definition_suffix=show_4k,
            show_cnword_suffix=show_cnword,
            show_moword_suffix=show_moword,
        ),
    )
    return (
        result.text,
        result.template,
        result.value("number"),
        result.value("originaltitle"),
        result.value("outline"),
        result.value("title"),
    )
