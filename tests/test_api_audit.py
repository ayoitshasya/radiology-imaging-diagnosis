"""GET /audit: filters, pagination, validation, and no way to change rows via the API."""

import pytest
from sqlalchemy import text

from backend.app.audit import record_event

NOTICE = "Educational use only. Not for clinical use."
UID_A, UID_B = "1.2.3.1", "1.2.3.2"


@pytest.fixture
def seeded(api):
    """Six events with fixed timestamps on 2026-01-01..06 (UTC), two studies."""
    client, _, engine = api
    rows = [
        ("study_synced", UID_A, "2026-01-01T10:00:00+00:00"),
        ("study_synced", UID_B, "2026-01-02T10:00:00+00:00"),
        ("analysis_completed", UID_A, "2026-01-03T10:00:00+00:00"),
        ("analysis_completed", UID_B, "2026-01-04T10:00:00+00:00"),
        ("review_submitted", UID_A, "2026-01-05T10:00:00+00:00"),
        ("analysis_returned_cached", UID_A, "2026-01-06T10:00:00+00:00"),
    ]
    with engine.begin() as conn:
        for event, uid, ts in rows:
            conn.execute(
                text(
                    "INSERT INTO audit_log (event_type, study_instance_uid, detail, created_at) "
                    "VALUES (:e, :u, '{}', :t)"
                ),
                {"e": event, "u": uid, "t": ts},
            )
    return client, engine


def test_newest_first_with_total_and_notice(seeded):
    client, _ = seeded
    body = client.get("/audit").json()
    assert body["total"] == 6 and body["notice"] == NOTICE
    days = [item["created_at"][:10] for item in body["items"]]
    assert days == sorted(days, reverse=True) and days[0] == "2026-01-06"


def test_filters_by_study_and_event_type(seeded):
    client, _ = seeded
    assert client.get("/audit", params={"study_instance_uid": UID_A}).json()["total"] == 4
    by_type = client.get("/audit", params={"event_type": "analysis_completed"}).json()
    assert by_type["total"] == 2
    both = client.get(
        "/audit", params={"study_instance_uid": UID_B, "event_type": "analysis_completed"}
    ).json()
    assert both["total"] == 1 and both["items"][0]["study_instance_uid"] == UID_B


def test_date_range_is_inclusive_since_exclusive_until(seeded):
    client, _ = seeded
    body = client.get(
        "/audit",
        params={"since": "2026-01-02T10:00:00Z", "until": "2026-01-05T10:00:00Z"},
    ).json()
    assert body["total"] == 3  # Jan 2, 3, 4; Jan 5 is excluded by until
    naive = client.get("/audit", params={"since": "2026-01-05T10:00:00"}).json()
    assert naive["total"] == 2  # no timezone means UTC


def test_pagination_pages_do_not_overlap(seeded):
    client, _ = seeded
    seen = []
    for offset in (0, 2, 4):
        page = client.get("/audit", params={"limit": 2, "offset": offset}).json()
        assert page["total"] == 6 and page["limit"] == 2 and page["offset"] == offset
        seen += [item["id"] for item in page["items"]]
    assert len(seen) == len(set(seen)) == 6
    assert client.get("/audit", params={"limit": 2, "offset": 6}).json()["items"] == []


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({"limit": 101}, "less than or equal to 100"),
        ({"limit": 0}, "greater than or equal to 1"),
        ({"offset": -1}, "greater than or equal to 0"),
        ({"event_type": "deleted_everything"}, "study_synced"),
        ({"study_instance_uid": "not-a-uid"}, "pattern"),
        ({"since": "yesterday"}, "datetime"),
        (
            {"since": "2026-01-05T00:00:00Z", "until": "2026-01-01T00:00:00Z"},
            "since must not be after until",
        ),
    ],
)
def test_bad_query_parameters_are_clear_422s(seeded, params, fragment):
    client, _ = seeded
    response = client.get("/audit", params=params)
    assert response.status_code == 422 and fragment in response.text


def test_audit_rows_cannot_be_changed_through_the_api(seeded):
    client, engine = seeded
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT id, event_type, detail FROM audit_log ORDER BY id")
        ).all()
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/audit").status_code == 405
    first_id = before[0].id
    for method in ("put", "patch", "delete"):
        assert getattr(client, method)(f"/audit/{first_id}").status_code in (404, 405)
    with engine.connect() as conn:
        after = conn.execute(text("SELECT id, event_type, detail FROM audit_log ORDER BY id")).all()
    assert after == before


def test_record_event_rejects_unknown_types(api):
    _, _, engine = api
    from sqlalchemy.orm import Session

    with Session(engine) as session, pytest.raises(ValueError, match="Unknown audit event"):
        record_event(session, "made_up_event", None, {})
