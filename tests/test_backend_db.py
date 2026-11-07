"""Backend schema and health tests against a throwaway Postgres database.

The database tests run the real Alembic migration into a separate database called
radiology_test on the compose Postgres, so the dev database is never touched. They are
skipped when Postgres is not reachable.
"""

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from torch import nn

from backend.app.main import create_app
from backend.app.model_service import ModelService
from backend.app.orthanc import OrthancClient
from backend.app.settings import ROOT, get_settings

TEST_DB = "radiology_test"
SHA = "a" * 64


def _server_url():
    try:
        return make_url(get_settings().database_url.get_secret_value())
    except Exception:  # noqa: BLE001 - missing settings means the DB tests cannot run
        return None


@pytest.fixture(scope="module")
def test_engine():
    """Fresh radiology_test database with the real migration applied."""
    url = _server_url()
    if url is None:
        pytest.skip("DATABASE_URL not configured")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    except DBAPIError:
        pytest.skip("Postgres not reachable")
    test_url = url.set(database=TEST_DB).render_as_string(hide_password=False)
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.attributes["database_url"] = test_url
    command.upgrade(cfg, "head")
    engine = create_engine(test_url)
    yield engine
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
    admin.dispose()


def insert_audit(engine) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO audit_log (event_type, study_instance_uid, detail) "
                "VALUES ('test', '1.2.3', '{\"k\": 1}') RETURNING id"
            )
        ).scalar_one()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET event_type = 'changed' WHERE id = :id",
        "DELETE FROM audit_log WHERE id = :id",
        "TRUNCATE audit_log",
    ],
)
def test_audit_log_rejects_update_delete_and_truncate(test_engine, statement):
    row_id = insert_audit(test_engine)
    with pytest.raises(DBAPIError, match="append-only"):
        with test_engine.begin() as conn:
            conn.execute(text(statement), {"id": row_id})
    with test_engine.connect() as conn:
        row = conn.execute(
            text("SELECT event_type FROM audit_log WHERE id = :id"), {"id": row_id}
        ).one()
    assert row.event_type == "test"


def test_audit_log_still_accepts_inserts(test_engine):
    first, second = insert_audit(test_engine), insert_audit(test_engine)
    assert second > first


def test_schema_has_no_personal_identifier_columns(test_engine):
    forbidden = {"patient_name", "patient_id", "birth_date", "patient_birth_date", "name"}
    columns = {
        c["name"]
        for table in ("predictions", "reviews", "audit_log")
        for c in inspect(test_engine).get_columns(table)
    }
    assert not columns & forbidden


def insert_prediction(conn, **overrides) -> int:
    values = {"oid": "o1", "uid": "1.2.3", "p": 0.7, "label": 1, "thr": 0.48, "sha": SHA}
    values.update(overrides)
    return conn.execute(
        text(
            "INSERT INTO predictions (orthanc_study_id, study_instance_uid, probability, "
            "label, threshold, model_name, checkpoint_sha256) "
            "VALUES (:oid, :uid, :p, :label, :thr, 'm', :sha) RETURNING id"
        ),
        values,
    ).scalar_one()


@pytest.mark.parametrize(
    "overrides",
    [{"p": 1.5}, {"label": 2}, {"thr": -0.1}, {"sha": "not-a-hash"}],
)
def test_prediction_constraints_reject_bad_values(test_engine, overrides):
    with pytest.raises(IntegrityError):
        with test_engine.begin() as conn:
            insert_prediction(conn, **overrides)


def test_rejection_requires_a_reason(test_engine):
    with test_engine.begin() as conn:
        pid = insert_prediction(conn)
        conn.execute(
            text(
                "INSERT INTO reviews (prediction_id, decision, reason, reviewer) "
                "VALUES (:p, 'approved', NULL, 'r1')"
            ),
            {"p": pid},
        )
    for reason in (None, "   "):
        with pytest.raises(IntegrityError):
            with test_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO reviews (prediction_id, decision, reason, reviewer) "
                        "VALUES (:p, 'rejected', :r, 'r1')"
                    ),
                    {"p": pid, "r": reason},
                )


# Health endpoint with injected fakes -------------------------------------------------


def fake_model() -> ModelService:
    return ModelService(
        model=nn.Identity(),
        model_name="test-model",
        checkpoint_sha256=SHA,
        threshold=0.48,
        device="cpu",
        target_layer="none",
    )


def orthanc_client(handler) -> OrthancClient:
    return OrthancClient(
        "http://orthanc.test", "u", "p", 2.0, transport=httpx.MockTransport(handler)
    )


def orthanc_up(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"Version": "1.13.0"})


def orthanc_down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def test_health_ok_when_all_dependencies_work(test_engine):
    app = create_app(
        orthanc=orthanc_client(orthanc_up), engine=test_engine, model_service=fake_model()
    )
    with TestClient(app) as client:
        response = client.get("/health")
    body = response.json()
    assert response.status_code == 200 and body["status"] == "ok"
    assert body["checks"]["model"]["threshold"] == 0.48
    assert body["notice"] == "Educational use only. Not for clinical use."


def test_health_503_when_orthanc_down(test_engine):
    app = create_app(
        orthanc=orthanc_client(orthanc_down), engine=test_engine, model_service=fake_model()
    )
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["checks"]["orthanc"]["ok"] is False
    assert "not reachable" in response.json()["checks"]["orthanc"]["error"]


def test_health_503_when_database_down():
    dead = create_engine(
        "postgresql+psycopg2://u:p@127.0.0.1:1/none", connect_args={"connect_timeout": 2}
    )
    app = create_app(orthanc=orthanc_client(orthanc_up), engine=dead, model_service=fake_model())
    with TestClient(app) as client:
        response = client.get("/health")
    db = response.json()["checks"]["database"]
    assert response.status_code == 503 and db["ok"] is False
    assert db["error"] == "OperationalError"  # type name only, no connection details


def test_settings_repr_hides_secrets():
    text_repr = repr(get_settings())
    assert get_settings().orthanc_password.get_secret_value() not in text_repr
    assert get_settings().database_url.get_secret_value() not in text_repr
