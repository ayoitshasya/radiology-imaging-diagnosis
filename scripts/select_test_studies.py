"""Select sample images that belong to the FULL test split, for leakage-safe demos.

The local 600-image sample was split independently of the full-data split used on Kaggle,
so most sample images were in the full TRAINING set and the full-data model has seen them.
Only sample images in the full test split are safe for Grad-CAM validation and demos.

Known limitation: the sample (download_rsna_sample.py) and the full split
(build_dataset.py) both use seed 42 on the same sorted patient list. The two draws share a
random permutation of the negative class, so all 300 sampled negatives fall in the full
train split and this selection contains positives only. Positives are unaffected because
the split draws them from an already-advanced random state. Fixing it needs a separate
sampling seed and a re-downloaded sample.

Matches the two manifests on image_id (the DICOM StudyInstanceUID), so no patient IDs are
needed. Writes test_studies.csv with paths relative to its own folder and a JSON report
of the counts by label and view.

Usage:
    python scripts/select_test_studies.py [--sample-manifest P] [--full-manifest P]
        [--output P] [--report P]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def select_test_studies(sample: pd.DataFrame, full: pd.DataFrame) -> pd.DataFrame:
    """Return sample rows whose image is in the full test split.

    Args:
        sample: Manifest of the local sample (image_id, path, label, split, view_position).
        full: Manifest of the full dataset with the same columns.

    Returns:
        Sample rows in the full test split, with ``split`` set to the full split and the
        sample's own split kept as ``sample_split``.

    Raises:
        RuntimeError: If a sample image is missing from the full manifest or the two
            manifests disagree on a label, which would mean they describe different data.
    """
    merged = sample.merge(
        full[["image_id", "label", "split"]],
        on="image_id",
        how="left",
        suffixes=("", "_full"),
        validate="one_to_one",
    )
    missing = int(merged["split_full"].isna().sum())
    if missing:
        raise RuntimeError(f"{missing} sample images are not in the full manifest")
    mismatched = int((merged["label"] != merged["label_full"]).sum())
    if mismatched:
        raise RuntimeError(f"{mismatched} images have different labels in the two manifests")

    test = merged[merged["split_full"] == "test"].copy()
    test = test.rename(columns={"split": "sample_split", "split_full": "split"})
    return test[["image_id", "path", "label", "split", "view_position", "sample_split"]]


def summarise(test: pd.DataFrame, n_sample: int) -> dict:
    """Counts by label, view and sample split; contains no identifiers."""
    by_view_label = test.groupby(["view_position", "label"]).size()
    return {
        "sample_images": n_sample,
        "in_full_test_split": len(test),
        "by_label": {str(k): int(v) for k, v in test["label"].value_counts().sort_index().items()},
        "by_view": {str(k): int(v) for k, v in test["view_position"].value_counts().items()},
        "by_view_and_label": {f"{v}_label_{lab}": int(n) for (v, lab), n in by_view_label.items()},
        "by_sample_split": {str(k): int(v) for k, v in test["sample_split"].value_counts().items()},
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; defaults come from the ``demo`` section of config.yaml."""
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["demo"]
    p = argparse.ArgumentParser(description="Select sample images in the full test split.")
    p.add_argument("--sample-manifest", type=Path, default=ROOT / cfg["sample_manifest"])
    p.add_argument("--full-manifest", type=Path, default=ROOT / cfg["full_manifest"])
    p.add_argument("--output", type=Path, default=ROOT / cfg["output"])
    p.add_argument("--report", type=Path, default=ROOT / cfg["report"])
    args = p.parse_args(argv)

    sample = pd.read_csv(args.sample_manifest)
    test = select_test_studies(sample, pd.read_csv(args.full_manifest))

    # Re-root image paths so they resolve relative to the output CSV's own folder.
    sample_dir = args.sample_manifest.resolve().parent
    out_dir = args.output.resolve().parent
    test["path"] = [
        Path(os.path.relpath(sample_dir / rel, out_dir)).as_posix() for rel in test["path"]
    ]
    missing = [rel for rel in test["path"] if not (out_dir / rel).is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} selected images are missing on disk")

    out_dir.mkdir(parents=True, exist_ok=True)
    test.to_csv(args.output, index=False)
    summary = summarise(test, len(sample))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", "utf-8")
    for key, value in summary.items():
        print(f"{key:<20} {value}")
    print(f"wrote {args.output} and {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
