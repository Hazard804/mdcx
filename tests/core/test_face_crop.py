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
