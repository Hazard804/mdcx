from mdcx.config.models import Language
from mdcx.crawlers.javlibrary import language_path, normalize_language


def test_normalize_language_keeps_language_enum():
    assert normalize_language(Language.ZH_CN) is Language.ZH_CN


def test_normalize_language_accepts_language_value():
    assert normalize_language("zh_tw") is Language.ZH_TW


def test_normalize_language_keeps_unknown_language_value():
    assert normalize_language("unknown") is Language.UNKNOWN


def test_language_path_maps_supported_javlibrary_languages():
    assert language_path(Language.ZH_CN) == "cn"
    assert language_path(Language.ZH_TW) == "tw"
    assert language_path(Language.JP) == "ja"
