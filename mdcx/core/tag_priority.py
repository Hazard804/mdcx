import random
import unicodedata

from ..config.resources import resources

_PRIORITY_START = "M女"
_PRIORITY_STOPS = {
    "kira☆kira",
    "S1 NO.1 STYLE",
}
_INFO_LANGUAGE_ATTRS = ("zh_cn", "zh_tw", "jp")
_NON_CONTENT_TAGS = {
    "16小时+",
    "16小時+",
    "16時間以上作品",
    "3D",
    "3D卡通",
    "3Dエロアニメ",
    "4K",
    "VR",
    "8K VR",
    "4小时+",
    "4小時+",
    "4小時以上作品",
    "单体作品",
    "單體作品",
    "精选合集",
    "ベスト・総集編",
    "经典老片",
    "經典老片",
    "經典",
    "个人撮影",
    "個人撮影",
    "主观视角",
    "主觀視角",
    "纪录片",
    "紀錄片",
    "ドキュメンタリー",
    "故事集",
    "西洋片",
    "形象影片",
    "寫真偶像",
    "イメージビデオ",
    "男性形象影片",
    "男寫真偶像",
    "イメージビデオ（男性）",
    "出道作品",
    "首次亮相",
    "重制版",
    "重製版",
    "複刻版",
    "成人电影",
    "成人電影",
    "法国",
    "法國",
    "韓國",
    "韩国",
    "台湾模特",
    "臺灣模特",
    "台湾モデル",
    "薄马赛克",
    "薄馬賽克",
    "ギリモザ",
    "流出",
    "破解",
    "无码",
    "無碼",
    "無修正",
}
_priority_tag_names_cache: tuple[int | None, frozenset[str]] = (None, frozenset())


def _normalize_tag(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _get_mapping_nodes():
    xml_info = resources.info_mapping_data
    if xml_info is None or not len(xml_info):
        return None, []
    return id(xml_info), xml_info.xpath("//a")


def get_priority_tag_names() -> frozenset[str]:
    """Build prioritized content tag names from mapping_info.xml output names."""
    global _priority_tag_names_cache

    mapping_id, nodes = _get_mapping_nodes()
    cached_mapping_id, cached_names = _priority_tag_names_cache
    if mapping_id == cached_mapping_id:
        return cached_names

    names: set[str] = set()
    in_priority_section = False

    for node in nodes:
        zh_cn = (node.get("zh_cn") or "").strip()
        if zh_cn == _PRIORITY_START:
            in_priority_section = True
        if not in_priority_section:
            continue
        if zh_cn in _PRIORITY_STOPS:
            break

        for attr in _INFO_LANGUAGE_ATTRS:
            value = (node.get(attr) or "").strip().strip(",")
            if not value or value == "删除" or value in _NON_CONTENT_TAGS:
                continue
            names.add(_normalize_tag(value))

    cached_names = frozenset(names)
    _priority_tag_names_cache = (mapping_id, cached_names)
    return cached_names


def clear_priority_tag_cache() -> None:
    global _priority_tag_names_cache
    _priority_tag_names_cache = (None, frozenset())


def _is_template_tag(tag: str, template: str, placeholder: str) -> bool:
    if placeholder not in template:
        return False

    prefix, suffix = template.split(placeholder, 1)
    prefix = _normalize_tag(prefix)
    suffix = _normalize_tag(suffix)
    normalized = _normalize_tag(tag)

    if not prefix and not suffix:
        return False
    if prefix and not normalized.startswith(prefix):
        return False
    if suffix and not normalized.endswith(suffix):
        return False

    value_start = len(prefix)
    value_end = len(normalized) - len(suffix) if suffix else len(normalized)
    return bool(normalized[value_start:value_end].strip())


def prioritize_nfo_tags(tags: list[str], series_tag: str = "", series_template: str = "") -> list[str]:
    priority_names = get_priority_tag_names()
    if not priority_names or len(tags) < 2:
        return tags

    priority_tags: list[str] = []
    series_tags: list[str] = []
    other_tags: list[str] = []
    normalized_series_tag = _normalize_tag(series_tag) if series_tag else ""

    for tag in tags:
        normalized = _normalize_tag(tag)
        if normalized in priority_names:
            priority_tags.append(tag)
        elif (normalized_series_tag and normalized == normalized_series_tag) or _is_template_tag(
            tag, series_template, "series"
        ):
            series_tags.append(tag)
        else:
            other_tags.append(tag)

    if not priority_tags:
        return tags

    random.shuffle(priority_tags)
    return priority_tags + series_tags + other_tags
