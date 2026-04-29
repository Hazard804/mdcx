from mdcx.config.enums import Website
from mdcx.config.models import Config
from mdcx.crawlers import get_registered_crawler_site_values


def test_fc2ppvdb_is_available_in_single_website_options():
    registered_sites = get_registered_crawler_site_values()

    assert Website.FC2PPVDB.value in registered_sites


def test_javdbapi_is_available_in_single_website_options():
    registered_sites = get_registered_crawler_site_values()

    assert Website.JAVDBAPI.value in registered_sites


def test_config_website_schema_uses_registered_crawler_sites():
    website_schema = Config.json_schema()["$defs"]["Website"]
    registered_sites = get_registered_crawler_site_values()

    assert website_schema["enum"] == registered_sites
    assert Website.AIRAV.value not in website_schema["enum"]
