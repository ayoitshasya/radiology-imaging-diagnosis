"""Download a reproducible, class-balanced sample of RSNA Pneumonia DICOMs.

Reads the stage 2 training labels, picks ``per_class`` unique patients with
Target=1 and ``per_class`` with Target=0, writes the selection to
``sample_manifest.csv`` and downloads only those DICOM files from Kaggle.

Requires the label CSVs to already be in the sample directory and the
KAGGLE_API_TOKEN environment variable to be set. Patient IDs are written
to the manifest only; they are never printed.

Usage:
    python scripts/download_rsna_sample.py
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import pydicom
import yaml
from tqdm import tqdm

if TYPE_CHECKING:
    from kaggle.api.kaggle_api_extended import KaggleApi

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    """Load the project config from the repository root."""
    with open(ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def one_row_per_patient(labels: pd.DataFrame) -> pd.DataFrame:
    """Collapse the labels table from one row per box to one row per patient.

    Positive patients have one row per opacity bounding box, so sampling the
    raw rows would favour patients with many boxes. Target is constant per
    patient, so taking the max is lossless.

    Args:
        labels: Rows of ``stage_2_train_labels.csv``.

    Returns:
        DataFrame with columns ``patientId`` and ``Target``, sorted by
        ``patientId`` so the sample does not depend on CSV row order.
    """
    return labels.groupby("patientId", as_index=False)["Target"].max()


def stratified_sample(patients: pd.DataFrame, per_class: int, seed: int) -> pd.DataFrame:
    """Draw ``per_class`` patients from each Target class with a fixed seed.

    A balanced sample makes the exploration plots show both classes equally;
    it does not reflect the real prevalence (about 23% positive in stage 2).

    Args:
        patients: One row per patient, as from :func:`one_row_per_patient`.
        per_class: Number of patients to draw for each Target value.
        seed: Random seed passed to pandas so the draw is reproducible.

    Returns:
        The sampled patients, sorted by ``patientId``.

    Raises:
        ValueError: If a class has fewer than ``per_class`` patients.
    """
    parts = []
    for target in (0, 1):
        pool = patients[patients["Target"] == target]
        if len(pool) < per_class:
            raise ValueError(f"Target={target} has {len(pool)} patients, need {per_class}")
        parts.append(pool.sample(n=per_class, random_state=seed))
    return pd.concat(parts).sort_values("patientId").reset_index(drop=True)


def is_valid_dicom(path: Path) -> bool:
    """Return True if ``path`` is a DICOM whose pixel data fully decodes.

    Decoding the pixels (not just the header) catches files truncated by an
    interrupted download, which would otherwise be skipped as present.
    """
    if not path.is_file():
        return False
    try:
        _ = pydicom.dcmread(path).pixel_array
        return True
    except Exception:  # noqa: BLE001 - any read or decode error means invalid
        return False


def download_one(
    api: KaggleApi,
    competition: str,
    remote: str,
    dest_dir: Path,
    target: Path,
    max_retries: int,
) -> bool:
    """Download one competition file, retrying with exponential backoff.

    The Kaggle API returns None and writes to ``dest_dir/<remote path>``, so
    success is judged by decoding the resulting file.
    """
    for attempt in range(max_retries):
        try:
            api.competition_download_file(competition, remote, path=str(dest_dir), quiet=True)
            if is_valid_dicom(target):
                return True
        except Exception:  # noqa: BLE001 - network and API errors are retried
            pass
        target.unlink(missing_ok=True)
        time.sleep(2**attempt)
    return False


def dir_size_mb(path: Path) -> float:
    """Total size of all files under ``path`` in megabytes."""
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def main() -> int:
    cfg = load_config()
    rs = cfg["rsna_sample"]
    seed = cfg["project"]["seed"]
    sample_dir = ROOT / rs["dir"]
    images_dir = sample_dir / rs["images_subdir"]

    free_gb = shutil.disk_usage(sample_dir).free / 1e9
    print(f"Free disk: {free_gb:.1f} GB (minimum {rs['min_free_gb']} GB)")
    if free_gb < rs["min_free_gb"]:
        print("Not enough free disk space; aborting.")
        return 1

    labels = pd.read_csv(sample_dir / rs["labels_csv"])
    class_info = pd.read_csv(sample_dir / rs["class_info_csv"]).drop_duplicates("patientId")
    sample = stratified_sample(one_row_per_patient(labels), rs["per_class"], seed)
    sample = sample.merge(class_info, on="patientId", how="left")
    sample.to_csv(sample_dir / "sample_manifest.csv", index=False)
    print(
        f"seed={seed}; sampled {len(sample)} patients "
        f"({(sample.Target == 1).sum()} positive, {(sample.Target == 0).sum()} negative)"
    )

    # Imported here because the kaggle package authenticates on import.
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()

    skipped, failed_rows = 0, []
    for row, pid in enumerate(tqdm(sample["patientId"], desc="DICOMs", unit="file")):
        target = images_dir / f"{pid}.dcm"
        if is_valid_dicom(target):
            skipped += 1
            continue
        remote = f"{rs['images_subdir']}/{pid}.dcm"
        if not download_one(api, rs["competition"], remote, sample_dir, target, rs["max_retries"]):
            failed_rows.append(row)

    n_files = sum(1 for _ in images_dir.glob("*.dcm"))
    print(f"Skipped (already present): {skipped}")
    print(f"Failed: {len(failed_rows)} (manifest rows: {failed_rows})")
    print(f"DICOMs on disk: {n_files}; sample folder size: {dir_size_mb(sample_dir):.1f} MB")
    return 1 if failed_rows else 0


if __name__ == "__main__":
    sys.exit(main())
