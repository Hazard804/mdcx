from mdcx.crawlers.base.compat import _select_language_payload

from mdcx.config.models import Language


def test_select_language_payload_prefers_requested_language():
    payloads = {
        "jp": {"title": "jp", "outline": "jp"},
        "zh_cn": {"title": "zh_cn", "outline": "zh_cn"},
        "zh_tw": {"title": "zh_tw", "outline": "zh_tw"},
    }

    res = _select_language_payload(payloads, Language.ZH_CN, Language.ZH_CN)

    assert res["title"] == "zh_cn"


def test_select_language_payload_falls_back_to_other_chinese_variant():
    payloads = {
        "jp": {"title": "jp", "outline": "jp"},
        "zh_tw": {"title": "zh_tw", "outline": "zh_tw"},
    }

    res = _select_language_payload(payloads, Language.ZH_CN, Language.ZH_CN)

    assert res["title"] == "zh_tw"


def test_select_language_payload_keeps_single_language_behavior():
    payloads = {
        "zh_cn": {"title": "only", "outline": "only"},
    }

    res = _select_language_payload(payloads, Language.JP, Language.UNDEFINED)

    assert res["title"] == "only"
