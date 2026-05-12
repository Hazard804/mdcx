import pytest
from lxml import etree

from mdcx.config.enums import NfoInclude
from mdcx.core import nfo as nfo_module
from mdcx.core import tag_priority
from mdcx.models.types import CrawlersResult, FileInfo


class _RenderedTitle:
    def __init__(self, text: str):
        self.text = text


def _mapping_info_xml():
    return etree.fromstring(
        """
        <info>
          <a zh_cn="删除" zh_tw="删除" jp="删除" keyword=",中文,中文字幕,字幕," />
          <a zh_cn="16小时+" zh_tw="16小時+" jp="16時間以上作品" keyword=",16小时+," />
          <a zh_cn="M女" zh_tw="M女" jp="M女" keyword=",M女," />
          <a zh_cn="潮吹" zh_tw="潮吹" jp="潮吹" keyword=",潮吹," />
          <a zh_cn="OL制服" zh_tw="商務套裝" jp="OL" keyword=",OL," />
          <a zh_cn="中出" zh_tw="中出" jp="中出" keyword=",中出," />
          <a zh_cn="口交" zh_tw="口交" jp="フェラ" keyword=",口交,フェラ," />
          <a zh_cn="巨乳" zh_tw="巨乳" jp="巨乳" keyword=",巨乳," />
          <a zh_cn="无码" zh_tw="無碼" jp="無修正" keyword=",无码,無碼,無修正," />
          <a zh_cn="kira☆kira" zh_tw="kira☆kira" jp="kira☆kira" keyword=",kira☆kira," />
          <a zh_cn="S1 NO.1 STYLE" zh_tw="S1 NO.1 STYLE" jp="S1 NO.1 STYLE" keyword=",S1 NO.1 STYLE," />
        </info>
        """.encode()
    )


@pytest.fixture(autouse=True)
def _priority_mapping(monkeypatch: pytest.MonkeyPatch):
    tag_priority.clear_priority_tag_cache()
    monkeypatch.setattr(tag_priority.resources, "info_mapping_data", _mapping_info_xml())
    yield
    tag_priority.clear_priority_tag_cache()


def test_prioritize_nfo_tags_uses_mapping_info_names_for_all_languages(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tag_priority.random, "shuffle", lambda items: items.reverse())

    tags = ["系列: 测试", "S1 NO.1 STYLE", "中出", "フェラ", "無碼", "巨乳", "16小时+"]

    assert tag_priority.prioritize_nfo_tags(tags, series_tag="系列: 测试", series_template="系列: series") == [
        "巨乳",
        "フェラ",
        "中出",
        "系列: 测试",
        "S1 NO.1 STYLE",
        "無碼",
        "16小时+",
    ]


def test_prioritize_nfo_tags_matches_series_by_template_when_value_was_mapped(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(tag_priority.random, "shuffle", lambda items: items.reverse())

    tags = ["潮吹", "OL制服", "SDJS", "中山秋穂", "系列: SOD女子社员", "片商: SOD"]

    assert tag_priority.prioritize_nfo_tags(
        tags,
        series_tag="系列: SOD女子社員",
        series_template="系列: series",
    ) == ["OL制服", "潮吹", "系列: SOD女子社员", "SDJS", "中山秋穂", "片商: SOD"]


def _build_file_info(tmp_path) -> FileInfo:
    file_info = FileInfo.empty()
    file_info.number = "ABC-123"
    file_info.file_path = tmp_path / "ABC-123.mp4"
    file_info.folder_path = tmp_path
    file_info.file_name = "ABC-123"
    return file_info


def _configure_nfo_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nfo_module.manager.config, "download_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "keep_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "outline_format", [])
    monkeypatch.setattr(nfo_module.manager.config, "main_mode", 1)
    monkeypatch.setattr(nfo_module.manager.config, "naming_media", "number title")
    monkeypatch.setattr(nfo_module.manager.config, "update_titletemplate", "number title")
    monkeypatch.setattr(nfo_module.manager.config, "nfo_include_new", [NfoInclude.TAG, NfoInclude.GENRE])
    monkeypatch.setattr(nfo_module.manager.config, "nfo_tag_series", "系列: series")
    monkeypatch.setattr(nfo_module.manager.config, "actor_no_name", "佚名")


@pytest.mark.asyncio
async def test_write_nfo_prioritizes_tag_and_genre_with_same_order(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _configure_nfo_writer(monkeypatch)
    monkeypatch.setattr(nfo_module, "render_name", lambda *args, **kwargs: _RenderedTitle("模板标题"))
    monkeypatch.setattr(tag_priority.random, "shuffle", lambda items: items.reverse())

    data = CrawlersResult.empty()
    data.number = "ABC-123"
    data.title = "标题"
    data.originaltitle = "原标题"
    data.series = "测试"
    data.tags = ["系列: 测试", "S1 NO.1 STYLE", "中出", "フェラ", "無碼", "巨乳", "16小时+"]

    nfo_file = tmp_path / "ABC-123.nfo"
    result = await nfo_module.write_nfo(_build_file_info(tmp_path), data, nfo_file, tmp_path, update=True)

    assert result is True
    root = etree.fromstring(nfo_file.read_text(encoding="utf-8").encode("utf-8"))
    expected = ["巨乳", "フェラ", "中出", "系列: 测试", "S1 NO.1 STYLE", "無碼", "16小时+"]
    assert root.xpath("//tag/text()") == expected
    assert root.xpath("//genre/text()") == expected
