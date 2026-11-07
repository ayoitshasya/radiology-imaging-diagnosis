"""GET /studies and POST /studies/sync against a fake Orthanc and a throwaway database."""

from sqlalchemy import text

NOTICE = "Educational use only. Not for clinical use."


def audit_count(engine, event_type: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM audit_log WHERE event_type = :e"), {"e": event_type}
        ).scalar_one()


def test_listing_before_sync_shows_not_synced(api, tmp_path):
    client, fake, _ = api
    fake.add_study(tmp_path, "s1")
    fake.add_study(tmp_path, "s2")
    body = client.get("/studies").json()
    assert body["count"] == 2 and body["notice"] == NOTICE
    assert {s["status"] for s in body["studies"]} == {"not_synced"}
    assert all(s["latest_prediction"] is None for s in body["studies"])


def test_sync_adds_new_studies_once_and_audits_each(api, tmp_path):
    client, fake, engine = api
    for oid in ("s1", "s2", "s3"):
        fake.add_study(tmp_path, oid)
    first = client.post("/studies/sync").json()
    assert (first["added"], first["already_synced"], first["pending"]) == (3, 0, 3)
    assert first["notice"] == NOTICE
    assert audit_count(engine, "study_synced") == 3

    second = client.post("/studies/sync").json()  # idempotent: nothing new
    assert (second["added"], second["already_synced"], second["pending"]) == (0, 3, 3)
    assert audit_count(engine, "study_synced") == 3

    fake.add_study(tmp_path, "s4")
    third = client.post("/studies/sync").json()
    assert third["added"] == 1 and audit_count(engine, "study_synced") == 4
    statuses = {
        s["orthanc_study_id"]: s["status"] for s in client.get("/studies").json()["studies"]
    }
    assert set(statuses.values()) == {"pending"}


def test_sync_counts_but_keeps_studies_missing_from_orthanc(api, tmp_path):
    client, fake, engine = api
    fake.add_study(tmp_path, "s1")
    fake.add_study(tmp_path, "s2")
    client.post("/studies/sync")
    del fake.studies["s2"]
    body = client.post("/studies/sync").json()
    assert body["missing_from_orthanc"] == 1 and body["orthanc_studies"] == 1
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM studies")).scalar_one() == 2


def test_orthanc_down_gives_503_and_changes_nothing(api, tmp_path):
    client, fake, engine = api
    fake.add_study(tmp_path, "s1")
    fake.down = True
    assert client.get("/studies").status_code == 503
    response = client.post("/studies/sync")
    assert response.status_code == 503 and "not reachable" in response.json()["detail"]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM studies")).scalar_one() == 0
    assert audit_count(engine, "study_synced") == 0


def test_listing_exposes_no_patient_tags(api, tmp_path):
    client, fake, _ = api
    fake.add_study(tmp_path, "s1")
    text_body = client.get("/studies").text
    assert "PatientName" not in text_body and "Anonymous" not in text_body
