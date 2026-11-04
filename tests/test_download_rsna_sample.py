"""Tests for the sampling and validation logic in scripts/download_rsna_sample.py."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_rsna_sample.py"
_spec = importlib.util.spec_from_file_location("download_rsna_sample", SCRIPT)
drs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drs)


def make_labels(n_pos: int, n_neg: int, boxes_per_pos: int = 2) -> pd.DataFrame:
    """Synthetic labels with several box rows per positive patient, as in RSNA."""
    rows = [{"patientId": f"pos{i:03d}", "Target": 1} for i in range(n_pos)] * boxes_per_pos
    rows += [{"patientId": f"neg{i:03d}", "Target": 0} for i in range(n_neg)]
    return pd.DataFrame(rows)


def test_one_row_per_patient_removes_box_duplicates():
    patients = drs.one_row_per_patient(make_labels(5, 7, boxes_per_pos=3))
    assert len(patients) == 12
    assert patients["patientId"].is_unique


def test_stratified_sample_is_balanced_unique_and_reproducible():
    patients = drs.one_row_per_patient(make_labels(50, 80))
    a = drs.stratified_sample(patients, per_class=10, seed=42)
    b = drs.stratified_sample(patients, per_class=10, seed=42)
    assert a["Target"].value_counts().to_dict() == {0: 10, 1: 10}
    assert a["patientId"].is_unique
    pd.testing.assert_frame_equal(a, b)


def test_stratified_sample_rejects_too_small_class():
    patients = drs.one_row_per_patient(make_labels(3, 80))
    with pytest.raises(ValueError):
        drs.stratified_sample(patients, per_class=10, seed=42)


def test_is_valid_dicom_rejects_missing_and_truncated(tmp_path):
    assert not drs.is_valid_dicom(tmp_path / "missing.dcm")
    truncated = tmp_path / "truncated.dcm"
    truncated.write_bytes(b"\x00" * 128 + b"DICM" + b"\x00" * 16)
    assert not drs.is_valid_dicom(truncated)
