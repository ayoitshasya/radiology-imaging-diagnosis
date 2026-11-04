"""Build a preprocessed, patient-split PNG dataset from RSNA DICOMs.

Turns a folder of ``<patientId>.dcm`` files plus ``stage_2_train_labels.csv`` into:

- ``<output>/images/<StudyInstanceUID>.png``: 8-bit grayscale, resized square images
- ``<output>/manifest.csv``: image_id, path, label, split, view_position, patient_sex,
  patient_age_bin
- a JSON summary (default ``reports/preprocessing_summary.json``) with label and view
  balance per split

The script is self-contained (no project imports, paths only from arguments) so it runs
unchanged locally and in a Kaggle notebook. Patient IDs are used in memory for the split
only; they are never written to the manifest, the summary or any log line. The study UID
is the image identifier, as required by the project data rules.

Usage:
    python ml/preprocessing/build_dataset.py --input <dicom dir> --labels <labels csv>
        --output <out dir> [--size 224] [--seed 42]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pydicom
from pydicom.pixels import apply_voi_lut
from sklearn.model_selection import train_test_split
from tqdm import tqdm

SPLITS = ("train", "val", "test")
MAX_PLAUSIBLE_AGE = 100


def dicom_to_uint8(ds: pydicom.Dataset) -> np.ndarray:
    """Convert DICOM pixels to an 8-bit image where higher values are brighter.

    Applies the VOI LUT or window if the header has one, so values match what a viewer
    would display. Non-8-bit results are min-max scaled to 0-255. MONOCHROME1 images
    store bright as low values, so they are inverted after scaling to keep one polarity
    across the dataset; otherwise the model would see some images as negatives.

    Args:
        ds: A DICOM dataset with pixel data.

    Returns:
        A 2D ``uint8`` array.
    """
    arr = apply_voi_lut(ds.pixel_array, ds)
    if arr.dtype != np.uint8:
        # Limitation: per-image min-max scaling discards absolute intensity, which is
        # acceptable for X-ray classification but would not be for calibrated modalities.
        arr = arr.astype(np.float64)
        lo, hi = arr.min(), arr.max()
        arr = np.zeros_like(arr) if hi == lo else (arr - lo) / (hi - lo) * 255.0
        arr = np.round(arr).astype(np.uint8)
    if ds.PhotometricInterpretation == "MONOCHROME1":
        arr = 255 - arr
    return arr


def resize_square(img: np.ndarray, size: int) -> np.ndarray:
    """Resize to ``size`` x ``size`` with area interpolation.

    Area interpolation averages source pixels when shrinking, which avoids the aliasing
    that nearest or bilinear resizing produces on 1024 to 224 downsampling.
    """
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)


def age_bin(age: object) -> str:
    """Bin a DICOM PatientAge value into decades such as ``"50-59"``.

    Decades instead of exact ages keep the manifest less identifying while still allowing
    subgroup checks. Non-numeric or implausible ages (over 100) become ``"unknown"``.
    """
    text = str(age).strip().upper().rstrip("Y")
    if not text.isdigit() or int(text) > MAX_PLAUSIBLE_AGE:
        return "unknown"
    lo = int(text) // 10 * 10
    return f"{lo}-{lo + 9}"


def split_by_patient(patients: pd.DataFrame, seed: int) -> dict[str, str]:
    """Assign each patient to train, val or test (70/15/15), stratified on label.

    Splitting patients rather than images guarantees no patient appears in two splits, so
    validation and test scores measure performance on unseen people.

    Args:
        patients: One row per patient with columns ``patient`` and ``label``.
        seed: Random seed for both stratified splits.

    Returns:
        Mapping from patient key to split name.
    """
    train, rest = train_test_split(
        patients, test_size=0.30, stratify=patients["label"], random_state=seed
    )
    val, test = train_test_split(rest, test_size=0.50, stratify=rest["label"], random_state=seed)
    mapping: dict[str, str] = {}
    for name, part in zip(SPLITS, (train, val, test), strict=True):
        mapping.update(dict.fromkeys(part["patient"], name))
    return mapping


def check_no_patient_overlap(df: pd.DataFrame) -> None:
    """Raise if any patient key occurs in more than one split.

    Uses an exception rather than ``assert`` because asserts are stripped under
    ``python -O`` and this check must never be skipped.

    Raises:
        RuntimeError: If any patient is in more than one split (the IDs are not shown).
    """
    splits_per_patient = df.groupby("patient")["split"].nunique()
    leaked = int((splits_per_patient > 1).sum())
    if leaked:
        raise RuntimeError(f"Patient leakage: {leaked} patients appear in more than one split")


def png_is_valid(path: Path, size: int) -> bool:
    """Return True if ``path`` is a readable grayscale PNG of the expected size."""
    if not path.is_file():
        return False
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    return img is not None and img.shape == (size, size)


def build_summary(df: pd.DataFrame, size: int, seed: int, counts: dict[str, int]) -> dict:
    """Aggregate label and view balance per split; contains no identifiers."""
    summary: dict = {"seed": seed, "size": size, **counts, "splits": {}}
    for name in SPLITS:
        part = df[df["split"] == name]
        views = {}
        for view, grp in part.groupby("view_position"):
            views[str(view)] = {
                "images": len(grp),
                "positive": int(grp["label"].sum()),
                "positive_rate": round(float(grp["label"].mean()), 4),
            }
        summary["splits"][name] = {
            "images": len(part),
            "patients": int(part["patient"].nunique()),
            "positive": int(part["label"].sum()),
            "negative": int((part["label"] == 0).sum()),
            "positive_rate": round(float(part["label"].mean()), 4),
            "views": views,
        }
    return summary


def run(
    input_dir: Path, labels_csv: Path, output_dir: Path, size: int, seed: int, report_path: Path
) -> dict:
    """Run the full pipeline and return the summary dictionary."""
    print(f"seed={seed} size={size}")
    labels = pd.read_csv(labels_csv).groupby("patientId")["Target"].max()
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    rows, skipped_existing, unlabeled = [], 0, 0
    for dcm_path in tqdm(sorted(input_dir.glob("*.dcm")), desc="DICOMs", unit="img"):
        patient = dcm_path.stem
        if patient not in labels.index:
            unlabeled += 1
            continue
        ds = pydicom.dcmread(dcm_path, stop_before_pixels=True)
        image_id = str(ds.StudyInstanceUID)
        png_path = images_dir / f"{image_id}.png"
        if png_is_valid(png_path, size):
            skipped_existing += 1
        else:
            img = resize_square(dicom_to_uint8(pydicom.dcmread(dcm_path)), size)
            if not cv2.imwrite(str(png_path), img):
                raise OSError(f"Could not write PNG for image_id {image_id}")
        rows.append(
            {
                "patient": patient,
                "image_id": image_id,
                "path": png_path.relative_to(output_dir).as_posix(),
                "label": int(labels[patient]),
                "view_position": str(ds.get("ViewPosition", "unknown")),
                "patient_sex": str(ds.get("PatientSex", "unknown")),
                "patient_age_bin": age_bin(ds.get("PatientAge", "")),
            }
        )

    df = pd.DataFrame(rows)
    if df["image_id"].duplicated().any():
        raise RuntimeError("Duplicate StudyInstanceUID values; image_id would not be unique")
    patients = df.groupby("patient", as_index=False)["label"].max()
    df["split"] = df["patient"].map(split_by_patient(patients, seed))
    check_no_patient_overlap(df)

    counts = {"images": len(df), "skipped_existing": skipped_existing, "unlabeled": unlabeled}
    summary = build_summary(df, size, seed, counts)
    columns = [
        "image_id",
        "path",
        "label",
        "split",
        "view_position",
        "patient_sex",
        "patient_age_bin",
    ]
    df[columns].to_csv(output_dir / "manifest.csv", index=False)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    for name in SPLITS:
        s = summary["splits"][name]
        print(
            f"{name:<5} images={s['images']} positive_rate={s['positive_rate']} "
            f"views={ {v: d['images'] for v, d in s['views'].items()} }"
        )
    print(f"skipped existing PNGs: {skipped_existing}; DICOMs without labels: {unlabeled}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", type=Path, required=True, help="folder of <patientId>.dcm")
    p.add_argument("--labels", type=Path, required=True, help="stage_2_train_labels.csv")
    p.add_argument("--output", type=Path, required=True, help="output folder")
    p.add_argument("--size", type=int, default=224, help="square output size in pixels")
    p.add_argument("--seed", type=int, default=42, help="seed for the patient split")
    p.add_argument(
        "--report",
        type=Path,
        default=Path("reports/preprocessing_summary.json"),
        help="where to write the JSON summary",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    run(args.input, args.labels, args.output, args.size, args.seed, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
