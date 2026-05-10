from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
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


def _cuda_enabled_count() -> int:
    cuda_module = getattr(cv2, "cuda", None)
    if cuda_module is None or not hasattr(cuda_module, "getCudaEnabledDeviceCount"):
        return 0
    try:
        return int(cuda_module.getCudaEnabledDeviceCount())
    except Exception:
        return 0


def _opencl_enabled() -> bool:
    ocl_module = getattr(cv2, "ocl", None)
    if ocl_module is None:
        return False
    checker = getattr(ocl_module, "haveOpenCL", None)
    if checker is None:
        return False
    try:
        return bool(checker())
    except Exception:
        return False


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


def _create_yunet_detector(model_path: Path, backend_id: int, target_id: int):
    creator = getattr(cv2, "FaceDetectorYN_create", None)
    if creator is None:
        face_detector = getattr(cv2, "FaceDetectorYN", None)
        creator = getattr(face_detector, "create", None) if face_detector is not None else None
    if creator is None:
        return None
    try:
        return creator(str(model_path), "", (320, 320), 0.9, 0.3, 5000, backend_id, target_id)
    except Exception:
        return None


def _build_yunet_backends() -> list[tuple[str, int, int]]:
    backends: list[tuple[str, int, int]] = []
    dnn = cv2.dnn
    if _cuda_enabled_count() > 0:
        backend_id = getattr(dnn, "DNN_BACKEND_CUDA", None)
        target_id = getattr(dnn, "DNN_TARGET_CUDA", None)
        if backend_id is not None and target_id is not None:
            backends.append(("CUDA", backend_id, target_id))
    if _opencl_enabled():
        backend_id = getattr(dnn, "DNN_BACKEND_OPENCV", None)
        target_id = getattr(dnn, "DNN_TARGET_OPENCL", None)
        if backend_id is not None and target_id is not None:
            backends.append(("OpenCL", backend_id, target_id))
    backends.append(("CPU", getattr(dnn, "DNN_BACKEND_OPENCV", 0), getattr(dnn, "DNN_TARGET_CPU", 0)))
    return backends


@lru_cache(maxsize=1)
def _get_haar_cascade() -> cv2.CascadeClassifier | None:
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not cascade_path.is_file():
        return None
    cascade = cv2.CascadeClassifier(cascade_path.as_posix())
    if cascade.empty():
        return None
    return cascade


def _detect_faces_by_haar(image_bgr: np.ndarray) -> list[FaceBox]:
    cascade = _get_haar_cascade()
    if cascade is None:
        return []
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(24, 24),
    )
    return [FaceBox(int(x), int(y), int(x + w), int(y + h)) for x, y, w, h in faces]


def _detect_faces_by_yunet(image_bgr: np.ndarray, log_fn=None) -> list[FaceBox]:
    model_path = _load_yunet_model()
    if model_path is None:
        _log_face("\n 🖼 人脸裁剪: YuNet 模型不可用，跳过 YuNet", log_fn)
        return []

    w, h = image_bgr.shape[1], image_bgr.shape[0]
    backends = _build_yunet_backends()
    _log_face(
        f"\n 🖼 人脸裁剪: YuNet 检测开始，候选后端={','.join(name for name, _, _ in backends)}，尺寸={w}x{h}",
        log_fn,
    )

    for backend_name, backend_id, target_id in backends:
        detector = _create_yunet_detector(model_path, backend_id, target_id)
        if detector is None:
            _log_face(f"\n 🖼 人脸裁剪: YuNet {backend_name} 后端初始化失败", log_fn)
            continue
        try:
            detector.setInputSize((w, h))
            _, faces = detector.detect(image_bgr)
        except Exception:
            _log_face(f"\n 🖼 人脸裁剪: YuNet {backend_name} 后端检测异常", log_fn)
            continue
        if faces is None or len(faces) == 0:
            _log_face(f"\n 🖼 人脸裁剪: YuNet {backend_name} 未检测到人脸", log_fn)
            return []
        face_boxes: list[FaceBox] = []
        for face in faces:
            x, y, face_w, face_h = (float(face[i]) for i in range(4))
            score = float(face[14]) if len(face) > 14 else 0.0
            face_boxes.append(
                FaceBox(
                    left=max(int(round(x)), 0),
                    top=max(int(round(y)), 0),
                    right=min(int(round(x + face_w)), w),
                    bottom=min(int(round(y + face_h)), h),
                    score=score,
                )
            )
        _log_face(f"\n 🖼 人脸裁剪: YuNet {backend_name} 检测到 {len(face_boxes)} 张脸", log_fn)
        return face_boxes
    return []


def _select_primary_face(faces: list[FaceBox]) -> FaceBox | None:
    if not faces:
        return None
    return max(faces, key=lambda face: (face.score, face.width * face.height))


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
    _log_face(
        f"\n 🖼 人脸裁剪: 开始识别，源图={image.width}x{image.height}，裁剪宽度={crop_width}",
        log_fn,
    )
    rgb_image = image.convert("RGB")
    try:
        image_bgr = cv2.cvtColor(np.asarray(rgb_image), cv2.COLOR_RGB2BGR)
    finally:
        rgb_image.close()
    faces = _detect_faces_by_yunet(image_bgr, log_fn=log_fn)
    if not faces:
        _log_face("\n 🖼 人脸裁剪: YuNet 无结果，回退 Haar", log_fn)
        faces = _detect_faces_by_haar(image_bgr)
        if faces:
            _log_face(f"\n 🖼 人脸裁剪: Haar 检测到 {len(faces)} 张脸", log_fn)
        else:
            _log_face("\n 🖼 人脸裁剪: Haar 也未检测到人脸", log_fn)
    primary_face = _select_primary_face(faces)
    if primary_face is None:
        return None
    _log_face(
        f"\n 🖼 人脸裁剪: 选中人脸 left={primary_face.left}, top={primary_face.top}, right={primary_face.right}, bottom={primary_face.bottom}, score={primary_face.score:.3f}",
        log_fn,
    )
    if crop_width >= image.width:
        return 0
    left = _build_face_focus_left(image.width, crop_width, primary_face)
    _log_face(f"\n 🖼 人脸裁剪: 计算裁剪起点 left={left}", log_fn)
    return left
