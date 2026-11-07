"""Backend settings: secrets from the environment or .env, project choices from config.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings.

    Connection details and credentials come from environment variables, falling back to
    the repository's ``.env``; real environment variables win. Secrets are ``SecretStr``
    so they print as ``**********`` in reprs, logs and tracebacks.
    """

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: SecretStr
    orthanc_url: str
    orthanc_username: str
    orthanc_password: SecretStr

    # Filled from config.yaml by get_settings(); listed here for type checking.
    model_name: str = ""
    checkpoint: Path = Path()
    checkpoint_dvc: Path = Path()
    metrics_report: Path = Path()
    orthanc_timeout_seconds: float = 10.0
    notice: str = ""
    device: str = "cpu"
    target_layer: str = ""


def load_project_config(path: Path = ROOT / "config.yaml") -> dict:
    """Read the non-secret backend values from config.yaml, with paths made absolute."""
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    b = cfg["backend"]
    return {
        "model_name": b["model_name"],
        "checkpoint": ROOT / b["checkpoint"],
        "checkpoint_dvc": ROOT / b["checkpoint_dvc"],
        "metrics_report": ROOT / b["metrics_report"],
        "orthanc_timeout_seconds": b["orthanc_timeout_seconds"],
        "notice": b["notice"],
        "device": cfg["device"],
        "target_layer": cfg["explainability"]["target_layer"],
    }


@lru_cache
def get_settings() -> Settings:
    """Settings for the running app, built once per process."""
    return Settings(**load_project_config())
