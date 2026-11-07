"""Select sample images that belong to the FULL test split, for leakage-safe demos.

The local 600-image sample was split independently of the full-data split used on Kaggle,
so most sample images were in the full TRAINING set and the full-data model has seen them.
Only images in the full test split are safe for Grad-CAM validation and demos.

Known limitation and what was done about it: the sample (download_rsna_sample.py) and the
full split (build_dataset.py) both used seed 42 on the same sorted patient list. The two
draws shared a random permutation of the negative class, so all 300 sampled negatives fell
in the full train split and the sample alone yields positives only (40). Positives were
unaffected because the split draws them from an already-advanced random state. Rather
than redraw the sample, which would change committed sample reports, 40 extra negatives
(20 AP, 20 PA) from the full test split were added by scripts/select_demo_negatives.py
with a separate seed (demo_negatives.seed in config.yaml). This script now combines both
sources. The sample itself is unchanged and its seed coupling remains.

Matches manifests on image_id (the DICOM StudyInstanceUID), so no patient IDs are needed.
Writes test_studies.csv with paths relative to its own folder, a ``source`` column naming
the input each row came from, and a JSON report of counts by label, view and source.

Usage:
    python scripts/select_test_studies.py [--sample-manifests P [P ...]]
        [--full-manifest P] [--output P] [--report P]
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
COLUMNS = ["image_id", "path", "label", "split", "view_position", "source"]


def select_test_studies(sample: pd.DataFrame, full: pd.DataFrame) -> pd.DataFrame:
    """Return rows whose image is in the full test split.

    Args:
        sample: Combined local manifests (image_id, path, label, view_position, source).
        full: Manifest of the full dataset.

    Returns:
        Rows in the full test split, with ``split`` taken from the full manifest.

    Raises:
        RuntimeError: If an image is missing from the full manifest or the manifests
            disagree on a label, which would mean they describe different data.
        pandas.errors.MergeError: If an image_id appears twice in the local manifests.
    """
    merged = sample.drop(columns=["split"], errors="ignore").merge(
        full[["image_id", "label", "split"]],
        on="image_id",
        how="left",
        suffixes=("", "_full"),
        validate="one_to_one",
    )
    missing = int(merged["split"].isna().sum())
    if missing:
        raise RuntimeError(f"{missing} local images are not in the full manifest")
    mismatched = int((merged["label"] != merged["label_full"]).sum())
    if mismatched:
        raise RuntimeError(f"{mismatched} images have different labels in the manifests")
    return merged[merged["split"] == "test"][COLUMNS].reset_index(drop=True)


def load_manifests(paths: list[Path], out_dir: Path) -> pd.DataFrame:
    """Read each manifest, re-root its image paths to ``out_dir`` and tag its source.

    Each manifest's paths are relative to its own folder, so they are rewritten relative
    to the output CSV's folder before the manifests are combined.
    """
    frames = []
    for path in paths:
        df = pd.read_csv(path)
        base = path.resolve().parent
        df["path"] = [Path(os.path.relpath(base / rel, out_dir)).as_posix() for rel in df["path"]]
        df["source"] = base.name
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def summarise(test: pd.DataFrame, n_local: int) -> dict:
    """Counts by label, view and source; contains no identifiers."""
    by_view_label = test.groupby(["view_position", "label"]).size()
    by_source_label = test.groupby(["source", "label"]).size()
    return {
        "local_images": n_local,
        "in_full_test_split": len(test),
        "by_label": {str(k): int(v) for k, v in test["label"].value_counts().sort_index().items()},
        "by_view": {str(k): int(v) for k, v in test["view_position"].value_counts().items()},
        "by_view_and_label": {f"{v}_label_{lab}": int(n) for (v, lab), n in by_view_label.items()},
        "by_source_and_label": {
            f"{s}_label_{lab}": int(n) for (s, lab), n in by_source_label.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; defaults come from the ``demo`` section of config.yaml."""
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["demo"]
    p = argparse.ArgumentParser(description="Select local images in the full test split.")
    p.add_argument(
        "--sample-manifests",
        type=Path,
        nargs="+",
        default=[ROOT / m for m in cfg["sample_manifests"]],
    )
    p.add_argument("--full-manifest", type=Path, default=ROOT / cfg["full_manifest"])
    p.add_argument("--output", type=Path, default=ROOT / cfg["output"])
    p.add_argument("--report", type=Path, default=ROOT / cfg["report"])
    args = p.parse_args(argv)

    out_dir = args.output.resolve().parent
    local = load_manifests(args.sample_manifests, out_dir)
    test = select_test_studies(local, pd.read_csv(args.full_manifest))
    missing = [rel for rel in test["path"] if not (out_dir / rel).is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} selected images are missing on disk")

    out_dir.mkdir(parents=True, exist_ok=True)
    test.to_csv(args.output, index=False)
    summary = summarise(test, len(local))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", "utf-8")
    for key, value in summary.items():
        print(f"{key:<20} {value}")
    print(f"wrote {args.output} and {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
