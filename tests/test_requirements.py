"""The backend's runtime requirements stay a pinned subset of the development environment."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?==(\S+)")


def pins(path: Path) -> dict[str, str]:
    """Package name (lower case, extras dropped) to exact version, from == lines only."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = PIN.match(line.split("#", 1)[0].strip())
        if match:
            out[match.group(1).lower()] = match.group(3)
    return out


def test_every_backend_requirement_is_pinned():
    lines = [
        line.split("#", 1)[0].strip()
        for line in (ROOT / "backend/requirements.txt").read_text(encoding="utf-8").splitlines()
    ]
    packages = [line for line in lines if line and not line.startswith("-")]
    assert packages and all(PIN.match(line) for line in packages), packages


def test_backend_pins_match_the_development_environment():
    backend, root = pins(ROOT / "backend/requirements.txt"), pins(ROOT / "requirements.txt")
    mismatched = {name: (v, root.get(name)) for name, v in backend.items() if root.get(name) != v}
    assert mismatched == {}


def test_development_only_tools_are_not_in_the_image():
    backend = pins(ROOT / "backend/requirements.txt")
    for tool in ("dvc", "kaggle", "pytest", "pytest-cov", "ruff", "simpleitk", "monai", "nibabel"):
        assert tool not in backend
