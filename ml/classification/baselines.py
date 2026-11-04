"""Shortcut and trivial baselines on the test split, for comparison with the model.

- View-only: scores each image by the positive rate of its ViewPosition in the train
  split. Because AP films are more often positive, this measures how much of the task
  the view shortcut alone solves.
- Majority class: predicts the train split's most common class for every image.

Uses only the manifest; no model or images are loaded.

Usage:
    python -m ml.classification.baselines [--data-dir DIR] [--smoke-test]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ml.classification.common import ROOT, load_config
from ml.classification.evaluate import auroc, bootstrap_ci, fmt, sensitivity, specificity


def view_only_scores(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, dict]:
    """Score test images by their view's positive rate in the train split.

    A view absent from train gets the overall train positive rate.

    Returns:
        (test scores, train positive rate per view).
    """
    rates = train.groupby("view_position")["label"].mean()
    fallback = float(train["label"].mean())
    scores = test["view_position"].map(rates).fillna(fallback).to_numpy(dtype=float)
    return scores, {str(k): round(float(v), 4) for k, v in rates.items()}


def majority_class(train: pd.DataFrame) -> int:
    """Most common train label; ties go to 0 (no pneumonia), the conservative default."""
    counts = train["label"].value_counts()
    return int(counts.idxmax()) if counts.get(1, 0) != counts.get(0, 0) else 0


def run_baselines(manifest: pd.DataFrame, n_resamples: int, level: float, seed: int) -> dict:
    """Compute both baselines on the test split with bootstrap CIs."""
    train = manifest[manifest["split"] == "train"]
    test = manifest[manifest["split"] == "test"]
    y = test["label"].to_numpy()

    scores, rates = view_only_scores(train, test)
    view_only = {
        "description": "score = train-split positive rate of the image's view position",
        "train_positive_rate_by_view": rates,
        "test": bootstrap_ci(y, scores, 0.5, {"auroc": auroc}, n_resamples, level, seed),
    }

    majority = majority_class(train)
    constant = np.full(len(y), float(majority))
    majority_baseline = {
        "description": "predict the train split's majority class for every image",
        "predicted_class": majority,
        # A constant score cannot rank cases, so AUROC is 0.5 by definition.
        "test_auroc": 0.5,
        "test_accuracy": round(float((y == majority).mean()), 4),
        "test_sensitivity": round(sensitivity(y, constant, 0.5), 4),
        "test_specificity": round(specificity(y, constant, 0.5), 4),
        "note": "accuracy shown only to illustrate why it misleads; see evaluate.py",
    }
    return {
        "seed": seed,
        "bootstrap": {"resamples": n_resamples, "ci_level": level},
        "test_n": int(len(y)),
        "test_prevalence": round(float(y.mean()), 4),
        "view_only": view_only,
        "majority_class": majority_baseline,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Shortcut and trivial baselines on test.")
    p.add_argument("--data-dir", type=Path)
    p.add_argument("--smoke-test", action="store_true", help="write to reports/smoke")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    cfg = load_config()
    cc, ec = cfg["classification"], cfg["evaluation"]
    data_dir = args.data_dir or ROOT / cc["data_dir"]
    seed = cfg["project"]["seed"]
    result = run_baselines(
        pd.read_csv(data_dir / "manifest.csv"), ec["bootstrap_resamples"], ec["ci_level"], seed
    )
    out_dir = ROOT / cc["reports_dir"] / ("smoke" if args.smoke_test else "")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "baselines.json"
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    v = result["view_only"]["test"]["auroc"]
    print(f"seed={seed} test n={result['test_n']} prevalence={result['test_prevalence']}")
    print(f"view-only AUROC={fmt(v['value'])} [{fmt(v['ci_low'])}, {fmt(v['ci_high'])}]")
    print(
        f"majority class={result['majority_class']['predicted_class']} "
        f"accuracy={result['majority_class']['test_accuracy']:.3f} AUROC=0.5"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
