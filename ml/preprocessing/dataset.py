"""PyTorch Dataset over the manifest written by build_dataset.py."""

from __future__ import annotations

from pathlib import Path

import cv2
import pandas as pd
import torch
from torch.utils.data import Dataset
from torchvision.transforms import v2

# ImageNet statistics, because the classifier starts from ImageNet-pretrained weights and
# expects inputs on the same scale it was trained with.
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def to_three_channels(x: torch.Tensor) -> torch.Tensor:
    """Repeat a 1 x H x W tensor to 3 x H x W.

    A named function instead of a lambda so the transform can be pickled into DataLoader
    worker processes, which Windows starts by spawning.
    """
    return x.repeat(3, 1, 1)


def build_transform(train: bool) -> v2.Compose:
    """Return the augmentation pipeline for a single-channel uint8 image tensor.

    Training uses mild geometric and intensity changes that mimic real variation in
    patient positioning and exposure without moving anatomy to implausible places.

    Horizontal flip is deliberately left out. In a chest X-ray the heart sits on the
    patient's left, and a flipped film shows the heart on the wrong side (as in the rare
    condition dextrocardia). Some papers flip anyway for extra variety, but it teaches the
    model anatomy that almost never occurs and can hide laterality cues near the heart
    border, so it is not worth the risk here.

    Args:
        train: If True, include augmentation; validation and test get none.

    Returns:
        A transform that outputs a normalised 3 x H x W float32 tensor.
    """
    steps: list = []
    if train:
        steps += [
            v2.RandomAffine(degrees=10, translate=(0.05, 0.05), scale=(0.95, 1.05), fill=0),
            v2.ColorJitter(brightness=0.1, contrast=0.1),
        ]
    steps += [
        v2.ToDtype(torch.float32, scale=True),
        # Pretrained backbones expect 3 channels; copying the gray channel adds no
        # information but lets the ImageNet weights be used unchanged.
        v2.Lambda(to_three_channels),
        v2.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ]
    return v2.Compose(steps)


class ChestXrayDataset(Dataset):
    """Images and labels for one split of the preprocessed manifest.

    Returns only the image tensor and label; no identifiers or demographics, so nothing
    patient-related can leak into training logs.
    """

    def __init__(self, data_dir: str | Path, split: str, train: bool | None = None) -> None:
        """Load the manifest rows for ``split``.

        Args:
            data_dir: Folder containing ``manifest.csv`` and the ``images/`` folder.
            split: One of ``"train"``, ``"val"`` or ``"test"``.
            train: Whether to augment. Defaults to True only for the train split.
        """
        self.data_dir = Path(data_dir)
        manifest = pd.read_csv(self.data_dir / "manifest.csv")
        self.rows = manifest[manifest["split"] == split].reset_index(drop=True)
        if self.rows.empty:
            raise ValueError(f"No rows for split '{split}' in {self.data_dir / 'manifest.csv'}")
        self.transform = build_transform(split == "train" if train is None else train)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        row = self.rows.iloc[idx]
        img = cv2.imread(str(self.data_dir / row["path"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(f"Unreadable image for image_id {row['image_id']}")
        tensor = torch.from_numpy(img).unsqueeze(0)  # 1 x H x W uint8
        label = torch.tensor(int(row["label"]), dtype=torch.long)
        return self.transform(tensor), label
