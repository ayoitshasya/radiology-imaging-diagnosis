"""POST /studies/{id}/analyse and GET /studies/{id}/result with fakes and a test database."""

import io

import pydicom
import pytest
from sqlalchemy import text

from ml.explainability.gradcam import predict_probability
from ml.preprocessing.build_dataset import preprocess_dicom

NOTICE = "Educational use only. Not for clinical use."


def count(engine, sql: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar_one()


def synced(api, tmp_path, oid="s1", **kwargs):
    client, fake, engine = api
    fake.add_study(tmp_path, oid, **kwargs)
    client.post("/studies/sync")
    return client, fake, engine


def test_analyse_unknown_study_is_404(api):
    client, _, engine = api
    response = client.post("/studies/nope/analyse")
    assert response.status_code == 404 and "sync" in response.json()["detail"]
    assert count(engine, "SELECT count(*) FROM predictions") == 0


def test_analyse_returns_full_prediction_and_audits(api, tmp_path, test_model_service):
    client, _, engine = synced(api, tmp_path)
    body = client.post("/studies/s1/analyse").json()
    assert 0.0 <= body["probability"] <= 1.0
    assert body["label"] == int(body["probability"] >= 0.5)
    assert body["threshold"] == 0.5 and body["model_name"] == "test-densenet"
    assert body["checkpoint_sha256"] == "b" * 64
    assert body["notice"] == NOTICE and body["cached"] is False
    assert count(engine, "SELECT count(*) FROM predictions") == 1
    assert (
        count(engine, "SELECT count(*) FROM audit_log WHERE event_type='analysis_completed'") == 1
    )
    assert len(client.app.state.overlay_cache) == 1
    statuses = {s["status"] for s in client.get("/studies").json()["studies"]}
    assert statuses == {"analysed"}


def test_api_probability_matches_shared_pipeline(api, tmp_path, test_model_service):
    client, fake, _ = synced(api, tmp_path, photometric="MONOCHROME1")
    body = client.post("/studies/s1/analyse").json()
    ds = pydicom.dcmread(io.BytesIO(fake.studies["s1"]["dicom"]))
    expected = predict_probability(test_model_service.model, preprocess_dicom(ds, 224))
    assert body["probability"] == pytest.approx(expected)


def test_second_analyse_returns_stored_result_and_audits(api, tmp_path):
    client, _, engine = synced(api, tmp_path)
    first = client.post("/studies/s1/analyse").json()
    second = client.post("/studies/s1/analyse").json()
    assert second["cached"] is True and second["prediction_id"] == first["prediction_id"]
    assert second["probability"] == first["probability"]
    assert count(engine, "SELECT count(*) FROM predictions") == 1
    assert (
        count(engine, "SELECT count(*) FROM audit_log WHERE event_type='analysis_returned_cached'")
        == 1
    )


def test_force_adds_a_new_prediction_and_keeps_the_old(api, tmp_path):
    client, _, engine = synced(api, tmp_path)
    first = client.post("/studies/s1/analyse").json()
    forced = client.post("/studies/s1/analyse", params={"force": "true"}).json()
    assert forced["cached"] is False and forced["prediction_id"] != first["prediction_id"]
    assert forced["prediction_count"] == 2
    with engine.connect() as conn:
        old = conn.execute(
            text("SELECT probability FROM predictions WHERE id = :i"), {"i": first["prediction_id"]}
        ).scalar_one()
        forced_flags = (
            conn.execute(
                text(
                    "SELECT detail->>'forced' FROM audit_log WHERE event_type='analysis_completed' "
                    "ORDER BY id"
                )
            )
            .scalars()
            .all()
        )
    assert old == first["probability"]
    assert forced_flags == ["false", "true"]


def test_result_endpoint(api, tmp_path):
    client, _, _ = synced(api, tmp_path)
    assert client.get("/studies/s1/result").status_code == 404  # synced, not analysed
    assert client.get("/studies/unknown/result").status_code == 404
    analysed = client.post("/studies/s1/analyse").json()
    result = client.get("/studies/s1/result").json()
    assert result["prediction_id"] == analysed["prediction_id"] and result["notice"] == NOTICE


def test_uid_mismatch_is_409_and_stores_nothing(api, tmp_path):
    client, fake, engine = synced(api, tmp_path)
    fake.add_study(tmp_path, "other")
    fake.studies["s1"]["dicom"] = fake.studies["other"]["dicom"]  # wrong image behind s1
    response = client.post("/studies/s1/analyse")
    assert response.status_code == 409
    assert count(engine, "SELECT count(*) FROM predictions") == 0
    assert (
        count(engine, "SELECT count(*) FROM audit_log WHERE event_type='analysis_completed'") == 0
    )


def test_orthanc_down_during_analyse_is_503_and_stores_nothing(api, tmp_path):
    client, fake, engine = synced(api, tmp_path)
    fake.down = True
    assert client.post("/studies/s1/analyse").status_code == 503
    assert count(engine, "SELECT count(*) FROM predictions") == 0
