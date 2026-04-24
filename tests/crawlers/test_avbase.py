import pytest

import mdcx.crawlers.avbase_new as avbase_module
from mdcx.crawlers.avbase_new import AvbaseCrawler
from mdcx.models.types import CrawlerInput


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("55", "55"),
        ("収録分数 55", "55"),
        ("収録分数 0:55:00", "55"),
        ("収録分数 00:55:00", "55"),
        ("収録分数 1:05:30", "65"),
        ("収録分数 0:00:30", "1"),
    ],
)
def test_parse_runtime(raw: str, expected: str):
    assert AvbaseCrawler._parse_runtime(raw) == expected


@pytest.mark.asyncio
async def test_post_process_uses_dmm_validation_for_dmm_thumb_and_poster(monkeypatch: pytest.MonkeyPatch):
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        if url.endswith("ps.jpg"):
            return None
        return url

    monkeypatch.setattr(avbase_module, "check_url", fake_check_url)

    crawler = AvbaseCrawler(client=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    result = avbase_module.CrawlerData(
        title="VR SAMPLE",
        thumb="https://pics.dmm.co.jp/mono/movie/adult/pred816/pred816pl.jpg",
        studio="",
    ).to_result()

    processed = await crawler.post_process(ctx, result)

    assert processed.thumb == "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816pl.jpg"
    assert processed.poster == ""
    assert processed.image_download is False
    assert called_urls == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816pl.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816ps.jpg",
    ]


@pytest.mark.asyncio
async def test_sanitize_extrafanart_urls_keeps_full_batch_when_random_probe_passes(
    monkeypatch: pytest.MonkeyPatch,
):
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        if url.endswith("unchecked.jpg"):
            raise AssertionError("随机抽检通过后不应继续校验未抽中的剧照")
        return url

    monkeypatch.setattr(avbase_module, "check_url", fake_check_url)
    monkeypatch.setattr(avbase_module.random, "sample", lambda population, k: [0, 1, 2])

    crawler = AvbaseCrawler(client=None)

    result = await crawler._sanitize_extrafanart_urls(
        [
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample2.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample3.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/unchecked.jpg",
        ]
    )

    assert result == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample1.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample2.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample3.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/unchecked.jpg",
    ]
    assert called_urls == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample1.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample2.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample3.jpg",
    ]


@pytest.mark.asyncio
async def test_sanitize_extrafanart_urls_falls_back_to_full_validation_when_random_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        if url.endswith("badextra.jpg"):
            return None
        return url

    monkeypatch.setattr(avbase_module, "check_url", fake_check_url)
    monkeypatch.setattr(avbase_module.random, "sample", lambda population, k: [0, 1, 2])

    crawler = AvbaseCrawler(client=None)

    result = await crawler._sanitize_extrafanart_urls(
        [
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/badextra.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample2.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample3.jpg",
        ]
    )

    assert result == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample1.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample2.jpg",
        "https://pics.dmm.co.jp/digital/video/pred00816/sample3.jpg",
    ]
    assert called_urls == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample1.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/badextra.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample2.jpg",
        "https://pics.dmm.co.jp/digital/video/pred00816/badextra.jpg",
        "https://pics.dmm.co.jp/digital/video/pred00816/sample3.jpg",
    ]
