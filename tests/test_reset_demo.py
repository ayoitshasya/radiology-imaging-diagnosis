"""scripts/reset_demo_state.py against the throwaway database, never the dev one."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from pydantic import SecretStr
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "reset_demo_state", ROOT / "scripts/reset_demo_state.py"
)
reset_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reset_demo)


def populate(api, tmp_path):
    """Two studies synced and analysed, one reviewed, via the real API."""
    client, fake, engine = api
    for oid in ("s1", "s2"):
        fake.add_study(tmp_path, oid)
    client.post("/studies/sync")
    for oid in ("s1", "s2"):
        client.post(f"/studies/{oid}/analyse")
    client.post("/studies/s1/review", json={"decision": "approved", "reviewer": "A"})
    return client, fake, engine


def rows(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).all()


def test_reset_clears_tables_keeps_audit_and_records_marker(api, tmp_path):
    client, _, engine = populate(api, tmp_path)
    audit_before = rows(engine, "SELECT id, event_type, detail FROM audit_log ORDER BY id")
    max_pred = rows(engine, "SELECT max(id) FROM predictions")[0][0]

    deleted = reset_demo.reset(engine)

    assert deleted["reviews"]["rows"] == 1 and deleted["predictions"]["rows"] == 2
    assert deleted["studies"]["rows"] == 2
    for table in ("reviews", "predictions", "studies"):
        assert rows(engine, f"SELECT count(*) FROM {table}")[0][0] == 0
    audit_after = rows(engine, "SELECT id, event_type, detail FROM audit_log ORDER BY id")
    assert audit_after[: len(audit_before)] == audit_before  # earlier events untouched
    assert len(audit_after) == len(audit_before) + 1
    marker = audit_after[-1]
    assert marker.event_type == "demo_reset"
    assert marker.detail["deleted"]["predictions"] == {
        "rows": 2,
        "min_id": deleted["predictions"]["min_id"],
        "max_id": max_pred,
    }

    # After the reset, re-sync and re-analyse: new IDs never reuse old ones.
    client.post("/studies/sync")
    new = client.post("/studies/s1/analyse").json()
    assert new["prediction_id"] > max_pred and new["cached"] is False


def test_dry_run_changes_nothing(api, tmp_path, monkeypatch, capsys):
    _, _, engine = populate(api, tmp_path)
    url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setattr(
        reset_demo, "get_settings", lambda: SimpleNamespace(database_url=SecretStr(url))
    )
    before = rows(
        engine,
        "SELECT (SELECT count(*) FROM predictions), (SELECT count(*) FROM "
        "reviews), (SELECT count(*) FROM studies), (SELECT count(*) FROM audit_log)",
    )
    assert reset_demo.main([]) == 2
    out = capsys.readouterr().out
    assert "Dry run: nothing deleted" in out and "append-only" in out
    assert (
        rows(
            engine,
            "SELECT (SELECT count(*) FROM predictions), (SELECT count(*) FROM "
            "reviews), (SELECT count(*) FROM studies), (SELECT count(*) FROM "
            "audit_log)",
        )
        == before
    )
