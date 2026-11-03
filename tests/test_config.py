"""Sanity checks for config.yaml and the project scaffold."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_config_has_required_sections():
    cfg = load_config()
    for section in ("project", "paths", "data", "classification", "segmentation"):
        assert section in cfg, f"missing section: {section}"


def test_split_fractions_leave_training_data():
    data = load_config()["data"]
    assert 0 < data["val_split"] + data["test_split"] < 1


def test_scaffold_directories_exist():
    for rel in ("data/raw", "data/processed", "ml/classification", "backend/app", "tests"):
        assert (ROOT / rel).is_dir(), f"missing directory: {rel}"
