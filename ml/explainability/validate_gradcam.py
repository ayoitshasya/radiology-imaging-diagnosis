"""Check whether Grad-CAM heatmaps point at the radiologists' opacity boxes.

Educational use only; not a medical device. Good localisation on this dataset would not
show that the explanations are clinically meaningful.

For every true positive in the chosen split (label 1 and predicted positive at the
threshold picked on validation), the RSNA bounding boxes are the reference and two
scores are computed:

1. mass in box: share of the heatmap's total value that falls inside the boxes
2. pointing game: whether the heatmap's peak pixel lies inside a box

Grad-CAM from the trained model is compared with a uniform heatmap and with Grad-CAM from
a randomly initialised DenseNet121 (no pretraining, no training).

RSNA boxes are keyed by patientId while images are keyed by study UID, so DICOM headers
are read to link the two. That mapping stays in memory and is never written or logged.

Usage:
    python -m ml.explainability.validate_gradcam [--data-dir D] [--manifest F] [--split S]
        [--dicom-dir D] [--labels F] [--checkpoint F] [--report F] [--device cuda]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pydicom
import torch
from matplotlib.figure import Figure
from torch import nn
from tqdm import tqdm

from ml.classification.common import ROOT, build_model, load_config, set_seed
from ml.classification.evaluate import finite_or_none
from ml.explainability.gradcam import compute_heatmap, load_image, load_model, to_input_tensor

METHODS = ("trained", "random_init", "uniform")


def scale_box(
    box: tuple[float, float, float, float], rows: int, cols: int, size: int
) -> tuple[float, float, float, float]:
    """Scale an RSNA box (x, y, width, height in original pixels) to a resized image.

    Returns:
        (x0, y0, x1, y1) in the resized image's pixel coordinates.
    """
    x, y, w, h = box
    sx, sy = size / cols, size / rows
    return x * sx, y * sy, (x + w) * sx, (y + h) * sy


def box_mask(boxes: list[tuple[float, float, float, float]], size: int) -> np.ndarray:
    """Boolean mask of pixels whose centre lies inside any box (union of boxes).

    The pixel-centre rule gives a scaled box a well-defined pixel area without counting
    edge pixels twice.
    """
    centres = np.arange(size) + 0.5
    mask = np.zeros((size, size), dtype=bool)
    for x0, y0, x1, y1 in boxes:
        rows = (centres >= y0) & (centres < y1)
        cols = (centres >= x0) & (centres < x1)
        mask |= rows[:, None] & cols[None, :]
    return mask


def mass_in_box(heatmap: np.ndarray, mask: np.ndarray) -> float:
    """Share of total heatmap value inside the mask; NaN for an all-zero heatmap."""
    total = float(heatmap.sum())
    return float(heatmap[mask].sum()) / total if total > 0 else float("nan")


def pointing_hit(heatmap: np.ndarray, mask: np.ndarray) -> float:
    """1.0 if the heatmap's peak is inside the mask, 0.0 if not, NaN if all zero.

    Ties go to the first peak in row-major order (numpy argmax).
    """
    if float(heatmap.sum()) <= 0:
        return float("nan")
    return float(mask.flat[int(np.argmax(heatmap))])


def mean_ci(values: np.ndarray, n_resamples: int, seed: int) -> dict:
    """Mean with a 95% percentile bootstrap CI over images; NaNs are excluded."""
    values = values[~np.isnan(values)]
    if not len(values):
        return {"mean": None, "ci_low": None, "ci_high": None, "n": 0}
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), (n_resamples, len(values)))].mean(axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    return {
        "mean": finite_or_none(values.mean()),
        "ci_low": finite_or_none(lo),
        "ci_high": finite_or_none(hi),
        "n": int(len(values)),
    }


def summarise(scores: pd.DataFrame, n_resamples: int, seed: int) -> dict:
    """Aggregate per-image scores into per-method means and paired differences."""
    out: dict = {"methods": {}, "paired_differences": {}}
    for method in METHODS:
        out["methods"][method] = {
            "mass_in_box": mean_ci(scores[f"{method}_mass"].to_numpy(), n_resamples, seed),
            "pointing_game": mean_ci(scores[f"{method}_hit"].to_numpy(), n_resamples, seed),
            "median_mass_in_box": finite_or_none(scores[f"{method}_mass"].median()),
        }
    for baseline in ("uniform", "random_init"):
        diff = (scores["trained_mass"] - scores[f"{baseline}_mass"]).to_numpy()
        out["paired_differences"][f"trained_minus_{baseline}_mass"] = mean_ci(
            diff, n_resamples, seed
        ) | {"share_of_images_trained_higher": finite_or_none(np.nanmean(diff > 0))}
    return out


def study_lookup(dicom_dir: Path, wanted: set[str]) -> dict[str, tuple[str, int, int]]:
    """Map study UID to (patient key, rows, columns) by reading DICOM headers only.

    The returned dict is the only place the patient key exists; callers use it to look up
    boxes and must not write or log it.
    """
    found: dict[str, tuple[str, int, int]] = {}
    for path in tqdm(sorted(dicom_dir.glob("*.dcm")), desc="DICOM headers", unit="file"):
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        uid = str(ds.StudyInstanceUID)
        if uid in wanted:
            found[uid] = (path.stem, int(ds.Rows), int(ds.Columns))
            if len(found) == len(wanted):
                break
    if len(found) != len(wanted):
        raise RuntimeError(f"{len(wanted) - len(found)} studies have no DICOM in {dicom_dir}")
    return found


@torch.no_grad()
def predict_probability(model: nn.Module, img: np.ndarray) -> float:
    """Pneumonia probability for one preprocessed image."""
    device = next(model.parameters()).device
    return float(torch.sigmoid(model(to_input_tensor(img).to(device))).item())


def plot_histogram(scores: pd.DataFrame, path: Path) -> None:
    """Histogram of mass-in-box per method. Contains no image pixels."""
    fig = Figure(figsize=(8, 4.5))
    ax = fig.subplots()
    bins = np.linspace(0, 1, 21)
    for method in METHODS:
        ax.hist(scores[f"{method}_mass"].dropna(), bins=bins, alpha=0.5, label=method)
    ax.set(
        xlabel="share of heatmap mass inside RSNA boxes",
        ylabel="true-positive images",
        title="Grad-CAM localisation versus baselines",
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def validate(args: argparse.Namespace, cfg: dict) -> dict:
    """Score every true positive in the split and return the report dictionary."""
    ec = cfg["explainability"]
    seed = cfg["project"]["seed"]
    set_seed(seed)
    manifest = pd.read_csv(args.data_dir / args.manifest)
    rows = manifest[(manifest["split"] == args.split) & (manifest["label"] == 1)]
    print(f"seed={seed} split={args.split} positives={len(rows)} threshold={args.threshold}")

    lookup = study_lookup(args.dicom_dir, set(rows["image_id"]))
    labels = pd.read_csv(args.labels)
    boxes_by_patient = {
        pid: list(g[["x", "y", "width", "height"]].itertuples(index=False, name=None))
        for pid, g in labels[labels["Target"] == 1].groupby("patientId")
    }

    trained = load_model(args.checkpoint, args.device)
    torch.manual_seed(seed)
    random_init = build_model(pretrained=False).to(args.device).eval()

    records, skipped_no_box = [], 0
    for row in tqdm(rows.itertuples(index=False), total=len(rows), desc="Grad-CAM"):
        img = load_image(args.data_dir / row.path)
        if predict_probability(trained, img) < args.threshold:
            continue
        patient, n_rows, n_cols = lookup[row.image_id]
        boxes = boxes_by_patient.get(patient, [])
        if not boxes:
            skipped_no_box += 1
            continue
        mask = box_mask([scale_box(b, n_rows, n_cols, img.shape[0]) for b in boxes], img.shape[0])
        heat_trained = compute_heatmap(trained, img, ec["target_layer"])
        heat_random = compute_heatmap(random_init, img, ec["target_layer"])
        area = float(mask.mean())
        records.append(
            {
                "view_position": row.view_position,
                "box_area_fraction": area,
                "trained_mass": mass_in_box(heat_trained, mask),
                "trained_hit": pointing_hit(heat_trained, mask),
                "random_init_mass": mass_in_box(heat_random, mask),
                "random_init_hit": pointing_hit(heat_random, mask),
                # A flat map's mass in box equals the box area; its peak is undefined, so its
                # pointing score is the expected hit rate of a random peak, also the area.
                "uniform_mass": area,
                "uniform_hit": area,
            }
        )

    scores = pd.DataFrame(records)
    if scores.empty:
        raise RuntimeError("No true positives to evaluate at this threshold")
    n_res = ec["validation"]["bootstrap_resamples"]
    report = {
        "seed": seed,
        "split": args.split,
        "manifest": args.manifest,
        "threshold": args.threshold,
        "threshold_source": "validation split (Youden J), from classification_metrics.json",
        "target_layer": ec["target_layer"],
        "positives_in_split": int(len(rows)),
        "true_positives_scored": int(len(scores)),
        "true_positives_without_boxes": skipped_no_box,
        "trained_all_zero_heatmaps": int(scores["trained_mass"].isna().sum()),
        "random_init_all_zero_heatmaps": int(scores["random_init_mass"].isna().sum()),
        "mean_box_area_fraction": finite_or_none(scores["box_area_fraction"].mean()),
        "overall": summarise(scores, n_res, seed),
        "by_view": {
            str(view): {"n": int(len(g))} | summarise(g, n_res, seed)
            for view, g in scores.groupby("view_position")
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", "utf-8")
    plot_histogram(scores, args.report.with_suffix(".png"))
    return report


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, dict]:
    """Parse arguments; defaults come from config.yaml for the local demo set."""
    cfg = load_config()
    ec, vc = cfg["explainability"], cfg["explainability"]["validation"]
    metrics = json.loads((ROOT / ec["metrics_report"]).read_text(encoding="utf-8"))
    p = argparse.ArgumentParser(description="Validate Grad-CAM localisation on RSNA boxes.")
    p.add_argument("--data-dir", type=Path, default=ROOT / vc["data_dir"])
    p.add_argument("--manifest", default=vc["manifest"], help="CSV name inside --data-dir")
    p.add_argument("--split", default=vc["split"])
    p.add_argument("--dicom-dir", type=Path, default=ROOT / vc["dicom_dir"])
    p.add_argument("--labels", type=Path, default=ROOT / vc["labels"])
    p.add_argument("--checkpoint", type=Path, default=ROOT / ec["checkpoint"])
    p.add_argument("--threshold", type=float, default=metrics["threshold"]["value"])
    p.add_argument("--report", type=Path, default=ROOT / vc["report"])
    p.add_argument("--device", default=cfg["device"])
    return p.parse_args(argv), cfg


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args, cfg = parse_args(argv)
    report = validate(args, cfg)
    o = report["overall"]
    print(
        f"true positives scored: {report['true_positives_scored']} "
        f"of {report['positives_in_split']} positives"
    )
    for method, m in o["methods"].items():
        mb, pg = m["mass_in_box"], m["pointing_game"]
        print(
            f"{method:<12} mass_in_box={mb['mean']} [{mb['ci_low']}, {mb['ci_high']}]  "
            f"pointing={pg['mean']} [{pg['ci_low']}, {pg['ci_high']}]"
        )
    for name, d in o["paired_differences"].items():
        print(
            f"{name}: {d['mean']} [{d['ci_low']}, {d['ci_high']}], "
            f"trained higher on {d['share_of_images_trained_higher']} of images"
        )
    print(f"wrote {args.report} and {args.report.with_suffix('.png')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
