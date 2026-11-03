"""Sanity checks for config.yaml and the project scaffold."""

from pathlib import Path, PureWindowsPath

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_config_has_required_sections():
    cfg = load_config()
    for section in ("project", "paths", "data", "classification", "explainability"):
        assert section in cfg, f"missing section: {section}"


def test_segmentation_is_out_of_scope():
    assert "segmentation" not in load_config()


def test_paths_are_relative_to_repo_root():
    # Absolute paths tie the config to one machine. PureWindowsPath catches drive paths
    # such as C:/...; it does not treat a bare "/" root as absolute, so check that too.
    for key, value in load_config()["paths"].items():
        assert not PureWindowsPath(value).is_absolute(), f"absolute path in paths.{key}"
        assert not str(value).startswith("/"), f"absolute path in paths.{key}"


def test_split_fractions_leave_training_data():
    data = load_config()["data"]
    assert 0 < data["val_split"] + data["test_split"] < 1


def test_scaffold_directories_exist():
    for rel in ("data/raw", "data/processed", "ml/classification", "backend/app", "tests"):
        assert (ROOT / rel).is_dir(), f"missing directory: {rel}"
