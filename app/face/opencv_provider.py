from __future__ import annotations

from pathlib import Path
from threading import Lock

import cv2
import numpy as np

from app.face.provider import (
    FaceEmbedding,
    MultipleFacesDetected,
    NoFaceDetected,
    PoorFaceQuality,
    ProviderUnavailable,
)


class OpenCVYuNetSFaceProvider:
    """CPU-capable YuNet detector + SFace embedding provider using OpenCV DNN."""

    provider_name = "opencv-yunet-sface"

    def __init__(self, detector_path: str, recognizer_path: str, model_name: str, model_version: str):
        detector = Path(detector_path)
        recognizer = Path(recognizer_path)
        if not detector.is_file() or not recognizer.is_file():
            raise ProviderUnavailable(
                "Face model files are missing. Download the model artifacts using the documented setup script."
            )
        try:
            self.detector = cv2.FaceDetectorYN_create(
                str(detector), "", (320, 320), 0.85, 0.3, 5000
            )
            self.recognizer = cv2.FaceRecognizerSF_create(str(recognizer), "")
        except cv2.error as exc:
            raise ProviderUnavailable("OpenCV could not load the configured face model files.") from exc
        self.model_name = model_name
        self.model_version = model_version
        # OpenCV's mutable DNN input size is shared by requests. Serialize access
        # to avoid detector/recognizer state races across concurrent class sessions.
        self._inference_lock = Lock()

    def create_embedding(self, image_bytes: bytes) -> FaceEmbedding:
        import io
        from PIL import Image

        try:
            with Image.open(io.BytesIO(image_bytes)) as im:
                rgb = np.asarray(im.convert("RGB"))
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            height, width = frame.shape[:2]
            with self._inference_lock:
                self.detector.setInputSize((width, height))
                _, faces = self.detector.detect(frame)
                if faces is None or len(faces) == 0:
                    raise NoFaceDetected("No face was detected. Retake the image or use manual attendance.")
                if len(faces) != 1:
                    raise MultipleFacesDetected("Capture one person at a time.")
                face = faces[0]
                face_confidence = float(face[-1])
                box_w, box_h = float(face[2]), float(face[3])
                if face_confidence < 0.85 or min(box_w, box_h) < 64:
                    raise PoorFaceQuality("The face is too small or unclear. Move closer and improve lighting.")
                aligned = self.recognizer.alignCrop(frame, face)
                feature = self.recognizer.feature(aligned).reshape(-1).astype(np.float32)
        except (NoFaceDetected, MultipleFacesDetected, PoorFaceQuality):
            raise
        except (cv2.error, ValueError, OSError) as exc:
            raise PoorFaceQuality("The image could not be evaluated. Capture a clear still image.") from exc
        norm = float(np.linalg.norm(feature))
        if norm <= 1e-12 or not np.isfinite(feature).all():
            raise PoorFaceQuality("The face template could not be generated reliably.")
        vector = (feature / norm).tolist()
        return FaceEmbedding(vector, self.provider_name, self.model_name, self.model_version)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    if a.shape != b.shape or a.ndim != 1:
        raise ValueError("Face embeddings have incompatible dimensions")
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-12:
        raise ValueError("Face embedding has zero magnitude")
    return float(np.dot(a, b) / denom)
