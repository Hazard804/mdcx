from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import cv2
import numpy as np
from PIL import Image

from ..config.manager import manager
from ..models.log_buffer import LogBuffer

YUNET_MODEL_URL = "https://huggingface.co/opencv/opencv_zoo/resolve/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YUNET_MODEL_NAME = "face_detection_yunet_2023mar.onnx"
YUNET_SCORE_THRESHOLD = 0.7
YUNET_NMS_THRESHOLD = 0.3
YUNET_TOP_K = 5000
YUNET_DETECT_MAX_SIDE = 800


@dataclass(frozen=True)
class FaceBox:
    left: int
    top: int
    right: int
    bottom: int
    score: float = 0.0

    @property
    def width(self) -> int:
        return max(self.right - self.left, 0)

    @property
    def height(self) -> int:
        return max(self.bottom - self.top, 0)


def _scale_face_box(face: FaceBox, scale: float, image_width: int, image_height: int) -> FaceBox:
    if scale == 1:
        return face
    return FaceBox(
        left=max(int(round(face.left / scale)), 0),
        top=max(int(round(face.top / scale)), 0),
        right=min(int(round(face.right / scale)), image_width),
        bottom=min(int(round(face.bottom / scale)), image_height),
        score=face.score,
    )


def _face_model_path() -> Path:
    model_path = manager.data_folder / "userdata" / "face_detector" / YUNET_MODEL_NAME
    model_path.parent.mkdir(parents=True, exist_ok=True)
    return model_path


def _download_face_model(model_path: Path) -> bool:
    tmp_path = model_path.with_suffix(".part")
    try:
        with urlopen(YUNET_MODEL_URL, timeout=30) as response:
            model_path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("wb") as fp:
                fp.write(response.read())
        tmp_path.replace(model_path)
        LogBuffer.log().write("\n 🖼 人脸识别模型已自动缓存")
        return True
    except (OSError, URLError, ValueError):
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return False


def _is_git_lfs_pointer(model_path: Path) -> bool:
    try:
        with model_path.open("rb") as fp:
            head = fp.read(256)
    except OSError:
        return False
    return head.startswith(b"version https://git-lfs.github.com/spec/v1")


def _log_face(message: str, log_fn=None) -> None:
    if log_fn is not None:
        log_fn(message)
    else:
        LogBuffer.log().write(message)


def _load_yunet_model() -> Path | None:
    model_path = _face_model_path()
    if model_path.is_file() and not _is_git_lfs_pointer(model_path):
        return model_path
    if model_path.is_file() and _is_git_lfs_pointer(model_path):
        try:
            model_path.unlink()
        except OSError:
            pass
        LogBuffer.log().write("\n 🖼 人脸裁剪: 检测到 LFS 占位模型，准备重新下载")
    if _download_face_model(model_path):
        return model_path
    return None


def _create_yunet_detector(model_path: Path):
    creator = getattr(cv2, "FaceDetectorYN_create", None)
    if creator is None:
        face_detector = getattr(cv2, "FaceDetectorYN", None)
        creator = getattr(face_detector, "create", None) if face_detector is not None else None
    if creator is None:
        return None
    try:
        return creator(
            str(model_path),
            "",
            (320, 320),
            YUNET_SCORE_THRESHOLD,
            YUNET_NMS_THRESHOLD,
            YUNET_TOP_K,
            getattr(cv2.dnn, "DNN_BACKEND_OPENCV", 0),
            getattr(cv2.dnn, "DNN_TARGET_CPU", 0),
        )
    except Exception:
        return None


def _resize_for_detection(image_bgr: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = image_bgr.shape[:2]
    max_side = max(w, h)
    if max_side <= YUNET_DETECT_MAX_SIDE:
        return image_bgr, 1
    scale = YUNET_DETECT_MAX_SIDE / max_side
    resized = cv2.resize(image_bgr, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)
    return resized, scale


def _detect_faces_by_yunet(image_bgr: np.ndarray) -> list[FaceBox]:
    model_path = _load_yunet_model()
    if model_path is None:
        return []

    source_h, source_w = image_bgr.shape[:2]
    detect_image, scale = _resize_for_detection(image_bgr)
    detect_h, detect_w = detect_image.shape[:2]
    detector = _create_yunet_detector(model_path)
    if detector is None:
        return []

    try:
        detector.setInputSize((detect_w, detect_h))
        _, faces = detector.detect(detect_image)
    except Exception:
        return []
    if faces is None or len(faces) == 0:
        return []

    face_boxes: list[FaceBox] = []
    for face in faces:
        x, y, face_w, face_h = (float(face[i]) for i in range(4))
        score = float(face[14]) if len(face) > 14 else 0.0
        face_box = FaceBox(
            left=max(int(round(x)), 0),
            top=max(int(round(y)), 0),
            right=min(int(round(x + face_w)), detect_w),
            bottom=min(int(round(y + face_h)), detect_h),
            score=score,
        )
        face_boxes.append(_scale_face_box(face_box, scale, source_w, source_h))
    return face_boxes


def _select_primary_face(faces: list[FaceBox], image_width: int) -> FaceBox | None:
    if not faces:
        return None

    def _score(face: FaceBox) -> tuple[float, int]:
        face_center_x = face.left + face.width / 2
        right_bias = face_center_x / image_width if image_width > 0 else 0
        normalized_score = max(face.score, 0)
        area = face.width * face.height
        # 封面人物通常在画面右侧；在检测分接近时，优先选择更适合 poster 裁剪的主体。
        poster_score = normalized_score * 100 + right_bias * 12 + min(area / 1000, 30)
        return poster_score, area

    return max(faces, key=_score)


def _build_face_focus_left(image_width: int, crop_width: int, face: FaceBox) -> int:
    desired_left = int(round(face.left + face.width / 2 - crop_width / 2))
    padding = max(int(round(max(face.width, face.height) * 0.35)), 8)
    min_left = max(0, face.right + padding - crop_width)
    max_left = min(image_width - crop_width, face.left - padding)
    if min_left <= max_left:
        return max(min(desired_left, max_left), min_left)
    return max(0, min(desired_left, max(image_width - crop_width, 0)))


def get_face_crop_left(image: Image.Image, crop_width: int, log_fn=None) -> int | None:
    if crop_width <= 0 or image.width <= 0 or image.height <= 0:
        return None
    rgb_image = image.convert("RGB")
    try:
        image_bgr = cv2.cvtColor(np.asarray(rgb_image), cv2.COLOR_RGB2BGR)
    finally:
        rgb_image.close()
    faces = _detect_faces_by_yunet(image_bgr)
    primary_face = _select_primary_face(faces, image.width)
    if primary_face is None:
        _log_face("\n 🖼 Poster裁剪: 未检测到有效人脸，使用居中裁剪", log_fn)
        return None
    if crop_width >= image.width:
        _log_face("\n 🖼 Poster裁剪: 人脸裁剪命中，使用 thumb face", log_fn)
        return 0
    left = _build_face_focus_left(image.width, crop_width, primary_face)
    _log_face("\n 🖼 Poster裁剪: 人脸裁剪命中，使用 thumb face", log_fn)
    return left
