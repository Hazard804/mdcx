import re
from dataclasses import dataclass, field
from enum import Enum

from ...models.types import CrawlersResult, FileInfo
from .fields import TRUNCATE_PRIORITY, NamingContext, build_naming_context
from .sanitize import cleanup_rendered_text, sanitize_name
from .template import render_template

LIST_TRUNCATE_FIELDS = {"actor", "all_actor", "director"}


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


def _smart_truncate(
    template: str,
    values: dict[str, str],
    target: NamingTarget,
    max_length: int,
) -> tuple[str, list[str]]:
    text = _render_with_values(template, values, target)
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
        text = _render_with_values(template, mutable_values, target)

    if len(text) > max_length:
        text = text[:max_length].rstrip(" ,，、;；:：._+-")
        text = _finalize_text(text, target)
    return text, truncated_fields


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

    text, truncated_fields = _smart_truncate(
        template,
        values,
        options.target,
        int(options.max_length or 0),
    )
    fallback = context.get("number") or context.get("title") or context.get("filename") or "MDCx"
    if not text:
        text = sanitize_name(fallback, allow_path_separator=False)
    return NameRenderResult(text=text, template=template, context=context, truncated_fields=truncated_fields)
