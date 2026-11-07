"""POST /studies/{id}/review and GET /studies/{id}/reviews with fakes and a test database."""

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import backend.app.routers.reviews as reviews_module
from backend.app.models import AuditLog

NOTICE = "Educational use only. Not for clinical use."


def count(engine, sql: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar_one()


def analysed(api, tmp_path, oid="s1"):
    client, fake, engine = api
    fake.add_study(tmp_path, oid)
    client.post("/studies/sync")
    client.post(f"/studies/{oid}/analyse")
    return client, fake, engine


def test_approve_with_optional_comment(api, tmp_path):
    client, _, engine = analysed(api, tmp_path)
    response = client.post(
        "/studies/s1/review",
        json={"decision": "approved", "reviewer": "Reviewer A", "comment": "Looks consistent"},
    )
    body = response.json()
    assert response.status_code == 201
    assert body["decision"] == "approved" and body["reason"] is None
    assert body["comment"] == "Looks consistent" and body["notice"] == NOTICE
    with engine.connect() as conn:
        detail = conn.execute(
            text("SELECT detail FROM audit_log WHERE event_type = 'review_submitted'")
        ).scalar_one()
    assert detail["review_id"] == body["review_id"] and detail["decision"] == "approved"
    assert "Looks consistent" not in str(detail)  # free text stays out of the audit log


def test_reject_without_reason_is_422_and_stores_nothing(api, tmp_path):
    client, _, engine = analysed(api, tmp_path)
    for payload in (
        {"decision": "rejected", "reviewer": "Reviewer A"},
        {"decision": "rejected", "reviewer": "Reviewer A", "reason": "   \x07  "},
    ):
        response = client.post("/studies/s1/review", json=payload)
        assert response.status_code == 422
        assert "reason is required" in response.text
    assert count(engine, "SELECT count(*) FROM reviews") == 0
    assert count(engine, "SELECT count(*) FROM audit_log WHERE event_type='review_submitted'") == 0


def test_reject_with_reason(api, tmp_path):
    client, _, _ = analysed(api, tmp_path)
    response = client.post(
        "/studies/s1/review",
        json={"decision": "rejected", "reviewer": "Reviewer B", "reason": "Heatmap off target"},
    )
    assert response.status_code == 201 and response.json()["reason"] == "Heatmap off target"


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"decision": "approved", "reviewer": "A", "reason": "x"}, "use comment"),
        ({"decision": "maybe", "reviewer": "A"}, "decision"),
        ({"decision": "approved", "reviewer": "  \x00 "}, "reviewer"),
        ({"decision": "approved", "reviewer": "A" * 101}, "reviewer"),
        ({"decision": "rejected", "reviewer": "A", "reason": "r" * 1001}, "reason"),
        ({"decision": "approved", "reviewer": "A", "extra": 1}, "extra"),
    ],
)
def test_bad_review_input_is_422(api, tmp_path, payload, fragment):
    client, _, _ = analysed(api, tmp_path)
    response = client.post("/studies/s1/review", json=payload)
    assert response.status_code == 422 and fragment in response.text


def test_free_text_is_sanitised(api, tmp_path):
    client, _, _ = analysed(api, tmp_path)
    body = client.post(
        "/studies/s1/review",
        json={
            "decision": "rejected",
            "reviewer": " Dr‮X\x07 ",
            "reason": "line one\r\nline two​\x00",
        },
    ).json()
    assert body["reviewer"] == "DrX" and body["reason"] == "line one\nline two"


def test_two_reviews_add_rows_and_latest_is_shown(api, tmp_path):
    client, _, engine = analysed(api, tmp_path)
    first = client.post(
        "/studies/s1/review", json={"decision": "approved", "reviewer": "Reviewer A"}
    ).json()
    second = client.post(
        "/studies/s1/review",
        json={"decision": "rejected", "reviewer": "Reviewer B", "reason": "Second opinion"},
    ).json()
    assert second["review_id"] != first["review_id"]
    history = client.get("/studies/s1/reviews").json()
    assert history["count"] == 2 and history["notice"] == NOTICE
    assert [r["review_id"] for r in history["reviews"]] == [first["review_id"], second["review_id"]]
    assert history["reviews"][0]["decision"] == "approved"  # first row unchanged
    assert count(engine, "SELECT count(*) FROM audit_log WHERE event_type='review_submitted'") == 2

    listed = client.get("/studies").json()["studies"][0]["latest_review"]
    result = client.get("/studies/s1/result").json()["latest_review"]
    assert listed["review_id"] == result["review_id"] == second["review_id"]
    assert result["decision"] == "rejected"


def test_forced_reanalysis_has_no_current_review(api, tmp_path):
    client, _, _ = analysed(api, tmp_path)
    client.post("/studies/s1/review", json={"decision": "approved", "reviewer": "A"})
    client.post("/studies/s1/analyse", params={"force": "true"})
    assert client.get("/studies/s1/result").json()["latest_review"] is None
    assert client.get("/studies/s1/reviews").json()["count"] == 1  # history kept


def test_review_of_unanalysed_or_unknown_study_is_404(api, tmp_path):
    client, fake, engine = api
    fake.add_study(tmp_path, "s1")
    client.post("/studies/sync")
    review = {"decision": "approved", "reviewer": "A"}
    assert client.post("/studies/s1/review", json=review).status_code == 404
    assert client.post("/studies/nope/review", json=review).status_code == 404
    assert client.get("/studies/nope/reviews").status_code == 404
    assert client.get("/studies/s1/reviews").json()["count"] == 0
    assert count(engine, "SELECT count(*) FROM reviews") == 0


def test_failed_audit_write_rolls_back_the_review(api, tmp_path, monkeypatch):
    client, _, engine = analysed(api, tmp_path)

    def broken_audit(session, *args, **kwargs):
        session.add(AuditLog(event_type=None, study_instance_uid=None, detail={}))

    monkeypatch.setattr(reviews_module, "record_event", broken_audit)
    with pytest.raises(IntegrityError):
        client.post("/studies/s1/review", json={"decision": "approved", "reviewer": "A"})
    assert count(engine, "SELECT count(*) FROM reviews") == 0
    assert count(engine, "SELECT count(*) FROM audit_log WHERE event_type='review_submitted'") == 0


def test_free_text_never_logged_at_info_or_above(api, tmp_path, caplog):
    client, _, _ = analysed(api, tmp_path)
    secrets = ("ReviewerZq81", "ReasonZq81", "CommentZq81")
    caplog.set_level(logging.DEBUG)
    client.post(
        "/studies/s1/review",
        json={
            "decision": "rejected",
            "reviewer": secrets[0],
            "reason": secrets[1],
            "comment": secrets[2],
        },
    )
    logged = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.INFO)
    assert not any(s in logged for s in secrets)
