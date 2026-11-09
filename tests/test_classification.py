"""Tests for ml/classification: model, loss weighting, threshold, bootstrap, training."""

import json

import cv2
import numpy as np
import pandas as pd
import pytest
import torch

from ml.classification.baselines import majority_class, view_only_scores
from ml.classification.common import ROOT, build_model, load_config
from ml.classification.evaluate import (
    METRICS,
    bootstrap_ci,
    evaluate_predictions,
    finite_or_none,
    youden_threshold,
)
from ml.classification.train import CHECKPOINT_NAME, compute_pos_weight, train

SAMPLE_DIR = ROOT / "data" / "processed" / "rsna_sample"


def strict_json(path):
    """Parse JSON, rejecting NaN and Infinity like a strict parser would."""
    return json.loads(path.read_text(), parse_constant=lambda c: pytest.fail(f"non-JSON {c}"))


def test_model_outputs_one_logit_per_image():
    model = build_model(pretrained=False).eval()
    with torch.no_grad():
        out = model(torch.randn(2, 3, 224, 224))
    assert out.shape == (2, 1)


def test_gradcam_target_layer_exists_in_model():
    layer = load_config()["explainability"]["target_layer"]
    assert layer in dict(build_model(pretrained=False).named_modules())


def test_pos_weight_is_negatives_over_positives():
    labels = np.array([0] * 30 + [1] * 10)
    assert compute_pos_weight(labels).item() == pytest.approx(3.0)


def test_pos_weight_rejects_no_positives():
    with pytest.raises(ValueError):
        compute_pos_weight(np.zeros(5))


def test_youden_threshold_on_separable_scores():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.7, 0.9])
    assert youden_threshold(y, p) == pytest.approx(0.7)


def test_threshold_is_picked_on_validation_only():
    rng = np.random.default_rng(0)
    y_val = rng.integers(0, 2, 200)
    p_val = np.clip(y_val * 0.3 + rng.random(200) * 0.7, 0, 1)
    views = np.array(["AP", "PA"] * 50)
    a = evaluate_predictions(
        y_val, p_val, rng.integers(0, 2, 100), rng.random(100), views, 50, 0.95, 42
    )
    # Entirely different test labels and scores must not move the threshold.
    b = evaluate_predictions(
        y_val, p_val, rng.integers(0, 2, 100), rng.random(100), views, 50, 0.95, 42
    )
    assert a["threshold"]["value"] == b["threshold"]["value"]
    assert a["threshold"]["value"] == pytest.approx(youden_threshold(y_val, p_val), abs=1e-6)
    assert a["test"] != b["test"]


def test_bootstrap_ci_is_seeded_and_reproducible():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 150)
    p = rng.random(150)
    first = bootstrap_ci(y, p, 0.5, METRICS, 200, 0.95, seed=42)
    again = bootstrap_ci(y, p, 0.5, METRICS, 200, 0.95, seed=42)
    other = bootstrap_ci(y, p, 0.5, METRICS, 200, 0.95, seed=7)
    assert first == again
    assert first != other
    # A percentile CI need not contain the point estimate, so only its ordering is checked.
    for m in first.values():
        assert m["ci_low"] <= m["ci_high"]


def test_undefined_metric_is_none_not_nan():
    y = np.zeros(20, dtype=int)  # no positives: sensitivity and AUROC undefined
    result = bootstrap_ci(y, np.random.default_rng(0).random(20), 0.5, METRICS, 50, 0.95, 42)
    assert result["sensitivity"] == {"value": None, "ci_low": None, "ci_high": None, "n_valid": 0}
    assert finite_or_none(float("nan")) is None
    json.dumps(result, allow_nan=False)


def test_view_only_baseline_uses_train_rates_only():
    train_df = pd.DataFrame(
        {"view_position": ["AP"] * 4 + ["PA"] * 4, "label": [1, 1, 1, 0, 0, 0, 0, 1]}
    )
    test_df = pd.DataFrame({"view_position": ["AP", "PA", "LL"], "label": [0, 1, 0]})
    scores, rates = view_only_scores(train_df, test_df)
    assert rates == {"AP": 0.75, "PA": 0.25}
    np.testing.assert_allclose(scores, [0.75, 0.25, 0.5])  # unseen view -> train overall
    flipped = test_df.assign(label=1 - test_df["label"])
    np.testing.assert_allclose(view_only_scores(train_df, flipped)[0], scores)


def test_majority_class_tie_goes_to_negative():
    assert majority_class(pd.DataFrame({"label": [0, 1]})) == 0
    assert majority_class(pd.DataFrame({"label": [1, 1, 0]})) == 1


@pytest.mark.needs_dvc  # trains on the DVC-tracked processed RSNA sample
def test_smoke_training_runs_end_to_end_on_sample(tmp_path):
    cfg = load_config()
    log = train(
        cfg,
        SAMPLE_DIR,
        tmp_path / "models",
        tmp_path / "reports",
        epochs=1,
        batch_size=4,
        device_name="cpu",
        smoke=True,
        pretrained=False,
    )
    assert len(log["epochs"]) == 1 and log["best_epoch"] == 1
    assert log["n_train"] == cfg["classification"]["smoke"]["train_images"]
    ckpt = torch.load(tmp_path / "models" / CHECKPOINT_NAME, weights_only=False)
    meta = ckpt["metadata"]
    for key in ("seed", "epoch", "val_auroc", "torch_version", "git_commit", "config"):
        assert key in meta
    assert strict_json(tmp_path / "reports" / "training_log.json")["seed"] == meta["seed"]
    assert (tmp_path / "reports" / "training_curves.png").is_file()


def test_training_fails_loudly_when_val_has_one_class(tmp_path):
    data = tmp_path / "processed"
    (data / "images").mkdir(parents=True)
    rows = []
    splits = [("train", k % 2) for k in range(8)] + [("val", 0)] * 4  # val: one class only
    for i, (split, label) in enumerate(splits):
        cv2.imwrite(str(data / "images" / f"{i}.png"), np.full((224, 224), 128, np.uint8))
        rows.append(
            {
                "image_id": str(i),
                "path": f"images/{i}.png",
                "label": label,
                "split": split,
                "view_position": "PA",
            }
        )
    pd.DataFrame(rows).to_csv(data / "manifest.csv", index=False)
    with pytest.raises(RuntimeError, match="undefined in every epoch"):
        train(
            load_config(),
            data,
            tmp_path / "m",
            tmp_path / "r",
            epochs=1,
            batch_size=4,
            device_name="cpu",
            smoke=False,
            pretrained=False,
        )
    assert strict_json(tmp_path / "r" / "training_log.json")["best_val_auroc"] is None
