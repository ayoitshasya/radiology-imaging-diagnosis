"""Tests for ml/explainability: heatmaps, overlays, box geometry and validation."""

import argparse
import json

import cv2
import numpy as np
import pandas as pd
import pydicom
import pytest
import torch
from conftest import write_dicom

from ml.classification.common import build_model, load_config
from ml.explainability.gradcam import compute_heatmap, load_model, normalise_heatmap, overlay
from ml.explainability.validate_gradcam import (
    box_mask,
    mass_in_box,
    mean_ci,
    pointing_hit,
    scale_box,
    validate,
)

LAYER = "features.denseblock4"


@pytest.fixture(scope="module")
def random_model():
    torch.manual_seed(0)
    return build_model(pretrained=False).eval()


@pytest.fixture
def image():
    return np.random.default_rng(0).integers(0, 256, (224, 224), dtype=np.uint8)


def test_normalise_heatmap_range_and_constant_map():
    out = normalise_heatmap(np.array([[2.0, 4.0], [6.0, 10.0]]))
    np.testing.assert_allclose(out, [[0.0, 0.25], [0.5, 1.0]])
    assert not normalise_heatmap(np.full((3, 3), 5.0)).any()


def test_heatmap_is_in_unit_range_with_image_shape(random_model, image):
    heat = compute_heatmap(random_model, image, LAYER)
    assert heat.shape == image.shape
    assert heat.min() >= 0.0 and heat.max() <= 1.0


def test_overlay_is_rgb_uint8_with_image_shape(image):
    heat = np.linspace(0, 1, image.size).reshape(image.shape)
    out = overlay(image, heat)
    assert out.shape == (224, 224, 3)
    assert out.dtype == np.uint8


@pytest.mark.parametrize(
    ("box", "rows", "cols", "expected"),
    [
        ((100, 200, 300, 400), 1024, 1024, (21.875, 43.75, 87.5, 131.25)),
        ((0, 0, 1024, 1024), 1024, 1024, (0, 0, 224, 224)),
        ((100, 100, 100, 100), 2048, 1024, (21.875, 10.9375, 43.75, 21.875)),
    ],
)
def test_scale_box(box, rows, cols, expected):
    assert scale_box(box, rows, cols, 224) == pytest.approx(expected)


def test_box_mask_uses_pixel_centres_and_unions_boxes():
    assert box_mask([(0, 0, 2, 2)], 10).sum() == 4
    assert box_mask([(0.6, 0, 2, 1)], 10).sum() == 1  # centre 0.5 excluded, 1.5 included
    assert box_mask([(0, 0, 2, 2), (1, 1, 3, 3)], 10).sum() == 7  # overlap counted once


def test_mass_in_box_and_pointing_with_known_answer():
    heat = np.zeros((10, 10))
    heat[0:2, 0:2] = 1.0  # 4 units inside the box
    heat[5, 5] = heat[7, 7] = 1.0  # 2 units outside
    mask = box_mask([(0, 0, 2, 2)], 10)
    assert mass_in_box(heat, mask) == pytest.approx(4 / 6)
    assert pointing_hit(heat, mask) == 1.0  # first peak in row-major order is (0, 0)
    heat[9, 9] = 2.0
    assert pointing_hit(heat, mask) == 0.0
    assert mass_in_box(np.ones((10, 10)), mask) == pytest.approx(mask.mean())


def test_all_zero_heatmap_gives_nan_not_a_score():
    mask = box_mask([(0, 0, 2, 2)], 10)
    assert np.isnan(mass_in_box(np.zeros((10, 10)), mask))
    assert np.isnan(pointing_hit(np.zeros((10, 10)), mask))


def test_mean_ci_is_seeded_and_skips_nan():
    values = np.array([0.1, 0.2, np.nan, 0.4, 0.8])
    assert mean_ci(values, 200, 42) == mean_ci(values, 200, 42)
    assert mean_ci(values, 200, 42)["n"] == 4
    assert mean_ci(np.array([np.nan]), 200, 42)["mean"] is None


def test_random_baseline_and_validation_run_end_to_end_without_patient_ids(tmp_path):
    """Synthetic studies through validate(); report must not contain the patient keys."""
    dicom_dir, data_dir = tmp_path / "dicoms", tmp_path / "data"
    dicom_dir.mkdir()
    (data_dir / "images").mkdir(parents=True)
    rng = np.random.default_rng(1)
    patients, manifest, label_rows = [f"patient-key-{i}" for i in range(3)], [], []
    for i, pid in enumerate(patients):
        path = write_dicom(
            dicom_dir / f"{pid}.dcm", rng.integers(0, 256, (256, 256)), view="AP" if i else "PA"
        )
        uid = str(pydicom.dcmread(path).StudyInstanceUID)
        cv2.imwrite(
            str(data_dir / "images" / f"{uid}.png"),
            rng.integers(0, 256, (224, 224), dtype=np.uint8),
        )
        manifest.append(
            {
                "image_id": uid,
                "path": f"images/{uid}.png",
                "label": 1,
                "split": "test",
                "view_position": "AP" if i else "PA",
            }
        )
        label_rows.append(
            {"patientId": pid, "x": 40, "y": 40, "width": 80, "height": 80, "Target": 1}
        )
    pd.DataFrame(manifest).to_csv(data_dir / "manifest.csv", index=False)
    pd.DataFrame(label_rows).to_csv(tmp_path / "labels.csv", index=False)

    # Same metadata shape as the Kaggle checkpoint, including the TorchVersion object.
    torch.manual_seed(0)
    ckpt = tmp_path / "model.pt"
    torch.save(
        {
            "model_state": build_model(pretrained=False).state_dict(),
            "metadata": {"torch_version": torch.__version__},
        },
        ckpt,
    )
    assert load_model(ckpt) is not None

    args = argparse.Namespace(
        data_dir=data_dir,
        manifest="manifest.csv",
        split="test",
        dicom_dir=dicom_dir,
        labels=tmp_path / "labels.csv",
        checkpoint=ckpt,
        threshold=0.0,
        report=tmp_path / "report.json",
        device="cpu",
    )
    report = validate(args, load_config())
    assert report["true_positives_scored"] == 3
    assert set(report["overall"]["methods"]) == {"trained", "random_init", "uniform"}
    text = (tmp_path / "report.json").read_text()
    json.loads(text, parse_constant=lambda c: pytest.fail(f"non-JSON {c}"))
    assert not any(pid in text for pid in patients)
    assert (tmp_path / "report.png").is_file()


def test_predict_probability_is_sigmoid_of_logit_and_shared(random_model, image):
    import ml.explainability.validate_gradcam as vg
    from ml.explainability.gradcam import predict_probability, to_input_tensor

    p = predict_probability(random_model, image)
    with torch.no_grad():
        expected = torch.sigmoid(random_model(to_input_tensor(image))).item()
    assert 0.0 <= p <= 1.0
    assert p == pytest.approx(expected)
    assert vg.predict_probability is predict_probability  # one definition, reused
