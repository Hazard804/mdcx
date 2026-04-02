import random
import re
import time
import traceback

import zhconv

from ..base.translate import (
    get_translator_skip_reason,
    translate_with_engine,
)
from ..base.web import get_actorname, get_yesjav_title
from ..config.enums import FieldRule, Language, TagInclude
from ..config.manager import manager
from ..config.resources import resources
from ..gen.field_enums import CrawlerResultFields
from ..models.log_buffer import LogBuffer
from ..models.types import CrawlersResult
from ..number import get_number_letters
from ..signals import signal
from ..utils import clean_list, get_used_time
from ..utils.language import is_japanese, is_probably_english_for_translation


def translate_info(json_data: CrawlersResult, has_sub: bool):
    xml_info = resources.info_mapping_data
    if xml_info is not None and len(xml_info) == 0:
        return json_data
    tag_translate = manager.config.get_field_config(CrawlerResultFields.TAGS).translate
    series_translate = manager.config.get_field_config(CrawlerResultFields.SERIES).translate
    studio_translate = manager.config.get_field_config(CrawlerResultFields.STUDIO).translate
    publisher_translate = manager.config.get_field_config(CrawlerResultFields.PUBLISHER).translate
    director_translate = manager.config.get_field_config(CrawlerResultFields.DIRECTORS).translate
    tag_language = manager.config.get_field_config(CrawlerResultFields.TAGS).language
    series_language = manager.config.get_field_config(CrawlerResultFields.SERIES).language
    studio_language = manager.config.get_field_config(CrawlerResultFields.STUDIO).language
    publisher_language = manager.config.get_field_config(CrawlerResultFields.PUBLISHER).language
    director_language = manager.config.get_field_config(CrawlerResultFields.DIRECTORS).language
    fields_rule = manager.config.fields_rule

    tag_include = manager.config.nfo_tag_include
    tag = json_data.tag
    remove_key = [
        "HD高画质",
        "HD高畫質",
        "高画质",
        "高畫質",
        "無碼流出",
        "无码流出",
        "無碼破解",
        "无码破解",
        "無碼片",
        "无码片",
        "有碼片",
        "有码片",
        "無碼",
        "无码",
        "有碼",
        "有码",
        "流出",
        "国产",
        "國產",
    ]
    for each_key in remove_key:
        tag = tag.replace(each_key, "")

    # 映射tag并且存在xml_info时，处理tag映射
    if tag_translate:
        tag_list = re.split(r"[,，]", tag)
        tag_new = []
        for each_info in tag_list:
            if each_info:  # 为空时会多出来一个
                info_data = resources.get_info_data(each_info)
                each_info = info_data.get(tag_language)
                if each_info and each_info not in tag_new:
                    tag_new.append(each_info)
        tag = ",".join(tag_new)

    # tag去重/去空/排序
    tag = clean_list(tag)

    # 添加演员
    if TagInclude.ACTOR in tag_include:
        whitelist = manager.config.nfo_tag_actor_contains
        for actor in json_data.actors:
            if not whitelist or actor in whitelist:
                nfo_tag_actor = manager.config.nfo_tag_actor.replace("actor", actor)
                tag = nfo_tag_actor + "," + tag

    # 添加番号前缀
    letters = json_data.letters
    if TagInclude.LETTERS in tag_include and letters and letters != "未知车牌":
        # 去除素人番号前缀数字
        if FieldRule.DEL_NUM in fields_rule:
            temp_n = re.findall(r"\d{3,}([a-zA-Z]+-\d+)", json_data.number)
            if temp_n:
                letters = get_number_letters(temp_n[0])
                json_data.letters = letters
                json_data.number = temp_n[0]
        tag = letters + "," + tag
        tag = tag.strip(",")

    # 添加字幕、马赛克信息到tag中
    mosaic = json_data.mosaic
    if has_sub and TagInclude.CNWORD in tag_include:
        tag += ",中文字幕"
    if mosaic and TagInclude.MOSAIC in tag_include:
        tag += "," + mosaic

    # 添加系列、制作、发行信息到tag中
    series = json_data.series
    studio = json_data.studio
    publisher = json_data.publisher
    director = json_data.director
    if not studio and publisher:
        studio = publisher
    if not publisher and studio:
        publisher = studio

    # 系列
    if series:  # 为空时会匹配所有
        if series_translate:  # 映射
            info_data = resources.get_info_data(series)
            series = info_data.get(series_language, "")
        if series and TagInclude.SERIES in tag_include:  # 写nfo
            nfo_tag_series = manager.config.nfo_tag_series.replace("series", series)
            if nfo_tag_series:
                tag += f",{nfo_tag_series}"

    # 片商
    if studio:
        if studio_translate:
            info_data = resources.get_info_data(studio)
            studio = info_data.get(studio_language, "")
        if studio and TagInclude.STUDIO in tag_include:
            nfo_tag_studio = manager.config.nfo_tag_studio.replace("studio", studio)
            if nfo_tag_studio:
                tag += f",{nfo_tag_studio}"

    # 发行
    if publisher:
        if publisher_translate:
            info_data = resources.get_info_data(publisher)
            publisher = info_data.get(publisher_language, "")
        if publisher and TagInclude.PUBLISHER in tag_include:
            nfo_tag_publisher = manager.config.nfo_tag_publisher.replace("publisher", publisher)
            if nfo_tag_publisher:
                tag += f",{nfo_tag_publisher}"

    # 导演
    if director and director_translate:
        info_data = resources.get_info_data(director)
        director = info_data.get(director_language, "")

    if tag_language == Language.ZH_CN:
        tag = zhconv.convert(tag, "zh-cn")
    elif tag_language == Language.ZH_TW:
        tag = zhconv.convert(tag, "zh-hant")

    # tag去重/去空/排序
    tag = clean_list(tag)

    json_data.tag = tag.strip(",")
    json_data.series = series
    json_data.studio = studio
    json_data.publisher = publisher
    json_data.director = director
    return json_data


async def translate_actor(res: CrawlersResult):
    # 网络请求真实的演员名字
    actor_realname = manager.config.actor_realname
    mosaic = res.mosaic
    number = res.number

    # 非读取模式，勾选了使用真实名字时; 读取模式，勾选了允许更新真实名字时
    if actor_realname:
        start_time = time.time()
        if mosaic != "国产" and (
            number.startswith("FC2") or number.startswith("SIRO") or re.search(r"\d{3,}[A-Z]{3,}-", number)
        ):
            result, temp_actor = await get_actorname(res.number)
            if result:
                actor: str = res.actor
                actor_list = res.all_actors
                res.actor = temp_actor
                # 从actor_list中循环查找元素是否包含字符串temp_actor，有则替换
                for item in actor_list:
                    if item.find(actor) != -1:
                        actor_list[actor_list.index(item)] = temp_actor
                res.all_actors = actor_list

                LogBuffer.log().write(
                    f"\n 👩🏻 Av-wiki done! Actor's real Japanese name is '{temp_actor}' ({get_used_time(start_time)}s)"
                )
            else:
                LogBuffer.log().write(f"\n 🔴 Av-wiki failed! {temp_actor} ({get_used_time(start_time)}s)")

    # 如果不映射，返回
    if not manager.config.get_field_config(CrawlerResultFields.ACTORS).translate:
        return res

    # 映射表数据加载失败，返回
    xml_actor = resources.actor_mapping_data
    if xml_actor is not None and len(xml_actor) == 0:
        return res

    map_actor_names(res)
    map_actor_names(res, True)

    return res


def map_actor_names(res: CrawlersResult, all_actors=False):
    actors = res.all_actors if all_actors else res.actors
    field_name = CrawlerResultFields.ALL_ACTORS if all_actors else CrawlerResultFields.ACTORS
    lang = manager.config.get_field_config(field_name).language
    # 查询映射表
    mapped = []
    for name in actors:
        if not name:
            continue
        actor_data = resources.get_actor_data(name)
        mapped_name = actor_data.get(lang)
        if mapped_name not in mapped:
            mapped.append(mapped_name)

    if all_actors:
        res.all_actors = mapped
    else:
        res.actors = mapped


async def translate_title_outline(json_data: CrawlersResult, cd_part: str, movie_number: str):
    title_language = manager.config.get_field_config(CrawlerResultFields.TITLE).language
    title_translate = manager.config.get_field_config(CrawlerResultFields.TITLE).translate
    outline_language = manager.config.get_field_config(CrawlerResultFields.OUTLINE).language
    outline_translate = manager.config.get_field_config(CrawlerResultFields.OUTLINE).translate
    translate_by = manager.config.translate_config.translate_by
    if title_language == Language.JP and outline_language == Language.JP:
        return
    trans_title = ""
    trans_outline = ""
    title_sehua = manager.config.title_sehua
    title_sehua_zh = manager.config.title_sehua_zh
    title_yesjav = manager.config.title_yesjav
    title_is_jp = is_japanese(json_data.title)
    title_is_en = is_probably_english_for_translation(json_data.title)
    title_translation_applied = False
    outline_translation_applied = False

    # 处理title
    if title_language != Language.JP:
        movie_title = ""

        # 匹配本地高质量标题(色花标题数据)
        if title_sehua_zh or (title_is_jp and title_sehua):
            start_time = time.time()
            try:
                movie_title = resources.sehua_title_data.get(movie_number)
            except Exception:
                signal.show_traceback_log(traceback.format_exc())
                signal.show_log_text(traceback.format_exc())
            if movie_title:
                json_data.title = movie_title
                LogBuffer.log().write(f"\n 🌸 Sehua title done!({get_used_time(start_time)}s)")

        # 匹配网络高质量标题（yesjav， 可在线更新）
        if not movie_title and title_yesjav and title_is_jp:
            start_time = time.time()
            movie_title = await get_yesjav_title(movie_number)
            if movie_title and not is_japanese(movie_title):
                json_data.title = movie_title
                LogBuffer.log().write(f"\n 🆈 Yesjav title done!({get_used_time(start_time)}s)")

        # 使用json_data数据
        if not movie_title and title_translate and (title_is_jp or title_is_en):
            trans_title = json_data.title

    # 处理outline
    if (
        json_data.outline
        and outline_language != Language.JP
        and outline_translate
        and (is_japanese(json_data.outline) or is_probably_english_for_translation(json_data.outline))
    ):
        trans_outline = json_data.outline

    # 翻译
    if manager.config.translate_config.translate_by and (
        (trans_title and title_translate) or (trans_outline and outline_translate)
    ):
        start_time = time.time()
        translate_by_list = manager.config.translate_config.translate_by.copy()
        random.shuffle(translate_by_list)
        for each in translate_by_list:
            if skip_reason := get_translator_skip_reason(each):
                LogBuffer.log().write(f"\n 🟡 Translation skipped!({each.capitalize()}) {skip_reason}")
                continue
            result = await translate_with_engine(
                each,
                trans_title,
                trans_outline,
                title_language=title_language,
                outline_language=outline_language,
            )
            if result.error:
                LogBuffer.log().write(
                    f"\n 🔴 Translation failed!({each.capitalize()})({get_used_time(start_time)}s) Error: {result.error}"
                )
                continue
            if result.translated_title:
                json_data.title = result.title
                title_translation_applied = True
            if result.translated_outline:
                json_data.outline = result.outline
                outline_translation_applied = True
            LogBuffer.log().write(f"\n 🍀 Translation done!({each.capitalize()})({get_used_time(start_time)}s)")
            json_data.outline_from = each
            break
        else:
            LogBuffer.log().write(
                f"\n 🔴 Translation failed! {translate_by} 均失败或不可用！({get_used_time(start_time)}s)"
            )

    # 简繁转换
    if title_language == "zh_cn" and (not trans_title or title_translation_applied or not (title_is_jp or title_is_en)):
        json_data.title = zhconv.convert(json_data.title, "zh-cn")
    elif title_language == "zh_tw" and (
        not trans_title or title_translation_applied or not (title_is_jp or title_is_en)
    ):
        json_data.title = zhconv.convert(json_data.title, "zh-hant")
        json_data.mosaic = zhconv.convert(json_data.mosaic, "zh-hant")

    if outline_language == "zh_cn" and (
        not trans_outline
        or outline_translation_applied
        or not (is_japanese(json_data.outline) or is_probably_english_for_translation(json_data.outline))
    ):
        json_data.outline = zhconv.convert(json_data.outline, "zh-cn")
    elif outline_language == "zh_tw" and (
        not trans_outline
        or outline_translation_applied
        or not (is_japanese(json_data.outline) or is_probably_english_for_translation(json_data.outline))
    ):
        json_data.outline = zhconv.convert(json_data.outline, "zh-hant")

    return json_data
