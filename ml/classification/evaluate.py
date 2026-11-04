"""Evaluate a trained classifier on the test split, overall and per view position.

Educational use only; not a medical device. These numbers describe a model on one public
dataset and say nothing about clinical performance.

The decision threshold is chosen on the validation split (Youden's J) and applied
unchanged to the test split. Nothing is tuned on test.

Usage:
    python -m ml.classification.evaluate [--checkpoint PATH] [--data-dir DIR]
        [--device cuda] [--smoke-test]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import torch
from matplotlib.figure import Figure
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)

from ml.classification.common import (
    ROOT,
    build_model,
    load_config,
    make_loader,
    num_workers_for_platform,
    predict,
    resolve_device,
)
from ml.classification.train import CHECKPOINT_NAME
from ml.preprocessing.dataset import ChestXrayDataset

# Accuracy is not reported as a headline metric. On imbalanced medical data it rewards
# the majority class: with 22.5% pneumonia prevalence in the full RSNA labels
# (positive_fraction in reports/data_exploration.json), a model that
# never predicts pneumonia is 77.5% accurate while missing every patient who has it.
# Sensitivity (missed disease), specificity (false alarms), precision and the
# threshold-free AUROC describe the trade-offs that matter.

Metric = Callable[[np.ndarray, np.ndarray, float], float]
VIEWS = ("AP", "PA")


def youden_threshold(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Threshold maximising Youden's J = sensitivity + specificity - 1.

    J weighs missed pneumonia and false alarms equally, a neutral default when no
    clinical cost ratio is defined. Call this on validation data only.
    """
    fpr, tpr, thresholds = roc_curve(y_true, scores)
    finite = np.isfinite(thresholds)  # roc_curve prepends +inf, which predicts nothing
    best = np.argmax((tpr - fpr)[finite])
    return float(thresholds[finite][best])


def _safe_ratio(num: int, den: int) -> float:
    return num / den if den else float("nan")


def auroc(y: np.ndarray, p: np.ndarray, _thr: float) -> float:
    """AUROC; NaN when only one class is present."""
    return float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else float("nan")


def sensitivity(y: np.ndarray, p: np.ndarray, thr: float) -> float:
    """True positive rate: share of pneumonia cases the model flags."""
    pred = p >= thr
    return _safe_ratio(int((pred & (y == 1)).sum()), int((y == 1).sum()))


def specificity(y: np.ndarray, p: np.ndarray, thr: float) -> float:
    """True negative rate: share of non-pneumonia cases the model clears."""
    pred = p >= thr
    return _safe_ratio(int((~pred & (y == 0)).sum()), int((y == 0).sum()))


def precision(y: np.ndarray, p: np.ndarray, thr: float) -> float:
    """Share of flagged cases that truly have pneumonia."""
    pred = p >= thr
    return _safe_ratio(int((pred & (y == 1)).sum()), int(pred.sum()))


METRICS: dict[str, Metric] = {
    "auroc": auroc,
    "sensitivity": sensitivity,
    "specificity": specificity,
    "precision": precision,
}


def finite_or_none(x: float, ndigits: int = 4) -> float | None:
    """Round ``x``, or return None if it is NaN, so reports stay valid JSON.

    An undefined metric (e.g. precision when nothing is flagged) becomes JSON null rather
    than NaN, which strict JSON parsers reject.
    """
    return None if np.isnan(x) else round(float(x), ndigits)


def fmt(x: float | None) -> str:
    """Format a metric for console output; None prints as n/a."""
    return "n/a" if x is None else f"{x:.3f}"


def bootstrap_ci(
    y: np.ndarray,
    p: np.ndarray,
    thr: float,
    metrics: dict[str, Metric],
    n_resamples: int,
    level: float,
    seed: int,
) -> dict[str, dict[str, float | None]]:
    """Point estimate and percentile bootstrap CI for each metric at a fixed threshold.

    Resamples cases with replacement. Resamples where a metric is undefined (for example
    no positives, so no sensitivity) are skipped and counted in ``n_valid``; undefined
    values are reported as None.

    Args:
        y: Binary labels.
        p: Predicted probabilities.
        thr: Decision threshold, fixed beforehand on validation data.
        metrics: Name to metric function.
        n_resamples: Number of bootstrap resamples.
        level: Confidence level, e.g. 0.95.
        seed: Seed for the resampling generator, so the CI is reproducible.

    Returns:
        ``{metric: {"value", "ci_low", "ci_high", "n_valid"}}``.
    """
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(y), size=(n_resamples, len(y)))
    alpha = (1 - level) / 2
    out = {}
    for name, fn in metrics.items():
        samples = np.array([fn(y[i], p[i], thr) for i in idx])
        samples = samples[~np.isnan(samples)]
        lo, hi = np.quantile(samples, [alpha, 1 - alpha]) if len(samples) else (np.nan, np.nan)
        out[name] = {
            "value": finite_or_none(fn(y, p, thr)),
            "ci_low": finite_or_none(lo),
            "ci_high": finite_or_none(hi),
            "n_valid": int(len(samples)),
        }
    return out


def evaluate_predictions(
    y_val: np.ndarray,
    p_val: np.ndarray,
    y_test: np.ndarray,
    p_test: np.ndarray,
    views_test: np.ndarray,
    n_resamples: int,
    level: float,
    seed: int,
) -> dict:
    """Pick the threshold on validation, then score the test set overall and per view.

    Test arrays are used only after the threshold is fixed, so no test information can
    influence it.
    """
    thr = youden_threshold(y_val, p_val)
    result = {
        "threshold": {
            "method": "youden_j_on_validation",
            "value": round(thr, 6),
            "val_sensitivity": finite_or_none(sensitivity(y_val, p_val, thr)),
            "val_specificity": finite_or_none(specificity(y_val, p_val, thr)),
        },
        "test": {},
    }
    groups = {"overall": np.ones(len(y_test), dtype=bool)}
    groups.update({v: views_test == v for v in VIEWS})
    for name, mask in groups.items():
        y, p = y_test[mask], p_test[mask]
        result["test"][name] = {
            "n": int(mask.sum()),
            "positives": int(y.sum()),
            "prevalence": round(float(y.mean()), 4) if len(y) else None,
            "metrics": bootstrap_ci(y, p, thr, METRICS, n_resamples, level, seed),
        }
    return result


def save_plots(
    y: np.ndarray, p: np.ndarray, views: np.ndarray, thr: float, bins: int, out_dir: Path
) -> None:
    """ROC, precision-recall, confusion matrix and calibration plots for the test set."""
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = {"overall": np.ones(len(y), dtype=bool), **{v: views == v for v in VIEWS}}

    fig = Figure(figsize=(6, 5))
    ax = fig.subplots()
    for name, m in groups.items():
        if len(np.unique(y[m])) == 2:
            fpr, tpr, _ = roc_curve(y[m], p[m])
            ax.plot(fpr, tpr, label=f"{name} (AUROC {roc_auc_score(y[m], p[m]):.3f})")
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="chance")
    ax.set(xlabel="1 - specificity", ylabel="sensitivity", title="ROC, test split")
    ax.legend()
    fig.savefig(out_dir / "roc.png", dpi=120)

    fig = Figure(figsize=(6, 5))
    ax = fig.subplots()
    for name, m in groups.items():
        if len(np.unique(y[m])) == 2:
            prec, rec, _ = precision_recall_curve(y[m], p[m])
            ax.plot(rec, prec, label=f"{name} (AP {average_precision_score(y[m], p[m]):.3f})")
    ax.axhline(y.mean(), color="k", ls="--", lw=1, label="prevalence")
    ax.set(xlabel="recall (sensitivity)", ylabel="precision", title="Precision-recall, test")
    ax.legend()
    fig.savefig(out_dir / "precision_recall.png", dpi=120)

    fig = Figure(figsize=(5, 5))
    ax = fig.subplots()
    cm = confusion_matrix(y, (p >= thr).astype(int), labels=[0, 1])
    ConfusionMatrixDisplay(cm, display_labels=["no pneumonia", "pneumonia"]).plot(
        ax=ax, colorbar=False
    )
    ax.set_title(f"Test confusion matrix, threshold {thr:.3f} (from val)")
    fig.savefig(out_dir / "confusion_matrix.png", dpi=120)

    fig = Figure(figsize=(6, 5))
    ax = fig.subplots()
    # Quantile bins hold equal numbers of images; uniform bins go empty on small test sets.
    frac_pos, mean_pred = calibration_curve(y, p, n_bins=bins, strategy="quantile")
    ax.plot(mean_pred, frac_pos, marker="o", label="model")
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect calibration")
    ax.set(
        xlabel="mean predicted probability",
        ylabel="observed fraction positive",
        title="Calibration, test split",
    )
    ax.legend()
    fig.savefig(out_dir / "calibration.png", dpi=120)


def evaluate(
    cfg: dict, checkpoint: Path, data_dir: Path, reports_dir: Path, device_name: str
) -> dict:
    """Load a checkpoint, predict val and test, and write metrics and plots."""
    ec, seed = cfg["evaluation"], cfg["project"]["seed"]
    device = resolve_device(device_name)
    ckpt = torch.load(checkpoint, map_location=device, weights_only=False)
    model = build_model(pretrained=False)
    model.load_state_dict(ckpt["model_state"])
    model.to(device)
    print(f"seed={seed} device={device} checkpoint epoch={ckpt['metadata']['epoch']}")

    workers = num_workers_for_platform(cfg["data"]["num_workers"])
    batch = cfg["classification"]["batch_size"]
    val_ds, test_ds = ChestXrayDataset(data_dir, "val"), ChestXrayDataset(data_dir, "test")
    y_val, p_val = predict(model, make_loader(val_ds, batch, False, workers, seed), device)
    y_test, p_test = predict(model, make_loader(test_ds, batch, False, workers, seed), device)
    views = test_ds.rows["view_position"].to_numpy()

    result = evaluate_predictions(
        y_val, p_val, y_test, p_test, views, ec["bootstrap_resamples"], ec["ci_level"], seed
    )
    meta = ckpt["metadata"]
    result = {
        "checkpoint": {k: meta[k] for k in ("epoch", "val_auroc", "seed", "git_commit")}
        | {"smoke_test": meta.get("smoke_test", False)},
        "bootstrap": {
            "resamples": ec["bootstrap_resamples"],
            "ci_level": ec["ci_level"],
            "seed": seed,
        },
        **result,
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "classification_metrics.json"
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    save_plots(
        y_test,
        p_test,
        views,
        result["threshold"]["value"],
        ec["calibration_bins"],
        reports_dir / "figures",
    )

    print(f"threshold (val, Youden J) = {result['threshold']['value']:.4f}")
    for group, r in result["test"].items():
        m = r["metrics"]
        print(
            f"{group:<8} n={r['n']:<4} "
            + " ".join(
                f"{k}={fmt(v['value'])} [{fmt(v['ci_low'])}, {fmt(v['ci_high'])}]"
                for k, v in m.items()
            )
        )
    print(f"wrote {out}")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments; unset values fall back to config.yaml."""
    p = argparse.ArgumentParser(description="Evaluate the pneumonia classifier on test.")
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--data-dir", type=Path)
    p.add_argument("--device", help="cpu or cuda (default: config device)")
    p.add_argument("--smoke-test", action="store_true", help="use smoke checkpoint and dirs")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    cfg = load_config()
    cc = cfg["classification"]
    sub = "smoke" if args.smoke_test else ""
    evaluate(
        cfg,
        checkpoint=args.checkpoint or ROOT / cc["models_dir"] / sub / CHECKPOINT_NAME,
        data_dir=args.data_dir or ROOT / cc["data_dir"],
        reports_dir=ROOT / cc["reports_dir"] / sub,
        device_name=args.device or cfg["device"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
