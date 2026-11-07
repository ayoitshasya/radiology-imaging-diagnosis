"""Tests for ml/preprocessing: split integrity, pixel handling, manifest and Dataset."""

import json

import numpy as np
import pandas as pd
import pydicom
import pytest
import torch
from conftest import write_dicom

from ml.preprocessing.build_dataset import (
    age_bin,
    check_no_patient_overlap,
    dicom_to_uint8,
    run,
    split_by_patient,
)
from ml.preprocessing.dataset import IMAGENET_MEAN, IMAGENET_STD, ChestXrayDataset

N_PATIENTS = 40  # 20 positive, 20 negative
SIZE = 224


def synthetic_patients(n: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        {"patient": [f"p{i:03d}" for i in range(n)], "label": [i % 2 for i in range(n)]}
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Run the full pipeline once on synthetic DICOMs; positives get two box rows like RSNA."""
    root = tmp_path_factory.mktemp("pipeline")
    dicom_dir = root / "dicoms"
    dicom_dir.mkdir()
    rng = np.random.default_rng(0)
    label_rows = []
    for i in range(N_PATIENTS):
        pid, target = f"patient{i:03d}", i % 2
        pixels = rng.integers(0, 256, size=(256, 256))
        write_dicom(dicom_dir / f"{pid}.dcm", pixels, view="AP" if i % 3 else "PA")
        label_rows += [{"patientId": pid, "Target": target}] * (2 if target else 1)
    labels_csv = root / "labels.csv"
    pd.DataFrame(label_rows).to_csv(labels_csv, index=False)

    out, report = root / "processed", root / "summary.json"
    run(dicom_dir, labels_csv, out, SIZE, 42, report)
    return {
        "out": out,
        "report": report,
        "dicom_dir": dicom_dir,
        "labels_csv": labels_csv,
        "patients": [r["patientId"] for r in label_rows],
    }


def test_patient_split_has_zero_overlap():
    patients = synthetic_patients()
    mapping = split_by_patient(patients, seed=42)
    # Three images per patient: every image must inherit its patient's single split.
    images = pd.DataFrame({"patient": np.repeat(patients["patient"], 3)})
    images["split"] = images["patient"].map(mapping)
    check_no_patient_overlap(images)
    by_split = {
        s: set(images.loc[images["split"] == s, "patient"]) for s in ("train", "val", "test")
    }
    assert not by_split["train"] & by_split["val"]
    assert not by_split["train"] & by_split["test"]
    assert not by_split["val"] & by_split["test"]
    assert set().union(*by_split.values()) == set(patients["patient"])


def test_overlap_check_fails_loudly():
    leaked = pd.DataFrame({"patient": ["a", "a", "b"], "split": ["train", "test", "val"]})
    with pytest.raises(RuntimeError, match="1 patients"):
        check_no_patient_overlap(leaked)


def test_same_seed_gives_same_split_and_other_seed_differs():
    patients = synthetic_patients()
    assert split_by_patient(patients, 42) == split_by_patient(patients, 42)
    assert split_by_patient(patients, 42) != split_by_patient(patients, 7)


def test_split_is_70_15_15_and_stratified():
    patients = synthetic_patients(100)  # 50% positive
    patients["split"] = patients["patient"].map(split_by_patient(patients, seed=42))
    assert patients["split"].value_counts().to_dict() == {"train": 70, "val": 15, "test": 15}
    rates = patients.groupby("split")["label"].mean()
    assert ((rates - 0.5).abs() <= 0.05).all(), rates.to_dict()


@pytest.mark.parametrize("photometric", ["MONOCHROME1", "MONOCHROME2"])
def test_photometric_handling(tmp_path, photometric):
    pixels = np.tile(np.arange(256, dtype=np.uint8), (8, 1))  # known 0..255 gradient
    ds = pydicom.dcmread(write_dicom(tmp_path / "x.dcm", pixels, photometric=photometric))
    out = dicom_to_uint8(ds)
    expected = 255 - pixels if photometric == "MONOCHROME1" else pixels
    assert out.dtype == np.uint8
    np.testing.assert_array_equal(out, expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("52", "50-59"), ("045Y", "40-49"), ("7", "0-9"), ("148", "unknown"), ("", "unknown")],
)
def test_age_bin(raw, expected):
    assert age_bin(raw) == expected


def test_manifest_rows_match_files_on_disk(built):
    out = built["out"]
    manifest = pd.read_csv(out / "manifest.csv")
    on_disk = {p.relative_to(out).as_posix() for p in (out / "images").glob("*.png")}
    assert len(manifest) == N_PATIENTS
    assert set(manifest["path"]) == on_disk
    assert manifest["image_id"].is_unique
    assert list(manifest.columns) == [
        "image_id",
        "path",
        "label",
        "split",
        "view_position",
        "patient_sex",
        "patient_age_bin",
    ]


def test_outputs_contain_no_patient_ids(built):
    text = (built["out"] / "manifest.csv").read_text() + built["report"].read_text()
    assert not any(pid in text for pid in built["patients"])


def test_summary_reports_balance_per_split(built):
    summary = json.loads(built["report"].read_text())
    assert sum(summary["splits"][s]["images"] for s in ("train", "val", "test")) == N_PATIENTS
    for split in summary["splits"].values():
        assert set(split["views"]) <= {"AP", "PA"}


def test_rerun_skips_existing_pngs_and_keeps_manifest(built, tmp_path):
    before = pd.read_csv(built["out"] / "manifest.csv")
    summary = run(
        built["dicom_dir"], built["labels_csv"], built["out"], SIZE, 42, tmp_path / "s.json"
    )
    assert summary["skipped_existing"] == len(before)
    pd.testing.assert_frame_equal(pd.read_csv(built["out"] / "manifest.csv"), before)


@pytest.mark.parametrize("split", ["train", "val", "test"])
def test_dataset_returns_3x224x224_float_tensor(built, split):
    image, label = ChestXrayDataset(built["out"], split)[0]
    assert image.shape == (3, SIZE, SIZE)
    assert image.dtype == torch.float32
    assert label.dtype == torch.long
    # Channels differ after per-channel ImageNet normalisation; undone, they must match.
    mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
    std = torch.tensor(IMAGENET_STD).view(3, 1, 1)
    raw = image * std + mean
    assert torch.allclose(raw[0], raw[1], atol=1e-5) and torch.allclose(raw[1], raw[2], atol=1e-5)


def test_preprocess_dicom_inverts_and_resizes_like_the_pipeline(tmp_path):
    from ml.preprocessing.build_dataset import preprocess_dicom, resize_square

    pixels = np.random.default_rng(3).integers(0, 256, (256, 256)).astype(np.uint8)
    ds = pydicom.dcmread(write_dicom(tmp_path / "m1.dcm", pixels, photometric="MONOCHROME1"))
    out = preprocess_dicom(ds, 224)
    assert out.shape == (224, 224) and out.dtype == np.uint8
    np.testing.assert_array_equal(out, resize_square(255 - pixels, 224))
