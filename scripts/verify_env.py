"""Import every project dependency and print its version.

Exits with status 1 if any import fails, so it can be used in CI.
"""

from __future__ import annotations

import importlib
import sys
from importlib.metadata import PackageNotFoundError, version

# (distribution name on PyPI, module to import)
PACKAGES: list[tuple[str, str]] = [
    ("torch", "torch"),
    ("torchvision", "torchvision"),
    ("monai", "monai"),
    ("nibabel", "nibabel"),
    ("SimpleITK", "SimpleITK"),
    ("pydicom", "pydicom"),
    ("pylibjpeg", "pylibjpeg"),
    ("pylibjpeg-libjpeg", "libjpeg"),
    ("python-gdcm", "gdcm"),
    ("numpy", "numpy"),
    ("pandas", "pandas"),
    ("scikit-learn", "sklearn"),
    ("matplotlib", "matplotlib"),
    ("opencv-python-headless", "cv2"),
    ("grad-cam", "pytorch_grad_cam"),
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("sqlalchemy", "sqlalchemy"),
    ("psycopg2-binary", "psycopg2"),
    ("python-multipart", "multipart"),
    ("alembic", "alembic"),
    ("dvc", "dvc"),
    ("kaggle", "kaggle"),
    ("pytest", "pytest"),
    ("pytest-cov", "pytest_cov"),
    ("ruff", "ruff"),
]


def check(dist: str, module: str) -> tuple[bool, str]:
    """Import ``module`` and return (ok, version-or-error)."""
    try:
        importlib.import_module(module)
        return True, version(dist)
    except PackageNotFoundError:
        return False, "not installed"
    except Exception as exc:  # noqa: BLE001 - report any import failure
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    print(f"Python {sys.version.split()[0]} at {sys.executable}\n")
    failures = 0
    for dist, module in PACKAGES:
        ok, info = check(dist, module)
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {dist:<24} {info}")

    import torch

    print(f"\ntorch CUDA available: {torch.cuda.is_available()}")
    print(f"\n{len(PACKAGES) - failures}/{len(PACKAGES)} packages OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
