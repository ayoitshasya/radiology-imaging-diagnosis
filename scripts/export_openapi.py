"""Export the backend's OpenAPI schema to docs/openapi.json.

The schema is built from the app object without starting it, so no database, Orthanc or
model is needed. With --check, nothing is written and the exit code is 1 if the committed
file is out of date.

Usage:
    python scripts/export_openapi.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import create_app  # noqa: E402

OUTPUT = ROOT / "docs" / "openapi.json"


def render_schema() -> str:
    """The OpenAPI schema as stable, indented JSON with a trailing newline."""
    return json.dumps(create_app().openapi(), indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write docs/openapi.json, or with --check report whether it is current."""
    p = argparse.ArgumentParser(description="Export the OpenAPI schema.")
    p.add_argument("--check", action="store_true", help="fail if docs/openapi.json is stale")
    args = p.parse_args(argv)
    schema = render_schema()
    if args.check:
        current = (
            OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUTPUT.exists() else ""
        )
        if current != schema:
            print(f"{OUTPUT.relative_to(ROOT)} is out of date; run scripts/export_openapi.py")
            return 1
        print(f"{OUTPUT.relative_to(ROOT)} is up to date")
        return 0
    OUTPUT.write_text(schema, encoding="utf-8", newline="\n")
    paths = json.loads(schema)["paths"]
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(paths)} paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
