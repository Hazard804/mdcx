"""
刮削过程的网络操作
"""

import asyncio
import re
import shutil
import time
from asyncio import to_thread
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import aiofiles
import aiofiles.os
from PIL import Image

from ..base.web import (
    check_url,
    download_extrafanart_task,
    download_file_with_filepath,
    get_dmm_trailer,
    get_imgsize,
    get_url_content_length,
)
from ..config.enums import DownloadableFile, FixedScrapingType, HDPicSource, KeepableFile
from ..config.manager import manager
from ..config.resource_policy import resource_policy
from ..manual import ManualConfig
from ..models.flags import Flags
from ..models.log_buffer import LogBuffer
from ..models.types import CrawlersResult, OtherInfo
from ..signals import signal
from ..utils import get_used_time, split_path
from ..utils.file import check_pic_async, copy_file_async, delete_file_async, move_file_async
from .amazon import (
    _beam_search_amazon_ean13_from_ranked_digits,
    _detect_amazon_barcode_candidates_from_image_bytes_with_reason,
    _extract_amazon_barcode_label_roi,
    _get_amazon_barcode_detector_skip_reason,
    get_big_pic_by_amazon,
    is_amazon_hard_match,
    try_get_amazon_barcode_from_covers,
    try_get_amazon_barcodes_from_covers,
)
from .image import cut_thumb_to_poster
from .media_resource import MediaResourceContext
from .mosaic import has_leak_mark, has_umr_mark

AMAZON_SEARCH_SCRAPING_TYPES = {FixedScrapingType.YOUMA}
AMAZON_SEARCH_SPECIAL_MOSAICS = {"里番", "裏番", "动漫", "動漫"}
POSTER_COPY_POLICY_MAP = {
    FixedScrapingType.YOUMA: DownloadableFile.IGNORE_YOUMA,
    FixedScrapingType.WUMA: DownloadableFile.IGNORE_WUMA,
    FixedScrapingType.FC2: DownloadableFile.IGNORE_FC2,
    FixedScrapingType.GUOCHAN: DownloadableFile.IGNORE_GUOCHAN,
    FixedScrapingType.OUMEI: DownloadableFile.IGNORE_OUMEI,
}
POSTER_DIRECT_DOWNLOAD_TYPES = {
    FixedScrapingType.WUMA,
    FixedScrapingType.FC2,
    FixedScrapingType.GUOCHAN,
    FixedScrapingType.OUMEI,
    FixedScrapingType.SUREN,
    FixedScrapingType.AUTO,
}
POSTER_AUTO_BEST_MIN_CROP_AREA_RATIO = 0.70
POSTER_AUTO_BEST_MIN_CROP_HEIGHT_RATIO = 0.80
POSTER_SKIP_AMAZON_MIN_BYTES = 400 * 1024


@dataclass(frozen=True)
class PosterCandidate:
    source: str
    url: str
    image_download: bool
    size: tuple[int, int] = (0, 0)


__all__ = [
    "_beam_search_amazon_ean13_from_ranked_digits",
    "_detect_amazon_barcode_candidates_from_image_bytes_with_reason",
    "_extract_amazon_barcode_label_roi",
    "_get_amazon_barcode_detector_skip_reason",
    "get_big_pic_by_amazon",
    "try_get_amazon_barcode_from_covers",
    "try_get_amazon_barcodes_from_covers",
]


def _should_search_amazon(result: CrawlersResult) -> bool:
    if result.scraping_type in {FixedScrapingType.SUREN, FixedScrapingType.FC2, FixedScrapingType.WUMA}:
        return False
    if result.scraping_type in AMAZON_SEARCH_SCRAPING_TYPES:
        return True
    return has_leak_mark(result.mosaic) or has_umr_mark(result.mosaic) or result.mosaic in AMAZON_SEARCH_SPECIAL_MOSAICS


def _get_poster_copy_policy(result: CrawlersResult, download_files: list[DownloadableFile]) -> bool:
    ignore_file = POSTER_COPY_POLICY_MAP.get(result.scraping_type)
    return bool(ignore_file and ignore_file in download_files)


def _should_try_direct_poster(result: CrawlersResult, poster_auto_best: bool) -> bool:
    if result.scraping_type in POSTER_DIRECT_DOWNLOAD_TYPES:
        return True
    if result.scraping_type == FixedScrapingType.YOUMA:
        return result.image_download or poster_auto_best
    return False


def _is_vr_result(result: CrawlersResult) -> bool:
    return "VR" in result.number.upper() or "VR" in result.title.upper()


async def _cleanup_download_part_files(*file_paths: Path) -> None:
    for file_path in file_paths:
        await delete_file_async(file_path.with_name(f"{file_path.name}.part"))


async def _get_image_size(url: str, media_context: MediaResourceContext | None = None) -> tuple[int, int]:
    if media_context is not None:
        return await media_context.probe_original_size(url)
    return await get_imgsize(url)


def _open_rgb_image_from_bytes(content: bytes) -> Image.Image | None:
    try:
        with Image.open(BytesIO(content)) as img:
            img.load()
            return img.convert("RGB")
    except Exception:
        return None


def _load_rgb_image_from_path(pic_path: Path) -> Image.Image | None:
    try:
        with Image.open(pic_path) as img:
            img.load()
            return img.convert("RGB")
    except Exception:
        return None


def _cut_thumb_right_image(thumb_img: Image.Image) -> Image.Image:
    w, h = thumb_img.size
    ax, ay, bx, by = w / 1.9, 0, w, h
    if w == 800:
        if h == 439:
            ax, ay, bx, by = 420, 0, w, h
        elif 499 <= h <= 503:
            ax, ay, bx, by = 437, 0, w, h
        else:
            ax, ay, bx, by = 421, 0, w, h
    elif w == 840 and h == 472:
        ax, ay, bx, by = 473, 0, 788, h
    cropped = thumb_img.crop((ax, ay, bx, by))
    try:
        return cropped.convert("RGB")
    finally:
        cropped.close()


def _get_thumb_right_crop_size(image_size: tuple[int, int]) -> tuple[int, int]:
    w, h = image_size
    if w <= 0 or h <= 0:
        return 0, 0
    ax, bx = w / 1.9, w
    if w == 800:
        if h == 439:
            ax, bx = 420, w
        elif 499 <= h <= 503:
            ax, bx = 437, w
        else:
            ax, bx = 421, w
    elif w == 840 and h == 472:
        ax, bx = 473, 788
    return max(int(bx - ax), 0), h


def _get_local_image_size(pic_path: Path) -> tuple[int, int]:
    try:
        with Image.open(pic_path) as img:
            return img.size
    except Exception:
        return 0, 0


async def _get_thumb_right_crop_size_from_path(pic_path: Path | None) -> tuple[int, int]:
    if not pic_path or not await aiofiles.os.path.exists(pic_path):
        return 0, 0
    return _get_thumb_right_crop_size(await to_thread(_get_local_image_size, pic_path))


def _image_area(size: tuple[int, int]) -> int:
    return max(size[0], 0) * max(size[1], 0)


def _is_known_image_size(size: tuple[int, int]) -> bool:
    return size[0] > 0 and size[1] > 0


def _dedupe_poster_candidates(candidates: list[PosterCandidate]) -> list[PosterCandidate]:
    result: list[PosterCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized_url = MediaResourceContext.normalize_url(candidate.url)
        if not normalized_url or normalized_url in seen:
            continue
        seen.add(normalized_url)
        result.append(candidate)
    return result


def _select_best_poster_candidate(
    candidates: list[PosterCandidate],
    crop_size: tuple[int, int],
) -> PosterCandidate | None:
    known_candidates = [each for each in candidates if _is_known_image_size(each.size)]
    if not known_candidates:
        LogBuffer.log().write("\n 🖼 Poster选优: 无可比较的 Poster 尺寸，保持原策略")
        return candidates[0] if candidates else None

    best = max(known_candidates, key=lambda item: _image_area(item.size))
    if _is_known_image_size(crop_size):
        best_area = _image_area(best.size)
        crop_area = _image_area(crop_size)
        if (
            best_area < crop_area * POSTER_AUTO_BEST_MIN_CROP_AREA_RATIO
            or best.size[1] < crop_size[1] * POSTER_AUTO_BEST_MIN_CROP_HEIGHT_RATIO
        ):
            LogBuffer.log().write(f"\n 🖼 Poster选优: 直下/搜索图{best.size}明显小于thumb右裁剪{crop_size}，改用裁剪")
            return None

    LogBuffer.log().write(f"\n 🖼 Poster选优: 使用 {best.source} {best.size}")
    return best


async def _select_poster_auto_best(
    result: CrawlersResult,
    other: OtherInfo,
    *,
    direct_url: str,
    direct_from: str,
    direct_size: tuple[int, int],
    crop_source_path: Path | None,
    media_context: MediaResourceContext | None = None,
) -> None:
    candidates: list[tuple[str, str, tuple[int, int]]] = []
    if direct_url:
        candidates.append((direct_url, direct_from or "poster", direct_size))

    enhanced_url = result.poster
    enhanced_from = result.poster_from
    if enhanced_url and enhanced_url != direct_url:
        candidates.append((enhanced_url, enhanced_from or "poster", await _get_image_size(enhanced_url, media_context)))

    known_candidates = [each for each in candidates if _is_known_image_size(each[2])]
    if not known_candidates:
        LogBuffer.log().write("\n 🖼 Poster选优: 无可比较的 Poster 尺寸，保持原策略")
        return

    best_url, best_from, best_size = max(known_candidates, key=lambda item: _image_area(item[2]))
    crop_size = await _get_thumb_right_crop_size_from_path(crop_source_path)
    if _is_known_image_size(crop_size):
        best_area = _image_area(best_size)
        crop_area = _image_area(crop_size)
        if (
            best_area < crop_area * POSTER_AUTO_BEST_MIN_CROP_AREA_RATIO
            or best_size[1] < crop_size[1] * POSTER_AUTO_BEST_MIN_CROP_HEIGHT_RATIO
        ):
            result.image_download = False
            LogBuffer.log().write(f"\n 🖼 Poster选优: 直下/搜索图{best_size}明显小于thumb右裁剪{crop_size}，改用裁剪")
            return

    result.poster = best_url
    result.poster_from = best_from
    result.image_download = True
    LogBuffer.log().write(f"\n 🖼 Poster选优: 使用 {best_from} {best_size}")


async def _is_existing_poster_better_than_youma_crop(
    result: CrawlersResult,
    other: OtherInfo,
    media_context: MediaResourceContext | None = None,
) -> bool:
    poster_size = await _get_image_size(result.poster, media_context)
    if not _is_known_image_size(poster_size):
        LogBuffer.log().write("\n 🖼 Amazon搜索：当前 Poster 尺寸未知，继续搜索高清图")
        return False

    crop_size = await _get_thumb_right_crop_size_from_path(other.fanart_path or other.thumb_path)
    if not _is_known_image_size(crop_size):
        return True

    poster_area = _image_area(poster_size)
    crop_area = _image_area(crop_size)
    if (
        poster_area < crop_area * POSTER_AUTO_BEST_MIN_CROP_AREA_RATIO
        or poster_size[1] < crop_size[1] * POSTER_AUTO_BEST_MIN_CROP_HEIGHT_RATIO
    ):
        LogBuffer.log().write(
            f"\n 🖼 Amazon搜索：当前 Poster{poster_size} 明显小于 thumb 右裁剪{crop_size}，继续搜索高清图"
        )
        return False

    return True


async def _should_skip_amazon_for_existing_poster(
    result: CrawlersResult,
    other: OtherInfo,
    *,
    poster_auto_best: bool = False,
    media_context: MediaResourceContext | None = None,
) -> bool:
    if not result.poster or result.poster_from == "Amazon":
        return False

    if result.scraping_type == FixedScrapingType.YOUMA and not poster_auto_best:
        if not await _is_existing_poster_better_than_youma_crop(result, other, media_context):
            return False
    elif not _is_known_image_size(await _get_image_size(result.poster, media_context)):
        LogBuffer.log().write("\n 🖼 Amazon搜索：当前 Poster 尺寸未知，继续搜索高清图")
        return False

    content_length = await get_url_content_length(result.poster)
    if not content_length:
        LogBuffer.log().write("\n 🖼 Amazon搜索：当前 Poster 大小未知，继续搜索高清图")
        return False

    if content_length < POSTER_SKIP_AMAZON_MIN_BYTES:
        LogBuffer.log().write(
            f"\n 🖼 Amazon搜索：当前 Poster 大小({content_length // 1024}KB)低于阈值，继续搜索高清图"
        )
        return False

    if result.scraping_type == FixedScrapingType.YOUMA and not poster_auto_best:
        result.image_download = True
    LogBuffer.log().write(
        f"\n 🖼 Amazon搜索：当前 Poster 已足够清晰({content_length // 1024}KB)，跳过 Amazon"
    )
    return True


def _prepare_similarity_image(img: Image.Image) -> Image.Image:
    target_ratio = 2 / 3
    w, h = img.size
    if w <= 0 or h <= 0:
        return img.resize((160, 240))
    ratio = w / h
    cropped = None
    if ratio > target_ratio:
        new_w = max(1, int(h * target_ratio))
        left = max(0, (w - new_w) // 2)
        cropped = img.crop((left, 0, left + new_w, h))
    elif ratio < target_ratio:
        new_h = max(1, int(w / target_ratio))
        top = max(0, (h - new_h) // 2)
        cropped = img.crop((0, top, w, top + new_h))
    source_img = cropped or img
    resized = source_img.resize((160, 240), Image.Resampling.LANCZOS)
    try:
        return resized.convert("RGB")
    finally:
        resized.close()
        if cropped is not None:
            cropped.close()


def _average_hash(img: Image.Image, hash_size: int = 8) -> int:
    gray = img.convert("L").resize((hash_size, hash_size), Image.Resampling.LANCZOS)
    try:
        pixels = list(gray.getdata())
        average = sum(pixels) / len(pixels)
        result = 0
        for index, pixel in enumerate(pixels):
            if pixel >= average:
                result |= 1 << index
        return result
    finally:
        gray.close()


def _histogram_similarity(img_a: Image.Image, img_b: Image.Image) -> float:
    hist_a = img_a.histogram()
    hist_b = img_b.histogram()
    if not hist_a or not hist_b:
        return 0.0
    intersection = sum(min(a, b) for a, b in zip(hist_a, hist_b, strict=False))
    total = min(sum(hist_a), sum(hist_b))
    return intersection / total if total else 0.0


def _cover_similarity(img_a: Image.Image, img_b: Image.Image) -> tuple[float, float, float]:
    prepared_a = _prepare_similarity_image(img_a)
    prepared_b = _prepare_similarity_image(img_b)
    try:
        hash_a = _average_hash(prepared_a)
        hash_b = _average_hash(prepared_b)
        hash_bits = 64
        hash_similarity = 1 - ((hash_a ^ hash_b).bit_count() / hash_bits)
        hist_similarity = _histogram_similarity(prepared_a, prepared_b)
        score = hash_similarity * 0.7 + hist_similarity * 0.3
        return score, hash_similarity, hist_similarity
    finally:
        prepared_a.close()
        prepared_b.close()


async def _download_image_to_memory(url: str, media_context: MediaResourceContext | None = None) -> Image.Image | None:
    if not url or not re.match(r"^https?://", url, flags=re.I):
        return None
    if media_context is not None:
        img = await media_context.open_rgb_image(url)
        if img is None:
            LogBuffer.log().write("\n 🟡 Amazon图片校验：读取参考图失败")
        return img
    async with manager.acquire_computed() as computed:
        content, error = await computed.async_client.get_content(url)
    if not content:
        if error:
            LogBuffer.log().write(f"\n 🟡 Amazon图片校验：读取参考图失败 {error}")
        return None
    return await to_thread(_open_rgb_image_from_bytes, content)


async def _verify_soft_amazon_poster(
    amazon_url: str,
    *,
    thumb_path: Path | None,
    original_poster_url: str,
    original_poster_from: str,
    media_context: MediaResourceContext | None = None,
    strict: bool = False,
) -> bool:
    verify_mode = "严格模式" if strict else "软匹配"
    LogBuffer.log().write(f"\n 🔎 Amazon图片校验：{verify_mode}，开始与已获取图片比对")
    amazon_img = await _download_image_to_memory(amazon_url, media_context)
    if amazon_img is None:
        LogBuffer.log().write("\n 🟡 Amazon图片校验未通过：Amazon图片读取失败")
        return False

    reference_images: list[tuple[str, Image.Image]] = []
    if thumb_path and await aiofiles.os.path.exists(thumb_path):
        thumb_img = await to_thread(_load_rgb_image_from_path, thumb_path)
        if thumb_img is not None:
            reference_images.append(("thumb right", await to_thread(_cut_thumb_right_image, thumb_img)))
            thumb_img.close()

    if (
        original_poster_url
        and not original_poster_from.startswith("Amazon")
        and "media-amazon.com" not in original_poster_url
        and original_poster_url != amazon_url
    ):
        poster_img = await _download_image_to_memory(original_poster_url, media_context)
        if poster_img is not None:
            reference_images.append(("poster", poster_img))

    if not reference_images:
        amazon_img.close()
        LogBuffer.log().write("\n 🟡 Amazon图片校验跳过：没有可用参考图，已放弃软匹配图片")
        return False

    best: tuple[float, str, float, float] = (0.0, "", 0.0, 0.0)
    try:
        for source, reference_img in reference_images:
            score, hash_similarity, hist_similarity = await to_thread(_cover_similarity, amazon_img, reference_img)
            if score > best[0]:
                best = (score, source, hash_similarity, hist_similarity)
            if score >= 0.82 and hash_similarity >= 0.86 and hist_similarity >= 0.70:
                LogBuffer.log().write(
                    f"\n 🟢 Amazon图片校验通过：参考({source}) "
                    f"相似度({score:.2f}) hash({hash_similarity:.2f}) hist({hist_similarity:.2f})"
                )
                return True
    finally:
        amazon_img.close()
        for _, reference_img in reference_images:
            reference_img.close()

    score, source, hash_similarity, hist_similarity = best
    LogBuffer.log().write(
        f"\n 🟡 Amazon图片校验未通过：最高参考({source or 'none'}) "
        f"相似度({score:.2f}) hash({hash_similarity:.2f}) hist({hist_similarity:.2f})，已放弃软匹配图片"
    )
    return False


async def trailer_download(
    result: CrawlersResult,
    folder_new: Path,
    folder_old: Path,
    naming_rule: str,
) -> bool | None:
    start_time = time.time()
    download_files = manager.config.download_files
    keep_files = manager.config.keep_files
    trailer_name = manager.config.trailer_simple_name
    result.trailer = await get_dmm_trailer(result.trailer)  # todo 或许找一个更合适的地方进行统一后处理
    trailer_url = result.trailer
    trailer_old_folder_path = folder_old / "trailers"
    trailer_new_folder_path = folder_new / "trailers"

    trailer_policy = resource_policy(
        DownloadableFile.TRAILER,
        KeepableFile.TRAILER,
        download_files=download_files,
        keep_files=keep_files,
    )

    # 预告片名字不含视频文件名（只让一个视频去下载即可）
    if trailer_name:
        trailer_folder_path = folder_new / "trailers"
        trailer_file_name = "trailer.mp4"
        trailer_file_path = trailer_folder_path / trailer_file_name

        # 预告片文件夹已在已处理列表时，返回（这时只需要下载一个，其他分集不需要下载）
        if trailer_folder_path in Flags.trailer_deal_set:
            return
        Flags.trailer_deal_set.add(trailer_folder_path)
        await _cleanup_download_part_files(trailer_file_path, trailer_file_path.with_suffix(".[DOWNLOAD].mp4"))

        # 不下载不保留时删除返回
        if trailer_policy.should_remove_existing:
            # 删除目标文件夹即可，其他文件夹和文件已经删除了
            if await aiofiles.os.path.exists(trailer_folder_path):
                await to_thread(shutil.rmtree, trailer_folder_path, ignore_errors=True)
            return

    else:
        # 预告片带文件名（每个视频都有机会下载，如果已有下载好的，则使用已下载的）
        trailer_file_name = naming_rule + "-trailer.mp4"
        trailer_folder_path = folder_new
        trailer_file_path = trailer_folder_path / trailer_file_name
        await _cleanup_download_part_files(trailer_file_path, trailer_file_path.with_suffix(".[DOWNLOAD].mp4"))

        # 不下载不保留时删除返回
        if trailer_policy.should_remove_existing:
            # 删除目标文件，删除预告片旧文件夹、新文件夹（deal old file时没删除）
            if await aiofiles.os.path.exists(trailer_file_path):
                await delete_file_async(trailer_file_path)
            if await aiofiles.os.path.exists(trailer_old_folder_path):
                await to_thread(shutil.rmtree, trailer_old_folder_path, ignore_errors=True)
            if trailer_new_folder_path != trailer_old_folder_path and await aiofiles.os.path.exists(
                trailer_new_folder_path
            ):
                await to_thread(shutil.rmtree, trailer_new_folder_path, ignore_errors=True)
            return

    # 选择保留文件，当存在文件时，不下载。（done trailer path 未设置时，把当前文件设置为 done trailer path，以便其他分集复制）
    if trailer_policy.should_keep and await aiofiles.os.path.exists(trailer_file_path):
        if not Flags.file_done_dic.get(result.number, {}).get("trailer"):
            Flags.file_done_dic[result.number].update({"trailer": trailer_file_path})
            # 带文件名时，删除掉新、旧文件夹，用不到了。（其他分集如果没有，可以复制第一个文件的预告片。此时不删，没机会删除了）
            if not trailer_name:
                if await aiofiles.os.path.exists(trailer_old_folder_path):
                    await to_thread(shutil.rmtree, trailer_old_folder_path, ignore_errors=True)
                if trailer_new_folder_path != trailer_old_folder_path and await aiofiles.os.path.exists(
                    trailer_new_folder_path
                ):
                    await to_thread(shutil.rmtree, trailer_new_folder_path, ignore_errors=True)
        LogBuffer.log().write(f"\n 🍀 Trailer done! (old)({get_used_time(start_time)}s) ")
        return True

    # 带文件名时，选择下载不保留，或者选择保留但没有预告片，检查是否有其他分集已下载或本地预告片
    # 选择下载不保留，当没有下载成功时，不会删除不保留的文件
    done_trailer_path = Flags.file_done_dic.get(result.number, {}).get("trailer")
    if not trailer_name and done_trailer_path and await aiofiles.os.path.exists(done_trailer_path):
        if await aiofiles.os.path.exists(trailer_file_path):
            await delete_file_async(trailer_file_path)
        await copy_file_async(done_trailer_path, trailer_file_path)
        LogBuffer.log().write(f"\n 🍀 Trailer done! (copy trailer)({get_used_time(start_time)}s)")
        return

    # 不下载时返回（选择不下载保留，但本地并不存在，此时返回）
    if not trailer_policy.should_download:
        return

    if ".fc2.com/" in trailer_url and "mid=" in trailer_url and "/up/" in trailer_url:
        tips = "🟡 FC2 预告片链接为带 mid 参数的临时地址，建议仅用于当前任务立即下载，后续直接复用远程链接可能失效。"
        LogBuffer.log().write("\n " + tips)
        signal.add_log(tips)

    # 下载预告片,检测链接有效性
    content_length = await check_url(trailer_url, length=True)
    if content_length:
        # 创建文件夹
        if trailer_name == 1 and not await aiofiles.os.path.exists(trailer_folder_path):
            await aiofiles.os.makedirs(trailer_folder_path)

        # 开始下载
        download_files = manager.config.download_files
        signal.show_traceback_log(f"🍔 {result.number} download trailer... {trailer_url}")
        trailer_file_path_temp = trailer_file_path
        if await aiofiles.os.path.exists(trailer_file_path):
            trailer_file_path_temp = trailer_file_path.with_suffix(".[DOWNLOAD].mp4")
        if await download_file_with_filepath(trailer_url, trailer_file_path_temp, trailer_folder_path):
            file_size = await aiofiles.os.path.getsize(trailer_file_path_temp)
            if file_size >= content_length or DownloadableFile.IGNORE_SIZE in download_files:
                LogBuffer.log().write(
                    f"\n 🍀 Trailer done! ({result.trailer_from} {file_size}/{content_length})({get_used_time(start_time)}s) "
                )
                signal.show_traceback_log(f"✅ {result.number} trailer done!")
                if trailer_file_path_temp != trailer_file_path:
                    await move_file_async(trailer_file_path_temp, trailer_file_path)
                    await delete_file_async(trailer_file_path_temp)
                done_trailer_path = Flags.file_done_dic.get(result.number, {}).get("trailer")
                if not done_trailer_path:
                    Flags.file_done_dic[result.number].update({"trailer": trailer_file_path})
                    if trailer_name == 0:  # 带文件名，已下载成功，删除掉那些不用的文件夹即可
                        if await aiofiles.os.path.exists(trailer_old_folder_path):
                            await to_thread(shutil.rmtree, trailer_old_folder_path, ignore_errors=True)
                        if trailer_new_folder_path != trailer_old_folder_path and await aiofiles.os.path.exists(
                            trailer_new_folder_path
                        ):
                            await to_thread(shutil.rmtree, trailer_new_folder_path, ignore_errors=True)
                return True
            else:
                LogBuffer.log().write(
                    f"\n 🟠 Trailer size is incorrect! delete it! ({result.trailer_from} {file_size}/{content_length}) "
                )

        # 删除下载失败的文件
        await delete_file_async(trailer_file_path_temp)
        LogBuffer.log().write(f"\n 🟠 Trailer download failed! ({trailer_url}) ")

    if await aiofiles.os.path.exists(trailer_file_path):  # 使用旧文件
        done_trailer_path = Flags.file_done_dic.get(result.number, {}).get("trailer")
        if not done_trailer_path:
            Flags.file_done_dic[result.number].update({"trailer": trailer_file_path})
            if trailer_name == 0:  # 带文件名，已下载成功，删除掉那些不用的文件夹即可
                if await aiofiles.os.path.exists(trailer_old_folder_path):
                    await to_thread(shutil.rmtree, trailer_old_folder_path, ignore_errors=True)
                if trailer_new_folder_path != trailer_old_folder_path and await aiofiles.os.path.exists(
                    trailer_new_folder_path
                ):
                    await to_thread(shutil.rmtree, trailer_new_folder_path, ignore_errors=True)
        LogBuffer.log().write("\n 🟠 Trailer download failed! 将继续使用之前的本地文件！")
        LogBuffer.log().write(f"\n 🍀 Trailer done! (old)({get_used_time(start_time)}s)")
        return True


async def _get_big_poster(
    result: CrawlersResult,
    other: OtherInfo,
    media_context: MediaResourceContext | None = None,
    *,
    poster_auto_best: bool = False,
):
    start_time = time.time()

    if HDPicSource.AMAZON not in manager.config.download_hd_pics:
        return

    # 初始化数据
    poster_url = result.poster
    poster_from_before_amazon = result.poster_from
    hd_pic_url = ""

    # 保持原有类型白名单，仅额外排除素人番号
    if result.scraping_type == FixedScrapingType.SUREN:
        LogBuffer.log().write("\n 🔎 Amazon搜索：检测为素人番号，已跳过")
    elif _should_search_amazon(result):
        if await _should_skip_amazon_for_existing_poster(
            result,
            other,
            poster_auto_best=poster_auto_best,
            media_context=media_context,
        ):
            return result
        originaltitle_amazon_raw = result.originaltitle_amazon
        originaltitle_amazon_replaced = originaltitle_amazon_raw
        series_raw = result.series
        series_replaced = series_raw
        for key, value in ManualConfig.SPECIAL_WORD.items():
            originaltitle_amazon_replaced = originaltitle_amazon_replaced.replace(key, value)
            series_replaced = series_replaced.replace(key, value)
        hd_pic_url = await get_big_pic_by_amazon(
            result,
            originaltitle_amazon_replaced,
            result.actor_amazon,
            series_replaced,
            originaltitle_amazon_raw,
            series_raw,
            media_context=media_context,
        )
        amazon_url = hd_pic_url or (result.poster if result.poster_from == "Amazon" else "")
        amazon_is_hd = bool(hd_pic_url)
        if amazon_url:
            amazon_match_is_hard = is_amazon_hard_match(result)
            should_verify_amazon = manager.config.amazon_strict_pic_verify or not amazon_match_is_hard
            amazon_verify_passed = not should_verify_amazon or await _verify_soft_amazon_poster(
                amazon_url,
                thumb_path=other.thumb_path,
                original_poster_url=poster_url,
                original_poster_from=poster_from_before_amazon,
                media_context=media_context,
                strict=manager.config.amazon_strict_pic_verify,
            )
            if amazon_verify_passed:
                result.poster = amazon_url
                result.poster_from = "Amazon"
                result.image_download = True
                hd_pic_url = amazon_url if amazon_is_hd else ""
            else:
                hd_pic_url = ""
                if result.poster_from == "Amazon":
                    result.poster = poster_url
                    result.poster_from = poster_from_before_amazon

    # 如果找到了高清链接，则替换
    if hd_pic_url:
        result.image_download = True
        LogBuffer.log().write(f"\n 🖼 HD Poster found! ({result.poster_from})({get_used_time(start_time)}s)")

    return result


async def thumb_download(
    result: CrawlersResult,
    other: OtherInfo,
    cd_part: str,
    folder_new_path: Path,
    thumb_final_path: Path,
    media_context: MediaResourceContext | None = None,
) -> bool:
    start_time = time.time()
    poster_path = other.poster_path
    thumb_path = other.thumb_path
    fanart_path = other.fanart_path
    thumb_policy = resource_policy(
        DownloadableFile.THUMB,
        KeepableFile.THUMB,
        download_files=manager.config.download_files,
        keep_files=manager.config.keep_files,
    )

    # 本地存在 thumb.jpg，且勾选保留旧文件时，不下载
    if thumb_path and thumb_policy.should_keep:
        LogBuffer.log().write(f"\n 🍀 Thumb done! (old)({get_used_time(start_time)}s) ")
        return True

    # 如果thumb不下载，看fanart、poster要不要下载，都不下载则返回
    if not thumb_policy.should_download:
        if (
            DownloadableFile.POSTER in manager.config.download_files
            and (KeepableFile.POSTER not in manager.config.keep_files or not poster_path)
            or DownloadableFile.FANART in manager.config.download_files
            and (KeepableFile.FANART not in manager.config.keep_files or not fanart_path)
        ):
            pass
        else:
            return True

    # 尝试复制其他分集。看分集有没有下载，如果下载完成则可以复制，否则就自行下载
    if cd_part:
        done_thumb_path = Flags.file_done_dic.get(result.number, {}).get("thumb")
        if (
            done_thumb_path
            and await aiofiles.os.path.exists(done_thumb_path)
            and split_path(done_thumb_path)[0] == split_path(thumb_final_path)[0]
        ):
            await copy_file_async(done_thumb_path, thumb_final_path)
            LogBuffer.log().write(f"\n 🍀 Thumb done! (copy cd-thumb)({get_used_time(start_time)}s) ")
            result.thumb_from = "copy cd-thumb"
            other.thumb_path = thumb_final_path
            return True

    # 下载图片
    cover_url = result.thumb
    cover_from = result.thumb_from
    if cover_url:
        cover_list = result.thumb_list
        while (cover_from, cover_url) in cover_list:
            cover_list.remove((cover_from, cover_url))
        cover_list.insert(0, (cover_from, cover_url))

        thumb_final_path_temp = thumb_final_path
        if await aiofiles.os.path.exists(thumb_final_path):
            thumb_final_path_temp = thumb_final_path.with_suffix(".[DOWNLOAD].jpg")
        for each in cover_list:
            if not each[1]:
                continue
            cover_from, cover_url = each
            if not cover_url:
                LogBuffer.log().write(
                    f"\n 🟠 检测到 Thumb 图片失效! 跳过！({cover_from})({get_used_time(start_time)}s) " + each[1]
                )
                continue
            result.thumb_from = cover_from
            if media_context is not None:
                downloaded = await media_context.save_image(cover_url, thumb_final_path_temp, folder_new_path)
            else:
                downloaded = await download_file_with_filepath(cover_url, thumb_final_path_temp, folder_new_path)
            if downloaded:
                cover_size = await check_pic_async(thumb_final_path_temp)
                if cover_size:
                    # 图片下载正常，替换旧的 thumb.jpg
                    if thumb_final_path_temp != thumb_final_path:
                        await move_file_async(thumb_final_path_temp, thumb_final_path)
                        await delete_file_async(thumb_final_path_temp)
                    if cd_part:
                        Flags.file_done_dic[result.number].update({"thumb": thumb_final_path})
                    other.thumb_marked = False  # 表示还没有走加水印流程
                    LogBuffer.log().write(f"\n 🍀 Thumb done! ({result.thumb_from})({get_used_time(start_time)}s) ")
                    other.thumb_path = thumb_final_path
                    return True
                LogBuffer.log().write(f"\n 🟠 Thumb download failed! {cover_from}: {cover_url} ")
    else:
        LogBuffer.log().write("\n 🟠 Thumb url is empty! ")

    # 下载失败，本地有图
    if thumb_path:
        LogBuffer.log().write("\n 🟠 Thumb download failed! 将继续使用之前的图片！")
        LogBuffer.log().write(f"\n 🍀 Thumb done! (old)({get_used_time(start_time)}s) ")
        return True
    else:
        if DownloadableFile.IGNORE_PIC_FAIL in manager.config.download_files:
            LogBuffer.log().write("\n 🟠 Thumb download failed! (你已勾选「图片下载失败时，不视为失败！」) ")
            LogBuffer.log().write(f"\n 🍀 Thumb done! (none)({get_used_time(start_time)}s)")
            return True
        else:
            LogBuffer.log().write(
                "\n 🔴 Thumb download failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」 "
            )
            LogBuffer.error().write(
                "Thumb download failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」"
            )
            return False


def _field_priority_try_all_images_enabled() -> bool:
    return bool(manager.config.scrape_like == "info" and manager.config.field_priority_try_all_images)


def _can_direct_download_poster_candidate(
    result: CrawlersResult,
    candidate: PosterCandidate,
    poster_auto_best: bool,
) -> bool:
    if poster_auto_best:
        return True
    if result.scraping_type in POSTER_DIRECT_DOWNLOAD_TYPES:
        return True
    if result.scraping_type == FixedScrapingType.YOUMA:
        return candidate.image_download
    return False


async def _build_poster_candidates(
    result: CrawlersResult,
    *,
    poster_auto_best: bool,
    extra_candidates: list[PosterCandidate] | None = None,
    media_context: MediaResourceContext | None = None,
) -> list[PosterCandidate]:
    candidates = [
        PosterCandidate(result.poster_from or "poster", result.poster, result.image_download)
        for _ in [None]
        if result.poster
    ]
    if extra_candidates:
        candidates.extend(extra_candidates)
    if _field_priority_try_all_images_enabled():
        candidates.extend(
            PosterCandidate(source, url, image_download) for source, url, image_download in result.poster_list if url
        )
    candidates = _dedupe_poster_candidates(candidates)
    candidates = [
        candidate
        for candidate in candidates
        if _can_direct_download_poster_candidate(result, candidate, poster_auto_best)
    ]
    if poster_auto_best:
        sized_candidates = []
        for candidate in candidates:
            sized_candidates.append(
                PosterCandidate(
                    candidate.source,
                    candidate.url,
                    candidate.image_download,
                    await _get_image_size(candidate.url, media_context),
                )
            )
        candidates = sized_candidates
    return candidates


async def _download_poster_candidate(
    result: CrawlersResult,
    other: OtherInfo,
    candidate: PosterCandidate,
    *,
    cd_part: str,
    folder_new_path: Path,
    poster_final_path: Path,
    poster_final_path_temp: Path,
    media_context: MediaResourceContext | None = None,
) -> bool:
    LogBuffer.log().write(f"\n 🖼 Poster策略: 尝试直下 Poster ({candidate.source})")
    start_time = time.time()
    if media_context is not None:
        downloaded = await media_context.save_image(candidate.url, poster_final_path_temp, folder_new_path)
    else:
        downloaded = await download_file_with_filepath(candidate.url, poster_final_path_temp, folder_new_path)
    if not downloaded:
        LogBuffer.log().write(f"\n 🟠 Poster download failed! {candidate.source}: {candidate.url} ")
        return False

    poster_size = await check_pic_async(poster_final_path_temp)
    if not poster_size:
        LogBuffer.log().write(f"\n 🟠 Poster download failed! {candidate.source}: {candidate.url} ")
        return False

    if poster_final_path_temp != poster_final_path:
        await move_file_async(poster_final_path_temp, poster_final_path)
        await delete_file_async(poster_final_path_temp)
    if cd_part:
        Flags.file_done_dic[result.number].update({"poster": poster_final_path})
    result.poster = candidate.url
    result.poster_from = candidate.source
    result.image_download = candidate.image_download or result.image_download
    other.poster_marked = False  # 下载的图，还没加水印
    other.poster_path = poster_final_path
    LogBuffer.log().write(f"\n 🍀 Poster done! ({candidate.source})({get_used_time(start_time)}s)")
    return True


async def _allow_youma_direct_poster_without_auto_best(
    result: CrawlersResult,
    other: OtherInfo,
    media_context: MediaResourceContext | None = None,
) -> None:
    if result.scraping_type != FixedScrapingType.YOUMA or result.image_download or not result.poster:
        return
    if await _is_existing_poster_better_than_youma_crop(result, other, media_context):
        result.image_download = True
        LogBuffer.log().write("\n 🖼 Poster策略: 当前 Poster 不弱于 thumb 右裁剪，允许直下")


async def poster_download(
    result: CrawlersResult,
    other: OtherInfo,
    cd_part: str,
    folder_new_path: Path,
    poster_final_path: Path,
    media_context: MediaResourceContext | None = None,
) -> bool:
    start_time = time.time()
    download_files = manager.config.download_files
    keep_files = manager.config.keep_files
    poster_policy = resource_policy(
        DownloadableFile.POSTER,
        KeepableFile.POSTER,
        download_files=download_files,
        keep_files=keep_files,
    )
    poster_path = other.poster_path
    thumb_path = other.thumb_path
    fanart_path = other.fanart_path
    # 不下载poster、不保留poster时，返回
    if poster_policy.should_remove_existing:
        if poster_path:
            await delete_file_async(poster_path)
        return True

    # 本地有poster时，且勾选保留旧文件时，不下载
    if poster_path and poster_policy.should_keep:
        LogBuffer.log().write(f"\n 🍀 Poster done! (old)({get_used_time(start_time)}s)")
        return True

    # 不下载时返回
    if not poster_policy.should_download:
        return True

    # 尝试复制其他分集。看分集有没有下载，如果下载完成则可以复制，否则就自行下载
    if cd_part:
        done_poster_path = Flags.file_done_dic.get(result.number, {}).get("poster")
        if (
            done_poster_path
            and await aiofiles.os.path.exists(done_poster_path)
            and split_path(done_poster_path)[0] == split_path(poster_final_path)[0]
        ):
            await copy_file_async(done_poster_path, poster_final_path)
            result.poster_from = "copy cd-poster"
            other.poster_path = poster_final_path
            LogBuffer.log().write(f"\n 🍀 Poster done! (copy cd-poster)({get_used_time(start_time)}s)")
            return True

    # 命中对应的“不裁剪直接复制缩略图”选项时，直接复制 thumb。
    if thumb_path:
        copy_flag = _get_poster_copy_policy(result, download_files)
        if copy_flag:
            await copy_file_async(thumb_path, poster_final_path)
            other.poster_marked = other.thumb_marked
            result.poster_from = "copy thumb"
            other.poster_path = poster_final_path
            LogBuffer.log().write(f"\n 🖼 Poster策略: 命中直复制缩略图({result.scraping_type.value})")
            LogBuffer.log().write(f"\n 🍀 Poster done! (copy thumb)({get_used_time(start_time)}s)")
            return True

    poster_auto_best = (
        result.scraping_type == FixedScrapingType.YOUMA
        and DownloadableFile.POSTER_AUTO_BEST in download_files
        and DownloadableFile.IGNORE_YOUMA not in download_files
    )
    direct_poster_candidates = []
    if poster_auto_best and result.poster:
        direct_poster_candidates.append(
            PosterCandidate(result.poster_from or "poster", result.poster, result.image_download)
        )

    # 获取高清 poster
    await _get_big_poster(result, other, media_context, poster_auto_best=poster_auto_best)
    if _is_vr_result(result) and result.poster:
        result.image_download = True
        if poster_auto_best:
            LogBuffer.log().write("\n 🖼 Poster选优: VR作品保持直下 Poster 策略")
    if not poster_auto_best:
        await _allow_youma_direct_poster_without_auto_best(result, other, media_context)

    # 下载图片
    poster_final_path_temp = poster_final_path
    if await aiofiles.os.path.exists(poster_final_path):
        poster_final_path_temp = poster_final_path.with_suffix(".[DOWNLOAD].jpg")

    poster_candidates = await _build_poster_candidates(
        result,
        poster_auto_best=poster_auto_best,
        extra_candidates=direct_poster_candidates,
        media_context=media_context,
    )
    if poster_auto_best and not _is_vr_result(result):
        crop_size = await _get_thumb_right_crop_size_from_path(fanart_path or thumb_path)
        failed_urls: set[str] = set()
        while poster_candidates:
            available_candidates = [
                candidate
                for candidate in poster_candidates
                if MediaResourceContext.normalize_url(candidate.url) not in failed_urls
            ]
            best_candidate = _select_best_poster_candidate(available_candidates, crop_size)
            if best_candidate is None:
                result.image_download = False
                break
            result.poster = best_candidate.url
            result.poster_from = best_candidate.source
            result.image_download = True
            if await _download_poster_candidate(
                result,
                other,
                best_candidate,
                cd_part=cd_part,
                folder_new_path=folder_new_path,
                poster_final_path=poster_final_path,
                poster_final_path_temp=poster_final_path_temp,
                media_context=media_context,
            ):
                return True
            failed_urls.add(MediaResourceContext.normalize_url(best_candidate.url))
            LogBuffer.log().write("\n 🖼 Poster选优: 移除失败候选后重新比较")
    else:
        for candidate in poster_candidates:
            if await _download_poster_candidate(
                result,
                other,
                candidate,
                cd_part=cd_part,
                folder_new_path=folder_new_path,
                poster_final_path=poster_final_path,
                poster_final_path_temp=poster_final_path_temp,
                media_context=media_context,
            ):
                return True

    # 判断之前有没有 poster 和 thumb
    if not poster_path and not thumb_path:
        other.poster_path = None
        if DownloadableFile.IGNORE_PIC_FAIL in download_files:
            LogBuffer.log().write("\n 🟠 Poster download failed! (你已勾选「图片下载失败时，不视为失败！」) ")
            LogBuffer.log().write(f"\n 🍀 Poster done! (none)({get_used_time(start_time)}s)")
            return True
        else:
            LogBuffer.log().write(
                "\n 🔴 Poster download failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」 "
            )
            LogBuffer.error().write(
                "Poster download failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」"
            )
            return False

    # 使用thumb裁剪
    poster_final_path_temp = poster_final_path.with_suffix(".[CUT].jpg")
    if fanart_path:
        thumb_path = fanart_path
    cut_log = LogBuffer.log().write
    if thumb_path and await asyncio.to_thread(
        cut_thumb_to_poster, result, thumb_path, poster_final_path_temp, result.scraping_type, cut_log
    ):
        # 裁剪成功，替换旧图
        await move_file_async(poster_final_path_temp, poster_final_path)
        if cd_part:
            Flags.file_done_dic[result.number].update({"poster": poster_final_path})
        other.poster_path = poster_final_path
        other.poster_marked = False
        return True

    # 裁剪失败，本地有图
    if poster_path:
        LogBuffer.log().write("\n 🟠 Poster cut failed! 将继续使用之前的图片！")
        LogBuffer.log().write(f"\n 🍀 Poster done! (old)({get_used_time(start_time)}s) ")
        return True
    else:
        if DownloadableFile.IGNORE_PIC_FAIL in download_files:
            LogBuffer.log().write("\n 🟠 Poster cut failed! (你已勾选「图片下载失败时，不视为失败！」) ")
            LogBuffer.log().write(f"\n 🍀 Poster done! (none)({get_used_time(start_time)}s)")
            return True
        else:
            LogBuffer.log().write(
                "\n 🔴 Poster cut failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」 "
            )
            LogBuffer.error().write("Poster failed！你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」")
            return False


async def fanart_download(
    number: str,
    other: OtherInfo,
    cd_part: str,
    fanart_final_path: Path,
) -> bool:
    """
    复制thumb为fanart
    """
    start_time = time.time()
    thumb_path = other.thumb_path
    fanart_path = other.fanart_path
    download_files = manager.config.download_files
    keep_files = manager.config.keep_files
    fanart_policy = resource_policy(
        DownloadableFile.FANART,
        KeepableFile.FANART,
        download_files=download_files,
        keep_files=keep_files,
    )

    # 不保留不下载时删除返回
    if fanart_policy.should_remove_existing:
        if fanart_path and await aiofiles.os.path.exists(fanart_path):
            await delete_file_async(fanart_path)
        return True

    # 保留，并且本地存在 fanart.jpg，不下载返回
    if fanart_policy.should_keep and fanart_path:
        LogBuffer.log().write(f"\n 🍀 Fanart done! (old)({get_used_time(start_time)}s)")
        return True

    # 不下载时，返回
    if not fanart_policy.should_download:
        return True

    # 尝试复制其他分集。看分集有没有下载，如果下载完成则可以复制，否则就自行下载
    if cd_part:
        done_fanart_path = Flags.file_done_dic.get(number, {}).get("fanart")
        if (
            done_fanart_path
            and await aiofiles.os.path.exists(done_fanart_path)
            and done_fanart_path.parent == fanart_final_path.parent
        ):
            if fanart_path:
                await delete_file_async(fanart_path)
            await copy_file_async(done_fanart_path, fanart_final_path)
            other.fanart_path = fanart_final_path
            LogBuffer.log().write(f"\n 🍀 Fanart done! (copy cd-fanart)({get_used_time(start_time)}s)")
            return True

    # 复制thumb
    if thumb_path:
        if fanart_path:
            await delete_file_async(fanart_path)
        await copy_file_async(thumb_path, fanart_final_path)
        other.fanart_path = fanart_final_path
        other.fanart_marked = other.thumb_marked
        LogBuffer.log().write(f"\n 🍀 Fanart done! (copy thumb)({get_used_time(start_time)}s)")
        if cd_part:
            Flags.file_done_dic[number].update({"fanart": fanart_final_path})
        return True
    else:
        # 本地有 fanart 时，不下载
        if fanart_path:
            LogBuffer.log().write("\n 🟠 Fanart copy failed! 未找到 thumb 图片，将继续使用之前的图片！")
            LogBuffer.log().write(f"\n 🍀 Fanart done! (old)({get_used_time(start_time)}s)")
            return True

        else:
            if DownloadableFile.IGNORE_PIC_FAIL in download_files:
                LogBuffer.log().write("\n 🟠 Fanart failed! (你已勾选「图片下载失败时，不视为失败！」) ")
                LogBuffer.log().write(f"\n 🍀 Fanart done! (none)({get_used_time(start_time)}s)")
                return True
            else:
                LogBuffer.log().write(
                    "\n 🔴 Fanart failed! 你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」 "
                )
                LogBuffer.error().write(
                    "Fanart 下载失败！你可以到「设置」-「下载」，勾选「图片下载失败时，不视为失败！」"
                )
                return False


async def extrafanart_download(extrafanart: list[str], extrafanart_from: str, folder_new_path: Path) -> bool | None:
    start_time = time.time()
    download_files = manager.config.download_files
    keep_files = manager.config.keep_files
    extrafanart_policy = resource_policy(
        DownloadableFile.EXTRAFANART,
        KeepableFile.EXTRAFANART,
        download_files=download_files,
        keep_files=keep_files,
    )
    extrafanart_list = extrafanart
    extrafanart_folder_path = folder_new_path / "extrafanart"

    # 不下载不保留时删除返回
    if extrafanart_policy.should_remove_existing:
        if await aiofiles.os.path.exists(extrafanart_folder_path):
            await to_thread(shutil.rmtree, extrafanart_folder_path, ignore_errors=True)
        return

    # 本地存在 extrafanart_folder，且勾选保留旧文件时，不下载
    if extrafanart_policy.should_keep and await aiofiles.os.path.exists(extrafanart_folder_path):
        LogBuffer.log().write(f"\n 🍀 Extrafanart done! (old)({get_used_time(start_time)}s) ")
        return True

    # 如果 extrafanart 不下载
    if not extrafanart_policy.should_download:
        return True

    if extrafanart_list:
        extrafanart_folder_path_temp = extrafanart_folder_path
        if await aiofiles.os.path.exists(extrafanart_folder_path_temp):
            extrafanart_folder_path_temp = extrafanart_folder_path.with_name(
                extrafanart_folder_path.name + "[DOWNLOAD]"
            )
            if not await aiofiles.os.path.exists(extrafanart_folder_path_temp):
                await aiofiles.os.makedirs(extrafanart_folder_path_temp)
        else:
            await aiofiles.os.makedirs(extrafanart_folder_path_temp)

        extrafanart_count = 0
        extrafanart_count_succ = 0
        task_list = []
        for extrafanart_url in extrafanart_list:
            extrafanart_count += 1
            extrafanart_name = "fanart" + str(extrafanart_count) + ".jpg"
            extrafanart_file_path = extrafanart_folder_path_temp / extrafanart_name
            task_list.append((extrafanart_url, extrafanart_file_path, extrafanart_folder_path_temp, extrafanart_name))

        # 使用异步并发执行下载任务
        tasks = [download_extrafanart_task(task) for task in task_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if res is True:
                extrafanart_count_succ += 1
        if extrafanart_count_succ == extrafanart_count:
            if extrafanart_folder_path_temp != extrafanart_folder_path:
                await to_thread(shutil.rmtree, extrafanart_folder_path)
                await aiofiles.os.rename(extrafanart_folder_path_temp, extrafanart_folder_path)
            LogBuffer.log().write(
                f"\n 🍀 ExtraFanart done! ({extrafanart_from} {extrafanart_count_succ}/{extrafanart_count})({get_used_time(start_time)}s)"
            )
            return True
        else:
            LogBuffer.log().write(
                f"\n 🟠 ExtraFanart download failed! ({extrafanart_from} {extrafanart_count_succ}/{extrafanart_count})({get_used_time(start_time)}s)"
            )
            if extrafanart_folder_path_temp != extrafanart_folder_path:
                await to_thread(shutil.rmtree, extrafanart_folder_path_temp)
            else:
                LogBuffer.log().write(f"\n 🍀 ExtraFanart done! (incomplete)({get_used_time(start_time)}s)")
                return False
        LogBuffer.log().write("\n 🟠 ExtraFanart download failed! 将继续使用之前的本地文件！")
    if await aiofiles.os.path.exists(extrafanart_folder_path):  # 使用旧文件
        LogBuffer.log().write(f"\n 🍀 ExtraFanart done! (old)({get_used_time(start_time)}s)")
        return True
