import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from ...models.types import CrawlersResult, FileInfo
from .fields import TRUNCATE_PRIORITY, NamingContext, build_naming_context
from .sanitize import cleanup_rendered_text, sanitize_folder_segment, sanitize_name
from .template import render_template

LIST_TRUNCATE_FIELDS = {"actor", "all_actor", "director"}
BLOCK_START_TAGS = {"autoescape", "block", "call", "filter", "for", "if", "macro", "raw", "with"}


class NamingTarget(Enum):
    FOLDER = "folder"
    FILE = "file"
    NFO_TITLE = "nfo_title"


@dataclass(frozen=True)
class NameRenderOptions:
    target: NamingTarget
    show_definition_suffix: bool = False
    show_cnword_suffix: bool = False
    show_moword_suffix: bool = False
    max_length: int | None = None


@dataclass(frozen=True)
class NameRenderResult:
    text: str
    template: str
    context: NamingContext
    truncated_fields: list[str] = field(default_factory=list)

    def value(self, field: str) -> str:
        return self.context.get(field)


def _clip_text(value: str, max_length: int) -> str:
    if max_length <= 0:
        return ""
    if len(value) <= max_length:
        return value
    return value[:max_length].rstrip(" ,，、;；:：._+-")


def _clip_list(value: str, max_length: int) -> str:
    if max_length <= 0:
        return ""
    if len(value) <= max_length:
        return value

    delimiter_match = re.search(r"[,，、]", value)
    if not delimiter_match:
        return ""

    delimiter = delimiter_match.group(0)
    parts = [part.strip() for part in re.split(r"[,，、]", value) if part.strip()]
    kept: list[str] = []
    for part in parts:
        candidate = delimiter.join([*kept, part])
        if len(candidate) > max_length:
            break
        kept.append(part)
    return delimiter.join(kept)


def _clip_field(field_name: str, value: str, max_length: int) -> str:
    if field_name in LIST_TRUNCATE_FIELDS:
        return _clip_list(value, max_length)
    return _clip_text(value, max_length)


def _finalize_text(text: str, target: NamingTarget) -> str:
    if target == NamingTarget.NFO_TITLE:
        return cleanup_rendered_text(text)
    return sanitize_name(text, allow_path_separator=target == NamingTarget.FOLDER)


def _render_with_values(template: str, values: dict[str, str], target: NamingTarget) -> str:
    return _finalize_text(render_template(template, values), target)


def _render_folder_segment_with_values(template: str, values: dict[str, str]) -> str:
    return sanitize_folder_segment(render_template(template, values))


def _dedupe_fields(fields: list[str]) -> list[str]:
    result: list[str] = []
    for field_name in fields:
        if field_name not in result:
            result.append(field_name)
    return result


def _get_block_tag_name(tag: str) -> str:
    return tag.strip().split(None, 1)[0] if tag.strip() else ""


def _split_folder_template_segments(template: str) -> list[str] | None:
    segments: list[str] = []
    current: list[str] = []
    block_depth = 0
    index = 0
    text = str(template or "").replace("\\", "/")

    while index < len(text):
        if text.startswith("{{", index):
            end = text.find("}}", index + 2)
            if end == -1:
                return None
            current.append(text[index : end + 2])
            index = end + 2
            continue
        if text.startswith("{#", index):
            end = text.find("#}", index + 2)
            if end == -1:
                return None
            current.append(text[index : end + 2])
            index = end + 2
            continue
        if text.startswith("{%", index):
            end = text.find("%}", index + 2)
            if end == -1:
                return None
            tag = text[index + 2 : end]
            tag_name = _get_block_tag_name(tag)
            if tag_name.startswith("end"):
                block_depth = max(block_depth - 1, 0)
            elif tag_name in BLOCK_START_TAGS:
                block_depth += 1
            current.append(text[index : end + 2])
            index = end + 2
            continue

        char = text[index]
        if char == "/":
            if block_depth > 0:
                return None
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1

    segments.append("".join(current))
    return segments


def _smart_truncate(
    template: str,
    values: dict[str, str],
    target: NamingTarget,
    max_length: int,
    render_func: Callable[[str, dict[str, str]], str] | None = None,
    finalize_func: Callable[[str], str] | None = None,
) -> tuple[str, list[str]]:
    def render(current_template: str, current_values: dict[str, str]) -> str:
        if render_func:
            return render_func(current_template, current_values)
        return _render_with_values(current_template, current_values, target)

    finalize = finalize_func or (lambda current_text: _finalize_text(current_text, target))
    text = render(template, values)
    if max_length <= 0 or len(text) <= max_length:
        return text, []

    truncated_fields: list[str] = []
    mutable_values = values.copy()
    for field_name in TRUNCATE_PRIORITY:
        if len(text) <= max_length:
            break
        current = mutable_values.get(field_name, "")
        if not current:
            continue
        overflow = len(text) - max_length
        next_length = max(len(current) - overflow, 0)
        next_value = _clip_field(field_name, current, next_length)
        if next_value == current:
            continue
        mutable_values[field_name] = next_value
        truncated_fields.append(field_name)
        text = render(template, mutable_values)

    if len(text) > max_length:
        text = text[:max_length].rstrip(" ,，、;；:：._+-")
        text = finalize(text)
    return text, truncated_fields


def _smart_truncate_folder_path(
    template: str,
    values: dict[str, str],
    max_length: int,
) -> tuple[str, list[str]]:
    """按目录层级缩短，避免同名字段在不同目录段互相影响。"""

    parts: list[str] = []
    truncated_fields: list[str] = []
    segments = _split_folder_template_segments(template)
    if segments is None:
        return _smart_truncate(template, values, NamingTarget.FOLDER, max_length)

    for segment_template in segments:
        text, fields = _smart_truncate(
            segment_template,
            values,
            NamingTarget.FOLDER,
            max_length,
            render_func=_render_folder_segment_with_values,
            finalize_func=sanitize_folder_segment,
        )
        if text:
            parts.append(text)
        truncated_fields.extend(fields)

    text = sanitize_name("/".join(parts), allow_path_separator=True)
    return text, _dedupe_fields(truncated_fields)


def render_name(
    template: str, file_info: FileInfo, data: CrawlersResult, options: NameRenderOptions
) -> NameRenderResult:
    context = build_naming_context(
        file_info,
        data,
        show_definition_suffix=options.show_definition_suffix,
        show_cnword_suffix=options.show_cnword_suffix,
        show_moword_suffix=options.show_moword_suffix,
        escape_path_separator=options.target != NamingTarget.NFO_TITLE,
    )
    values = context.values.copy()
    values["fields"] = context.values

    max_length = int(options.max_length or 0)
    if options.target == NamingTarget.FOLDER:
        text, truncated_fields = _smart_truncate_folder_path(template, values, max_length)
    else:
        text, truncated_fields = _smart_truncate(
            template,
            values,
            options.target,
            max_length,
        )
    fallback = context.get("number") or context.get("title") or context.get("filename") or "MDCx"
    if not text:
        text = sanitize_name(fallback, allow_path_separator=False)
    return NameRenderResult(text=text, template=template, context=context, truncated_fields=truncated_fields)
