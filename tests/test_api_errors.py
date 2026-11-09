"""Error paths not covered elsewhere: unknown and malformed IDs, 502, model not loaded."""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import backend.app.main as main_module
from backend.app.main import create_app
from tests.conftest import FakeOrthanc

STUDY_ENDPOINTS = [
    ("post", "/studies/{id}/analyse"),
    ("get", "/studies/{id}/result"),
    ("get", "/studies/{id}/image"),
    ("get", "/studies/{id}/heatmap"),
    ("post", "/studies/{id}/review"),
    ("get", "/studies/{id}/reviews"),
]
REVIEW = {"decision": "approved", "reviewer": "A"}


def call(client, method: str, template: str, study_id: str):
    url = template.format(id=study_id)
    if method == "post" and url.endswith("/review"):
        return client.post(url, json=REVIEW)
    return getattr(client, method)(url)


@pytest.mark.parametrize(("method", "template"), STUDY_ENDPOINTS)
def test_unknown_study_is_404_on_every_endpoint_without_contacting_orthanc(
    api, tmp_path, method, template
):
    client, fake, _ = api
    fake.add_study(tmp_path, "s1")
    client.post("/studies/sync")
    fake.requests.clear()
    response = call(client, method, template, "not-a-synced-study")
    assert response.status_code == 404
    assert fake.requests == []  # rejected before any Orthanc call


MALFORMED = [
    ("%00", 422),  # was a 500 (NUL reached the database) before path validation
    ("\x00", 422),
    ("s1'--", 422),  # quote: fails the ID pattern
    ("a" * 300, 422),  # too long
    ("../system", 404),  # contains '/', matches no route at all
    ("s1/../../instances", 404),
]
# The NUL case (the one that crashed) on every endpoint proves each one validates its path;
# the other forms exercise the shared pattern once, on analyse.
CASES = [(m, t, "%00", 422) for m, t in STUDY_ENDPOINTS] + [
    (*STUDY_ENDPOINTS[0], bad, code) for bad, code in MALFORMED[1:]
]


@pytest.mark.parametrize(("method", "template", "bad_id", "expected"), CASES)
def test_malformed_ids_never_reach_orthanc(api, tmp_path, method, template, bad_id, expected):
    client, fake, engine = api
    fake.add_study(tmp_path, "s1")
    client.post("/studies/sync")
    fake.requests.clear()
    response = call(client, method, template, quote(bad_id, safe=""))
    assert response.status_code == expected
    assert fake.requests == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM predictions")).scalar_one() == 0


def test_orthanc_error_response_is_502_and_stores_nothing(api, tmp_path):
    client, fake, engine = api
    fake.add_study(tmp_path, "s1")
    client.post("/studies/sync")
    fake.file_status["s1"] = 500
    response = client.post("/studies/s1/analyse")
    assert response.status_code == 502 and "HTTP 500" in response.json()["detail"]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM predictions")).scalar_one() == 0


def test_model_load_failure_is_reported_and_blocks_only_model_endpoints(
    api_engine, tmp_path, monkeypatch
):
    def failing_load(settings):
        raise RuntimeError("checkpoint unreadable")

    monkeypatch.setattr(main_module, "load_model_service", failing_load)
    fake = FakeOrthanc()
    fake.add_study(tmp_path, "s1")
    with TestClient(create_app(orthanc=fake.client(), engine=api_engine)) as client:
        health = client.get("/health")
        assert health.status_code == 503
        assert health.json()["checks"]["model"] == {
            "ok": False,
            "error": "RuntimeError: checkpoint unreadable",
        }
        assert client.post("/studies/sync").status_code == 200  # no model needed
        assert client.get("/studies").status_code == 200
        analyse = client.post("/studies/s1/analyse")
        assert analyse.status_code == 503 and "Model not loaded" in analyse.json()["detail"]


def test_heatmap_follows_the_latest_prediction_after_force(api, tmp_path):
    client, fake, _ = api
    fake.add_study(tmp_path, "s1")
    client.post("/studies/sync")
    first = client.post("/studies/s1/analyse").json()
    forced = client.post("/studies/s1/analyse", params={"force": "true"}).json()
    heatmap = client.get("/studies/s1/heatmap")
    assert heatmap.headers["x-prediction-id"] == str(forced["prediction_id"])
    assert forced["prediction_id"] != first["prediction_id"]
    result = client.get("/studies/s1/result").json()
    assert result["prediction_id"] == forced["prediction_id"] and result["prediction_count"] == 2
