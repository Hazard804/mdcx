import pytest

import mdcx.crawlers.jav321 as jav321_module


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
        "https://pics.dmm.co.jp/digital/video/knld00010/sample1.jpg",
        "https://cdn.example.com/sample2.jpg",
    ]
    assert called_urls == [
        "https://pics.dmm.co.jp/digital/video/knld00010/sample1.jpg",
        "https://pics.dmm.co.jp/digital/video/knld00010/badextra.jpg",
        "https://pics.dmm.co.jp/digital/video/knld00010/sample1.jpg",
    ]
