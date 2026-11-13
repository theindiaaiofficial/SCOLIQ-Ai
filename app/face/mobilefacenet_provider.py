from __future__ import annotations

"""ONNX Runtime adapter for Qualcomm AI Hub MobileFaceNet float export.

This adapter targets the exact paired-input export described by the supplied
metadata.json: img1/img2 are float32 NCHW RGB images in [0, 1], and embeddings
has shape [2, 128]. The ONNX graph performs its own torchvision normalization
and flip augmentation. For this app's single-image enrollment/identify API, the
same aligned image is supplied to both inputs and the first embedding is used.
"""

import io
import json
import math
import time
from pathlib import Path
from threading import Lock
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.face.diagnostics import log_face_event

from app.face.provider import (
    FaceEmbedding,
    MultipleFacesDetected,
    NoFaceDetected,
    PoorFaceQuality,
    ProviderUnavailable,
)


class YuNetMobileFaceNetProvider:
    """CPU inference using YuNet detection/alignment + Qualcomm MobileFaceNet."""

    provider_name = "qualcomm-yunet-mobilefacenet"

    def __init__(
        self,
        detector_path: str,
        recognizer_path: str,
        model_name: str,
        model_version: str,
        *,
        metadata_path: str,
        external_data_path: str,
        input_size: int = 112,
        embedding_size: int = 128,
        input_name_1: str = "img1",
        input_name_2: str = "img2",
        output_name: str = "embeddings",
        score_threshold: float = 0.85,
        nms_threshold: float = 0.30,
        min_face_size: int = 64,
    ) -> None:
        detector_file = Path(detector_path)
        recognizer_file = Path(recognizer_path)
        metadata_file = Path(metadata_path)
        external_file = Path(external_data_path)
        for label, file_path in (
            ("YuNet detector", detector_file),
            ("MobileFaceNet ONNX", recognizer_file),
            ("MobileFaceNet metadata", metadata_file),
            ("MobileFaceNet external weights", external_file),
        ):
            if not file_path.is_file():
                raise ProviderUnavailable(f"{label} file is missing: {file_path}")

        if input_size != 112 or embedding_size != 128:
            raise ProviderUnavailable(
                "This Qualcomm MobileFaceNet export requires 112x112 inputs and 128-value embeddings."
            )
        if (
            input_name_1 == input_name_2
            or not input_name_1
            or not input_name_2
            or not output_name
        ):
            raise ProviderUnavailable(
                "MobileFaceNet input/output tensor names are invalid."
            )

        self.model_name = model_name
        self.model_version = model_version
        self.input_size = input_size
        self.embedding_size = embedding_size
        self.input_name_1 = input_name_1
        self.input_name_2 = input_name_2
        self.output_name = output_name
        self.min_face_size = min_face_size
        self.score_threshold = score_threshold
        self._inference_lock = Lock()

        self._validate_release_metadata(metadata_file)

        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ProviderUnavailable(
                "ONNX Runtime is not installed. Install requirements-prod.txt and restart the backend."
            ) from exc

        try:
            available = ort.get_available_providers()
            if "CPUExecutionProvider" not in available:
                raise ProviderUnavailable(
                    "ONNX Runtime CPUExecutionProvider is not available in this Python environment."
                )
            options = ort.SessionOptions()
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            # The model is small; keep predictable CPU usage on a school PC.
            options.intra_op_num_threads = 0
            options.inter_op_num_threads = 1
            self.session = ort.InferenceSession(
                str(recognizer_file),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self.detector = cv2.FaceDetectorYN_create(
                str(detector_file), "", (320, 320), score_threshold, nms_threshold, 5000
            )
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise ProviderUnavailable(
                "ONNX Runtime could not load MobileFaceNet. Keep mobile_facenet.onnx and mobile_facenet.data together."
            ) from exc

        self._validate_runtime_contract()
        self._warm_up()
        try:
            import onnxruntime as ort

            runtime_version = ort.__version__
            available_providers = ort.get_available_providers()
        except Exception:
            runtime_version = "unknown"
            available_providers = []
        log_face_event(
            "provider.initialized",
            provider=self.provider_name,
            model_name=self.model_name,
            model_version=self.model_version,
            detector_score_threshold=self.score_threshold,
            detector_nms_threshold=nms_threshold,
            min_face_size_px=self.min_face_size,
            input_size=self.input_size,
            embedding_size=self.embedding_size,
            onnxruntime_version=runtime_version,
            onnxruntime_providers=available_providers,
            detector_model_exists=detector_file.is_file(),
            detector_model_bytes=detector_file.stat().st_size,
            recognizer_model_bytes=recognizer_file.stat().st_size,
            metadata_bytes=metadata_file.stat().st_size,
            external_weights_bytes=external_file.stat().st_size,
        )

    def _validate_release_metadata(self, metadata_file: Path) -> None:
        try:
            metadata: dict[str, Any] = json.loads(
                metadata_file.read_text(encoding="utf-8")
            )
            model_files = metadata["model_files"]
            model_info = model_files["mobile_facenet.onnx"]
            inputs = model_info["inputs"]
            outputs = model_info["outputs"]
            expected_shape = [1, 3, self.input_size, self.input_size]
            for name in (self.input_name_1, self.input_name_2):
                spec = inputs[name]
                if (
                    spec.get("shape") != expected_shape
                    or spec.get("dtype") != "float32"
                ):
                    raise ValueError(f"Unexpected metadata for input {name}")
                if spec.get("value_range") != [0.0, 1.0]:
                    raise ValueError(f"Unexpected input value range for {name}")
            output_spec = outputs[self.output_name]
            if (
                output_spec.get("shape") != [2, self.embedding_size]
                or output_spec.get("dtype") != "float32"
            ):
                raise ValueError("Unexpected MobileFaceNet output metadata")
            if (
                metadata.get("runtime") != "onnx"
                or metadata.get("precision") != "float"
            ):
                raise ValueError(
                    "The supplied metadata is not the Qualcomm ONNX float export"
                )
        except Exception as exc:
            raise ProviderUnavailable(
                "MobileFaceNet metadata.json does not match the configured Qualcomm ONNX export."
            ) from exc

    def _validate_runtime_contract(self) -> None:
        try:
            runtime_inputs = {item.name: item for item in self.session.get_inputs()}
            runtime_outputs = {item.name: item for item in self.session.get_outputs()}
            if set(runtime_inputs) != {self.input_name_1, self.input_name_2}:
                raise ValueError(f"Unexpected model inputs: {sorted(runtime_inputs)}")
            if self.output_name not in runtime_outputs:
                raise ValueError(f"Missing output {self.output_name}")
            expected = [1, 3, self.input_size, self.input_size]
            for name in (self.input_name_1, self.input_name_2):
                item = runtime_inputs[name]
                if item.type != "tensor(float)" or list(item.shape) != expected:
                    raise ValueError(
                        f"Unexpected runtime input contract for {name}: {item.type} {item.shape}"
                    )
            output = runtime_outputs[self.output_name]
            if output.type != "tensor(float)" or list(output.shape) != [
                2,
                self.embedding_size,
            ]:
                raise ValueError(
                    f"Unexpected output contract: {output.type} {output.shape}"
                )
        except Exception as exc:
            raise ProviderUnavailable(
                "MobileFaceNet ONNX input/output contract differs from metadata.json."
            ) from exc

    def _run_pair(self, tensor: np.ndarray) -> np.ndarray:
        result = self.session.run(
            [self.output_name],
            {self.input_name_1: tensor, self.input_name_2: tensor},
        )[0]
        result = np.asarray(result, dtype=np.float32)
        if result.shape != (2, self.embedding_size):
            raise ProviderUnavailable(
                f"MobileFaceNet returned shape {result.shape}; expected (2, {self.embedding_size})."
            )
        if not np.isfinite(result).all():
            raise ProviderUnavailable("MobileFaceNet returned non-finite values.")
        # Same pixels are passed to both pair inputs. Their descriptors must agree.
        if not np.allclose(result[0], result[1], rtol=1e-4, atol=1e-5):
            raise ProviderUnavailable(
                "MobileFaceNet paired outputs disagree for identical images; refusing to create a template."
            )
        return result

    def _warm_up(self) -> None:
        # A synthetic neutral tensor checks runtime/graph/sidecar compatibility
        # without using anyone's face or claiming recognition accuracy.
        dummy = np.full((1, 3, self.input_size, self.input_size), 0.5, dtype=np.float32)
        try:
            with self._inference_lock:
                output = self._run_pair(dummy)
            if float(np.linalg.norm(output[0])) <= 1e-12:
                raise ProviderUnavailable(
                    "MobileFaceNet warm-up returned a zero embedding."
                )
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise ProviderUnavailable(
                "MobileFaceNet synthetic warm-up inference failed."
            ) from exc

    def _align_face(self, frame_bgr: np.ndarray, face: np.ndarray) -> np.ndarray:
        """Align YuNet's five landmarks to the Qualcomm 112px input template."""
        landmarks = np.asarray(face[4:14], dtype=np.float32).reshape(5, 2)
        if not np.isfinite(landmarks).all():
            log_face_event("alignment.rejected", reason="non_finite_landmarks")
            raise PoorFaceQuality(
                "The face landmarks are incomplete. Retake the image."
            )

        target = np.array(
            [
                [38.2946, 51.6963],
                [73.5318, 51.5014],
                [56.0252, 71.7366],
                [41.5493, 92.3655],
                [70.7299, 92.2041],
            ],
            dtype=np.float32,
        )
        started = time.perf_counter()
        transform, _ = cv2.estimateAffinePartial2D(landmarks, target, method=cv2.LMEDS)
        if transform is None or not np.isfinite(transform).all():
            log_face_event("alignment.rejected", reason="affine_transform_failed")
            raise PoorFaceQuality(
                "The face could not be aligned reliably. Retake the image."
            )

        scale = float(
            math.sqrt(float(transform[0, 0]) ** 2 + float(transform[1, 0]) ** 2)
        )
        rotation_deg = float(
            math.degrees(math.atan2(float(transform[1, 0]), float(transform[0, 0])))
        )
        aligned = cv2.warpAffine(
            frame_bgr,
            transform,
            (self.input_size, self.input_size),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
        log_face_event(
            "alignment.complete",
            input_width=int(frame_bgr.shape[1]),
            input_height=int(frame_bgr.shape[0]),
            output_width=int(aligned.shape[1]),
            output_height=int(aligned.shape[0]),
            affine_scale=round(scale, 5),
            rotation_degrees=round(rotation_deg, 3),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return aligned

    @staticmethod
    def _summarize_detections(
        faces: np.ndarray | None, width: int, height: int
    ) -> list[dict[str, Any]]:
        if faces is None:
            return []
        summaries: list[dict[str, Any]] = []
        for face in np.asarray(faces)[:5]:
            box_width = float(face[2])
            box_height = float(face[3])
            summaries.append(
                {
                    "confidence": round(float(face[-1]), 5),
                    "box_width_px": round(box_width, 1),
                    "box_height_px": round(box_height, 1),
                    "box_width_ratio": round(box_width / max(width, 1), 5),
                    "box_height_ratio": round(box_height / max(height, 1), 5),
                }
            )
        return summaries

    @staticmethod
    def _estimate_pose_degrees(landmarks: np.ndarray, width: int, height: int) -> tuple[float | None, float | None, float | None]:
        """Approximate yaw/pitch/roll from YuNet's five landmarks for capture guidance."""
        model_points = np.array(
            [
                [-30.0, -30.0, 30.0], [30.0, -30.0, 30.0], [0.0, 0.0, 50.0],
                [-25.0, 30.0, 20.0], [25.0, 30.0, 20.0],
            ], dtype=np.float64
        )
        focal = float(max(width, height))
        camera = np.array(
            [[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1]], dtype=np.float64
        )
        try:
            ok, rotation_vector, _ = cv2.solvePnP(
                model_points, landmarks.astype(np.float64), camera,
                np.zeros((4, 1), dtype=np.float64), flags=cv2.SOLVEPNP_EPNP,
            )
            if not ok:
                return None, None, None
            rotation, _ = cv2.Rodrigues(rotation_vector)
            sy = math.sqrt(rotation[0, 0] ** 2 + rotation[1, 0] ** 2)
            yaw = math.degrees(math.atan2(-rotation[2, 0], sy))
            pitch = math.degrees(math.atan2(rotation[2, 1], rotation[2, 2]))
            roll = math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]))
            if not all(math.isfinite(value) for value in (yaw, pitch, roll)):
                return None, None, None
            return yaw, pitch, roll
        except Exception:
            return None, None, None

    def analyze_capture_guidance(self, image_bytes: bytes) -> dict[str, Any]:
        """Analyze a transient camera frame; never creates/stores an identity embedding."""
        if not image_bytes or len(image_bytes) > 2 * 1024 * 1024:
            return {
                "face_detected": False, "face_count": 0, "pose_bucket": "pose_unknown",
                "quality_grade": "RETAKE_RECOMMENDED", "capture_ready": False,
                "guidance": ["Camera preview frame is too large. Keep the preview image under 2 MB."],
                "metrics": {}, "identity_evidence": False,
            }
        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Unsupported image type")
                oriented = ImageOps.exif_transpose(image)
                rgb = np.asarray(oriented.convert("RGB"))
        except Exception:
            return {
                "face_detected": False, "face_count": 0, "pose_bucket": "pose_unknown",
                "quality_grade": "RETAKE_RECOMMENDED", "capture_ready": False,
                "guidance": ["Camera frame could not be read. Keep the camera steady and try again."],
                "metrics": {}, "identity_evidence": False,
            }

        height, width = rgb.shape[:2]
        if width < 160 or height < 160 or width > 4096 or height > 4096:
            return {
                "face_detected": False, "face_count": 0, "pose_bucket": "pose_unknown",
                "quality_grade": "RETAKE_RECOMMENDED", "capture_ready": False,
                "guidance": ["Move the phone slightly closer or adjust the camera frame."],
                "metrics": {"image_pixels": [width, height]}, "identity_evidence": False,
            }
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        with self._inference_lock:
            self.detector.setInputSize((width, height))
            _, faces = self.detector.detect(frame)

        face_count = 0 if faces is None else len(faces)
        if face_count == 0:
            return {
                "face_detected": False, "face_count": 0, "pose_bucket": "pose_unknown",
                "quality_grade": "RETAKE_RECOMMENDED", "capture_ready": False,
                "guidance": ["Bring one face into the camera view and center it in the frame."],
                "metrics": {"image_pixels": [width, height]}, "identity_evidence": False,
            }
        if face_count != 1:
            return {
                "face_detected": False, "face_count": face_count, "pose_bucket": "pose_unknown",
                "quality_grade": "RETAKE_RECOMMENDED", "capture_ready": False,
                "guidance": ["Only one person should be visible. Ask others to step out of the frame."],
                "metrics": {"face_count": face_count, "image_pixels": [width, height]}, "identity_evidence": False,
            }

        face = faces[0]
        confidence = float(face[-1])
        x, y, box_width, box_height = [float(value) for value in face[:4]]
        landmarks = np.asarray(face[4:14], dtype=np.float32).reshape(5, 2)
        yaw, pitch, roll = self._estimate_pose_degrees(landmarks, width, height)
        x1, y1 = max(0, int(x)), max(0, int(y))
        x2, y2 = min(width, int(x + box_width)), min(height, int(y + box_height))
        crop = gray[y1:y2, x1:x2]
        if crop.size == 0:
            brightness, contrast, sharpness = 0.0, 0.0, 0.0
        else:
            brightness = float(np.mean(crop))
            contrast = float(np.std(crop))
            sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var())

        if yaw is None or pitch is None:
            pose_bucket = "pose_unknown"
        elif abs(yaw) < 12 and abs(pitch) < 12:
            pose_bucket = "front"
        elif yaw <= -12:
            pose_bucket = "turn_left"
        elif yaw >= 12:
            pose_bucket = "turn_right"
        elif pitch <= -12:
            pose_bucket = "look_up"
        else:
            pose_bucket = "look_down"

        guidance: list[str] = []
        hard_retake = False
        if brightness < 35:
            guidance.append("Too dark. Face an even light source."); hard_retake = True
        elif brightness < 55:
            guidance.append("Lighting is low. Move toward soft, even light.")
        elif brightness > 230:
            guidance.append("Too bright. Avoid direct light on the face."); hard_retake = True
        elif brightness > 210:
            guidance.append("Lighting is a little bright. Avoid direct light.")
        if contrast < 12:
            guidance.append("Very low contrast. Move to soft, even lighting."); hard_retake = True
        elif contrast < 22:
            guidance.append("Low contrast. Use soft, even lighting.")
        if sharpness < 16:
            guidance.append("Image is too blurry. Hold the phone steady."); hard_retake = True
        elif sharpness < 35:
            guidance.append("Image is slightly soft. Hold the phone steady.")
        if min(box_width, box_height) < max(64, self.min_face_size):
            guidance.append("Face is too small. Move a little closer."); hard_retake = True
        if confidence < self.score_threshold:
            guidance.append("Face detection is uncertain. Center the face and improve lighting."); hard_retake = True
        if box_width / max(width, 1) < 0.08:
            guidance.append("Face is too small in the frame. Move a little closer."); hard_retake = True
        elif box_width / max(width, 1) < 0.12:
            guidance.append("Move a little closer so the face fills more of the frame.")
        if yaw is None or pitch is None:
            guidance.append("Pose is not clear yet. Look toward the camera and try again."); hard_retake = True
        elif abs(yaw) > 35 or abs(pitch) > 28:
            guidance.append("Turn less and keep your face closer to the camera direction."); hard_retake = True
        if abs(roll or 0.0) > 25:
            guidance.append("Keep your head upright."); hard_retake = True
        elif abs(roll or 0.0) > 18:
            guidance.append("Try to keep your head a little straighter.")
        center_x = (x + box_width / 2) / max(width, 1)
        center_y = (y + box_height / 2) / max(height, 1)
        if abs(center_x - 0.5) > 0.28 or abs(center_y - 0.5) > 0.30:
            guidance.append("Move your face toward the center of the guide.")
        quality_grade = "RETAKE_RECOMMENDED" if hard_retake else ("FAIR" if guidance else "GOOD")
        metrics = {
            "brightness_mean": round(brightness, 2),
            "contrast_stddev": round(contrast, 2),
            "sharpness_laplacian_variance": round(sharpness, 2),
            "detector_confidence": round(confidence, 4),
            "face_width_ratio": round(box_width / max(width, 1), 4),
            "face_center_normalized": [round(center_x, 4), round(center_y, 4)],
            "estimated_yaw_degrees": None if yaw is None else round(yaw, 1),
            "estimated_pitch_degrees": None if pitch is None else round(pitch, 1),
            "estimated_roll_degrees": None if roll is None else round(roll, 1),
        }
        return {
            "face_detected": True,
            "face_count": face_count,
            "pose_bucket": pose_bucket,
            "quality_grade": quality_grade,
            "capture_ready": quality_grade in {"GOOD", "FAIR"},
            "guidance": guidance or ["Good capture quality. Hold this pose briefly."],
            "metrics": metrics,
            "identity_evidence": False,
        }

    def create_embedding(self, image_bytes: bytes) -> FaceEmbedding:
        total_started = time.perf_counter()
        stage = "decode"
        log_face_event(
            "embedding.started",
            upload_bytes=len(image_bytes),
            detector_score_threshold=self.score_threshold,
            detector_nms_threshold=self.detector.getNMSThreshold(),
            min_face_size_px=self.min_face_size,
        )
        try:
            decode_started = time.perf_counter()
            with Image.open(io.BytesIO(image_bytes)) as image:
                source_format = image.format
                source_width, source_height = image.size
                exif_orientation = int(image.getexif().get(274, 1))
                # Normalize phone-camera EXIF rotation before OpenCV detection.
                oriented = ImageOps.exif_transpose(image)
                rgb = np.asarray(oriented.convert("RGB"))
            if rgb.ndim != 3 or rgb.shape[2] != 3:
                raise PoorFaceQuality("The uploaded image could not be decoded as RGB.")
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            height, width = frame.shape[:2]
            if height < 1 or width < 1:
                raise PoorFaceQuality("The uploaded image has invalid dimensions.")
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            log_face_event(
                "image.decoded",
                source_format=source_format,
                source_width=int(source_width),
                source_height=int(source_height),
                exif_orientation=exif_orientation,
                decoded_width=int(width),
                decoded_height=int(height),
                aspect_ratio=round(width / max(height, 1), 5),
                rgb_dtype=str(rgb.dtype),
                gray_mean=round(float(gray.mean()), 2),
                gray_std=round(float(gray.std()), 2),
                elapsed_ms=round((time.perf_counter() - decode_started) * 1000, 2),
            )

            stage = "yunet_detection"
            with self._inference_lock:
                self.detector.setInputSize((width, height))
                configured_threshold = float(self.detector.getScoreThreshold())
                detection_started = time.perf_counter()
                _, faces = self.detector.detect(frame)
                detection_ms = round(
                    (time.perf_counter() - detection_started) * 1000, 2
                )
                face_count = 0 if faces is None else int(len(faces))
                log_face_event(
                    "yunet.detection_complete",
                    image_width=int(width),
                    image_height=int(height),
                    input_size=list(self.detector.getInputSize()),
                    score_threshold=configured_threshold,
                    nms_threshold=float(self.detector.getNMSThreshold()),
                    face_count=face_count,
                    candidates=self._summarize_detections(faces, width, height),
                    elapsed_ms=detection_ms,
                )

                if faces is None or len(faces) == 0:
                    # Diagnostic-only probe: lower YuNet's score gate to reveal
                    # whether a weak candidate exists. Probe results are NEVER
                    # accepted for enrollment or attendance decisions.
                    probe_threshold = min(configured_threshold, 0.35)
                    probe_faces = None
                    probe_ms = 0.0
                    if probe_threshold < configured_threshold:
                        try:
                            self.detector.setScoreThreshold(probe_threshold)
                            probe_started = time.perf_counter()
                            _, probe_faces = self.detector.detect(frame)
                            probe_ms = round(
                                (time.perf_counter() - probe_started) * 1000, 2
                            )
                        finally:
                            self.detector.setScoreThreshold(configured_threshold)
                    log_face_event(
                        "yunet.low_threshold_probe",
                        probe_threshold=probe_threshold,
                        probe_face_count=(
                            0 if probe_faces is None else int(len(probe_faces))
                        ),
                        probe_candidates=self._summarize_detections(
                            probe_faces, width, height
                        ),
                        elapsed_ms=probe_ms,
                        probe_is_diagnostic_only=True,
                    )
                    raise NoFaceDetected(
                        "No face was detected. Retake the image or use manual attendance."
                    )

                if len(faces) != 1:
                    log_face_event(
                        "yunet.multiple_faces_rejected",
                        face_count=int(len(faces)),
                        candidates=self._summarize_detections(faces, width, height),
                    )
                    raise MultipleFacesDetected("Capture one person at a time.")

                face = faces[0]
                confidence = float(face[-1])
                box_width, box_height = float(face[2]), float(face[3])
                if confidence < self.score_threshold:
                    log_face_event(
                        "yunet.quality_rejected",
                        reason="confidence_below_configured_threshold",
                        confidence=round(confidence, 5),
                        configured_threshold=self.score_threshold,
                    )
                    raise PoorFaceQuality(
                        "The face detection confidence is too low. Improve lighting and retake the image."
                    )
                if min(box_width, box_height) < self.min_face_size:
                    log_face_event(
                        "yunet.quality_rejected",
                        reason="face_box_below_minimum_size",
                        confidence=round(confidence, 5),
                        box_width_px=round(box_width, 1),
                        box_height_px=round(box_height, 1),
                        min_face_size_px=self.min_face_size,
                    )
                    raise PoorFaceQuality(
                        "The face is too small or unclear. Move closer and improve lighting."
                    )
                log_face_event(
                    "yunet.face_accepted",
                    confidence=round(confidence, 5),
                    box_width_px=round(box_width, 1),
                    box_height_px=round(box_height, 1),
                    box_width_ratio=round(box_width / width, 5),
                    box_height_ratio=round(box_height / height, 5),
                )

                stage = "alignment"
                aligned_bgr = self._align_face(frame, face)
                aligned_rgb = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2RGB)
                chw = np.transpose(aligned_rgb.astype(np.float32) / 255.0, (2, 0, 1))
                tensor = np.ascontiguousarray(chw[None, ...], dtype=np.float32)
                log_face_event(
                    "onnx.input_prepared",
                    shape=list(tensor.shape),
                    dtype=str(tensor.dtype),
                    min_value=round(float(tensor.min()), 6),
                    max_value=round(float(tensor.max()), 6),
                    mean_value=round(float(tensor.mean()), 6),
                    channel_means=[
                        round(float(value), 6) for value in tensor.mean(axis=(0, 2, 3))
                    ],
                )

                stage = "mobilefacenet_inference"
                inference_started = time.perf_counter()
                paired_embeddings = self._run_pair(tensor)
                inference_ms = round(
                    (time.perf_counter() - inference_started) * 1000, 2
                )
                feature = paired_embeddings[0]
                norm_0 = float(np.linalg.norm(paired_embeddings[0]))
                norm_1 = float(np.linalg.norm(paired_embeddings[1]))
                pair_max_abs_diff = float(
                    np.max(np.abs(paired_embeddings[0] - paired_embeddings[1]))
                )
                log_face_event(
                    "onnx.inference_complete",
                    output_shape=list(paired_embeddings.shape),
                    output_dtype=str(paired_embeddings.dtype),
                    output_norm_row_0=round(norm_0, 7),
                    output_norm_row_1=round(norm_1, 7),
                    paired_output_max_abs_diff=round(pair_max_abs_diff, 9),
                    inference_ms=inference_ms,
                )

            stage = "embedding_validation"
            norm = float(np.linalg.norm(feature))
            if norm <= 1e-12 or not np.isfinite(feature).all():
                log_face_event(
                    "embedding.rejected",
                    reason="zero_norm_or_non_finite",
                    norm=round(norm, 9),
                    all_finite=bool(np.isfinite(feature).all()),
                )
                raise PoorFaceQuality(
                    "The face template could not be generated reliably."
                )
            vector = (feature / norm).astype(np.float32).tolist()
            log_face_event(
                "embedding.completed",
                embedding_dimensions=len(vector),
                embedding_norm=round(float(np.linalg.norm(vector)), 7),
                total_elapsed_ms=round((time.perf_counter() - total_started) * 1000, 2),
                result="success",
            )
            return FaceEmbedding(
                vector, self.provider_name, self.model_name, self.model_version
            )
        except (
            NoFaceDetected,
            MultipleFacesDetected,
            PoorFaceQuality,
            ProviderUnavailable,
        ) as exc:
            log_face_event(
                "embedding.rejected",
                stage=stage,
                exception_type=type(exc).__name__,
                reason=str(exc),
                total_elapsed_ms=round((time.perf_counter() - total_started) * 1000, 2),
            )
            raise
        except Exception as exc:
            log_face_event(
                "embedding.failed",
                stage=stage,
                exception_type=type(exc).__name__,
                total_elapsed_ms=round((time.perf_counter() - total_started) * 1000, 2),
            )
            raise PoorFaceQuality(
                "The image/model could not be evaluated. Retake the still image or use manual attendance."
            ) from exc
