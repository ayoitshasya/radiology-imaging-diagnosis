"""The committed docs/openapi.json must match the schema the app generates."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("export_openapi", ROOT / "scripts/export_openapi.py")
export_openapi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export_openapi)


def test_committed_openapi_schema_is_up_to_date():
    committed = (ROOT / "docs" / "openapi.json").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == export_openapi.render_schema(), (
        "docs/openapi.json is out of date; run: python scripts/export_openapi.py"
    )


def test_schema_documents_the_notice_and_identifier_warning():
    schema = export_openapi.render_schema()
    assert "Educational use only. Not for clinical use." in schema
    assert "Do not type patient names, patient IDs" in schema
