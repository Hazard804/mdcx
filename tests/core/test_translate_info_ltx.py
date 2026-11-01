import pytest

from mdcx.config.enums import TagInclude
from mdcx.config.manager import manager
from mdcx.core.mosaic import LTX_CRACK_TAG, LTX_DESTROYED
from mdcx.core.translate import translate_info
from mdcx.models.types import CrawlersResult


def _build_result() -> CrawlersResult:
    res = CrawlersResult.empty()
    res.mosaic = "无码破解"
    res.tag = ""
    res.actors = []
    return res


@pytest.mark.parametrize(
    ("destroyed", "include_ltx_crack", "expected"),
    [
        (LTX_DESTROYED, True, ["无码破解", LTX_CRACK_TAG]),
        (LTX_DESTROYED, False, ["无码破解"]),
        ("  -ltx ", True, ["无码破解", LTX_CRACK_TAG]),
        ("-U", True, ["无码破解"]),
        ("-UC", True, ["无码破解"]),
        ("", True, ["无码破解"]),
    ],
)
def test_translate_info_appends_ltx_crack_tag(
    monkeypatch: pytest.MonkeyPatch,
    destroyed: str,
    include_ltx_crack: bool,
    expected: list[str],
):
    includes = [TagInclude.MOSAIC]
    if include_ltx_crack:
        includes.append(TagInclude.LTX_CRACK)
    monkeypatch.setattr(manager.config, "nfo_tag_include", includes)

    res = _build_result()
    translate_info(res, False, destroyed)

    assert res.tag.split(",") == expected


def test_translate_info_ltx_crack_tag_ignores_duplicate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "nfo_tag_include", [TagInclude.MOSAIC, TagInclude.LTX_CRACK])

    res = _build_result()
    res.tag = LTX_CRACK_TAG
    translate_info(res, False, LTX_DESTROYED)

    assert res.tag.split(",").count(LTX_CRACK_TAG) == 1
