"""Shared helpers for classification training, evaluation and baselines."""

from __future__ import annotations

import os
import random
import subprocess
from pathlib import Path

import numpy as np
import torch
import yaml
from torch import nn
from torch.utils.data import DataLoader, Dataset, Subset
from torchvision.models import DenseNet121_Weights, densenet121

ROOT = Path(__file__).resolve().parents[2]


def load_config(path: Path | None = None) -> dict:
    """Load ``config.yaml`` from the repository root unless another path is given."""
    with open(path or ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def set_seed(seed: int) -> None:
    """Seed every random source used in training and make cuDNN deterministic.

    Determinism costs some GPU speed, but it lets a reported result be reproduced from
    the seed stored in the checkpoint.
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def seed_worker(worker_id: int) -> None:
    """Seed NumPy and ``random`` inside a DataLoader worker from torch's per-worker seed."""
    worker_seed = torch.initial_seed() % 2**32
    np.random.seed(worker_seed)
    random.seed(worker_seed)


def resolve_device(requested: str) -> torch.device:
    """Return the requested device, falling back to CPU if CUDA is unavailable."""
    if requested.startswith("cuda") and not torch.cuda.is_available():
        print("CUDA requested but not available; using CPU")
        return torch.device("cpu")
    return torch.device(requested)


def num_workers_for_platform(configured: int) -> int:
    """Use no worker processes on Windows to keep memory low on the laptop."""
    return 0 if os.name == "nt" else configured


def git_commit() -> str:
    """Current git commit hash, suffixed ``-dirty`` if tracked files have uncommitted changes.

    Without the suffix, a checkpoint trained on uncommitted code would claim a commit that
    did not produce it. Returns ``"unknown"`` outside a git checkout.
    """

    def git(*args: str) -> str:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
        return out.stdout.strip()

    try:
        dirty = git("status", "--porcelain", "--untracked-files=no")
        return git("rev-parse", "HEAD") + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_model(pretrained: bool) -> nn.Module:
    """DenseNet121 with its 1000-class ImageNet head replaced by a single logit.

    DenseNet121 is the backbone used by CheXNet-style chest X-ray classifiers; its dense
    connections reuse low-level features, which suits subtle opacities. One logit with a
    sigmoid gives P(pneumonia), the quantity the ROC and threshold analysis need.

    Args:
        pretrained: Load ImageNet weights (downloads once into the torch cache).

    Returns:
        The model, outputting shape ``(N, 1)``.
    """
    weights = DenseNet121_Weights.IMAGENET1K_V1 if pretrained else None
    model = densenet121(weights=weights)
    model.classifier = nn.Linear(model.classifier.in_features, 1)
    return model


def balanced_subset(dataset: Dataset, labels: np.ndarray, n: int, seed: int) -> Subset:
    """Pick ``n`` items, half positive and half negative, reproducibly.

    Used by the smoke test so a tiny validation set still contains both classes, without
    which AUROC is undefined.
    """
    rng = np.random.default_rng(seed)
    per_class = n // 2
    idx = np.concatenate(
        [rng.choice(np.flatnonzero(labels == c), size=per_class, replace=False) for c in (0, 1)]
    )
    return Subset(dataset, sorted(idx.tolist()))


def make_loader(
    dataset: Dataset, batch_size: int, shuffle: bool, workers: int, seed: int
) -> DataLoader:
    """DataLoader with a seeded generator so shuffling order is reproducible."""
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=workers,
        worker_init_fn=seed_worker,
        generator=generator,
    )


@torch.no_grad()
def predict(
    model: nn.Module, loader: DataLoader, device: torch.device
) -> tuple[np.ndarray, np.ndarray]:
    """Run the model in eval mode and return (labels, probabilities) as NumPy arrays."""
    model.eval()
    labels, probs = [], []
    for images, targets in loader:
        logits = model(images.to(device)).squeeze(1)
        probs.append(torch.sigmoid(logits.float()).cpu().numpy())
        labels.append(targets.numpy())
    return np.concatenate(labels), np.concatenate(probs)
