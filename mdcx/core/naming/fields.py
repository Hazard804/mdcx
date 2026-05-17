import os
from dataclasses import dataclass

from ...base.number import deal_actor_more
from ...config.manager import manager
from ...models.types import CrawlersResult, FileInfo
from ...number import get_number_first_letters
from ...utils import get_new_release, split_path

FIELD_DESCRIPTIONS: dict[str, str] = {
    "number": "番号",
    "title": "标题",
    "originaltitle": "原标题",
    "actor": "演员",
    "first_actor": "首位演员",
    "all_actor": "全部演员",
    "letters": "番号前缀",
    "first_letters": "番号首字符",
    "outline": "简介",
    "director": "导演",
    "series": "系列",
    "studio": "片商",
    "publisher": "发行商",
    "release": "发行日期",
    "year": "年份",
    "runtime": "时长",
    "mosaic": "有码/无码",
    "definition": "清晰度",
    "cnword": "字幕标识",
    "moword": "版本标识",
    "filename": "原文件名",
    "wanted": "想看人数",
    "score": "评分",
    "four_k": "4K 标识",
}

FIELD_NAMES = tuple(FIELD_DESCRIPTIONS)
TRUNCATE_PRIORITY = (
    "outline",
    "originaltitle",
    "title",
    "actor",
    "all_actor",
    "series",
    "studio",
    "publisher",
    "director",
    "filename",
    "release",
    "number",
)


@dataclass(frozen=True)
class NamingContext:
    values: dict[str, str]
    raw_values: dict[str, str]

    def get(self, field: str) -> str:
        return self.values.get(field, "")


def _clean_field_value(value: object, escape_path_separator: bool) -> str:
    text = str(value or "")
    if escape_path_separator:
        text = text.replace("/", "-").replace("\\", "-").strip(". ")
    return text


def build_naming_context(
    file_info: FileInfo,
    data: CrawlersResult,
    *,
    show_definition_suffix: bool,
    show_cnword_suffix: bool,
    show_moword_suffix: bool,
    escape_path_separator: bool,
) -> NamingContext:
    """构建命名模板需要的全部字段值。"""

    _, file_full_name = split_path(file_info.file_path)
    filename = os.path.splitext(file_full_name)[0]

    destroyed = file_info.destroyed
    leak = file_info.leak
    wuma = file_info.wuma
    youma = file_info.youma
    moword = destroyed + leak + wuma + youma
    cnword = file_info.c_word
    definition = file_info.definition.replace("UHD8", "UHD")

    number = data.number
    title = data.title
    if not number:
        number = title or filename

    definition_suffix = ""
    if show_definition_suffix and definition in {"8K", "UHD", "4K"}:
        definition_suffix = f"-{definition}"

    suffix_values = {
        "moword": moword if show_moword_suffix else "",
        "cnword": cnword if show_cnword_suffix else "",
        "definition": definition_suffix,
    }
    for suffix in manager.config.suffix_sort:
        number += suffix_values.get(getattr(suffix, "value", str(suffix)), "")

    actor = data.actor or manager.config.actor_no_name
    first_actor = actor.split(",")[0] if actor else ""
    all_actor = deal_actor_more(data.all_actor)
    actor = deal_actor_more(actor)

    score = str(data.score or "0.0")
    year = str(data.year or "0000")
    release = get_new_release(data.release, manager.config.release_rule)
    first_letters = get_number_first_letters(number)
    four_k = definition if definition in {"8K", "UHD", "4K"} else ""

    raw_values = {
        "number": number,
        "title": title,
        "originaltitle": data.originaltitle,
        "actor": actor,
        "first_actor": first_actor,
        "all_actor": all_actor,
        "letters": data.letters,
        "first_letters": first_letters,
        "outline": data.outline,
        "director": data.director,
        "series": data.series or "未知系列",
        "studio": data.studio,
        "publisher": data.publisher,
        "release": release,
        "year": year,
        "runtime": data.runtime,
        "mosaic": data.mosaic,
        "definition": definition,
        "cnword": cnword,
        "moword": moword,
        "filename": filename,
        "wanted": str(data.wanted or ""),
        "score": score,
        "four_k": four_k,
    }
    values = {field: _clean_field_value(value, escape_path_separator) for field, value in raw_values.items()}
    return NamingContext(values=values, raw_values=raw_values)
