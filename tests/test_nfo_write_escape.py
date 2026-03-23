import pytest
from lxml import etree

from mdcx.config.enums import NfoInclude, Website
from mdcx.core import nfo as nfo_module
from mdcx.models.types import CrawlersResult, FileInfo


def _build_file_info(tmp_path) -> FileInfo:
    file_info = FileInfo.empty()
    file_info.number = "ABC-123"
    file_info.file_path = tmp_path / "ABC-123.mp4"
    file_info.folder_path = tmp_path
    file_info.file_name = "ABC-123"
    return file_info


def _configure_nfo_writer(monkeypatch: pytest.MonkeyPatch, includes: list[NfoInclude]) -> None:
    monkeypatch.setattr(nfo_module.manager.config, "download_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "keep_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "outline_format", [])
    monkeypatch.setattr(nfo_module.manager.config, "main_mode", 1)
    monkeypatch.setattr(nfo_module.manager.config, "naming_media", "number title")
    monkeypatch.setattr(nfo_module.manager.config, "update_titletemplate", "number title")
    monkeypatch.setattr(nfo_module.manager.config, "nfo_include_new", includes)
    monkeypatch.setattr(nfo_module.manager.config, "nfo_tagline", "说明 & release")
    monkeypatch.setattr(nfo_module.manager.config, "actor_no_name", "佚名")


@pytest.mark.asyncio
async def test_write_nfo_keeps_cdata_fields_unescaped(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _configure_nfo_writer(
        monkeypatch,
        [
            NfoInclude.PLOT_,
            NfoInclude.OUTLINE,
            NfoInclude.ORIGINALPLOT,
        ],
    )
    monkeypatch.setattr(
        nfo_module,
        "render_name_template",
        lambda *args, **kwargs: ("模板标题", "", "", "", "", ""),
    )

    file_info = _build_file_info(tmp_path)
    data = CrawlersResult.empty()
    data.number = "ABC-123"
    data.title = "标题"
    data.originaltitle = "原标题"
    data.outline = "中文简介 A&amp;B"
    data.originalplot = "日文简介 C&amp;D ]]> E"

    nfo_file = tmp_path / "ABC-123.nfo"
    result = await nfo_module.write_nfo(file_info, data, nfo_file, tmp_path, update=True)

    assert result is True
    content = nfo_file.read_text(encoding="utf-8")
    assert "<plot><![CDATA[中文简介 A&B]]></plot>" in content
    assert "<outline><![CDATA[中文简介 A&B]]></outline>" in content
    assert "<originalplot><![CDATA[日文简介 C&D ]]]]><![CDATA[> E]]></originalplot>" in content

    root = etree.fromstring(content.encode("utf-8"))
    assert root.findtext("plot") == "中文简介 A&B"
    assert root.findtext("outline") == "中文简介 A&B"
    assert root.findtext("originalplot") == "日文简介 C&D ]]> E"


@pytest.mark.asyncio
async def test_write_nfo_escapes_non_cdata_fields_without_double_escape(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _configure_nfo_writer(
        monkeypatch,
        [
            NfoInclude.PLOT_,
            NfoInclude.OUTLINE,
            NfoInclude.ORIGINALPLOT,
            NfoInclude.OUTLINE_NO_CDATA,
            NfoInclude.ORIGINALTITLE,
            NfoInclude.SORTTITLE,
            NfoInclude.ACTOR,
            NfoInclude.DIRECTOR,
            NfoInclude.SERIES,
            NfoInclude.SERIES_SET,
            NfoInclude.STUDIO,
            NfoInclude.PUBLISHER,
            NfoInclude.TAG,
            NfoInclude.GENRE,
            NfoInclude.POSTER,
            NfoInclude.COVER,
            NfoInclude.TRAILER,
        ],
    )
    monkeypatch.setattr(
        nfo_module,
        "render_name_template",
        lambda *args, **kwargs: ("模板&amp;标题", "", "", "", "", ""),
    )

    file_info = _build_file_info(tmp_path)
    data = CrawlersResult.empty()
    data.number = "ABC-123"
    data.title = "主标题&amp;别名"
    data.originaltitle = "原标题&amp;别名"
    data.outline = "简介&amp;内容"
    data.originalplot = "原始简介&amp;内容"
    data.release = "2025-01-01"
    data.actors = ["演员A&B", "演员C&amp;D"]
    data.directors = ["导演A&B"]
    data.series = "系列A&amp;B"
    data.studio = "片商A&B"
    data.publisher = "发行A&amp;B"
    data.tags = ["标签A&B", "标签C&amp;D"]
    data.poster = "https://example.com/poster?a=1&b=2"
    data.thumb = "https://example.com/cover?a=1&amp;b=2"
    data.trailer = "https://example.com/trailer?a=1&b=2"
    data.external_ids = {
        Website.JAVDB: "javdb?id=1&lang=zh",
        Website.MMTV: "mmtv&amp;id=2",
    }

    nfo_file = tmp_path / "ABC-123.nfo"
    result = await nfo_module.write_nfo(file_info, data, nfo_file, tmp_path, update=True)

    assert result is True
    content = nfo_file.read_text(encoding="utf-8")
    assert "<title>模板&amp;标题</title>" in content
    assert "<plot>简介&amp;内容</plot>" in content
    assert "<originalplot>原始简介&amp;内容</originalplot>" in content
    assert "<tagline>说明 &amp; 2025-01-01</tagline>" in content
    assert "<poster>https://example.com/poster?a=1&amp;b=2</poster>" in content
    assert "<cover>https://example.com/cover?a=1&amp;b=2</cover>" in content
    assert "<trailer>https://example.com/trailer?a=1&amp;b=2</trailer>" in content
    assert "<javdbid>javdb?id=1&amp;lang=zh</javdbid>" in content
    assert "<mmtvid>mmtv&amp;id=2</mmtvid>" in content
    assert "&amp;amp;" not in content

    root = etree.fromstring(content.encode("utf-8"))
    assert root.findtext("title") == "模板&标题"
    assert root.findtext("plot") == "简介&内容"
    assert root.findtext("originalplot") == "原始简介&内容"
    assert root.findtext("poster") == "https://example.com/poster?a=1&b=2"
    assert root.findtext("cover") == "https://example.com/cover?a=1&b=2"
    assert root.findtext("trailer") == "https://example.com/trailer?a=1&b=2"
    assert root.findtext("javdbid") == "javdb?id=1&lang=zh"
    assert root.findtext("mmtvid") == "mmtv&id=2"
    assert root.xpath("//actor/name/text()") == ["演员A&B", "演员C&D"]
    assert root.xpath("//director/text()") == ["导演A&B"]
    assert root.xpath("//tag/text()") == ["标签A&B", "标签C&D"]
    assert root.xpath("//genre/text()") == ["标签A&B", "标签C&D"]
