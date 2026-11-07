"""Download negative studies from the FULL test split for leakage-safe demos.

The 600-image sample has no negatives in the full test split: download_rsna_sample.py and
build_dataset.py both used seed 42 on the same sorted patient list, so every sampled
negative went to the full train split. This script adds ``per_view`` AP and ``per_view``
PA negatives that the full-data model never trained on, without changing the sample.

The full manifest is keyed by study UID and has no patient key, but Kaggle files are
named by patientId. So the full split is reproduced in memory with the same function and
seed, checked against the manifest's split-by-label counts, and every downloaded file is
then verified by its study UID against the manifest. Patient IDs exist only in memory,
in the DVC-tracked ids file, and as DICOM file names under data/raw; they are never
printed or written to reports.

A view is only known once the DICOM header is downloaded, so candidates are downloaded in
batches and a file whose view quota is already full is deleted straight away.

Usage:
    python scripts/select_demo_negatives.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pydicom
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.preprocessing.build_dataset import split_by_patient  # noqa: E402

VIEWS = ("AP", "PA")


def load_downloader():
    """Import scripts/download_rsna_sample.py, which is not a package module."""
    spec = importlib.util.spec_from_file_location(
        "download_rsna_sample", Path(__file__).parent / "download_rsna_sample.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reproduce_full_split(labels: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Recompute the full-data split per patient, exactly as build_dataset.py did.

    Returns:
        One row per patient with columns ``patient``, ``label`` and ``split``.
    """
    patients = (
        labels.groupby("patientId", as_index=False)["Target"]
        .max()
        .rename(columns={"patientId": "patient", "Target": "label"})
    )
    patients["split"] = patients["patient"].map(split_by_patient(patients, seed))
    return patients


def check_reproduction(patients: pd.DataFrame, full_manifest: pd.DataFrame) -> None:
    """Raise unless split-by-label counts match the full manifest exactly.

    Raises:
        RuntimeError: If the reproduced split differs from the one used on Kaggle.
    """
    ours = patients.groupby(["split", "label"]).size()
    theirs = full_manifest.groupby(["split", "label"]).size()
    if not ours.equals(theirs):
        raise RuntimeError(f"Reproduced split does not match the full manifest:\n{ours}\n{theirs}")


def main() -> int:
    """Select, download and verify the demo negatives; write the ids file and a report."""
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    rs, dn = cfg["rsna_sample"], cfg["demo_negatives"]
    split_seed, demo_seed = cfg["project"]["seed"], dn["seed"]
    if demo_seed == split_seed:
        raise ValueError("demo_negatives.seed must differ from the split seed")
    print(f"split seed={split_seed} demo seed={demo_seed}")

    labels = pd.read_csv(ROOT / rs["dir"] / rs["labels_csv"])
    full = pd.read_csv(ROOT / cfg["demo"]["full_manifest"])
    patients = reproduce_full_split(labels, split_seed)
    check_reproduction(patients, full)
    print("reproduced full split matches the manifest's split x label counts")

    in_sample = set(pd.read_csv(ROOT / rs["dir"] / "sample_manifest.csv")["patientId"])
    pool = patients[
        (patients["split"] == "test")
        & (patients["label"] == 0)
        & ~patients["patient"].isin(in_sample)
    ]
    order = np.random.default_rng(demo_seed).permutation(sorted(pool["patient"]))
    print(f"candidate full-test negatives not in the sample: {len(order)}")

    by_uid = full.set_index("image_id")
    out_dir = ROOT / dn["dir"]
    images_dir = out_dir / rs["images_subdir"]
    downloader = load_downloader()
    accepted: dict[str, list[str]] = {v: [] for v in VIEWS}
    stats = {"downloaded": 0, "discarded_view_quota_full": 0, "failed_download": 0}

    pos = 0
    while any(len(accepted[v]) < dn["per_view"] for v in VIEWS):
        if pos >= len(order):
            raise RuntimeError("Ran out of candidates before filling both view quotas")
        batch = list(order[pos : pos + dn["batch_size"]])
        pos += len(batch)
        _, failed_rows = downloader.download_ids(batch, out_dir, rs)
        stats["failed_download"] += len(failed_rows)
        for row, pid in enumerate(batch):
            if row in failed_rows:
                continue
            path = images_dir / f"{pid}.dcm"
            stats["downloaded"] += 1
            ds = pydicom.dcmread(path, stop_before_pixels=True)
            uid, view = str(ds.StudyInstanceUID), str(ds.ViewPosition)
            if (
                uid not in by_uid.index
                or by_uid.at[uid, "split"] != "test"
                or by_uid.at[uid, "label"] != 0
            ):
                raise RuntimeError("A downloaded study is not a negative in the full test split")
            if view in accepted and len(accepted[view]) < dn["per_view"]:
                accepted[view].append(pid)
            else:
                path.unlink()
                stats["discarded_view_quota_full"] += 1

    chosen = sorted(accepted["AP"] + accepted["PA"])
    pd.DataFrame({"patientId": chosen, "Target": 0}).to_csv(out_dir / dn["ids_file"], index=False)
    on_disk = sorted(p.stem for p in images_dir.glob("*.dcm"))
    if on_disk != chosen:
        raise RuntimeError("Files on disk do not match the accepted negatives")

    report = {
        "split_seed": split_seed,
        "demo_seed": demo_seed,
        "candidates": int(len(order)),
        "candidates_tried": int(pos),
        **stats,
        "accepted_by_view": {v: len(accepted[v]) for v in VIEWS},
        "accepted_total": len(chosen),
        "all_verified_full_test_negatives": True,
    }
    report_path = ROOT / dn["report"]
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", "utf-8")
    for key, value in report.items():
        print(f"{key:<34} {value}")
    print(f"wrote {out_dir / dn['ids_file']} and {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
