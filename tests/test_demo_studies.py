"""Tests for the leakage-safe demo set: selection logic and the committed demo CSV."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_CSV = ROOT / "data" / "demo" / "test_studies.csv"
FULL_MANIFEST = ROOT / "data" / "processed" / "full" / "manifest.csv"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sts = load_script("select_test_studies")
sdn = load_script("select_demo_negatives")


@pytest.mark.needs_dvc  # reads the DVC-tracked demo CSV and full manifest
def test_no_demo_study_is_in_full_train_or_val_split():
    demo = pd.read_csv(DEMO_CSV)
    split = pd.read_csv(FULL_MANIFEST).set_index("image_id")["split"]
    assert demo["image_id"].isin(split.index).all(), "demo study missing from full manifest"
    full_splits = split.loc[demo["image_id"]]
    assert not full_splits.isin(["train", "val"]).any()
    assert (full_splits == "test").all()
    assert set(demo["label"]) == {0, 1}, "demo set should contain both negatives and positives"


def full_manifest() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "image_id": ["a", "b", "c", "d"],
            "label": [1, 0, 0, 1],
            "split": ["test", "test", "train", "val"],
        }
    )


def local(ids, labels) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "image_id": ids,
            "path": [f"images/{i}.png" for i in ids],
            "label": labels,
            "split": "train",
            "view_position": "AP",
            "source": "s",
        }
    )


def test_selector_keeps_only_full_test_rows_with_full_split():
    out = sts.select_test_studies(local(["a", "b", "c", "d"], [1, 0, 0, 1]), full_manifest())
    assert list(out["image_id"]) == ["a", "b"]
    assert set(out["split"]) == {"test"}
    assert list(out.columns) == sts.COLUMNS


def test_selector_fails_loudly_on_bad_input():
    with pytest.raises(RuntimeError, match="different labels"):
        sts.select_test_studies(local(["a"], [0]), full_manifest())
    with pytest.raises(RuntimeError, match="not in the full manifest"):
        sts.select_test_studies(local(["zz"], [0]), full_manifest())
    with pytest.raises(pd.errors.MergeError):
        sts.select_test_studies(local(["a", "a"], [1, 1]), full_manifest())


def test_split_reproduction_check_detects_mismatch():
    labels = pd.DataFrame(
        {"patientId": [f"p{i:03d}" for i in range(40)], "Target": [i % 2 for i in range(40)]}
    )
    patients = sdn.reproduce_full_split(labels, seed=42)
    manifest = patients.rename(columns={"patient": "image_id"})
    sdn.check_reproduction(patients, manifest)  # identical counts: no error
    shifted = manifest.copy()
    shifted.loc[shifted.index[0], "split"] = "val" if shifted.iloc[0]["split"] != "val" else "test"
    with pytest.raises(RuntimeError, match="does not match"):
        sdn.check_reproduction(patients, shifted)
