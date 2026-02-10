from mdcx.config.enums import Website
from mdcx.core.nfo import get_external_id_tag_name


def test_get_external_id_tag_name_for_normal_site():
    assert get_external_id_tag_name(Website.JAVDB) == "javdbid"


def test_get_external_id_tag_name_for_site_starting_with_digit():
    assert get_external_id_tag_name(Website.MMTV) == "mmtvid"
