"""GET /studies/{id}/image and /heatmap: PNGs built in memory, never written to disk."""

import builtins
import io
import tempfile
from contextlib import contextmanager

import cv2
import numpy as np
import pydicom
import pytest
from sqlalchemy import text

from ml.preprocessing.build_dataset import preprocess_dicom

NOTICE = "Educational use only. Not for clinical use."


@contextmanager
def no_disk_writes():
    """Make every file-writing path raise while active; wrap only the API calls with it.

    Test setup (writing synthetic DICOMs) happens outside, so a failure here can only
    come from the request path.
    """
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"disk write attempted: {file}")
        return real_open(file, mode, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("temporary file or image write attempted")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(builtins, "open", guarded_open)
        mp.setattr(io, "open", guarded_open)
        for name in ("NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile", "mkstemp"):
            mp.setattr(tempfile, name, forbidden)
        mp.setattr(cv2, "imwrite", forbidden)
        yield


def decode(png: bytes, flags=cv2.IMREAD_UNCHANGED) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(png, np.uint8), flags)


def synced(api, tmp_path, oid="s1"):
    client, fake, engine = api
    fake.add_study(tmp_path, oid)
    client.post("/studies/sync")
    return client, fake, engine


def test_image_is_the_preprocessed_model_input(api, tmp_path):
    client, fake, _ = synced(api, tmp_path)
    with no_disk_writes():
        response = client.get("/studies/s1/image")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-notice"] == NOTICE
    assert response.headers["cache-control"] == "no-store"
    expected = preprocess_dicom(pydicom.dcmread(io.BytesIO(fake.studies["s1"]["dicom"])), 224)
    np.testing.assert_array_equal(decode(response.content), expected)  # PNG is lossless


def test_image_unknown_study_is_404(api):
    client, _, _ = api
    assert client.get("/studies/missing/image").status_code == 404


def test_heatmap_404_before_analysis(api, tmp_path):
    client, _, _ = synced(api, tmp_path)
    assert client.get("/studies/s1/heatmap").status_code == 404


def test_heatmap_from_cache_then_recomputed_identically(api, tmp_path):
    client, _, _ = synced(api, tmp_path)
    with no_disk_writes():
        pred = client.post("/studies/s1/analyse").json()
        cached = client.get("/studies/s1/heatmap")
    assert cached.status_code == 200 and cached.headers["x-heatmap-source"] == "cache"
    assert cached.headers["x-prediction-id"] == str(pred["prediction_id"])
    assert cached.headers["x-notice"] == NOTICE
    assert decode(cached.content).shape == (224, 224, 3)

    client.app.state.overlay_cache._items.clear()  # as after a restart
    with no_disk_writes():
        recomputed = client.get("/studies/s1/heatmap")
    assert recomputed.headers["x-heatmap-source"] == "recomputed"
    assert recomputed.content == cached.content  # deterministic model and Grad-CAM


def test_heatmap_refuses_to_recompute_for_another_checkpoint(api, tmp_path):
    client, _, engine = synced(api, tmp_path)
    client.post("/studies/s1/analyse")
    client.app.state.overlay_cache._items.clear()
    with engine.begin() as conn:  # simulate a prediction made by a different model
        conn.execute(text("UPDATE predictions SET checkpoint_sha256 = :h"), {"h": "c" * 64})
    response = client.get("/studies/s1/heatmap")
    assert response.status_code == 409 and "force" in response.json()["detail"]


def test_orthanc_down_image_is_503(api, tmp_path):
    client, fake, _ = synced(api, tmp_path)
    fake.down = True
    assert client.get("/studies/s1/image").status_code == 503
