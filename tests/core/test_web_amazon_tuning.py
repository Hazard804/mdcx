import numpy as np
import pytest
from PIL import Image, ImageDraw

from mdcx.config.enums import FixedScrapingType, HDPicSource
from mdcx.config.manager import manager
from mdcx.core.web import (
    _match_amazon_reference_images,
    _orb_inlier_count,
    _verify_soft_amazon_poster,
)
from mdcx.models.log_buffer import LogBuffer
from mdcx.models.types import CrawlersResult, OtherInfo


def _textured_image(seed: int, size: tuple[int, int] = (300, 450)) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(arr)


def _with_bottom_band(img: Image.Image, ratio: float = 0.10) -> Image.Image:
    out = img.copy()
    w, h = out.size
    band = int(h * ratio)
    draw = ImageDraw.Draw(out)
    draw.rectangle([0, h - band, w, h], fill=(248, 246, 240))
    return out


def test_orb_inlier_count_matches_same_cover_with_band():
    base = _textured_image(1)
    banded = _with_bottom_band(base)
    try:
        assert _orb_inlier_count(base, banded) >= 25
    finally:
        base.close()
        banded.close()


def test_orb_inlier_count_rejects_different_cover():
    first = _textured_image(2)
    second = _textured_image(3)
    try:
        assert _orb_inlier_count(first, second) < 25
    finally:
        first.close()
        second.close()


def test_match_amazon_reference_images_keeps_primary_rule(monkeypatch: pytest.MonkeyPatch):
    amazon = _textured_image(4)
    reference = _textured_image(5)
    try:
        monkeypatch.setattr("mdcx.core.web._cover_similarity", lambda *_args: (0.97, 1.0, 0.90))
        passed, source, score, _hash, _hist, inliers = _match_amazon_reference_images(
            amazon, [("thumb right", reference)]
        )
        assert passed is True
        assert source == "thumb right"
        assert score == pytest.approx(0.97)
        assert inliers == 0
    finally:
        amazon.close()
        reference.close()


def test_match_amazon_reference_images_rescues_with_orb(monkeypatch: pytest.MonkeyPatch):
    amazon = _textured_image(6)
    reference = _textured_image(7)
    try:
        monkeypatch.setattr("mdcx.core.web._cover_similarity", lambda *_args: (0.79, 0.77, 0.86))
        monkeypatch.setattr("mdcx.core.web._orb_inlier_count", lambda *_args: 30)
        passed, source, score, _hash, _hist, inliers = _match_amazon_reference_images(
            amazon, [("thumb right", reference)]
        )
        assert passed is True
        assert source == "thumb right"
        assert inliers == 30
    finally:
        amazon.close()
        reference.close()


def test_match_amazon_reference_images_rejects_when_orb_is_weak(monkeypatch: pytest.MonkeyPatch):
    amazon = _textured_image(8)
    reference = _textured_image(9)
    try:
        monkeypatch.setattr("mdcx.core.web._cover_similarity", lambda *_args: (0.72, 0.70, 0.78))
        monkeypatch.setattr("mdcx.core.web._orb_inlier_count", lambda *_args: 8)
        passed, _source, _score, _hash, _hist, inliers = _match_amazon_reference_images(
            amazon, [("thumb right", reference)]
        )
        assert passed is False
        assert inliers == 0
    finally:
        amazon.close()
        reference.close()


@pytest.mark.asyncio
async def test_verify_soft_amazon_poster_uses_full_thumb_for_portrait_reference(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """竖版 thumb 右裁会切掉主体，原图口径必须能单独命中。"""
    portrait = _textured_image(10, (200, 300))
    thumb_path = tmp_path / "thumb.jpg"
    portrait.save(thumb_path, format="JPEG")
    portrait.close()

    async def fake_download(_url: str, _media_context=None):
        return _textured_image(10, (200, 300))

    monkeypatch.setattr("mdcx.core.web._download_image_to_memory", fake_download)

    passed = await _verify_soft_amazon_poster(
        "https://example.test/amazon.jpg",
        thumb_path=thumb_path,
        original_poster_url="",
        original_poster_from="",
    )
    assert passed is True


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_tries_next_candidate_after_verify_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    title = "作品标题 ABC-123"
    html_search = """
    <html>
      <body>
        <div data-component-type="s-search-result" data-asin="B000DVD">
          <a class="a-text-bold">DVD</a>
          <h2><a href="/dp/B000DVD"><span>作品标题 ABC-123 [DVD]</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000DVD"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81dvd._AC_UL320_.jpg" />
        </div>
        <div data-component-type="s-search-result" data-asin="B000BD">
          <a class="a-text-bold">Blu-ray</a>
          <h2><a href="/dp/B000BD"><span>作品标题 ABC-123 [Blu-ray]</span></a></h2>
          <a class="a-link-normal s-no-outline" href="/dp/B000BD"></a>
          <img class="s-image" src="https://m.media-amazon.com/images/I/81bd._AC_UL320_.jpg" />
        </div>
      </body>
    </html>
    """
    html_detail = "<html><body><span id='productTitle'>作品标题 ABC-123</span></body></html>"
    verified: list[str] = []

    async def fake_try_get_amazon_barcodes_from_covers(_result, *_args, **_kwargs):
        return []

    async def fake_get_amazon_data(req_url: str):
        if "/dp/" in req_url:
            return True, html_detail
        return True, html_search

    async def fake_get_imgsize(_url: str):
        return 1800, 2700

    async def fake_verify(url: str, _is_hard: bool) -> bool:
        verified.append(url)
        return url.endswith("81bd.jpg")

    monkeypatch.setattr(
        "mdcx.core.amazon.try_get_amazon_barcodes_from_covers", fake_try_get_amazon_barcodes_from_covers
    )
    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)

    from mdcx.core.amazon import get_big_pic_by_amazon

    result = CrawlersResult.empty()
    result.number = "ABC-123"

    pic_url = await get_big_pic_by_amazon(result, title, ["演员A"], verify=fake_verify)

    assert pic_url == "https://m.media-amazon.com/images/I/81bd.jpg"
    assert verified == [
        "https://m.media-amazon.com/images/I/81dvd.jpg",
        "https://m.media-amazon.com/images/I/81bd.jpg",
    ]
    assert result.amazon_match_verified is True


@pytest.mark.asyncio
async def test_get_big_poster_skips_second_verification_when_amazon_already_verified(
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_get_big_pic_by_amazon(result: CrawlersResult, *args, **kwargs):
        result.amazon_match_is_hard = False
        result.amazon_match_verified = True
        return "https://m.media-amazon.com/images/I/81verified.jpg"

    async def fail_verify(*args, **kwargs):
        pytest.fail("已在 Amazon 内部校验过的候选不应再次校验")

    monkeypatch.setattr(manager.config, "download_hd_pics", [HDPicSource.AMAZON])
    monkeypatch.setattr("mdcx.core.web.get_big_pic_by_amazon", fake_get_big_pic_by_amazon)
    monkeypatch.setattr("mdcx.core.web._verify_soft_amazon_poster", fail_verify)

    result = CrawlersResult.empty()
    result.mosaic = "有码"
    result.scraping_type = FixedScrapingType.YOUMA
    result.originaltitle_amazon = "测试标题"
    other = OtherInfo.empty()

    from mdcx.core.web import _get_big_poster

    await _get_big_poster(result, other)

    assert result.poster == "https://m.media-amazon.com/images/I/81verified.jpg"
    assert result.poster_from == "Amazon"


def _search_card_html(asin: str, title: str, ver: str = "DVD", img: str = "81dvd") -> str:
    return f"""
        <div data-component-type="s-search-result" data-asin="{asin}">
          <a class="a-text-bold">{ver}</a>
          <h2><a href="/dp/{asin}"><span>{title}</span></a></h2>
          <img class="s-image" src="https://m.media-amazon.com/images/I/{img}._AC_UL320_.jpg" />
        </div>
    """


def _patch_amazon_search(monkeypatch: pytest.MonkeyPatch, html_search: str, html_detail: str):
    async def fake_try_get_amazon_barcodes_from_covers(_result, *_args, **_kwargs):
        return []

    async def fake_get_amazon_data(req_url: str):
        if "/dp/" in req_url:
            return True, html_detail
        return True, html_search

    async def fake_get_imgsize(_url: str):
        return 1800, 2700

    monkeypatch.setattr(
        "mdcx.core.amazon.try_get_amazon_barcodes_from_covers", fake_try_get_amazon_barcodes_from_covers
    )
    monkeypatch.setattr("mdcx.core.amazon.get_amazon_data", fake_get_amazon_data)
    monkeypatch.setattr("mdcx.core.amazon.get_imgsize", fake_get_imgsize)


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_matches_number_wrapped_in_brackets(monkeypatch: pytest.MonkeyPatch):
    """`【PSI-111】 [DVD]` 归一化后不能变成 PSI111DVD，否则番号边界判定会漏掉。"""
    title = "二穴ディルドの虜 6人のダブルアクメ"
    html_search = "<html><body>" + _search_card_html("B0PSI111", f"{title} 【PSI-111】 [DVD]") + "</body></html>"
    _patch_amazon_search(monkeypatch, html_search, "<html><body><span id='productTitle'></span></body></html>")
    verified: list[tuple[str, bool]] = []

    async def fake_verify(url: str, is_hard: bool) -> bool:
        verified.append((url, is_hard))
        return True

    from mdcx.core.amazon import get_big_pic_by_amazon

    result = CrawlersResult.empty()
    result.number = "PSI-111"

    pic_url = await get_big_pic_by_amazon(result, title, [], verify=fake_verify)

    assert pic_url == "https://m.media-amazon.com/images/I/81dvd.jpg"
    assert result.amazon_match_is_hard is True
    assert result.amazon_match_reason == "number"
    assert verified == [("https://m.media-amazon.com/images/I/81dvd.jpg", True)]


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_accepts_multi_actor_without_actor_evidence(monkeypatch: pytest.MonkeyPatch):
    """多演员作品在 Amazon 没有演员证据时，标题完全一致应放行并交图片校验。"""
    title = "インテリおばさんの好色日記"
    html_search = "<html><body>" + _search_card_html("B0RUKO040", f"{title} [DVD]") + "</body></html>"
    _patch_amazon_search(monkeypatch, html_search, "<html><body><span id='productTitle'></span></body></html>")
    verified: list[tuple[str, bool]] = []

    async def fake_verify(url: str, is_hard: bool) -> bool:
        verified.append((url, is_hard))
        return True

    from mdcx.core.amazon import get_big_pic_by_amazon

    result = CrawlersResult.empty()
    result.number = "RUKO-040"

    pic_url = await get_big_pic_by_amazon(
        result, title, ["成宮いろは", "雪野ひかる", "美里このみ", "楠木奏"], verify=fake_verify
    )

    assert pic_url == "https://m.media-amazon.com/images/I/81dvd.jpg"
    # 缺演员证据只能算软匹配，必须经过图片校验
    assert result.amazon_match_is_hard is False
    assert verified == [("https://m.media-amazon.com/images/I/81dvd.jpg", False)]
    LogBuffer.clear_task()


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_rejects_multi_actor_when_title_is_not_exact(monkeypatch: pytest.MonkeyPatch):
    """演员命中 0 且标题只是近似时仍应拒绝，避免同系列不同卷误命中。"""
    title = "掃除機オナニーの虜"
    html_search = (
        "<html><body>"
        + _search_card_html("B0PSI114", "掃除機オナニーの虜 完全保存版 特別編集 [DVD]")
        + "</body></html>"
    )
    _patch_amazon_search(monkeypatch, html_search, "<html><body><span id='productTitle'></span></body></html>")
    verified: list[str] = []

    async def fake_verify(url: str, _is_hard: bool) -> bool:
        verified.append(url)
        return True

    from mdcx.core.amazon import get_big_pic_by_amazon

    result = CrawlersResult.empty()
    result.number = "PSI-115"

    pic_url = await get_big_pic_by_amazon(result, title, ["宮咲志帆", "風見渚", "小滝紗由美"], verify=fake_verify)

    assert pic_url == ""
    assert verified == []
    LogBuffer.clear_task()


@pytest.mark.asyncio
async def test_get_big_pic_by_amazon_accepts_partial_actor_match(monkeypatch: pytest.MonkeyPatch):
    """多演员作品只命中 1 个演员、标题一致时，应放行而不是要求命中半数以上。"""
    title = "絶頂84回!大痙攣93回!潮吹き8300cc!エロス極限突破トランス絶頂FUCK 楓カレン"
    html_search = "<html><body>" + _search_card_html("B0IPX320", f"{title} アイデアポケット [DVD]") + "</body></html>"
    _patch_amazon_search(monkeypatch, html_search, "<html><body><span id='productTitle'></span></body></html>")

    async def fake_verify(_url: str, _is_hard: bool) -> bool:
        return True

    from mdcx.core.amazon import get_big_pic_by_amazon

    result = CrawlersResult.empty()
    result.number = "IPX-320"

    pic_url = await get_big_pic_by_amazon(result, title, ["楓カレン", "枫花恋", "かえでかれん"], verify=fake_verify)

    assert pic_url == "https://m.media-amazon.com/images/I/81dvd.jpg"
    assert result.amazon_match_is_hard is False
    LogBuffer.clear_task()
    LogBuffer.clear_task()
