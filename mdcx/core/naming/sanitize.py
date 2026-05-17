import re

from ...consts import IS_WINDOWS
from ...utils import nfd2c

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def cleanup_rendered_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", str(text or ""))
    return text.strip()


def _avoid_windows_reserved_name(segment: str) -> str:
    if not IS_WINDOWS:
        return segment
    name, dot, suffix = segment.partition(".")
    if name.rstrip(". ").upper() in WINDOWS_RESERVED_NAMES:
        return f"{name}_{dot}{suffix}"
    return segment


def _sanitize_segment(segment: str, *, strip_hyphen: bool) -> str:
    segment = re.sub(r"[ \t]{2,}", " ", segment)
    segment = segment.replace("--", "-").strip()
    if strip_hyphen:
        segment = segment.strip("- .")
    segment = segment.rstrip(". ").strip()
    segment = _avoid_windows_reserved_name(segment)
    return segment


def sanitize_name(text: str, *, allow_path_separator: bool) -> str:
    text = cleanup_rendered_text(text)
    if allow_path_separator:
        text = re.sub(r'[\\:*?"<>|\r\n]+', "", text).strip(" /")
        text = re.sub(r"/{2,}", "/", text)
        text = text.replace(" /", "/").replace("/ ", "/")
        parts = [_sanitize_segment(part, strip_hyphen=False) for part in text.split("/")]
        text = "/".join(part for part in parts if part and part.strip("._- "))
        text = text.strip("- .")
    else:
        text = re.sub(r'[\\/:*?"<>|\r\n]+', "", text).strip()
        text = _sanitize_segment(text, strip_hyphen=True)
    return nfd2c(text)
