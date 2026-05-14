from lxml import etree

from mdcx.config.resources import resources


def test_get_info_data_matches_output_language_attrs(monkeypatch):
    xml_info = etree.fromstring(
        """
        <info>
          <a zh_cn="苗条" zh_tw="苗條" jp="スレンダー" keyword=",纖細,苗条的,苗條的," />
        </info>
        """.encode()
    )
    monkeypatch.setattr(resources, "info_mapping_data", xml_info)

    info_data = resources.get_info_data("スレンダー")

    assert info_data["has_name"] is True
    assert info_data["zh_cn"] == "苗条"
    assert info_data["zh_tw"] == "苗條"
    assert info_data["jp"] == "スレンダー"


def test_get_info_data_keeps_keyword_matching(monkeypatch):
    xml_info = etree.fromstring(
        """
        <info>
          <a zh_cn="足交" zh_tw="足交" jp="足交" keyword=",足コキ,足交," />
        </info>
        """.encode()
    )
    monkeypatch.setattr(resources, "info_mapping_data", xml_info)

    info_data = resources.get_info_data("足コキ")

    assert info_data["has_name"] is True
    assert info_data["zh_cn"] == "足交"
