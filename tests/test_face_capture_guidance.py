from __future__ import annotations

import io
from threading import Lock

import numpy as np
from PIL import Image

from app.face.mobilefacenet_provider import YuNetMobileFaceNetProvider


class EmptyDetector:
    def setInputSize(self, size):
        self.size = size

    def detect(self, frame):
        return 0, None


class MultipleFaceDetector(EmptyDetector):
    def detect(self, frame):
        faces = np.zeros((2, 15), dtype=np.float32)
        return 0, faces


def _jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (320, 240), color=(120, 120, 120)).save(output, format="JPEG")
    return output.getvalue()


def _provider(detector):
    provider = object.__new__(YuNetMobileFaceNetProvider)
    provider.detector = detector
    provider._inference_lock = Lock()
    return provider


def test_guidance_returns_retake_for_no_face_without_embedding():
    result = _provider(EmptyDetector()).analyze_capture_guidance(_jpeg())
    assert result["face_detected"] is False
    assert result["capture_ready"] is False
    assert result["pose_bucket"] == "pose_unknown"
    assert result["identity_evidence"] is not True


def test_guidance_rejects_multiple_visible_faces():
    result = _provider(MultipleFaceDetector()).analyze_capture_guidance(_jpeg())
    assert result["face_detected"] is False
    assert result["capture_ready"] is False
    assert result["face_count"] == 2
    assert "Only one person" in result["guidance"][0]
