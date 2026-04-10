from types import SimpleNamespace

import pytest

from mdcx.config.enums import Language
from mdcx.core import nfo as nfo_module
from mdcx.gen.field_enums import CrawlerResultFields


@pytest.mark.asyncio
async def test_get_nfo_data_reads_multiline_plot_via_xpath(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(nfo_module.manager.config, "read_mode", [])
    monkeypatch.setattr(
        nfo_module.manager.config.__class__,
        "get_field_config",
        lambda self, field: SimpleNamespace(
            language=Language.ZH_CN if field == CrawlerResultFields.OUTLINE else Language.JP
        ),
    )

    video_path = tmp_path / "JUMS-150.mp4"
    video_path.write_bytes(b"")
    nfo_path = tmp_path / "JUMS-150.nfo"
    nfo_path.write_text(
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>[JUMS-150]巡 一周年8小时</title>
  <originaltitle>JUMS-150 めぐり The First Anniversary 8時間</originaltitle>
  <num>JUMS-150</num>
  <plot><![CDATA[中文简介第一段

中文简介第二段

極上のエロスを纏ってカムバックした国民的AV女優『めぐり』。

由 百度 提供翻译]]></plot>
  <outline><![CDATA[中文简介第一段

中文简介第二段

極上のエロスを纏ってカムバックした国民的AV女優『めぐり』。

由 百度 提供翻译]]></outline>
  <originalplot><![CDATA[極上のエロスを纏ってカムバックした国民的AV女優『めぐり』。]]></originalplot>
</movie>
""",
        encoding="utf-8",
    )

    data, info = await nfo_module.get_nfo_data(video_path, "JUMS-150")

    assert data is not None
    assert info is not None
    assert data.outline == "中文简介第一段\n\n中文简介第二段"
    assert data.originalplot == "極上のエロスを纏ってカムバックした国民的AV女優『めぐり』。"
    assert data.outline_from == "百度"
