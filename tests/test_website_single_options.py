from pathlib import Path

from mdcx.config.enums import Website


def test_fc2ppvdb_is_available_in_single_website_options():
    view_source = Path("mdcx/views/MDCx.py").read_text(encoding="utf-8")

    assert f'"{Website.FC2PPVDB.value}"' in view_source


def test_javdbapi_is_available_in_single_website_options():
    view_source = Path("mdcx/views/MDCx.py").read_text(encoding="utf-8")

    assert f'"{Website.JAVDBAPI.value}"' in view_source
