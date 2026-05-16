from pathlib import Path

import numpy as np
from PIL import Image

from mdcx.core import face_crop


class _FakeYuNetDetector:
    def __init__(self):
        self.detect_count = 0
        self.input_size = None

    def setInputSize(self, size):
        self.input_size = size

    def detect(self, image_bgr):
        self.detect_count += 1
        faces = np.array(
            [
                [80, 40, 90, 120, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.92],
                [500, 45, 80, 110, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.88],
            ],
            dtype=np.float32,
        )
        return 1, faces


class _FallbackYuNetDetector:
    def __init__(self, face_results):
        self.detect_count = 0
        self.input_sizes = []
        self._face_results = face_results

    def setInputSize(self, size):
        self.input_sizes.append(size)

    def detect(self, image_bgr):
        self.detect_count += 1
        faces = self._face_results[self.detect_count - 1]
        if faces is None:
            return 1, None
        return 1, np.array(faces, dtype=np.float32)


def test_face_crop_uses_single_cpu_yunet_detection_and_prefers_poster_subject(monkeypatch):
    detector = _FakeYuNetDetector()

    monkeypatch.setattr(face_crop, "_load_yunet_model", lambda: Path("yunet.onnx"))
    monkeypatch.setattr(face_crop, "_create_yunet_detector", lambda model_path: detector)

    image = Image.new("RGB", (800, 450), "white")
    logs: list[str] = []

    left = face_crop.get_face_crop_left(image, 300, log_fn=logs.append)

    assert detector.detect_count == 1
    assert detector.input_size == (800, 450)
    assert left == 390
    assert "".join(logs) == "\n 🖼 Poster裁剪: 人脸裁剪命中，使用 thumb face"


def test_face_crop_uses_rotated_fallback_and_maps_face_to_source(monkeypatch):
    detector = _FallbackYuNetDetector(
        [
            [],
            [[100, 200, 80, 100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.91]],
        ]
    )

    monkeypatch.setattr(face_crop, "_load_yunet_model", lambda: Path("yunet.onnx"))
    monkeypatch.setattr(face_crop, "_create_yunet_detector", lambda model_path: detector)

    image = Image.new("RGB", (800, 450), "white")
    logs: list[str] = []

    left = face_crop.get_face_crop_left(image, 300, log_fn=logs.append)

    assert detector.detect_count == 2
    assert detector.input_sizes == [(800, 450), (450, 800)]
    assert left == 100
    assert "".join(logs) == "\n 🖼 Poster裁剪: 旋转90度人脸裁剪命中，使用 thumb face"


def test_face_crop_falls_back_to_center_when_all_rotations_miss(monkeypatch):
    detector = _FallbackYuNetDetector([[], [], [], []])

    monkeypatch.setattr(face_crop, "_load_yunet_model", lambda: Path("yunet.onnx"))
    monkeypatch.setattr(face_crop, "_create_yunet_detector", lambda model_path: detector)

    image = Image.new("RGB", (800, 450), "white")
    logs: list[str] = []

    left = face_crop.get_face_crop_left(image, 300, log_fn=logs.append)

    assert detector.detect_count == 4
    assert detector.input_sizes == [(800, 450), (450, 800), (450, 800), (800, 450)]
    assert left is None
    assert "".join(logs) == "\n 🖼 Poster裁剪: 未检测到有效人脸，使用居中裁剪"
