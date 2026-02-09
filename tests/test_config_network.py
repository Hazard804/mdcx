from mdcx.config.models import Config


def test_config_update_normalizes_cf_bypass_proxy_scheme():
    data = {"cf_bypass_proxy": "127.0.0.1:7890"}

    Config.update(data)

    assert data["cf_bypass_proxy"] == "http://127.0.0.1:7890"


def test_config_update_keeps_cf_bypass_proxy_with_existing_scheme():
    data = {"cf_bypass_proxy": "socks5://127.0.0.1:7890"}

    Config.update(data)

    assert data["cf_bypass_proxy"] == "socks5://127.0.0.1:7890"
