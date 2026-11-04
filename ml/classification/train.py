"""Train a DenseNet121 pneumonia classifier on the preprocessed manifest.

Educational use only; not a medical device.

All settings come from config.yaml (``classification`` section); the flags below override
them. ``--smoke-test`` checks the pipeline end to end on a tiny balanced subset and writes
to ``models/smoke`` and ``reports/smoke`` so its meaningless metrics never mix with real
results.

Usage:
    python -m ml.classification.train [--epochs N] [--batch-size N] [--device cuda]
        [--data-dir DIR] [--smoke-test]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torchvision
from matplotlib.figure import Figure
from sklearn.metrics import roc_auc_score
from torch import nn
from torch.utils.data import DataLoader

from ml.classification.common import (
    ROOT,
    balanced_subset,
    build_model,
    git_commit,
    load_config,
    make_loader,
    num_workers_for_platform,
    resolve_device,
    set_seed,
)
from ml.preprocessing.dataset import ChestXrayDataset

CHECKPOINT_NAME = "densenet121_best.pt"


def compute_pos_weight(labels: np.ndarray) -> torch.Tensor:
    """Ratio of negatives to positives in the training labels.

    BCEWithLogitsLoss multiplies the loss of positive examples by this value, so a
    minority positive class contributes as much total loss as the majority. It must come
    from the train split only; using val or test labels would leak their class balance.

    Args:
        labels: Binary training labels.

    Returns:
        A one-element float tensor.

    Raises:
        ValueError: If there are no positive labels.
    """
    labels = np.asarray(labels)
    n_pos = int((labels == 1).sum())
    if n_pos == 0:
        raise ValueError("No positive labels in the training split; pos_weight is undefined")
    return torch.tensor([(len(labels) - n_pos) / n_pos], dtype=torch.float32)


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    scaler: torch.amp.GradScaler,
    device: torch.device,
    clip_norm: float,
) -> float:
    """One pass over the training data; returns the mean loss per image."""
    model.train()
    use_amp = device.type == "cuda"
    total, count = 0.0, 0
    for images, targets in loader:
        images, targets = images.to(device), targets.float().to(device)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type="cuda", enabled=use_amp):
            loss = criterion(model(images).squeeze(1), targets)
        scaler.scale(loss).backward()
        # Gradients are scaled under AMP; unscale before clipping so the norm is real.
        scaler.unscale_(optimizer)
        nn.utils.clip_grad_norm_(model.parameters(), clip_norm)
        scaler.step(optimizer)
        scaler.update()
        total += loss.item() * len(targets)
        count += len(targets)
    return total / count


@torch.no_grad()
def validate(
    model: nn.Module, loader: DataLoader, criterion: nn.Module, device: torch.device
) -> tuple[float, float]:
    """Return (mean val loss, val AUROC). AUROC is NaN if val has a single class."""
    model.eval()
    total, labels, probs = 0.0, [], []
    for images, targets in loader:
        logits = model(images.to(device)).squeeze(1).float()
        total += criterion(logits, targets.float().to(device)).item() * len(targets)
        labels.append(targets.numpy())
        probs.append(torch.sigmoid(logits).cpu().numpy())
    y, p = np.concatenate(labels), np.concatenate(probs)
    auroc = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else float("nan")
    return total / len(y), auroc


def plot_curves(history: list[dict], path: Path) -> None:
    """Save train/val loss and val AUROC per epoch as one PNG."""
    epochs = [h["epoch"] for h in history]
    # Figure without pyplot needs no GUI backend, so this works headless on Kaggle too.
    fig = Figure(figsize=(11, 4))
    ax_loss, ax_auc = fig.subplots(1, 2)
    ax_loss.plot(epochs, [h["train_loss"] for h in history], marker="o", label="train")
    ax_loss.plot(epochs, [h["val_loss"] for h in history], marker="o", label="val")
    ax_loss.set(xlabel="epoch", ylabel="BCE loss (pos-weighted)", title="Loss")
    ax_loss.legend()
    aurocs = [np.nan if h["val_auroc"] is None else h["val_auroc"] for h in history]
    ax_auc.plot(epochs, aurocs, marker="o", color="tab:green")
    ax_auc.set(xlabel="epoch", ylabel="AUROC", title="Validation AUROC")
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def train(
    cfg: dict,
    data_dir: Path,
    models_dir: Path,
    reports_dir: Path,
    epochs: int,
    batch_size: int,
    device_name: str,
    smoke: bool,
    pretrained: bool,
) -> dict:
    """Train with early stopping on val AUROC and return the training log."""
    cc = cfg["classification"]
    seed = cfg["project"]["seed"]
    set_seed(seed)
    device = resolve_device(device_name)
    print(f"seed={seed} device={device} smoke={smoke} epochs={epochs} batch_size={batch_size}")

    train_ds, val_ds = ChestXrayDataset(data_dir, "train"), ChestXrayDataset(data_dir, "val")
    train_labels = train_ds.rows["label"].to_numpy()
    if smoke:
        sc = cc["smoke"]
        train_ds = balanced_subset(train_ds, train_labels, sc["train_images"], seed)
        val_ds = balanced_subset(val_ds, val_ds.rows["label"].to_numpy(), sc["val_images"], seed)
        train_labels = train_labels[train_ds.indices]

    workers = num_workers_for_platform(cfg["data"]["num_workers"])
    train_loader = make_loader(train_ds, batch_size, True, workers, seed)
    val_loader = make_loader(val_ds, batch_size, False, workers, seed)

    pos_weight = compute_pos_weight(train_labels)
    print(f"train={len(train_ds)} val={len(val_ds)} pos_weight={pos_weight.item():.4f}")
    model = build_model(pretrained).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight.to(device))
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=cc["learning_rate"], weight_decay=cc["weight_decay"]
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=cc["plateau_factor"], patience=cc["plateau_patience"]
    )
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")

    models_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    history, best_auroc, best_epoch, stale = [], -1.0, 0, 0
    for epoch in range(1, epochs + 1):
        train_loss = train_one_epoch(
            model, train_loader, criterion, optimizer, scaler, device, cc["grad_clip_norm"]
        )
        val_loss, val_auroc = validate(model, val_loader, criterion, device)
        lr = optimizer.param_groups[0]["lr"]
        scheduler.step(val_auroc)
        history.append(
            {
                "epoch": epoch,
                "train_loss": round(train_loss, 5),
                "val_loss": round(val_loss, 5),
                # NaN (single-class val) is stored as None so the log stays valid JSON.
                "val_auroc": None if np.isnan(val_auroc) else round(val_auroc, 5),
                "lr": lr,
            }
        )
        print(
            f"epoch {epoch}: train_loss={train_loss:.4f} val_loss={val_loss:.4f} "
            f"val_auroc={val_auroc:.4f} lr={lr:.2e}"
        )

        if val_auroc > best_auroc:
            best_auroc, best_epoch, stale = val_auroc, epoch, 0
            metadata = {
                "seed": seed,
                "epoch": epoch,
                "val_auroc": val_auroc,
                "torch_version": torch.__version__,
                "torchvision_version": torchvision.__version__,
                "git_commit": git_commit(),
                "pretrained": pretrained,
                "smoke_test": smoke,
                "pos_weight": pos_weight.item(),
                "batch_size": batch_size,
                "config": cfg,
            }
            torch.save(
                {"model_state": model.state_dict(), "metadata": metadata},
                models_dir / CHECKPOINT_NAME,
            )
        else:
            stale += 1
            if stale >= cc["early_stopping_patience"]:
                print(f"early stopping: no val AUROC gain for {stale} epochs")
                break

    log = {
        "seed": seed,
        "device": str(device),
        "smoke_test": smoke,
        "pretrained": pretrained,
        "pos_weight": round(pos_weight.item(), 5),
        "n_train": len(train_ds),
        "n_val": len(val_ds),
        "best_epoch": best_epoch,
        "best_val_auroc": round(best_auroc, 5) if best_epoch else None,
        "stopped_early": len(history) < epochs,
        "epochs": history,
    }
    log_text = json.dumps(log, indent=2, allow_nan=False) + "\n"
    (reports_dir / "training_log.json").write_text(log_text, "utf-8")
    plot_curves(history, reports_dir / "training_curves.png")
    if not best_epoch:
        # Write the log first so the failed run can be inspected, then fail loudly rather
        # than finish "successfully" with no checkpoint for evaluate.py to load.
        raise RuntimeError(
            "Validation AUROC was undefined in every epoch (val split has a single class); "
            "no checkpoint was saved"
        )
    print(
        f"best epoch {best_epoch} val_auroc={best_auroc:.4f}; "
        f"checkpoint: {models_dir / CHECKPOINT_NAME}"
    )
    return log


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments; unset values fall back to config.yaml."""
    p = argparse.ArgumentParser(description="Train the DenseNet121 pneumonia classifier.")
    p.add_argument("--epochs", type=int)
    p.add_argument("--batch-size", type=int)
    p.add_argument("--device", help="cpu or cuda (default: config device)")
    p.add_argument("--data-dir", type=Path, help="folder with manifest.csv and images/")
    p.add_argument("--smoke-test", action="store_true", help="2 epochs on 64 images")
    p.add_argument("--no-pretrained", action="store_true", help="random init (tests only)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    cfg = load_config()
    cc = cfg["classification"]
    smoke = args.smoke_test
    sub = "smoke" if smoke else ""
    train(
        cfg,
        data_dir=args.data_dir or ROOT / cc["data_dir"],
        models_dir=ROOT / cc["models_dir"] / sub,
        reports_dir=ROOT / cc["reports_dir"] / sub,
        epochs=args.epochs or (cc["smoke"]["epochs"] if smoke else cc["epochs"]),
        batch_size=args.batch_size or (cc["smoke"]["batch_size"] if smoke else cc["batch_size"]),
        device_name=args.device or cfg["device"],
        smoke=smoke,
        pretrained=cc["pretrained"] and not args.no_pretrained,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
