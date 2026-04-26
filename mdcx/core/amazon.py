"""
Amazon 相关封面搜索与条码识别逻辑
"""

import re
import urllib.parse
from asyncio import to_thread
from difflib import SequenceMatcher
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from lxml import etree
from PIL import Image

from ..base.web import get_amazon_data, get_imgsize
from ..config.manager import manager
from ..models.log_buffer import LogBuffer
from ..models.types import CrawlersResult
from ..utils import convert_half


def _normalize_amazon_barcode(barcode: str) -> str:
    digits = re.sub(r"\D", "", str(barcode or ""))
    return digits if len(digits) == 13 else ""


def _extract_labeled_amazon_barcodes(text: str) -> set[str]:
    normalized_text = str(text or "")
    if not normalized_text:
        return set()
    normalized_text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", normalized_text)
    normalized_text = normalized_text.replace("\u00a0", " ")
    result: set[str] = set()
    for raw_barcode in re.findall(
        r"(?i)(?:EAN|JAN|ISBN(?:-13)?)\s*[：:﹕]?\s*([0-9][0-9\-\s]{10,20})", normalized_text
    ):
        if barcode := _normalize_amazon_barcode(raw_barcode):
            result.add(barcode)
    return result


def _get_amazon_total_result_count(html_content: str) -> int | None:
    if not html_content:
        return None
    if matched := re.search(r'"totalResultCount":(\d+)', html_content):
        return int(matched.group(1))
    return None


def _is_valid_ean13_barcode(barcode: str) -> bool:
    if not (digits := _normalize_amazon_barcode(barcode)):
        return False
    numbers = [int(each) for each in digits]
    check_digit = (10 - ((sum(numbers[:-1:2]) + 3 * sum(numbers[1:-1:2])) % 10)) % 10
    return check_digit == numbers[-1]


@lru_cache(maxsize=1)
def _get_amazon_barcode_digit_templates() -> dict[str, tuple[object, ...]]:
    import cv2
    import numpy as np

    result: dict[str, tuple[object, ...]] = {}
    fonts = (
        cv2.FONT_HERSHEY_SIMPLEX,
        cv2.FONT_HERSHEY_DUPLEX,
        cv2.FONT_HERSHEY_COMPLEX,
        cv2.FONT_HERSHEY_TRIPLEX,
    )
    for digit in "0123456789":
        templates: list[object] = []
        for font in fonts:
            for scale in (1.8, 2.0, 2.2):
                canvas = np.full((128, 96), 255, np.uint8)
                (text_width, text_height), baseline = cv2.getTextSize(digit, font, scale, 3)
                x = (canvas.shape[1] - text_width) // 2
                y = (canvas.shape[0] + text_height) // 2 - baseline
                cv2.putText(canvas, digit, (x, y), font, scale, 0, 3, cv2.LINE_AA)
                _, binary = cv2.threshold(canvas, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                ys, xs = np.where(binary > 0)
                if len(xs) == 0:
                    continue
                glyph = binary[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
                templates.append(cv2.resize(glyph, (40, 64), interpolation=cv2.INTER_AREA))
        result[digit] = tuple(templates)
    return result


def _normalize_amazon_barcode_digit_glyph(glyph: object) -> object | None:
    import cv2
    import numpy as np

    glyph_array = np.asarray(glyph)
    if glyph_array.ndim != 2:
        return None
    ys, xs = np.where(glyph_array > 0)
    if len(xs) == 0:
        return None
    cropped = glyph_array[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    return cv2.resize(cropped, (40, 64), interpolation=cv2.INTER_AREA)


def _rank_amazon_barcode_digits(glyph: object) -> list[tuple[float, str]]:
    import cv2

    ranked: list[tuple[float, str]] = []
    for digit, templates in _get_amazon_barcode_digit_templates().items():
        if not templates:
            continue
        score = max(
            float(cv2.matchTemplate(glyph, each_template, cv2.TM_CCOEFF_NORMED)[0][0]) for each_template in templates
        )
        ranked.append((score, digit))
    ranked.sort(reverse=True)
    return ranked


def _beam_search_amazon_ean13_candidates_from_ranked_digits(
    ranked_digits: list[list[tuple[float, str]]],
    limit: int = 5,
) -> list[str]:
    beams: list[tuple[str, float]] = [("", 0.0)]
    for each_ranked in ranked_digits:
        next_beams: list[tuple[str, float]] = []
        for prefix, score in beams:
            for each_score, digit in each_ranked[:3]:
                next_beams.append((prefix + digit, score + each_score))
        next_beams.sort(key=lambda item: item[1], reverse=True)
        beams = next_beams[:120]

    valid = [(digits, score) for digits, score in beams if _is_valid_ean13_barcode(digits)]
    valid.sort(key=lambda item: item[1], reverse=True)
    result: list[str] = []
    seen_digits: set[str] = set()
    for digits, _ in valid:
        if digits in seen_digits:
            continue
        seen_digits.add(digits)
        result.append(digits)
        if len(result) >= limit:
            break
    return result


def _beam_search_amazon_ean13_from_ranked_digits(ranked_digits: list[list[tuple[float, str]]]) -> str:
    candidates = _beam_search_amazon_ean13_candidates_from_ranked_digits(ranked_digits, limit=1)
    return candidates[0] if candidates else ""


def _extract_amazon_barcode_label_roi(gray_image: object, detected_points: object) -> object | None:
    import cv2
    import numpy as np

    gray_array = np.asarray(gray_image)
    points_array = np.asarray(detected_points, dtype=np.float32)
    if gray_array.ndim != 2 or points_array.shape != (4, 2):
        return None

    x1 = max(int(np.floor(points_array[:, 0].min())), 0)
    x2 = min(int(np.ceil(points_array[:, 0].max())), gray_array.shape[1])
    y1 = max(int(np.floor(points_array[:, 1].min())), 0)
    y2 = min(int(np.ceil(points_array[:, 1].max())), gray_array.shape[0])
    width = x2 - x1
    height = y2 - y1
    if width < 20 or height < 8:
        return None

    expand_x_left = max(int(width * 0.55), 6)
    expand_x_right = max(int(width * 0.18), 4)
    expand_y_top = max(int(height * 0.45), 4)
    expand_y_bottom = max(int(height * 0.85), 8)
    roi_x1 = max(x1 - expand_x_left, 0)
    roi_x2 = min(x2 + expand_x_right, gray_array.shape[1])
    roi_y1 = max(y1 - expand_y_top, 0)
    roi_y2 = min(y2 + expand_y_bottom, gray_array.shape[0])
    roi = gray_array[roi_y1:roi_y2, roi_x1:roi_x2]
    if roi.size == 0:
        return None

    best_candidate: tuple[float, int, int, int, int] | None = None
    for threshold in (150, 160, 170, 180, 190, 200):
        _, bright_mask = cv2.threshold(roi, threshold, 255, cv2.THRESH_BINARY)
        component_count, _, stats, _ = cv2.connectedComponentsWithStats(bright_mask, 8)
        for index in range(1, component_count):
            comp_x, comp_y, comp_w, comp_h, comp_area = stats[index]
            if comp_area < max(int(roi.size * 0.01), 150):
                continue
            if comp_w < max(int(width * 0.5), 20) or comp_h < max(int(height * 1.2), 18):
                continue
            overlap_x = min(comp_x + comp_w, x2 - roi_x1) - max(comp_x, x1 - roi_x1)
            if overlap_x < width * 0.6:
                continue
            bottom_gap = abs((comp_y + comp_h) - (y2 - roi_y1 + height * 0.65))
            score = float(comp_area) - float(bottom_gap) * 10.0
            candidate = (score, comp_x, comp_y, comp_w, comp_h)
            if best_candidate is None or candidate > best_candidate:
                best_candidate = candidate

    if best_candidate is None:
        return None

    _, label_x, label_y, label_w, label_h = best_candidate
    return roi[label_y : label_y + label_h, label_x : label_x + label_w]


def _collect_amazon_barcode_ocr_candidates_from_components(
    binary_image: object,
    components: list[tuple[int, int, int, int]],
) -> list[str]:
    if not components:
        return []

    median_height = sorted(comp_h for _, _, _, comp_h in components)[len(components) // 2]
    ranked_digits: list[list[tuple[float, str]]] = []
    for comp_x, comp_y, comp_w, comp_h in components:
        glyph_image = binary_image[comp_y : comp_y + comp_h, comp_x : comp_x + comp_w]
        glyph = _normalize_amazon_barcode_digit_glyph(glyph_image)
        if median_height > 0 and comp_h >= max(int(median_height * 1.8), 96):
            crop_height = min(comp_h, max(int(median_height * 1.5), int(comp_h * 0.26)))
            cropped_glyph = _normalize_amazon_barcode_digit_glyph(glyph_image[comp_h - crop_height :])
            if cropped_glyph is not None:
                glyph = cropped_glyph
        if glyph is None:
            return []
        ranked_digits.append(_rank_amazon_barcode_digits(glyph))
    return _beam_search_amazon_ean13_candidates_from_ranked_digits(ranked_digits)


def _append_unique_barcodes(result: list[str], barcodes: list[str], limit: int = 5):
    for barcode in barcodes:
        if barcode in result:
            continue
        result.append(barcode)
        if len(result) >= limit:
            break


def _extract_amazon_barcode_via_digit_ocr_candidates_from_label(label_gray: object) -> list[str]:
    import cv2
    import numpy as np

    label_array = np.asarray(label_gray)
    if label_array.ndim != 2 or label_array.size == 0:
        return []

    scale = max(4.0, min(10.0, 420.0 / max(label_array.shape[0], 1)))
    enlarged = cv2.resize(label_array, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    result: list[str] = []

    for band_ratio in (0.58, 0.60, 0.62, 0.64):
        digit_band = enlarged[int(enlarged.shape[0] * band_ratio) :]
        if digit_band.size == 0:
            continue
        _, binary = cv2.threshold(digit_band, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        binary[: max(1, int(binary.shape[0] * 0.15)), :] = 0

        for kernel_width in (3, 2, 1, 4):
            eroded = cv2.erode(binary, cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1)), iterations=1)
            component_count, _, stats, _ = cv2.connectedComponentsWithStats(eroded, 8)
            components: list[tuple[int, int, int, int]] = []
            for index in range(1, component_count):
                comp_x, comp_y, comp_w, comp_h, comp_area = stats[index]
                if comp_area < max(80, int(eroded.shape[0] * eroded.shape[1] * 0.002)):
                    continue
                if comp_w < max(8, int(eroded.shape[1] * 0.02)) or comp_h < max(18, int(eroded.shape[0] * 0.22)):
                    continue
                if comp_y <= int(eroded.shape[0] * 0.35):
                    continue
                components.append((comp_x, comp_y, comp_w, comp_h))
            components.sort()
            if len(components) != 13:
                continue
            _append_unique_barcodes(result, _collect_amazon_barcode_ocr_candidates_from_components(eroded, components))
            if len(result) >= 5:
                return result

    _, full_binary = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    for kernel_width in (3, 2, 1, 4):
        eroded = cv2.erode(full_binary, cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1)), iterations=1)
        component_count, _, stats, _ = cv2.connectedComponentsWithStats(eroded, 8)
        components: list[tuple[int, int, int, int]] = []
        for index in range(1, component_count):
            comp_x, comp_y, comp_w, comp_h, comp_area = stats[index]
            if comp_area < max(80, int(eroded.shape[0] * eroded.shape[1] * 0.0012)):
                continue
            if comp_w < max(8, int(eroded.shape[1] * 0.012)) or comp_h < max(18, int(eroded.shape[0] * 0.08)):
                continue
            if comp_y + comp_h < int(eroded.shape[0] * 0.8):
                continue
            components.append((comp_x, comp_y, comp_w, comp_h))

        components.sort()
        if len(components) < 13:
            continue

        candidate_groups: list[list[tuple[int, int, int, int]]] = []
        seen_groups: set[tuple[tuple[int, int, int, int], ...]] = set()

        bottom_components = sorted(components, key=lambda item: (item[1] + item[3], -item[3], -item[2]), reverse=True)[
            :13
        ]
        if len(bottom_components) == 13:
            bottom_group = sorted(bottom_components)
            group_key = tuple(bottom_group)
            if group_key not in seen_groups:
                seen_groups.add(group_key)
                candidate_groups.append(bottom_group)

        max_start = max(len(components) - 13, 0)
        for start_index in range(max_start + 1):
            subset = components[start_index : start_index + 13]
            if len(subset) != 13:
                continue
            group_key = tuple(subset)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            candidate_groups.append(subset)

        for subset in candidate_groups:
            _append_unique_barcodes(result, _collect_amazon_barcode_ocr_candidates_from_components(eroded, subset))
            if len(result) >= 5:
                return result

    return result


def _extract_amazon_barcode_via_digit_ocr_from_label(label_gray: object) -> str:
    candidates = _extract_amazon_barcode_via_digit_ocr_candidates_from_label(label_gray)
    return candidates[0] if candidates else ""


def _try_extract_amazon_barcode_via_digit_ocr(image_array: object, detected_points: object) -> str:
    import numpy as np

    image = np.asarray(image_array)
    if image.size == 0:
        return ""

    if image.ndim == 2:
        gray_image = image
    elif image.ndim == 3 and image.shape[2] == 1:
        gray_image = image[:, :, 0]
    elif image.ndim == 3:
        import cv2

        gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        return ""

    points_array = np.asarray(detected_points, dtype=np.float32)
    if points_array.ndim == 2 and points_array.shape == (4, 2):
        point_groups = [points_array]
    elif points_array.ndim == 3 and points_array.shape[1:] == (4, 2):
        point_groups = list(points_array)
    else:
        return ""

    for each_points in point_groups:
        if (label_roi := _extract_amazon_barcode_label_roi(gray_image, each_points)) is None:
            continue
        if barcode := _extract_amazon_barcode_via_digit_ocr_from_label(label_roi):
            return barcode

    return ""


def _try_extract_amazon_barcode_candidates_via_digit_ocr(image_array: object, detected_points: object) -> list[str]:
    import numpy as np

    image = np.asarray(image_array)
    if image.size == 0:
        return []

    if image.ndim == 2:
        gray_image = image
    elif image.ndim == 3 and image.shape[2] == 1:
        gray_image = image[:, :, 0]
    elif image.ndim == 3:
        import cv2

        gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        return []

    points_array = np.asarray(detected_points, dtype=np.float32)
    if points_array.ndim == 2 and points_array.shape == (4, 2):
        point_groups = [points_array]
    elif points_array.ndim == 3 and points_array.shape[1:] == (4, 2):
        point_groups = list(points_array)
    else:
        return []

    result: list[str] = []
    for each_points in point_groups:
        if (label_roi := _extract_amazon_barcode_label_roi(gray_image, each_points)) is None:
            continue
        _append_unique_barcodes(result, _extract_amazon_barcode_via_digit_ocr_candidates_from_label(label_roi))
        if len(result) >= 5:
            break

    return result


def _get_amazon_barcode_detector_skip_reason() -> str:
    try:
        import cv2
        import numpy  # noqa: F401
    except Exception as exc:
        return f"当前环境缺少扫码依赖 opencv-contrib-python-headless ({exc.__class__.__name__}: {exc})"

    if not hasattr(cv2, "barcode_BarcodeDetector"):
        return "当前 OpenCV 不支持 barcode_BarcodeDetector"

    return ""


def _detect_amazon_barcode_candidates_from_image_bytes_with_reason(image_bytes: bytes) -> tuple[list[str], str]:
    if not image_bytes:
        return [], "图片内容为空"

    if skip_reason := _get_amazon_barcode_detector_skip_reason():
        return [], skip_reason

    import cv2
    import numpy as np

    try:
        img = Image.open(BytesIO(image_bytes))
        img.load()
    except Exception as exc:
        return [], f"图片解析失败 ({exc.__class__.__name__}: {exc})"

    crop_ratios = [
        (0.0, 0.0, 1.0, 1.0),
        (0.0, 0.76, 0.56, 1.0),
        (0.0, 0.80, 0.48, 1.0),
        (0.05, 0.78, 0.40, 0.98),
        (0.08, 0.82, 0.36, 0.98),
    ]
    detector = cv2.barcode_BarcodeDetector()
    ocr_fallback_attempted = False
    try:
        for left_ratio, top_ratio, right_ratio, bottom_ratio in crop_ratios:
            crop_box = (
                int(img.width * left_ratio),
                int(img.height * top_ratio),
                max(int(img.width * right_ratio), int(img.width * left_ratio) + 1),
                max(int(img.height * bottom_ratio), int(img.height * top_ratio) + 1),
            )
            crop = img.crop(crop_box).convert("RGB")
            for scale in (1, 2):
                processed = crop
                if scale > 1:
                    processed = crop.resize(
                        (max(crop.width * scale, 1), max(crop.height * scale, 1)),
                        resample=Image.Resampling.LANCZOS,
                    )
                try:
                    image_array = cv2.cvtColor(np.array(processed), cv2.COLOR_RGB2BGR)
                    retval, decoded_info, decoded_type, detected_points = detector.detectAndDecodeWithType(image_array)
                except Exception:
                    continue
                if not retval:
                    detected_points = None
                    try:
                        detected, fallback_points = detector.detect(image_array)
                    except Exception:
                        detected = False
                        fallback_points = None
                    if detected:
                        detected_points = fallback_points
                else:
                    for info, code_type in zip(decoded_info, decoded_type, strict=False):
                        if str(code_type).upper() != "EAN_13":
                            continue
                        if barcode := _normalize_amazon_barcode(info):
                            return [barcode], "direct"
                if detected_points is None:
                    continue
                ocr_fallback_attempted = True
                if barcodes := _try_extract_amazon_barcode_candidates_via_digit_ocr(image_array, detected_points):
                    return barcodes, "ocr_digits"
    finally:
        img.close()

    if ocr_fallback_attempted:
        return [], "条码已定位，但条码下数字 OCR 未识别到有效 EAN/JAN"
    return [], "未识别到 EAN/JAN 条码"


def _detect_amazon_barcode_from_image_bytes_with_reason(image_bytes: bytes) -> tuple[str, str]:
    barcodes, reason = _detect_amazon_barcode_candidates_from_image_bytes_with_reason(image_bytes)
    return (barcodes[0] if barcodes else ""), reason


def _detect_amazon_barcode_from_image_bytes(image_bytes: bytes) -> str:
    barcode, _ = _detect_amazon_barcode_from_image_bytes_with_reason(image_bytes)
    return barcode


async def try_get_amazon_barcodes_from_covers(result: CrawlersResult) -> list[str]:
    cover_candidates: list[tuple[str, str]] = []
    seen_cover_keys: set[str] = set()
    primary_cover = (result.thumb_from, result.thumb)
    for source, cover in [primary_cover, *result.thumb_list]:
        cover = str(cover or "").strip()
        if not cover:
            continue
        cover_key = cover.lower()
        if cover_key in seen_cover_keys:
            continue
        seen_cover_keys.add(cover_key)
        cover_candidates.append((str(source or "").strip() or "unknown", cover))

    if not cover_candidates:
        LogBuffer.log().write("\n 🟡 Amazon条码快路径：没有可扫描的封面来源")
        return []

    cover_candidates = cover_candidates[:3]
    LogBuffer.log().write(f"\n 🔎 Amazon条码快路径：开始扫描封面条码，共 {len(cover_candidates)} 张候选封面")

    if skip_reason := await to_thread(_get_amazon_barcode_detector_skip_reason):
        LogBuffer.log().write(f"\n 🟡 Amazon条码快路径跳过：{skip_reason}")
        return []

    for index, (source, cover) in enumerate(cover_candidates, start=1):
        LogBuffer.log().write(f"\n 🔎 Amazon条码识别：扫描封面[{index}/{len(cover_candidates)}] ({source}) {cover}")
        content: bytes | None = None
        error = ""
        if re.match(r"^https?://", cover, flags=re.I):
            content, error = await manager.computed.async_client.get_content(cover)
        else:
            cover_path = Path(cover)
            if cover_path.is_file():
                try:
                    content = await to_thread(cover_path.read_bytes)
                except Exception as exc:
                    error = str(exc)
        if not content:
            if error:
                LogBuffer.log().write(f"\n 🟡 Amazon条码识别：读取封面失败 ({source}) {error}")
            continue
        barcodes, detect_reason = await to_thread(
            _detect_amazon_barcode_candidates_from_image_bytes_with_reason, content
        )
        if barcodes:
            primary_barcode = barcodes[0]
            if detect_reason == "ocr_digits":
                LogBuffer.log().write(
                    f"\n 🔢 Amazon条码识别：OCR回退命中 EAN/JAN {primary_barcode} ({source}) 候选{len(barcodes)}个"
                )
            else:
                LogBuffer.log().write(f"\n 🔢 Amazon条码识别：命中 EAN/JAN {primary_barcode} ({source})")
            return barcodes
        LogBuffer.log().write(f"\n 🟡 Amazon条码识别：未识别到条码 ({source}) {detect_reason}")

    LogBuffer.log().write("\n 🟡 Amazon条码快路径：封面未识别到可用 EAN/JAN，回退标题搜索")
    return []


async def try_get_amazon_barcode_from_covers(result: CrawlersResult) -> str:
    barcodes = await try_get_amazon_barcodes_from_covers(result)
    return barcodes[0] if barcodes else ""


async def get_big_pic_by_amazon(
    result: CrawlersResult,
    originaltitle_amazon: str,
    actor_amazon: list[str],
    series: str = "",
    originaltitle_amazon_raw: str = "",
    series_raw: str = "",
) -> str:
    if not originaltitle_amazon and not originaltitle_amazon_raw:
        return ""
    hd_pic_url = ""
    invalid_actor_names = {
        manager.config.actor_no_name.strip(),
        "未知演员",
        "未知演員",
        "女优不明",
        "女優不明",
        "人物不明",
        "素人",
        "素人(多人)",
        "素人（多人）",
        "素人妻",
        "素人娘",
        "素人(援交)",
        "素人（援交）",
        "素人(偷窃)",
        "素人（偷窃）",
        "素人(患者)",
        "素人（患者）",
        "S级素人",
        "S級素人",
    }

    def is_valid_actor_name(actor_name: str) -> bool:
        actor_name = re.sub(r"\s+", " ", actor_name).strip()
        if not actor_name:
            return False
        return actor_name not in invalid_actor_names

    actor_groups: list[set[str]] = []
    actor_group_key_set: set[tuple[str, ...]] = set()
    actor_keyword_set: set[str] = set()
    actor_search_keywords: list[str] = []
    for actor in actor_amazon:
        if not actor:
            continue
        actor = re.sub(r"\s+", " ", actor).strip()
        if not is_valid_actor_name(actor):
            continue
        group: set[str] = set()
        alias_list = [alias.strip() for alias in re.findall(r"[^\(\)\（\）]+", actor) if alias.strip()]
        for each in alias_list + [actor]:
            each = re.sub(r"\s+", " ", each).strip()
            if not is_valid_actor_name(each):
                continue
            group.add(each)
            actor_keyword_set.add(each)
            if each not in actor_search_keywords:
                actor_search_keywords.append(each)
        if group:
            group_key = tuple(sorted(group))
            if group_key not in actor_group_key_set:
                actor_groups.append(group)
                actor_group_key_set.add(group_key)

    actor_keywords = list(actor_keyword_set)
    actor_keywords_sorted = sorted(actor_keywords, key=len, reverse=True)
    actor_groups_normalized = [{convert_half(alias).upper() for alias in group} for group in actor_groups]
    has_valid_actor = bool(actor_groups_normalized)
    expected_actor_count = len(actor_groups_normalized)
    if not has_valid_actor:
        LogBuffer.log().write("\n 🔎 Amazon搜索：未找到有效演员，切换为标题/番号模式")

    def build_number_regex(number_text: str) -> re.Pattern[str] | None:
        normalized_number = convert_half(number_text or "").upper().strip()
        if not normalized_number:
            return None
        token_list = re.findall(r"[A-Z0-9]+", normalized_number)
        if not token_list:
            return None
        pattern = r"(?<![A-Z0-9])" + r"[^A-Z0-9]*".join(re.escape(token) for token in token_list) + r"(?![A-Z0-9])"
        return re.compile(pattern, flags=re.IGNORECASE)

    number_regex = build_number_regex(result.number)

    def text_has_target_number(text: str) -> bool:
        if not number_regex or not text:
            return False
        return bool(number_regex.search(convert_half(text).upper()))

    def count_actor_group_matches(text: str) -> int:
        if not actor_groups_normalized or not text:
            return 0
        normalized_text = convert_half(re.sub(r"\s+", " ", text or "")).upper()
        return sum(1 for group in actor_groups_normalized if any(alias in normalized_text for alias in group))

    def strip_trailing_media_noise(base_title: str) -> str:
        title = re.sub(r"\s+", " ", base_title).strip()
        if not title:
            return ""
        trim_chars = " 　-—｜|/／・,，、：:()（）[]【】"
        trailing_media_noise = re.compile(
            r"(?:[\s　\-\—\｜\|/／・,，、：:\(\)（）\[\]［］]+)?"
            r"(?:dod|dvd|blu[- ]?ray|software\s+download|ブルーレイ(?:ディスク)?|ソフトウェアダウンロード)"
            r"(?:[\s　\-\—\｜\|/／・,，、：:\(\)（）\[\]［］]+)?$",
            flags=re.I,
        )
        while True:
            updated, count = trailing_media_noise.subn("", title)
            if count == 0:
                break
            updated = updated.strip(trim_chars)
            if not updated or updated == title:
                break
            title = updated
        return title

    def strip_actor_suffix(base_title: str) -> str:
        title = base_title.strip()
        if not title or not actor_keywords_sorted:
            return title
        trim_chars = " 　-—｜|/／・,，、：:()（）[]【】"
        while True:
            changed = False
            for actor in actor_keywords_sorted:
                escaped_actor = re.escape(actor)
                for pattern in (
                    rf"(?:\s|　)+{escaped_actor}$",
                    rf"(?:-|—|｜|/|／|・|,|，|、|：|:)\s*{escaped_actor}$",
                    rf"{escaped_actor}$",
                ):
                    new_title, count = re.subn(pattern, "", title)
                    if count == 0:
                        continue
                    new_title = new_title.strip(trim_chars)
                    if new_title and new_title != title:
                        title = new_title
                        changed = True
                        break
                if changed:
                    break
            if not changed:
                break
        return title

    def normalize_amazon_search_title(base_title: str) -> tuple[str, bool]:
        normalized = re.sub(r"【.*?】", "", base_title or "")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return "", False
        cleaned = strip_trailing_media_noise(normalized)
        cleaned = strip_actor_suffix(cleaned)
        cleaned = strip_trailing_media_noise(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned, cleaned != normalized

    originaltitle_amazon, originaltitle_amazon_simplified = normalize_amazon_search_title(originaltitle_amazon)
    originaltitle_amazon_raw, originaltitle_amazon_raw_simplified = normalize_amazon_search_title(
        originaltitle_amazon_raw
    )
    series = strip_trailing_media_noise(re.sub(r"【.*?】", "", series).strip())
    series_raw = strip_trailing_media_noise(re.sub(r"【.*?】", "", series_raw).strip())
    if originaltitle_amazon_simplified or originaltitle_amazon_raw_simplified:
        LogBuffer.log().write("\n 🔎 Amazon清洗关键词: 已移除标题尾部的演员/媒介噪音")
    search_queue: list[tuple[str, str, bool]] = []
    search_keyword_set: set[str] = set()
    split_keyword_added = False
    actor_fragment_added = False

    def append_search_keyword(keyword: str, *, fallback_series: str = "", is_initial_query: bool = False):
        keyword = re.sub(r"\s+", " ", keyword).strip()
        if keyword and keyword not in search_keyword_set:
            search_queue.append((keyword, fallback_series, is_initial_query))
            search_keyword_set.add(keyword)

    def append_title_search_variants(
        keyword: str,
        *,
        fallback_series: str = "",
        is_initial_query: bool = False,
        prefer_plain_first: bool = False,
    ):
        keyword = re.sub(r"\s+", " ", keyword).strip()
        if not keyword:
            return
        if result.number and not text_has_target_number(keyword):
            numbered_keyword = f"{keyword} {result.number}"
            if prefer_plain_first:
                append_search_keyword(keyword, fallback_series=fallback_series, is_initial_query=is_initial_query)
                append_search_keyword(
                    numbered_keyword, fallback_series=fallback_series, is_initial_query=is_initial_query
                )
                return
            append_search_keyword(numbered_keyword, fallback_series=fallback_series, is_initial_query=is_initial_query)
        append_search_keyword(keyword, fallback_series=fallback_series, is_initial_query=is_initial_query)

    append_title_search_variants(
        originaltitle_amazon,
        fallback_series=series,
        is_initial_query=True,
        prefer_plain_first=originaltitle_amazon_simplified,
    )
    append_title_search_variants(
        originaltitle_amazon_raw,
        fallback_series=series_raw,
        is_initial_query=True,
        prefer_plain_first=originaltitle_amazon_raw_simplified,
    )

    def append_split_keyword(base_title: str):
        for each_name in base_title.split(" "):
            if each_name not in search_keyword_set and (
                len(each_name) > 8
                or (not each_name.encode("utf-8").isalnum() and len(each_name) > 4)
                and each_name not in actor_keywords
            ):
                append_search_keyword(each_name)

    def append_split_keyword_from_replaced_title():
        nonlocal split_keyword_added
        if split_keyword_added:
            return
        split_keyword_added = True
        append_split_keyword(originaltitle_amazon_raw)

    def append_actor_fragment_keywords_from_titles():
        nonlocal actor_fragment_added
        if actor_fragment_added or not actor_keywords_sorted:
            return
        actor_fragment_added = True
        trim_chars = " 　-—｜|/／・,，、：:()（）[]【】"
        for base_title in [originaltitle_amazon_raw, originaltitle_amazon]:
            normalized_base_title = re.sub(r"\s+", " ", base_title).strip()
            if not normalized_base_title:
                continue
            for actor in actor_keywords_sorted:
                index = normalized_base_title.find(actor)
                if index <= 0:
                    continue
                fragment = normalized_base_title[index:].strip(trim_chars)
                if fragment and fragment != normalized_base_title:
                    append_title_search_variants(fragment)

    def append_series_fallback_keywords(base_title: str, fallback_series: str):
        if not fallback_series:
            return
        append_search_keyword(fallback_series)
        if fallback_series in base_title:
            stripped_title = re.sub(re.escape(fallback_series), " ", base_title, count=1)
            append_title_search_variants(stripped_title)

    no_result_tips = (
        "キーワードが正しく入力されていても一致する商品がない場合は、別の言葉をお試しください。",
        "検索に一致する商品はありませんでした。",
        "No results for",
        "did not match any products",
        "没有找到与",
        "沒有找到與",
        "找不到與",
        "未找到与",
        "您的搜索查询无结果。",
        "请尝试检查您的拼写或使用更多常规术语",
    )

    def is_no_result(html_content: str) -> bool:
        if not html_content:
            return True
        if any(each in html_content for each in no_result_tips):
            return True
        if "s-no-results" in html_content.lower():
            return True
        return False

    media_title_keywords = [
        "dod",
        "dvd",
        "blu-ray",
        "blu ray",
        "software download",
        "ブルーレイ",
        "ブルーレイディスク",
        "ソフトウェアダウンロード",
        "[dvd]",
        "[dod]",
        "[blu-ray]",
        "［dvd］",
        "［dod］",
        "［blu-ray］",
    ]
    metadata_source_fields: list[str] = []
    for raw_field, mapped_field in [
        (result.amazon_raw_director, result.director),
        (result.amazon_raw_studio, result.studio),
        (result.amazon_raw_publisher, result.publisher),
    ]:
        for each_field in [raw_field, mapped_field]:
            each_field = (each_field or "").strip()
            if each_field and each_field not in metadata_source_fields:
                metadata_source_fields.append(each_field)
    if any(
        [
            result.amazon_raw_director and result.amazon_raw_director != result.director,
            result.amazon_raw_studio and result.amazon_raw_studio != result.studio,
            result.amazon_raw_publisher and result.amazon_raw_publisher != result.publisher,
        ]
    ):
        LogBuffer.log().write("\n 🔎 Amazon清洗关键词: 已优先使用未映射字段")
    metadata_keywords: list[str] = []
    for field in metadata_source_fields:
        for each in re.split(r"[,，/／|｜]", field):
            each = each.strip()
            if each:
                metadata_keywords.append(each)
    suffix_cleanup_keywords = sorted(
        set(media_title_keywords + actor_keywords + metadata_keywords),
        key=len,
        reverse=True,
    )

    def clean_amazon_title_for_compare(title: str) -> str:
        cleaned = re.sub(r"【.*?】", " ", title)
        cleaned = re.sub(r"[［\[]\s*(?:dvd|blu[- ]?ray|software\s+download)\s*[］\]]", " ", cleaned, flags=re.I)
        trim_chars = " 　-—｜|/／・,，、：:()（）[]【】!?！？…."
        while True:
            changed = False
            for keyword in suffix_cleanup_keywords:
                escaped_keyword = re.escape(keyword)
                for pattern in (
                    rf"(?:\s|　)+{escaped_keyword}$",
                    rf"(?:-|—|｜|/|／|・|,|，|、|：|:)\s*{escaped_keyword}$",
                    rf"{escaped_keyword}$",
                ):
                    updated = re.sub(pattern, "", cleaned, flags=re.I).strip(trim_chars)
                    if updated and updated != cleaned:
                        cleaned = updated
                        changed = True
                        break
                if changed:
                    break
            if not changed:
                break
        return re.sub(r"\s+", " ", cleaned).strip(trim_chars)

    def normalize_title_for_compare(title: str) -> str:
        wildcard_placeholder = "\u2606"
        wildcard_token = "MDCXWILDCARDTOKEN"
        title = re.sub(r"[●○◯〇◎◉◆◇■□△▲▽▼※＊*]", wildcard_token, title)
        normalized = convert_half(title).lower()
        if number_regex:
            normalized = number_regex.sub(" ", normalized.upper()).lower()
        normalized = re.sub(r"【.*?】", "", normalized)
        normalized = re.sub(r"[［\[]\s*(?:dvd|blu[- ]?ray|software\s+download)\s*[］\]]", "", normalized, flags=re.I)
        normalized = normalized.replace(wildcard_token.lower(), wildcard_placeholder)
        normalized = re.sub(r"[\s　\-\—\｜\|/／・,，、：:()（）\[\]【】!?！？…\.]", "", normalized)
        return normalized

    def calculate_title_confidence(expected_title: str, candidate_title: str) -> float:
        expected = normalize_title_for_compare(clean_amazon_title_for_compare(expected_title))
        candidate = normalize_title_for_compare(clean_amazon_title_for_compare(candidate_title))
        if not expected or not candidate:
            return 0.0
        if expected == candidate:
            return 1.0

        wildcard_placeholder = "\u2606"

        def _strip_wildcard(text: str) -> str:
            return text.replace(wildcard_placeholder, "")

        def _chars_match(ch_a: str, ch_b: str) -> bool:
            return ch_a == ch_b or ch_a == wildcard_placeholder or ch_b == wildcard_placeholder

        def _wildcard_contains(pattern_text: str, target_text: str) -> bool:
            if not pattern_text or not target_text or len(pattern_text) > len(target_text):
                return False
            window = len(pattern_text)
            max_start = len(target_text) - window
            for start in range(max_start + 1):
                if all(_chars_match(pattern_text[index], target_text[start + index]) for index in range(window)):
                    return True
            return False

        def _wildcard_full_match(text_a: str, text_b: str) -> bool:
            if len(text_a) != len(text_b):
                return False
            return all(_chars_match(ch_a, ch_b) for ch_a, ch_b in zip(text_a, text_b, strict=False))

        contain_ratio = 0.0
        expected_plain_len = max(len(_strip_wildcard(expected)), 1)
        candidate_plain_len = max(len(_strip_wildcard(candidate)), 1)
        if _wildcard_contains(expected, candidate):
            contain_ratio = max(
                contain_ratio,
                1.0 if expected_plain_len >= 12 else min(1.0, expected_plain_len / candidate_plain_len),
            )
        if _wildcard_contains(candidate, expected):
            contain_ratio = max(
                contain_ratio,
                1.0 if candidate_plain_len >= 12 else min(1.0, candidate_plain_len / expected_plain_len),
            )

        sequence_ratio = SequenceMatcher(None, expected, candidate).ratio()
        expected_no_wildcard = _strip_wildcard(expected)
        candidate_no_wildcard = _strip_wildcard(candidate)
        if expected_no_wildcard and candidate_no_wildcard:
            sequence_ratio = max(
                sequence_ratio, SequenceMatcher(None, expected_no_wildcard, candidate_no_wildcard).ratio()
            )

        def _bigrams(text: str) -> set[str]:
            if len(text) < 2:
                return {text}
            return {text[i : i + 2] for i in range(len(text) - 1)}

        bigrams_expected = _bigrams(expected_no_wildcard or expected)
        bigrams_candidate = _bigrams(candidate_no_wildcard or candidate)
        jaccard = (
            len(bigrams_expected & bigrams_candidate) / len(bigrams_expected | bigrams_candidate)
            if bigrams_expected and bigrams_candidate
            else 0.0
        )

        score = 0.6 * sequence_ratio + 0.25 * contain_ratio + 0.15 * jaccard
        if _wildcard_full_match(expected, candidate) or _wildcard_full_match(candidate, expected):
            score = max(score, 0.95)
        if contain_ratio >= 0.95 and min(len(expected), len(candidate)) >= 12:
            score = max(score, 0.92)
        return score

    expected_titles: list[str] = []
    expected_title_set: set[str] = set()
    for title_text, fallback_series in [(originaltitle_amazon_raw, series_raw), (originaltitle_amazon, series)]:
        title_text = re.sub(r"\s+", " ", title_text).strip()
        if title_text and title_text not in expected_title_set:
            expected_titles.append(title_text)
            expected_title_set.add(title_text)
        if fallback_series and fallback_series in title_text:
            stripped_title = re.sub(re.escape(fallback_series), " ", title_text, count=1)
            stripped_title = re.sub(r"\s+", " ", stripped_title).strip()
            if stripped_title and stripped_title not in expected_title_set:
                expected_titles.append(stripped_title)
                expected_title_set.add(stripped_title)

    def get_best_title_confidence(candidate_title: str, *extra_titles: str) -> float:
        title_candidates = [each for each in [*expected_titles, *extra_titles] if each]
        if not title_candidates or not candidate_title:
            return 0.0
        return max(calculate_title_confidence(each_title, candidate_title) for each_title in title_candidates)

    def get_media_priority(pic_ver: str) -> int:
        if not pic_ver:
            return 2
        version_text = pic_ver.strip().lower()
        if "dvd" in version_text:
            return 3
        if "software download" in version_text:
            return 2
        if any(each in version_text for each in ["blu-ray", "blu ray", "ブルーレイ", "ブルーレイディスク"]):
            return 1
        return 0

    def is_supported_pic_ver(pic_ver: str) -> bool:
        return get_media_priority(pic_ver) > 0 or not pic_ver

    async def search_amazon(title: str) -> tuple[bool, str]:
        url_search = (
            "https://www.amazon.co.jp/black-curtain/save-eligibility/black-curtain?returnUrl=/s?k="
            + urllib.parse.quote_plus(urllib.parse.quote_plus(title.replace("&", " ")))
            + "&ref=nb_sb_noss"
        )
        return await get_amazon_data(url_search)

    async def search_amazon_by_actor_fallback() -> str:
        if not actor_search_keywords:
            return ""
        confidence_threshold = 0.75
        best_rejected_candidate: tuple[float, str, str, str] | None = None
        fallback_candidates: list[tuple[tuple[int, float, int], str, str, str]] = []
        fallback_candidate_keys: set[tuple[str, str, str]] = set()

        def update_best_rejected(score: float, actor_name: str, pic_title: str, reason: str):
            nonlocal best_rejected_candidate
            if best_rejected_candidate is None or score > best_rejected_candidate[0]:
                best_rejected_candidate = (score, actor_name, pic_title, reason)

        LogBuffer.log().write("\n 🔎 Amazon兜底：开始按演员名搜索并匹配标题置信度")
        for actor_name in actor_search_keywords:
            success, html_search = await search_amazon(actor_name)
            if not success or not html_search or is_no_result(html_search):
                continue
            html = etree.fromstring(html_search, etree.HTMLParser())
            pic_card = html.xpath('//div[@data-component-type="s-search-result" and @data-asin]')
            for each in pic_card:
                pic_ver_list = each.xpath('.//a[contains(@class, "a-text-bold")]/text()')
                pic_title_list = each.xpath(".//h2//a//span/text() | .//h2//span/text()")
                pic_url_list = each.xpath('.//img[contains(@class, "s-image")]/@src')
                if not (pic_url_list and pic_title_list):
                    continue
                pic_ver = pic_ver_list[0] if pic_ver_list else ""
                pic_title = pic_title_list[0]
                pic_url = pic_url_list[0]
                if not is_supported_pic_ver(pic_ver):
                    update_best_rejected(0.0, actor_name, pic_title, f"媒介类型不支持({pic_ver})")
                    continue
                if ".jpg" not in pic_url:
                    update_best_rejected(0.0, actor_name, pic_title, "图片地址不是JPG")
                    continue
                cleaned_title = clean_amazon_title_for_compare(pic_title)
                confidence = get_best_title_confidence(cleaned_title)
                if confidence < confidence_threshold:
                    update_best_rejected(
                        confidence,
                        actor_name,
                        pic_title,
                        f"置信度不足({confidence:.2f} < {confidence_threshold:.2f})",
                    )
                    continue
                url = re.sub(r"\._[_]?AC_[^\.]+\.", ".", pic_url)
                candidate_key = (url, actor_name, pic_title)
                if candidate_key in fallback_candidate_keys:
                    continue
                fallback_candidate_keys.add(candidate_key)
                fallback_candidates.append(
                    (
                        (1 if text_has_target_number(pic_title) else 0, confidence, get_media_priority(pic_ver)),
                        url,
                        pic_title,
                        actor_name,
                    )
                )

        if not fallback_candidates:
            if best_rejected_candidate:
                score, rejected_actor, rejected_title, rejected_reason = best_rejected_candidate
                LogBuffer.log().write(
                    f"\n 🟡 Amazon兜底未命中：最高候选分({score:.2f}) 演员({rejected_actor}) "
                    f"原因({rejected_reason}) 标题({rejected_title})"
                )
            else:
                LogBuffer.log().write("\n 🟡 Amazon兜底未命中：演员搜索无可评估候选结果")
            return ""

        fallback_candidates = sorted(fallback_candidates, key=lambda item: item[0], reverse=True)
        best_fallback_match: tuple[tuple[int, float, int], str, str, str, int] | None = None
        for current_match, matched_url, matched_title, matched_actor in fallback_candidates:
            width, _ = await get_imgsize(matched_url)
            width = width or 0
            if best_fallback_match is None:
                best_fallback_match = (current_match, matched_url, matched_title, matched_actor, width)
            if is_hd_candidate_width(width):
                number_match, confidence, _ = current_match
                LogBuffer.log().write(
                    f"\n 🟢 Amazon兜底命中：演员({matched_actor}) 置信度({confidence:.2f}) "
                    f"番号命中({bool(number_match)}) 标题({matched_title})"
                )
                return matched_url

        if best_fallback_match is None:
            return ""
        (number_match, confidence, _), matched_url, matched_title, matched_actor, _ = best_fallback_match
        LogBuffer.log().write(
            f"\n 🟢 Amazon兜底命中：演员({matched_actor}) 置信度({confidence:.2f}) 番号命中({bool(number_match)})"
            f" 标题({matched_title})"
        )
        result.poster = matched_url
        result.poster_from = "Amazon"
        return ""

    def normalize_detail_url(detail_url: str) -> str:
        if not detail_url:
            return ""
        absolute_url = urllib.parse.urljoin("https://www.amazon.co.jp", detail_url)
        decoded_url = urllib.parse.unquote_plus(absolute_url)
        if matched := re.search(r"/dp/([^/?&#]+)", decoded_url):
            return f"https://www.amazon.co.jp/dp/{matched.group(1)}"
        return ""

    def build_candidate_key(detail_url: str, pic_url: str) -> str:
        normalized_detail_url = normalize_detail_url(detail_url)
        if normalized_detail_url:
            return normalized_detail_url
        return re.sub(r"\._[_]?AC_[^\.]+\.", ".", pic_url)

    def create_candidate(
        *,
        url: str,
        detail_url: str,
        pic_title: str,
        pic_ver: str,
        media_priority: int,
        title_confidence: float,
        quick_actor_matches: int,
        quick_number_match: bool,
        target_barcode: str = "",
        barcode_search_rank: int = 0,
    ) -> dict[str, object]:
        return {
            "url": url,
            "detail_url": detail_url,
            "pic_title": pic_title,
            "pic_ver": pic_ver,
            "media_priority": media_priority,
            "title_confidence": title_confidence,
            "quick_actor_matches": quick_actor_matches,
            "detail_actor_matches": 0,
            "quick_number_match": quick_number_match,
            "detail_number_match": False,
            "detail_actor_count": 0,
            "detail_checked": False,
            "detail_barcode_match": False,
            "detail_barcodes": (),
            "target_barcode": target_barcode,
            "barcode_search_rank": barcode_search_rank,
            "width": 0,
        }

    async def enrich_candidate(candidate: dict[str, object]):
        if candidate["detail_checked"] or not candidate["detail_url"]:
            candidate["detail_checked"] = True
            return
        success, html_detail = await get_amazon_data(str(candidate["detail_url"]))
        candidate["detail_checked"] = True
        if not success or not html_detail:
            return
        html = etree.fromstring(html_detail, etree.HTMLParser())
        detail_actor_names: list[str] = []
        for each_xpath in [
            '//span[contains(@class, "author")]/a/text()',
            '//div[@id="bylineInfo_feature_div"]//a/text()',
            '//div[@id="bylineInfo"]//a/text()',
        ]:
            detail_actor_names.extend(text.strip() for text in html.xpath(each_xpath) if text and text.strip())
        detail_actor_names = list(dict.fromkeys(detail_actor_names))
        detail_texts: list[str] = []
        for each_xpath in [
            '//span[@id="productTitle"]/text()',
            '//ul[@class="a-unordered-list a-vertical a-spacing-mini"]//text()',
            '//div[@id="detailBulletsWrapper_feature_div"]//text()',
            '//div[@id="detailBullets_feature_div"]//text()',
            '//table[@id="productDetails_detailBullets_sections1"]//text()',
            '//div[@id="prodDetails"]//text()',
            '//div[@id="productOverview_feature_div"]//text()',
            '//div[@id="productDescription"]//text()',
        ]:
            detail_texts.extend(text.strip() for text in html.xpath(each_xpath) if text and text.strip())
        detail_title = next((text for text in detail_texts if text), "")
        if detail_title:
            candidate["title_confidence"] = max(
                float(candidate["title_confidence"]),
                get_best_title_confidence(detail_title),
            )
        detail_blob = " ".join(detail_actor_names + detail_texts)
        detail_barcodes = tuple(sorted(_extract_labeled_amazon_barcodes(detail_blob)))
        candidate["detail_actor_count"] = len(detail_actor_names)
        candidate["detail_actor_matches"] = max(
            int(candidate["detail_actor_matches"]),
            int(candidate["quick_actor_matches"]),
            count_actor_group_matches(detail_blob),
        )
        candidate["detail_number_match"] = text_has_target_number(detail_blob)
        candidate["detail_barcodes"] = detail_barcodes
        target_barcode = _normalize_amazon_barcode(str(candidate.get("target_barcode", "")))
        candidate["detail_barcode_match"] = bool(target_barcode and target_barcode in detail_barcodes)

    def candidate_actor_match_count(candidate: dict[str, object]) -> int:
        return max(int(candidate["quick_actor_matches"]), int(candidate["detail_actor_matches"]))

    def candidate_number_match(candidate: dict[str, object]) -> bool:
        return bool(candidate["quick_number_match"] or candidate["detail_number_match"])

    required_actor_match_count = (
        min(expected_actor_count, max(2, (expected_actor_count + 1) // 2)) if has_valid_actor else 0
    )

    def candidate_has_detail_evidence(candidate: dict[str, object]) -> bool:
        return bool(candidate["detail_url"]) and bool(candidate["detail_checked"])

    def candidate_correctness_key(candidate: dict[str, object]) -> tuple[int, int, int, int, int, int, int, int]:
        title_confidence = float(candidate["title_confidence"])
        actor_match_count = candidate_actor_match_count(candidate)
        detail_actor_matches = int(candidate["detail_actor_matches"])
        detail_actor_count = int(candidate["detail_actor_count"])
        detail_verified = candidate_has_detail_evidence(candidate)
        detail_barcode_match = bool(candidate.get("detail_barcode_match"))
        detail_number_match = bool(candidate["detail_number_match"])
        number_match = candidate_number_match(candidate)

        if has_valid_actor:
            verified_actor_match = detail_verified and detail_actor_matches >= required_actor_match_count
            quick_actor_match = actor_match_count >= required_actor_match_count
            verified_single_actor_match = (
                detail_verified and expected_actor_count == 1 and detail_actor_matches >= 1 and detail_actor_count <= 1
            )
        else:
            verified_actor_match = False
            quick_actor_match = False
            verified_single_actor_match = False

        return (
            1 if detail_barcode_match else 0,
            1 if detail_number_match else 0,
            1 if verified_single_actor_match else 0,
            1 if verified_actor_match else 0,
            1 if detail_verified else 0,
            1 if number_match else 0,
            1 if quick_actor_match else 0,
            1 if title_confidence >= 0.93 else 0,
        )

    def candidate_score(candidate: dict[str, object]) -> float:
        title_confidence = float(candidate["title_confidence"])
        actor_match_count = candidate_actor_match_count(candidate)
        actor_ratio = actor_match_count / expected_actor_count if expected_actor_count else 0.0
        score = title_confidence * 100
        if bool(candidate.get("detail_barcode_match")):
            score += 220
        if candidate_number_match(candidate):
            score += 120
        if has_valid_actor:
            score += actor_ratio * 20
        if (
            expected_actor_count == 1
            and int(candidate["detail_actor_count"]) > 1
            and not candidate_number_match(candidate)
        ):
            score -= 12
        score += int(candidate["media_priority"]) * 2
        return score

    def is_candidate_acceptable(candidate: dict[str, object]) -> bool:
        if bool(candidate.get("detail_barcode_match")):
            return True
        title_confidence = float(candidate["title_confidence"])
        actor_match_count = candidate_actor_match_count(candidate)
        detail_actor_count = int(candidate["detail_actor_count"])
        number_match = candidate_number_match(candidate)
        if number_match:
            return title_confidence >= 0.55
        if has_valid_actor:
            if expected_actor_count == 1:
                if detail_actor_count > 1:
                    return title_confidence >= 0.92
                return (actor_match_count >= 1 and title_confidence >= 0.78) or title_confidence >= 0.93
            return title_confidence >= 0.76 and actor_match_count >= required_actor_match_count
        return title_confidence >= 0.88

    def candidate_sort_key(
        candidate: dict[str, object],
    ) -> tuple[int, int, int, int, int, int, int, int, float, int, int]:
        return (
            *candidate_correctness_key(candidate),
            candidate_score(candidate),
            int(candidate["media_priority"]),
            int(candidate["width"]),
        )

    def candidate_probe_order_key(
        candidate: dict[str, object],
    ) -> tuple[int, int, int, int, int, int, int, int, float, int]:
        return (
            *candidate_correctness_key(candidate),
            candidate_score(candidate),
            int(candidate["media_priority"]),
        )

    def is_hd_candidate_width(width: int) -> bool:
        return width >= 1770 or 1750 > width > 600 or not width

    def barcode_candidate_sort_key(
        candidate: dict[str, object],
    ) -> tuple[int, int, int, int, int, int, float, int, int]:
        return (
            1 if bool(candidate.get("detail_barcode_match")) else 0,
            int(candidate["media_priority"]),
            1 if candidate_number_match(candidate) else 0,
            candidate_actor_match_count(candidate),
            1 if candidate_has_detail_evidence(candidate) else 0,
            0 - int(candidate.get("barcode_search_rank", 0)),
            float(candidate["title_confidence"]),
            int(candidate["width"]),
            len(tuple(candidate.get("detail_barcodes", ()))),
        )

    async def try_get_big_pic_by_amazon_via_barcode() -> str:
        barcodes = (await try_get_amazon_barcodes_from_covers(result))[:3]
        if not barcodes:
            LogBuffer.log().write("\n 🟡 Amazon条码快路径跳过：未获取到条码，回退标题搜索")
            return ""

        async def try_get_big_pic_by_amazon_via_single_barcode(
            barcode: str, barcode_index: int, total_barcodes: int
        ) -> str:
            LogBuffer.log().write(
                f"\n 🔎 Amazon条码快路径：开始搜索 EAN/JAN[{barcode_index}/{total_barcodes}] {barcode}"
            )
            success, html_search = await search_amazon(barcode)
            if not success or not html_search or is_no_result(html_search):
                LogBuffer.log().write(f"\n 🟡 Amazon条码快路径未命中：搜索无结果 {barcode}")
                return ""

            total_result_count = _get_amazon_total_result_count(html_search)
            html = etree.fromstring(html_search, etree.HTMLParser())
            pic_card = html.xpath('//div[@data-component-type="s-search-result" and @data-asin]')
            if not pic_card:
                LogBuffer.log().write(f"\n 🟡 Amazon条码快路径未命中：结果页无有效卡片 {barcode}")
                return ""
            result_count_desc = str(len(pic_card))
            if total_result_count is not None:
                result_count_desc += f"/{total_result_count}"
            LogBuffer.log().write(f"\n 🔎 Amazon条码快路径：条码搜索命中 {result_count_desc} 条候选")

            barcode_candidates: dict[str, dict[str, object]] = {}
            for search_rank, each in enumerate(pic_card[:8]):
                pic_ver_list = each.xpath('.//a[contains(@class, "a-text-bold")]/text()')
                pic_title_list = each.xpath(".//h2//a//span/text() | .//h2//span/text()")
                pic_url_list = each.xpath('.//img[contains(@class, "s-image")]/@src')
                detail_url_list = each.xpath('.//h2//a/@href | .//a[contains(@class, "s-no-outline")]/@href')
                if not (pic_url_list and pic_title_list and detail_url_list):
                    continue
                pic_ver = pic_ver_list[0] if pic_ver_list else ""
                pic_title = pic_title_list[0]
                pic_url = pic_url_list[0]
                detail_url = detail_url_list[0]
                if not (is_supported_pic_ver(pic_ver) and ".jpg" in pic_url):
                    continue
                title_confidence = get_best_title_confidence(pic_title)
                quick_number_match = text_has_target_number(pic_title)
                quick_actor_matches = count_actor_group_matches(pic_title)
                normalized_detail_url = normalize_detail_url(detail_url)
                url = re.sub(r"\._[_]?AC_[^\.]+\.", ".", pic_url)
                each_key = build_candidate_key(detail_url, url)
                media_priority = get_media_priority(pic_ver)
                candidate = barcode_candidates.get(each_key)
                if candidate is None:
                    barcode_candidates[each_key] = create_candidate(
                        url=url,
                        detail_url=normalized_detail_url,
                        pic_title=pic_title,
                        pic_ver=pic_ver,
                        media_priority=media_priority,
                        title_confidence=title_confidence,
                        quick_actor_matches=quick_actor_matches,
                        quick_number_match=quick_number_match,
                        target_barcode=barcode,
                        barcode_search_rank=search_rank,
                    )
                    continue
                if title_confidence > float(candidate["title_confidence"]) or (
                    title_confidence == float(candidate["title_confidence"])
                    and media_priority > int(candidate["media_priority"])
                ):
                    candidate["url"] = url
                    candidate["pic_title"] = pic_title
                    candidate["pic_ver"] = pic_ver
                    candidate["media_priority"] = media_priority
                if normalized_detail_url and (
                    not candidate["detail_url"]
                    or "/dp/" in normalized_detail_url
                    and "/dp/" not in str(candidate["detail_url"])
                ):
                    candidate["detail_url"] = normalized_detail_url
                candidate["title_confidence"] = max(float(candidate["title_confidence"]), title_confidence)
                candidate["quick_actor_matches"] = max(int(candidate["quick_actor_matches"]), quick_actor_matches)
                candidate["quick_number_match"] = bool(candidate["quick_number_match"] or quick_number_match)

            if not barcode_candidates:
                LogBuffer.log().write(f"\n 🟡 Amazon条码快路径未命中：结果页没有可评估候选 {barcode}")
                return ""

            probe_limit = 3 if total_result_count is not None and total_result_count <= 5 else 5
            LogBuffer.log().write(
                f"\n 🔎 Amazon条码快路径：开始详情页校验，候选 {len(barcode_candidates)} 条，探测前 {min(probe_limit, len(barcode_candidates))} 条"
            )
            probe_candidates = sorted(barcode_candidates.values(), key=barcode_candidate_sort_key, reverse=True)[
                : min(probe_limit, len(barcode_candidates))
            ]

            confirmed_candidates: list[dict[str, object]] = []
            accepted_candidates: list[dict[str, object]] = []
            for each_candidate in probe_candidates:
                await enrich_candidate(each_candidate)
                width, _ = await get_imgsize(str(each_candidate["url"]))
                each_candidate["width"] = width or 0
                if bool(each_candidate.get("detail_barcode_match")):
                    confirmed_candidates.append(each_candidate)
                    continue
                if (
                    total_result_count is not None
                    and total_result_count <= 5
                    and is_candidate_acceptable(each_candidate)
                ):
                    accepted_candidates.append(each_candidate)

            if confirmed_candidates:
                best_candidate = sorted(confirmed_candidates, key=barcode_candidate_sort_key, reverse=True)[0]
                if is_hd_candidate_width(int(best_candidate["width"])):
                    LogBuffer.log().write(
                        f"\n 🟢 Amazon条码快路径命中：EAN/JAN({barcode}) "
                        f"介质({best_candidate['pic_ver'] or 'unknown'}) 标题({best_candidate['pic_title']})"
                    )
                    return str(best_candidate["url"])
                result.poster = str(best_candidate["url"])
                result.poster_from = "Amazon"
                LogBuffer.log().write(
                    f"\n 🟡 Amazon条码快路径命中低清图：EAN/JAN({barcode}) "
                    f"介质({best_candidate['pic_ver'] or 'unknown'}) 标题({best_candidate['pic_title']})"
                )
                return ""

            if accepted_candidates:
                best_candidate = sorted(accepted_candidates, key=barcode_candidate_sort_key, reverse=True)[0]
                if is_hd_candidate_width(int(best_candidate["width"])):
                    LogBuffer.log().write(
                        f"\n 🟢 Amazon条码快路径弱确认命中：标题置信度({float(best_candidate['title_confidence']):.2f}) "
                        f"番号命中({candidate_number_match(best_candidate)}) "
                        f"介质({best_candidate['pic_ver'] or 'unknown'}) 标题({best_candidate['pic_title']})"
                    )
                    return str(best_candidate["url"])
                result.poster = str(best_candidate["url"])
                result.poster_from = "Amazon"
                LogBuffer.log().write(
                    f"\n 🟡 Amazon条码快路径弱确认低清图：标题置信度({float(best_candidate['title_confidence']):.2f}) "
                    f"番号命中({candidate_number_match(best_candidate)}) "
                    f"介质({best_candidate['pic_ver'] or 'unknown'}) 标题({best_candidate['pic_title']})"
                )
                return ""

            LogBuffer.log().write(f"\n 🟡 Amazon条码快路径未命中：候选详情页无条码确认 {barcode}")
            return ""

        for barcode_index, barcode in enumerate(barcodes, start=1):
            if hd_pic_url := await try_get_big_pic_by_amazon_via_single_barcode(barcode, barcode_index, len(barcodes)):
                return hd_pic_url
            if result.poster_from == "Amazon":
                return ""

        LogBuffer.log().write("\n 🟡 Amazon条码快路径未命中：所有条码候选均未通过校验，回退标题搜索")
        return ""

    hd_pic_url = await try_get_big_pic_by_amazon_via_barcode()
    if hd_pic_url or result.poster_from == "Amazon":
        return hd_pic_url

    candidate_pool: dict[str, dict[str, object]] = {}
    query_index = 0
    while query_index < len(search_queue):
        current_title, current_series, is_initial_query = search_queue[query_index]
        success, html_search = await search_amazon(current_title)

        if not success or (is_initial_query and is_no_result(html_search)):
            if is_initial_query:
                append_series_fallback_keywords(current_title, current_series)
                append_split_keyword_from_replaced_title()
                append_actor_fragment_keywords_from_titles()
            query_index += 1
            continue

        if result and html_search:
            html = etree.fromstring(html_search, etree.HTMLParser())
            query_has_signal = False
            pic_card = html.xpath('//div[@data-component-type="s-search-result" and @data-asin]')
            for each in pic_card:
                pic_ver_list = each.xpath('.//a[contains(@class, "a-text-bold")]/text()')
                pic_title_list = each.xpath(".//h2//a//span/text() | .//h2//span/text()")
                pic_url_list = each.xpath('.//img[contains(@class, "s-image")]/@src')
                detail_url_list = each.xpath('.//h2//a/@href | .//a[contains(@class, "s-no-outline")]/@href')
                if not (pic_url_list and pic_title_list and detail_url_list):
                    continue
                pic_ver = pic_ver_list[0] if pic_ver_list else ""
                pic_title = pic_title_list[0]
                pic_url = pic_url_list[0]
                detail_url = detail_url_list[0]
                if not (is_supported_pic_ver(pic_ver) and ".jpg" in pic_url):
                    continue
                title_confidence = get_best_title_confidence(pic_title, current_title)
                collect_threshold = 0.45 if text_has_target_number(current_title) else 0.58
                quick_number_match = text_has_target_number(pic_title)
                quick_actor_matches = count_actor_group_matches(pic_title)
                if title_confidence < collect_threshold and not quick_number_match:
                    continue
                if title_confidence >= 0.8 or quick_number_match:
                    query_has_signal = True
                url = re.sub(r"\._[_]?AC_[^\.]+\.", ".", pic_url)
                each_key = build_candidate_key(detail_url, url)
                normalized_detail_url = normalize_detail_url(detail_url)
                media_priority = get_media_priority(pic_ver)
                candidate = candidate_pool.get(each_key)
                if candidate is None:
                    candidate_pool[each_key] = create_candidate(
                        url=url,
                        detail_url=normalized_detail_url,
                        pic_title=pic_title,
                        pic_ver=pic_ver,
                        media_priority=media_priority,
                        title_confidence=title_confidence,
                        quick_actor_matches=quick_actor_matches,
                        quick_number_match=quick_number_match,
                    )
                else:
                    if title_confidence > float(candidate["title_confidence"]) or (
                        title_confidence == float(candidate["title_confidence"])
                        and media_priority > int(candidate["media_priority"])
                    ):
                        candidate["url"] = url
                        candidate["pic_title"] = pic_title
                        candidate["pic_ver"] = pic_ver
                        candidate["media_priority"] = media_priority
                    if normalized_detail_url and (
                        not candidate["detail_url"]
                        or "/dp/" in normalized_detail_url
                        and "/dp/" not in str(candidate["detail_url"])
                    ):
                        candidate["detail_url"] = normalized_detail_url
                    candidate["title_confidence"] = max(float(candidate["title_confidence"]), title_confidence)
                    candidate["quick_actor_matches"] = max(int(candidate["quick_actor_matches"]), quick_actor_matches)
                    candidate["quick_number_match"] = bool(candidate["quick_number_match"] or quick_number_match)

            if is_initial_query and not query_has_signal:
                append_series_fallback_keywords(current_title, current_series)
                append_split_keyword_from_replaced_title()
                append_actor_fragment_keywords_from_titles()

            if (
                "s-pagination-item s-pagination-next s-pagination-button s-pagination-separator" in html_search
                or len(pic_card) > 5
            ):
                amazon_orginaltitle_actor = result.amazon_orginaltitle_actor
                if has_valid_actor and amazon_orginaltitle_actor and amazon_orginaltitle_actor not in current_title:
                    append_search_keyword(f"{current_title} {amazon_orginaltitle_actor}")

        query_index += 1

    if candidate_pool:
        preliminary_candidates = sorted(candidate_pool.values(), key=candidate_sort_key, reverse=True)
        for each_candidate in preliminary_candidates[: min(6, len(preliminary_candidates))]:
            await enrich_candidate(each_candidate)
        accepted_candidates = [candidate for candidate in candidate_pool.values() if is_candidate_acceptable(candidate)]
        if accepted_candidates:
            probe_candidates = sorted(accepted_candidates, key=candidate_probe_order_key, reverse=True)[
                : min(6, len(accepted_candidates))
            ]
            best_fallback_candidate: dict[str, object] | None = None
            for each_candidate in probe_candidates:
                width, _ = await get_imgsize(str(each_candidate["url"]))
                each_candidate["width"] = width or 0
                if best_fallback_candidate is None:
                    best_fallback_candidate = each_candidate
                if is_hd_candidate_width(int(each_candidate["width"])):
                    LogBuffer.log().write(
                        f"\n 🟢 Amazon命中：标题置信度({float(each_candidate['title_confidence']):.2f}) "
                        f"番号命中({candidate_number_match(each_candidate)}) "
                        f"演员命中({candidate_actor_match_count(each_candidate)}/{expected_actor_count or 0}) "
                        f"介质({each_candidate['pic_ver'] or 'unknown'}) 标题({each_candidate['pic_title']})"
                    )
                    return str(each_candidate["url"])
            if best_fallback_candidate:
                result.poster = str(best_fallback_candidate["url"])
                result.poster_from = "Amazon"
                LogBuffer.log().write(
                    f"\n 🟡 Amazon命中低清图：标题置信度({float(best_fallback_candidate['title_confidence']):.2f}) "
                    f"番号命中({candidate_number_match(best_fallback_candidate)}) "
                    f"介质({best_fallback_candidate['pic_ver'] or 'unknown'}) 标题({best_fallback_candidate['pic_title']})"
                )
        else:
            best_rejected_candidate = sorted(candidate_pool.values(), key=candidate_sort_key, reverse=True)[0]
            LogBuffer.log().write(
                f"\n 🟡 Amazon搜索未命中：最高候选分({candidate_score(best_rejected_candidate):.2f}) "
                f"标题置信度({float(best_rejected_candidate['title_confidence']):.2f}) "
                f"番号命中({candidate_number_match(best_rejected_candidate)}) "
                f"演员命中({candidate_actor_match_count(best_rejected_candidate)}/{expected_actor_count or 0}) "
                f"标题({best_rejected_candidate['pic_title']})"
            )

    if not hd_pic_url and result.poster_from != "Amazon" and not candidate_pool:
        hd_pic_url = await search_amazon_by_actor_fallback()

    return hd_pic_url
