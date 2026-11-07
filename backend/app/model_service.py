"""Load the classifier once at startup, with its checkpoint hash and validated threshold."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from torch import nn

from backend.app.settings import ROOT, Settings
from ml.explainability.gradcam import load_model

log = logging.getLogger(__name__)
EXPECTED_THRESHOLD_METHOD = "youden_j_on_validation"


@dataclass(frozen=True)
class ModelService:
    """The loaded model plus everything a prediction response must report about it."""

    model: nn.Module
    model_name: str
    checkpoint_sha256: str
    threshold: float
    device: str
    target_layer: str


def sha256_of(path: Path) -> str:
    """SHA-256 of a file, read in chunks so large checkpoints do not fill memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_checkpoint(checkpoint: Path, dvc_pointer: Path) -> None:
    """Pull the checkpoint with DVC if it is missing; fail clearly if that does not work."""
    if checkpoint.exists():
        return
    log.warning("Checkpoint missing; running dvc pull %s", dvc_pointer.relative_to(ROOT))
    subprocess.run([sys.executable, "-m", "dvc", "pull", str(dvc_pointer)], cwd=ROOT, check=False)
    if not checkpoint.exists():
        raise RuntimeError(
            f"Checkpoint {checkpoint.relative_to(ROOT)} is missing and dvc pull did not "
            f"restore it. Run: python -m dvc pull {dvc_pointer.relative_to(ROOT)}"
        )


def load_threshold(metrics_report: Path) -> float:
    """Decision threshold chosen on validation, read from the evaluation report.

    Raises:
        RuntimeError: If the report does not state a validation-chosen threshold in [0, 1].
    """
    threshold = json.loads(metrics_report.read_text(encoding="utf-8"))["threshold"]
    if threshold.get("method") != EXPECTED_THRESHOLD_METHOD:
        raise RuntimeError(
            f"Threshold method is {threshold.get('method')!r}, expected "
            f"{EXPECTED_THRESHOLD_METHOD!r}; refusing to use it"
        )
    value = float(threshold["value"])
    if not 0.0 <= value <= 1.0:
        raise RuntimeError(f"Threshold {value} is outside [0, 1]")
    return value


def load_model_service(settings: Settings) -> ModelService:
    """Ensure the checkpoint exists, hash it, read the threshold and load the model."""
    ensure_checkpoint(settings.checkpoint, settings.checkpoint_dvc)
    service = ModelService(
        model=load_model(settings.checkpoint, settings.device),
        model_name=settings.model_name,
        checkpoint_sha256=sha256_of(settings.checkpoint),
        threshold=load_threshold(settings.metrics_report),
        device=settings.device,
        target_layer=settings.target_layer,
    )
    log.info(
        "Model %s loaded (sha256 %s..., threshold %.6f)",
        service.model_name,
        service.checkpoint_sha256[:12],
        service.threshold,
    )
    return service
