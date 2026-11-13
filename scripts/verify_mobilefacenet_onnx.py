from __future__ import annotations

"""Synthetic smoke test for the Qualcomm MobileFaceNet ONNX float release.

Run from the backend project root:
    python scripts/verify_mobilefacenet_onnx.py

This validates loading and tensor I/O only. It does not use a face image and
cannot establish accuracy or a safe attendance matching threshold.
"""

import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "face" / "mobile_facenet.onnx"
EXTERNAL_DATA = ROOT / "models" / "face" / "mobile_facenet.data"
METADATA = ROOT / "models" / "face" / "metadata.json"


def fail(message: str) -> int:
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


def main() -> int:
    for path in (MODEL, EXTERNAL_DATA, METADATA):
        if not path.is_file():
            return fail(f"Required model artifact is missing: {path}")

    try:
        metadata = json.loads(METADATA.read_text(encoding="utf-8"))
        model_spec = metadata["model_files"]["mobile_facenet.onnx"]
        expected_inputs = model_spec["inputs"]
        expected_outputs = model_spec["outputs"]
        import onnxruntime as ort
    except ImportError:
        return fail("onnxruntime is not installed. Run: python -m pip install -r requirements-prod.txt")
    except Exception as exc:
        return fail(f"Could not read metadata.json: {exc}")

    if metadata.get("runtime") != "onnx" or metadata.get("precision") != "float":
        return fail("metadata.json is not the Qualcomm ONNX float export.")

    try:
        session = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
        inputs = {item.name: item for item in session.get_inputs()}
        outputs = {item.name: item for item in session.get_outputs()}
        expected_names = {"img1", "img2"}
        if set(inputs) != expected_names:
            return fail(f"Unexpected input names: {sorted(inputs)}")
        if "embeddings" not in outputs:
            return fail(f"Missing 'embeddings' output. Got: {sorted(outputs)}")

        for name in expected_names:
            spec = expected_inputs[name]
            if spec["shape"] != [1, 3, 112, 112] or spec["dtype"] != "float32":
                return fail(f"metadata.json input contract unexpected for {name}")
            if list(inputs[name].shape) != [1, 3, 112, 112] or inputs[name].type != "tensor(float)":
                return fail(f"ONNX Runtime input contract unexpected for {name}: {inputs[name].shape} {inputs[name].type}")

        output_spec = expected_outputs["embeddings"]
        if output_spec["shape"] != [2, 128] or output_spec["dtype"] != "float32":
            return fail("metadata.json output contract unexpected")
        if list(outputs["embeddings"].shape) != [2, 128] or outputs["embeddings"].type != "tensor(float)":
            return fail(f"ONNX Runtime output contract unexpected: {outputs['embeddings'].shape}")

        # Synthetic deterministic input in the declared [0,1] range.
        rng = np.random.default_rng(20261109)
        tensor = rng.uniform(0.25, 0.75, size=(1, 3, 112, 112)).astype(np.float32)
        result = session.run(["embeddings"], {"img1": tensor, "img2": tensor})[0]
        result = np.asarray(result, dtype=np.float32)
        if result.shape != (2, 128):
            return fail(f"Inference returned {result.shape}, expected (2, 128)")
        if not np.isfinite(result).all():
            return fail("Inference returned NaN or infinity")
        if not np.allclose(result[0], result[1], rtol=1e-4, atol=1e-5):
            return fail("Identical inputs did not produce consistent paired embeddings")
        norm = float(np.linalg.norm(result[0]))
        if norm <= 1e-12:
            return fail("Model produced a zero-norm output")
    except Exception as exc:
        return fail(f"ONNX Runtime load/inference failed: {type(exc).__name__}: {exc}")

    print("PASS: ONNX Runtime loaded the Qualcomm model and external weights.")
    print("PASS: img1/img2 inputs, embeddings output and paired-output shape are correct.")
    print("PASS: synthetic inference returned finite, non-zero, consistent embeddings.")
    print("NOTE: This is not face-recognition accuracy, liveness, threshold or deployment validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
