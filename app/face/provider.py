from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class FaceProviderError(Exception):
    """A safe, user-visible face processing failure."""


class ProviderUnavailable(FaceProviderError):
    pass


class NoFaceDetected(FaceProviderError):
    pass


class MultipleFacesDetected(FaceProviderError):
    pass


class PoorFaceQuality(FaceProviderError):
    pass


@dataclass(frozen=True)
class FaceEmbedding:
    vector: list[float]
    provider: str
    model_name: str
    model_version: str


class FaceRecognitionProvider(Protocol):
    provider_name: str
    model_name: str
    model_version: str

    def create_embedding(self, image_bytes: bytes) -> FaceEmbedding: ...


class ManualOnlyProvider:
    """Explicit no-biometric mode. Manual attendance remains enabled."""
    provider_name = "manual"
    model_name = "none"
    model_version = "none"

    def create_embedding(self, image_bytes: bytes) -> FaceEmbedding:
        raise ProviderUnavailable("Face processing is disabled; use the approved manual attendance path.")


class FakeFaceProvider:
    """Deterministic test/development provider. Never permits real biometric use."""
    provider_name = "fake-test-only"
    model_name = "deterministic-test-vector"
    model_version = "1"

    def create_embedding(self, image_bytes: bytes) -> FaceEmbedding:
        import hashlib
        import math

        raw = hashlib.sha512(image_bytes).digest()
        values = [((byte / 127.5) - 1.0) for byte in raw]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return FaceEmbedding([v / norm for v in values], self.provider_name, self.model_name, self.model_version)
