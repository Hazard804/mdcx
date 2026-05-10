"""
Mosaic labels are post-processing metadata, not scraping media types.

The helpers in this module keep string compatibility with existing NFO/tag
values while giving callers explicit predicates for watermarking and
classification.
"""

from __future__ import annotations

CENSORED_MOSAIC = "有码"
UNCENSORED_MOSAIC = "无码"
UMR_MOSAIC = "无码破解"
LEAK_MOSAIC = "流出"
UNCENSORED_LEAK_MOSAIC = "无码流出"
GUOCHAN_MOSAIC = "国产"

_CENSORED_VALUES = {"有码", "有碼"}
_UNCENSORED_VALUES = {"无码", "無碼", "無修正"}
_GUOCHAN_VALUES = {"国产", "國產"}
_SPECIAL_VALUES = {"里番", "裏番", "动漫", "動漫", "同人", "书籍"}


def normalize_mosaic(value: object) -> str:
    """Normalize known mosaic labels to stable simplified Chinese values."""
    mosaic = str(value or "").strip()
    if not mosaic:
        return ""

    if mosaic in _GUOCHAN_VALUES:
        return GUOCHAN_MOSAIC
    if mosaic in _CENSORED_VALUES:
        return CENSORED_MOSAIC
    if mosaic in _UNCENSORED_VALUES:
        return UNCENSORED_MOSAIC
    if mosaic in _SPECIAL_VALUES:
        return mosaic.replace("裏番", "里番").replace("動漫", "动漫")

    has_uncensored = any(word in mosaic for word in _UNCENSORED_VALUES)
    if "破解" in mosaic:
        return UMR_MOSAIC
    if "流出" in mosaic:
        return UNCENSORED_LEAK_MOSAIC if has_uncensored else LEAK_MOSAIC

    return mosaic


def is_plain_uncensored_mosaic(value: object) -> bool:
    """Whether this label means plain uncensored media for scrape classification."""
    return normalize_mosaic(value) == UNCENSORED_MOSAIC


def is_censored_mosaic(value: object) -> bool:
    return normalize_mosaic(value) == CENSORED_MOSAIC


def is_guochan_mosaic(value: object) -> bool:
    return normalize_mosaic(value) == GUOCHAN_MOSAIC


def has_uncensored_mark(value: object) -> bool:
    """Whether post-processing should treat the label as having uncensored content."""
    return normalize_mosaic(value) in {UNCENSORED_MOSAIC, UMR_MOSAIC, UNCENSORED_LEAK_MOSAIC}


def has_umr_mark(value: object) -> bool:
    return normalize_mosaic(value) == UMR_MOSAIC


def has_leak_mark(value: object) -> bool:
    return normalize_mosaic(value) in {LEAK_MOSAIC, UNCENSORED_LEAK_MOSAIC}
