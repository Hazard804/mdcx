import pytest

import mdcx.crawlers.jav321 as jav321_module
from mdcx.config.enums import DownloadableFile


@pytest.mark.asyncio
async def test_validate_dmm_image_if_needed_skips_non_dmm(monkeypatch: pytest.MonkeyPatch):
    called = False

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        nonlocal called
        called = True
        return url

    monkeypatch.setattr(jav321_module, "check_url", fake_check_url)

    result = await jav321_module._validate_dmm_image_if_needed("https://example.com/poster.jpg", "poster")

    assert result == "https://example.com/poster.jpg"
    assert called is False


@pytest.mark.asyncio
async def test_validate_dmm_image_if_needed_returns_empty_for_invalid_dmm(monkeypatch: pytest.MonkeyPatch):
    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        return None

    monkeypatch.setattr(jav321_module, "check_url", fake_check_url)

    result = await jav321_module._validate_dmm_image_if_needed(
        "https://pics.dmm.co.jp/digital/video/knld00010/knld00010pl.jpg",
        "thumb",
    )

    assert result == ""


@pytest.mark.asyncio
async def test_validate_dmm_image_if_needed_prefers_aws_for_dmm_pics(monkeypatch: pytest.MonkeyPatch):
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        if "awsimgsrc.dmm.co.jp" in url:
            return url
        return None

    monkeypatch.setattr(jav321_module, "check_url", fake_check_url)

    result = await jav321_module._validate_dmm_image_if_needed(
        "https://pics.dmm.co.jp/digital/video/knld00010/knld00010pl.jpg",
        "thumb",
    )

    assert result == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/knld00010/knld00010pl.jpg"
    assert called_urls == ["https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/knld00010/knld00010pl.jpg"]


@pytest.mark.asyncio
async def test_filter_dmm_extrafanart_filters_invalid_dmm_and_keeps_non_dmm(monkeypatch: pytest.MonkeyPatch):
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        if "badextra" in url:
            return None
        return url

    monkeypatch.setattr(jav321_module, "check_url", fake_check_url)

    result = await jav321_module._filter_dmm_extrafanart(
        [
            "https://pics.dmm.co.jp/digital/video/knld00010/sample1.jpg",
            "https://pics.dmm.co.jp/digital/video/knld00010/badextra.jpg",
            "https://cdn.example.com/sample2.jpg",
            "https://pics.dmm.co.jp/digital/video/knld00010/sample1.jpg",
        ]
    )

    assert result == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/knld00010/sample1.jpg",
        "https://cdn.example.com/sample2.jpg",
    ]
    assert called_urls == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/knld00010/sample1.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/knld00010/badextra.jpg",
        "https://pics.dmm.co.jp/digital/video/knld00010/badextra.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/knld00010/sample1.jpg",
    ]


@pytest.mark.asyncio
async def test_filter_dmm_extrafanart_prefers_aws_for_dmm_pics(monkeypatch: pytest.MonkeyPatch):
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        if "awsimgsrc.dmm.co.jp" in url:
            return url
        return None

    monkeypatch.setattr(jav321_module, "check_url", fake_check_url)

    result = await jav321_module._filter_dmm_extrafanart(["https://pics.dmm.co.jp/digital/video/knld00010/sample1.jpg"])

    assert result == ["https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/knld00010/sample1.jpg"]
    assert called_urls == ["https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/knld00010/sample1.jpg"]


def test_normalize_extrafanart_urls_dedupes_without_validation():
    result = jav321_module._normalize_extrafanart_urls(
        [
            "https://cdn.example.com/sample2.jpg",
            "https://cdn.example.com/sample2.jpg",
            "https://pics.dmm.co.jp/digital/video/knld00010/sample1.jpg",
            "",
        ]
    )

    assert result == [
        "https://cdn.example.com/sample2.jpg",
        "https://pics.dmm.co.jp/digital/video/knld00010/sample1.jpg",
    ]


@pytest.mark.asyncio
async def test_main_skips_extrafanart_validation_when_download_disabled(monkeypatch: pytest.MonkeyPatch):
    html = """
    <html>
      <body>
        <div class="row"></div>
        <div class="row">
          <div class="col-md-3">
            <div class="col-xs-12 col-md-12">
              <p><a><img class="img-responsive" src="https://pics.dmm.co.jp/digital/video/knld00010/knld00010pl.jpg" /></a></p>
            </div>
            <div class="col-xs-12 col-md-12">
              <p><a><img class="img-responsive" src="https://pics.dmm.co.jp/digital/video/knld00010/sample1.jpg" /></a></p>
            </div>
          </div>
          <div class="col-md-9">
            <a href="/company/test">Test Studio</a>
          </div>
          <div class="col-md-1">
            <a href="//www.jav321.com/video/test">简体中文</a>
          </div>
        </div>
        <h3>Test Title <small></small></h3>
        <b>出演者</b>: Test Actor &nbsp; <br>
        <b>配信開始日</b>: 2024-01-01<br>
        <b>収録時間</b>: 120 分<br>
        <b>品番</b>: TEST-001<br>
        <b>平均評価</b>: 4.0<br>
        <div>Outline</div>
      </body>
    </html>
    """

    async def fake_post_text(url: str, data=None):
        return html, ""

    called_labels: list[str] = []

    async def fake_validate(url: str, label: str) -> str:
        called_labels.append(label)
        return url

    monkeypatch.setattr(jav321_module.manager.computed.async_client, "post_text", fake_post_text)
    monkeypatch.setattr(jav321_module, "_validate_dmm_image_if_needed", fake_validate)
    monkeypatch.setattr(
        jav321_module.manager.config, "download_files", [DownloadableFile.POSTER, DownloadableFile.THUMB]
    )

    result = await jav321_module.main("TEST-001")
    data = result["jav321"]["zh_cn"]

    assert called_labels == ["thumb", "poster"]
    assert data["extrafanart"] == [
        "https://pics.dmm.co.jp/digital/video/knld00010/knld00010pl.jpg",
        "https://pics.dmm.co.jp/digital/video/knld00010/sample1.jpg",
    ]
