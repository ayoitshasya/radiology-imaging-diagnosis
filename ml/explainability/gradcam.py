"""Grad-CAM heatmaps for the DenseNet121 pneumonia classifier.

Educational use only; not a medical device. A heatmap shows which image regions most
increased the model's pneumonia score. It is not a lesion outline and not evidence that
the model is right.

Usage:
    python -m ml.explainability.gradcam --image <png> [--checkpoint <pt>] [--output <png>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from pytorch_grad_cam import GradCAM
from pytorch_grad_cam.utils.image import show_cam_on_image
from pytorch_grad_cam.utils.model_targets import BinaryClassifierOutputTarget
from torch import nn
from torch.torch_version import TorchVersion

from ml.classification.common import ROOT, build_model, load_config
from ml.preprocessing.dataset import build_transform


def load_model(checkpoint_path: str | Path, device: str = "cpu") -> nn.Module:
    """Load trained weights into DenseNet121 in eval mode.

    Uses ``weights_only=True`` because a checkpoint is a pickle and full unpickling can
    execute code; the weights-only loader accepts tensors and plain containers only.
    TorchVersion is allowlisted because checkpoints from train.py before the fix store
    ``torch.__version__``, a str subclass, in their metadata.
    """
    with torch.serialization.safe_globals([TorchVersion]):
        ckpt = torch.load(checkpoint_path, map_location=device, weights_only=True)
    model = build_model(pretrained=False)
    model.load_state_dict(ckpt["model_state"])
    return model.to(device).eval()


def get_layer(model: nn.Module, name: str) -> nn.Module:
    """Return a submodule by dotted name, e.g. ``features.denseblock4``."""
    return dict(model.named_modules())[name]


def load_image(image_path: str | Path) -> np.ndarray:
    """Read a preprocessed grayscale PNG as a 2D uint8 array."""
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"Unreadable image: {Path(image_path).name}")
    return img


def to_input_tensor(img: np.ndarray) -> torch.Tensor:
    """Apply the evaluation transform (no augmentation) and add a batch dimension."""
    return build_transform(train=False)(torch.from_numpy(img).unsqueeze(0)).unsqueeze(0)


def normalise_heatmap(cam: np.ndarray) -> np.ndarray:
    """Min-max scale a heatmap to [0, 1].

    A constant map carries no spatial evidence, so it becomes all zeros rather than
    dividing by zero; callers can detect that case by a zero sum.
    """
    cam = cam.astype(np.float64)
    lo, hi = cam.min(), cam.max()
    if hi - lo < 1e-12:
        return np.zeros_like(cam)
    return (cam - lo) / (hi - lo)


def compute_heatmap(model: nn.Module, img: np.ndarray, target_layer: str) -> np.ndarray:
    """Grad-CAM for the pneumonia logit, resized to the image and scaled to [0, 1].

    Grad-CAM weights each channel of ``target_layer`` by the mean gradient of the
    pneumonia logit with respect to it, sums them and keeps positive values, giving the
    regions whose activation raised the score.

    Known limitation: features.denseblock4 is a 7x7 grid for a 224x224 input, so each
    heatmap cell covers about 32x32 pixels. The map can point to a region of lung but
    cannot trace the shape of an opacity.

    Args:
        model: Classifier in eval mode.
        img: 2D uint8 image as stored by the preprocessing pipeline.
        target_layer: Dotted module name of the layer to explain.

    Returns:
        Float array with the image's shape and values in [0, 1].
    """
    device = next(model.parameters()).device
    with GradCAM(model=model, target_layers=[get_layer(model, target_layer)]) as cam:
        raw = cam(
            input_tensor=to_input_tensor(img).to(device), targets=[BinaryClassifierOutputTarget(1)]
        )[0]
    return normalise_heatmap(raw)


def overlay(img: np.ndarray, heatmap: np.ndarray) -> np.ndarray:
    """Blend a [0, 1] heatmap over the grayscale image; returns HxWx3 uint8 RGB."""
    rgb = np.repeat((img.astype(np.float32) / 255.0)[..., None], 3, axis=2)
    return show_cam_on_image(rgb, heatmap.astype(np.float32), use_rgb=True)


def generate_heatmap(image_path: str | Path, checkpoint_path: str | Path) -> np.ndarray:
    """Load a checkpoint, explain one image and return the overlay (HxWx3 uint8 RGB)."""
    cfg = load_config()
    img = load_image(image_path)
    model = load_model(checkpoint_path)
    return overlay(img, compute_heatmap(model, img, cfg["explainability"]["target_layer"]))


def main(argv: list[str] | None = None) -> int:
    """CLI: write a Grad-CAM overlay PNG for one preprocessed image."""
    cfg = load_config()["explainability"]
    p = argparse.ArgumentParser(description="Grad-CAM overlay for one preprocessed PNG.")
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, default=ROOT / cfg["checkpoint"])
    p.add_argument("--output", type=Path, help="default: <output_dir>/<image name>")
    args = p.parse_args(argv)

    out = args.output or ROOT / cfg["output_dir"] / args.image.name
    out.parent.mkdir(parents=True, exist_ok=True)
    rgb = generate_heatmap(args.image, args.checkpoint)
    cv2.imwrite(str(out), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    print(f"wrote {out} (contains image pixels; keep it out of git)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
