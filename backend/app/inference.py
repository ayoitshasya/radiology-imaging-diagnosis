"""Fetch a study from Orthanc, preprocess it and run the model and Grad-CAM.

All image data stays in memory: DICOM bytes are read from a BytesIO, PNGs are encoded
with cv2.imencode, and overlays are kept only in a small in-memory cache.
"""

from __future__ import annotations

import io
import threading
from collections import OrderedDict

import cv2
import numpy as np
import pydicom
from fastapi import HTTPException

from backend.app.model_service import ModelService
from backend.app.models import Study
from backend.app.orthanc import OrthancClient
from ml.explainability.gradcam import compute_heatmap, overlay, predict_probability
from ml.preprocessing.build_dataset import preprocess_dicom

# Grad-CAM attaches hooks to the shared model, so concurrent requests could mix each
# other's activations. One lock serialises model use; analyses run one at a time.
MODEL_LOCK = threading.Lock()


def load_study_image(orthanc: OrthancClient, study: Study, size: int) -> np.ndarray:
    """Fetch the study's DICOM into memory and return the preprocessed model input.

    Raises:
        HTTPException: 409 if the DICOM's StudyInstanceUID differs from the synced record.
    """
    raw = orthanc.instance_file(orthanc.first_instance_id(study.orthanc_study_id))
    ds = pydicom.dcmread(io.BytesIO(raw))
    if str(ds.StudyInstanceUID) != study.study_instance_uid:
        raise HTTPException(409, detail="DICOM StudyInstanceUID does not match the synced study")
    return preprocess_dicom(ds, size)


def predict_and_explain(service: ModelService, img: np.ndarray) -> tuple[float, np.ndarray]:
    """Probability and Grad-CAM overlay (HxWx3 uint8 RGB) under the model lock."""
    with MODEL_LOCK:
        probability = predict_probability(service.model, img)
        heatmap = compute_heatmap(service.model, img, service.target_layer)
    return probability, overlay(img, heatmap)


def explain(service: ModelService, img: np.ndarray) -> np.ndarray:
    """Grad-CAM overlay only, under the model lock."""
    with MODEL_LOCK:
        heatmap = compute_heatmap(service.model, img, service.target_layer)
    return overlay(img, heatmap)


def png_bytes(img: np.ndarray) -> bytes:
    """Encode a grayscale or RGB image as PNG in memory."""
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    ok, buffer = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return buffer.tobytes()


class OverlayCache:
    """Bounded, thread-safe in-memory LRU cache of overlay PNGs keyed by prediction ID.

    Overlays are derived image data, so they are never written to disk or the database;
    after eviction or a restart they are recomputed on request.
    """

    def __init__(self, max_items: int = 32) -> None:
        self._items: OrderedDict[int, bytes] = OrderedDict()
        self._max = max_items
        self._lock = threading.Lock()

    def get(self, prediction_id: int) -> bytes | None:
        with self._lock:
            if prediction_id not in self._items:
                return None
            self._items.move_to_end(prediction_id)
            return self._items[prediction_id]

    def put(self, prediction_id: int, png: bytes) -> None:
        with self._lock:
            self._items[prediction_id] = png
            self._items.move_to_end(prediction_id)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)
