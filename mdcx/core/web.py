"""
刮削过程的网络操作
"""

import asyncio
import re
import shutil
import time
from asyncio import to_thread
from io import BytesIO
from pathlib import Path

import aiofiles
import aiofiles.os
from PIL import Image

from ..base.web import (
    check_url,
    download_extrafanart_task,
    download_file_with_filepath,
    get_big_pic_by_google,
    get_dmm_trailer,
    get_imgsize,
)
from ..config.enums import DownloadableFile, FixedScrapingType, HDPicSource
from ..config.manager import manager
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

AMAZON_SEARCH_SCRAPING_TYPES = {FixedScrapingType.YOUMA}
AMAZON_SEARCH_VARIANT_MOSAICS = {"流出", "无码破解", "無碼破解"}
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
    return result.mosaic in AMAZON_SEARCH_VARIANT_MOSAICS | AMAZON_SEARCH_SPECIAL_MOSAICS


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
        return await media_context.probe_size(url)
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
    if best_from.startswith("Google"):
        other.poster_size = best_size
    LogBuffer.log().write(f"\n 🖼 Poster选优: 使用 {best_from} {best_size}")


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
) -> bool:
    LogBuffer.log().write("\n 🔎 Amazon图片校验：软匹配，开始与已获取图片比对")
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
        if DownloadableFile.TRAILER not in download_files and DownloadableFile.TRAILER not in keep_files:
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
        if DownloadableFile.TRAILER not in download_files and DownloadableFile.TRAILER not in keep_files:
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
    if DownloadableFile.TRAILER in keep_files and await aiofiles.os.path.exists(trailer_file_path):
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
    if DownloadableFile.TRAILER not in download_files:
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


async def _get_big_thumb(
    result: CrawlersResult,
    other: OtherInfo,
    media_context: MediaResourceContext | None = None,
):
    """
    获取背景大图：
    1，官网图片
    2，Amazon 图片
    3，Google 搜图
    """
    start_time = time.time()
    if "thumb" not in manager.config.download_hd_pics:
        return
    number = result.number
    letters = result.letters
    number_lower_line = number.lower()
    number_lower_no_line = number_lower_line.replace("-", "")
    thumb_width = 0

    # faleno.jp 番号检查，都是大图，返回即可
    if result.thumb_from in ["faleno", "dahlia"]:
        if result.thumb:
            LogBuffer.log().write(f"\n 🖼 HD Thumb found! ({result.thumb_from})({get_used_time(start_time)}s)")
        other.poster_big = True
        return result

    # prestige 图片有的是大图，需要检测图片分辨率
    elif result.thumb_from in ["prestige", "mgstage"]:
        if result.thumb:
            thumb_width, h = await _get_image_size(result.thumb, media_context)

    # 片商官网查询
    elif HDPicSource.OFFICIAL in manager.config.download_hd_pics:
        # faleno.jp 番号检查
        if re.findall(r"F[A-Z]{2}SS", number):
            req_url = f"https://faleno.jp/top/works/{number_lower_no_line}/"
            async with manager.acquire_computed() as computed:
                response, error = await computed.async_client.get_text(req_url)
            if response is not None:
                temp_url = re.findall(
                    r'src="((https://cdn.faleno.net/top/wp-content/uploads/[^_]+_)([^?]+))\?output-quality=', response
                )
                if temp_url:
                    result.thumb = temp_url[0][0]
                    result.poster = temp_url[0][1] + "2125.jpg"
                    result.thumb_from = "faleno"
                    result.poster_from = "faleno"
                    other.poster_big = True
                    trailer_temp = re.findall(r'class="btn09"><a class="pop_sample" href="([^"]+)', response)
                    if trailer_temp:
                        result.trailer = trailer_temp[0]
                        result.trailer_from = "faleno"
                    LogBuffer.log().write(f"\n 🖼 HD Thumb found! (faleno)({get_used_time(start_time)}s)")
                    return result

        # km-produce.com 番号检查
        number_letter = letters.lower()
        kmp_key = ["vrkm", "mdtm", "mkmp", "savr", "bibivr", "scvr", "slvr", "averv", "kbvr", "cbikmv"]
        prestige_key = ["abp", "abw", "aka", "prdvr", "pvrbst", "sdvr", "docvr"]
        if number_letter in kmp_key:
            req_url = f"https://km-produce.com/img/title1/{number_lower_line}.jpg"
            real_url = ""
            if media_context is not None:
                if (await media_context.get_size(req_url))[0]:
                    real_url = req_url
            else:
                real_url = await check_url(req_url) or ""
            if real_url:
                result.thumb = real_url
                result.thumb_from = "km-produce"
                LogBuffer.log().write(f"\n 🖼 HD Thumb found! (km-produce)({get_used_time(start_time)}s)")
                return result

        # www.prestige-av.com 番号检查
        elif number_letter in prestige_key:
            number_num = re.findall(r"\d+", number)[0]
            if number_letter == "abw" and int(number_num) > 280:
                pass
            else:
                req_url = f"https://www.prestige-av.com/api/media/goods/prestige/{number_letter}/{number_num}/pb_{number_lower_line}.jpg"
                if number_letter == "docvr":
                    req_url = f"https://www.prestige-av.com/api/media/goods/doc/{number_letter}/{number_num}/pb_{number_lower_line}.jpg"
                if (await _get_image_size(req_url, media_context))[0] >= 800:
                    result.thumb = req_url
                    result.poster = req_url.replace("/pb_", "/pf_")
                    result.thumb_from = "prestige"
                    result.poster_from = "prestige"
                    other.poster_big = True
                    LogBuffer.log().write(f"\n 🖼 HD Thumb found! (prestige)({get_used_time(start_time)}s)")
                    return result

    # 使用google以图搜图
    pic_url = result.thumb
    if HDPicSource.GOOGLE in manager.config.download_hd_pics and pic_url and result.thumb_from != "theporndb":
        thumb_url, cover_size = await get_big_pic_by_google(
            pic_url,
            image_size_getter=media_context.probe_size if media_context is not None else None,
        )
        if thumb_url and cover_size[0] > thumb_width:
            other.thumb_size = cover_size
            pic_domain = re.findall(r"://([^/]+)", thumb_url)[0]
            result.thumb_from = f"Google({pic_domain})"
            result.thumb = thumb_url
            LogBuffer.log().write(f"\n 🖼 HD Thumb found! ({result.thumb_from})({get_used_time(start_time)}s)")

    return result


async def _get_big_poster(
    result: CrawlersResult,
    other: OtherInfo,
    media_context: MediaResourceContext | None = None,
):
    start_time = time.time()

    # 未勾选下载高清图poster时，返回
    if "poster" not in manager.config.download_hd_pics:
        return

    # 如果有大图时，直接下载
    if other.poster_big and (await _get_image_size(result.poster, media_context))[1] > 600:
        result.image_download = True
        LogBuffer.log().write(f"\n 🖼 HD Poster found! ({result.poster_from})({get_used_time(start_time)}s)")
        return

    # 初始化数据
    number = result.number
    poster_url = result.poster
    poster_from_before_amazon = result.poster_from
    hd_pic_url = ""
    poster_width = 0

    # 保持原有类型白名单，仅额外排除素人番号
    if HDPicSource.AMAZON in manager.config.download_hd_pics and result.scraping_type == FixedScrapingType.SUREN:
        LogBuffer.log().write("\n 🔎 Amazon搜索：检测为素人番号，已跳过")
    elif HDPicSource.AMAZON in manager.config.download_hd_pics and _should_search_amazon(result):
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
            if is_amazon_hard_match(result) or await _verify_soft_amazon_poster(
                amazon_url,
                thumb_path=other.thumb_path,
                original_poster_url=poster_url,
                original_poster_from=poster_from_before_amazon,
                media_context=media_context,
            ):
                result.poster = amazon_url
                result.poster_from = "Amazon"
                result.image_download = True
                hd_pic_url = amazon_url if amazon_is_hd else ""
            else:
                hd_pic_url = ""
                if result.poster_from == "Amazon":
                    result.poster = poster_url
                    result.poster_from = poster_from_before_amazon

    # 通过番号去 官网 查询获取稍微大一些的封面图，以便去 Google 搜索
    if not hd_pic_url and HDPicSource.OFFICIAL in manager.config.download_hd_pics and result.poster_from != "Amazon":
        letters = result.letters.upper()
        async with manager.acquire_computed() as computed:
            official_url = computed.official_websites.get(letters)
            if official_url:
                url_search = official_url + "/search/list?keyword=" + number.replace("-", "")
                html_search, error = await computed.async_client.get_text(url_search)
            else:
                html_search = None
        if official_url and html_search is not None:
            poster_url_list = re.findall(r'img class="c-main-bg lazyload" data-src="([^"]+)"', html_search)
            if poster_url_list:
                # 使用官网图作为封面去 google 搜索
                poster_url = poster_url_list[0]
                result.poster = poster_url
                result.poster_from = official_url.split(".")[-2].replace("https://", "")
                # vr作品或者官网图片高度大于500时，下载封面图开
                if "VR" in number.upper() or (await _get_image_size(poster_url, media_context))[1] > 500:
                    result.image_download = True

    # 使用google以图搜图，放在最后是因为有时有错误，比如 kawd-943
    poster_url = result.poster
    if (
        not hd_pic_url
        and poster_url
        and HDPicSource.GOOGLE in manager.config.download_hd_pics
        and result.poster_from != "theporndb"
    ):
        hd_pic_url, poster_size = await get_big_pic_by_google(
            poster_url,
            poster=True,
            image_size_getter=media_context.probe_size if media_context is not None else None,
        )
        if hd_pic_url:
            if "prestige" in result.poster or result.poster_from == "Amazon":
                poster_width, _ = await _get_image_size(poster_url, media_context)
            if poster_size[0] > poster_width:
                result.poster = hd_pic_url
                other.poster_size = poster_size
                pic_domain = re.findall(r"://([^/]+)", hd_pic_url)[0]
                result.poster_from = f"Google({pic_domain})"

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

    # 本地存在 thumb.jpg，且勾选保留旧文件时，不下载
    if thumb_path and DownloadableFile.THUMB in manager.config.keep_files:
        LogBuffer.log().write(f"\n 🍀 Thumb done! (old)({get_used_time(start_time)}s) ")
        return True

    # 如果thumb不下载，看fanart、poster要不要下载，都不下载则返回
    if DownloadableFile.THUMB not in manager.config.download_files:
        if (
            DownloadableFile.POSTER in manager.config.download_files
            and (DownloadableFile.POSTER not in manager.config.keep_files or not poster_path)
            or DownloadableFile.FANART in manager.config.download_files
            and (DownloadableFile.FANART not in manager.config.keep_files or not fanart_path)
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

    # 获取高清背景图
    await _get_big_thumb(result, other, media_context)

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
                    if (
                        not cover_from.startswith("Google")
                        or cover_size == other.thumb_size
                        or (
                            cover_size[0] >= 800
                            and abs(cover_size[0] / cover_size[1] - other.thumb_size[0] / other.thumb_size[1]) <= 0.1
                        )
                    ):
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
                    else:
                        await delete_file_async(thumb_final_path_temp)
                        LogBuffer.log().write(
                            f"\n 🟠 检测到 Thumb 分辨率不对{str(cover_size)}! 已删除 ({cover_from})({get_used_time(start_time)}s)"
                        )
                        continue
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
    poster_path = other.poster_path
    thumb_path = other.thumb_path
    fanart_path = other.fanart_path
    # 不下载poster、不保留poster时，返回
    if DownloadableFile.POSTER not in download_files and DownloadableFile.POSTER not in keep_files:
        if poster_path:
            await delete_file_async(poster_path)
        return True

    # 本地有poster时，且勾选保留旧文件时，不下载
    if poster_path and DownloadableFile.POSTER in keep_files:
        LogBuffer.log().write(f"\n 🍀 Poster done! (old)({get_used_time(start_time)}s)")
        return True

    # 不下载时返回
    if DownloadableFile.POSTER not in download_files:
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
    direct_poster_url = result.poster if poster_auto_best else ""
    direct_poster_from = result.poster_from if poster_auto_best else ""
    direct_poster_size = await _get_image_size(direct_poster_url, media_context) if direct_poster_url else (0, 0)

    # 获取高清 poster
    await _get_big_poster(result, other, media_context)
    if _is_vr_result(result) and result.poster:
        result.image_download = True
        if poster_auto_best:
            LogBuffer.log().write("\n 🖼 Poster选优: VR作品保持直下 Poster 策略")
    elif poster_auto_best:
        await _select_poster_auto_best(
            result,
            other,
            direct_url=direct_poster_url,
            direct_from=direct_poster_from,
            direct_size=direct_poster_size,
            crop_source_path=fanart_path or thumb_path,
            media_context=media_context,
        )

    # 下载图片
    poster_url = result.poster
    poster_from = result.poster_from
    poster_final_path_temp = poster_final_path
    if await aiofiles.os.path.exists(poster_final_path):
        poster_final_path_temp = poster_final_path.with_suffix(".[DOWNLOAD].jpg")
    try_direct_poster = bool(poster_url) and _should_try_direct_poster(result, poster_auto_best)
    LogBuffer.log().write(
        f"\n 🖼 Poster策略: type={result.scraping_type.value}, poster={'yes' if poster_url else 'no'}, "
        f"image_download={result.image_download}, auto_best={poster_auto_best}, direct={'yes' if try_direct_poster else 'no'}"
    )
    if try_direct_poster:
        start_time = time.time()
        if media_context is not None:
            downloaded = await media_context.save_image(poster_url, poster_final_path_temp, folder_new_path)
        else:
            downloaded = await download_file_with_filepath(poster_url, poster_final_path_temp, folder_new_path)
        if downloaded:
            poster_size = await check_pic_async(poster_final_path_temp)
            if poster_size:
                if (
                    not poster_from.startswith("Google")
                    or poster_size == other.poster_size
                    or "media-amazon.com" in poster_url
                ):
                    if poster_final_path_temp != poster_final_path:
                        await move_file_async(poster_final_path_temp, poster_final_path)
                        await delete_file_async(poster_final_path_temp)
                    if cd_part:
                        Flags.file_done_dic[result.number].update({"poster": poster_final_path})
                    other.poster_marked = False  # 下载的图，还没加水印
                    other.poster_path = poster_final_path
                    LogBuffer.log().write(f"\n 🍀 Poster done! ({poster_from})({get_used_time(start_time)}s)")
                    return True
                else:
                    await delete_file_async(poster_final_path_temp)
                    LogBuffer.log().write(f"\n 🟠 检测到 Poster 分辨率不对{str(poster_size)}! 已删除 ({poster_from})")
    else:
        LogBuffer.log().write("\n 🖼 Poster策略: 未尝试直下 poster，准备进入裁剪")

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

    # 不保留不下载时删除返回
    if DownloadableFile.FANART not in keep_files and DownloadableFile.FANART not in download_files:
        if fanart_path and await aiofiles.os.path.exists(fanart_path):
            await delete_file_async(fanart_path)
        return True

    # 保留，并且本地存在 fanart.jpg，不下载返回
    if DownloadableFile.FANART in keep_files and fanart_path:
        LogBuffer.log().write(f"\n 🍀 Fanart done! (old)({get_used_time(start_time)}s)")
        return True

    # 不下载时，返回
    if DownloadableFile.FANART not in download_files:
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
    extrafanart_list = extrafanart
    extrafanart_folder_path = folder_new_path / "extrafanart"

    # 不下载不保留时删除返回
    if DownloadableFile.EXTRAFANART not in download_files and DownloadableFile.EXTRAFANART not in keep_files:
        if await aiofiles.os.path.exists(extrafanart_folder_path):
            await to_thread(shutil.rmtree, extrafanart_folder_path, ignore_errors=True)
        return

    # 本地存在 extrafanart_folder，且勾选保留旧文件时，不下载
    if DownloadableFile.EXTRAFANART in keep_files and await aiofiles.os.path.exists(extrafanart_folder_path):
        LogBuffer.log().write(f"\n 🍀 Extrafanart done! (old)({get_used_time(start_time)}s) ")
        return True

    # 如果 extrafanart 不下载
    if DownloadableFile.EXTRAFANART not in download_files:
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
