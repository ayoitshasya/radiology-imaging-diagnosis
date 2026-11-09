# Radiology imaging diagnosis API

**Educational use only. Not for clinical use.** This API serves a classifier trained on
public RSNA Pneumonia data. Its outputs are model scores, not diagnoses, and must never be
used to make decisions about real patients.

**Reviewers: do not type patient names, patient IDs, dates of birth or any other patient
identifier into any field** (`reviewer`, `reason`, `comment`). Free text is stored only
in the reviews table, never copied into the audit log and never logged, but it is still
persisted.

Base URL (local demo): `http://127.0.0.1:8000`. Interactive docs are served at `/docs`;
the machine-readable schema is committed as [`docs/openapi.json`](openapi.json) and kept in
step by `python scripts/export_openapi.py` (a test fails if it is stale).

Every example below is a real response. Successful responses and the 404, 422, 502 and 503
errors were captured from the running stack (Orthanc, Postgres and the API) on the 80 demo
studies; the two 409 examples were captured from the same API code running against the
test harness (a fake Orthanc and a throwaway database), because producing them on the live
stack would require corrupting data. Long lists are shortened as noted.

## Conventions

- `{id}` in a path is the **Orthanc study ID** (five dash-separated hex groups, e.g.
  `29aa9e33-a3c9c0ba-d412334d-8decdd60-7eedb09b`). It must match `^[A-Za-z0-9._-]{1,64}$`, otherwise the request is
  rejected with 422 before any database or Orthanc call.
- Only the Orthanc study ID and the DICOM StudyInstanceUID identify a study. No patient
  name, patient ID or birth date is stored or returned.
- Every JSON response carries `"notice": "Educational use only. Not for clinical use."`.
  PNG responses carry it in the `X-Notice` header and are sent with
  `Cache-Control: no-store`.
- Errors are JSON with a `detail` field: a string, or for 422 a list of
  `{loc, msg, type}` objects.
- The API itself has no authentication. It is a local demo bound to 127.0.0.1; Orthanc
  and Postgres credentials stay server side in `.env`.

## Error codes

| Status | Meaning | Real example `detail` |
|---|---|---|
| 404 | Unknown or unsynced study; study not analysed yet; no matching route | `Unknown study; call POST /studies/sync first` / `Study not analysed yet; call POST .../analyse` |
| 409 | The DICOM in Orthanc does not match the synced study; or a heatmap would have to be recomputed with a different checkpoint than the one that made the prediction | `DICOM StudyInstanceUID does not match the synced study` / `Prediction was made with a different checkpoint; re-run analyse with force=true` (test harness) |
| 422 | Invalid input: body, query parameter or path ID | `Value error, reason is required when the decision is rejected` |
| 502 | Orthanc answered, but with an error (wrong credentials, server error) | `Orthanc rejected the credentials (401)` |
| 503 | Orthanc unreachable, or the model failed to load | `Orthanc not reachable: ConnectError` |

## Typical workflow

1. `POST /studies/sync` registers new Orthanc studies as pending.
2. `POST /studies/{id}/analyse` runs the model and Grad-CAM and stores a prediction.
3. `GET /studies/{id}/image` and `GET /studies/{id}/heatmap` show the input and overlay.
4. `POST /studies/{id}/review` records a reviewer's decision.
5. `GET /audit` shows what happened, newest first.

---

## GET /health

Checks Orthanc (`/system`), the database (`SELECT 1`) and whether the model loaded. Returns
200 only when all three pass, otherwise 503 with each component's state. Database errors
expose only the exception type.

Request: `GET /health`

Response `200`

```json
{
  "status": "ok",
  "checks": {
    "orthanc": {
      "ok": true,
      "version": "1.13.0"
    },
    "database": {
      "ok": true
    },
    "model": {
      "ok": true,
      "model_name": "densenet121-rsna-pneumonia",
      "checkpoint_sha256": "dfded9ad8bc13b45cc5fff5b4d333326840c87d0a2357ef1b02637ba49ba41e9",
      "threshold": 0.480127
    }
  },
  "notice": "Educational use only. Not for clinical use."
}
```

When Orthanc is unreachable (API started with `ORTHANC_URL` pointing at a closed port):


Response `503`

```json
{
  "status": "degraded",
  "checks": {
    "orthanc": {
      "ok": false,
      "error": "Orthanc not reachable: ConnectError"
    },
    "database": {
      "ok": true
    },
    "model": {
      "ok": true,
      "model_name": "densenet121-rsna-pneumonia",
      "checkpoint_sha256": "dfded9ad8bc13b45cc5fff5b4d333326840c87d0a2357ef1b02637ba49ba41e9",
      "threshold": 0.480127
    }
  },
  "notice": "Educational use only. Not for clinical use."
}
```

Status codes: 200, 503.

## GET /studies

Lists every study in Orthanc with its status: `not_synced` (in Orthanc only), `pending`
(synced, no prediction) or `analysed`, plus the latest prediction and the latest review of
that prediction. No parameters.

Request: `GET /studies`

Response `200`

```json
{
  "notice": "Educational use only. Not for clinical use.",
  "count": 80,
  "studies": [
    {
      "orthanc_study_id": "0076653e-a66505d8-a1aaa57b-68124ac8-a6932941",
      "study_instance_uid": "1.2.276.0.7230010.3.1.2.8323329.19132.1517874415.411944",
      "status": "analysed",
      "latest_prediction": {
        "prediction_id": 3,
        "probability": 0.31180739402770996,
        "label": 0,
        "threshold": 0.480127,
        "created_at": "2026-11-07T17:37:34.568488Z"
      },
      "latest_review": null
    },
    {
      "orthanc_study_id": "0231e54c-ab2fa3c7-402169e1-8a2ab3b8-3efea72e",
      "study_instance_uid": "1.2.276.0.7230010.3.1.2.8323329.12523.1517874365.526407",
      "status": "pending",
      "latest_prediction": null,
      "latest_review": null
    }
  ]
}
```

(Shortened to the first two of 80 entries.)

Status codes: 200; 502 or 503 if Orthanc fails.

## POST /studies/sync

Registers Orthanc studies the database does not know yet; they become `pending`. Uses
list-and-diff (one `GET /studies?expand` to Orthanc), is idempotent, never deletes, and
writes one `study_synced` audit event per new study. No parameters.

Request: `POST /studies/sync`

Response `200`

```json
{
  "notice": "Educational use only. Not for clinical use.",
  "orthanc_studies": 80,
  "added": 0,
  "already_synced": 80,
  "pending": 77,
  "missing_from_orthanc": 0
}
```

Status codes: 200; 502 or 503 if Orthanc fails.

## POST /studies/{id}/analyse

Fetches the study's DICOM from Orthanc into memory, checks its StudyInstanceUID, applies
the training preprocessing, runs the model and Grad-CAM, and stores the prediction with an
`analysis_completed` audit event. The label is `1` when the probability is at or above
the threshold chosen on the validation split (Youden's J); it is a model output, not a
diagnosis.

Idempotent: if a prediction exists, the stored one is returned with `"cached": true` and
an `analysis_returned_cached` event is written. Query parameter `force=true` adds a new
prediction instead; earlier rows are never changed.

First call:

Request: `POST /studies/{id}/analyse`

Response `200`

```json
{
  "notice": "Educational use only. Not for clinical use.",
  "prediction_id": 4,
  "orthanc_study_id": "f27b0b2c-8c0d643e-54be70e7-bffbb02f-adf19d3e",
  "study_instance_uid": "1.2.276.0.7230010.3.1.2.8323329.22597.1517874442.590609",
  "probability": 0.4155385494232178,
  "label": 0,
  "label_meaning": "1 = model score at or above the validation-chosen threshold (pneumonia opacity predicted); 0 = below it. A model output, not a diagnosis.",
  "threshold": 0.480127,
  "threshold_source": "validation split, Youden J",
  "model_name": "densenet121-rsna-pneumonia",
  "checkpoint_sha256": "dfded9ad8bc13b45cc5fff5b4d333326840c87d0a2357ef1b02637ba49ba41e9",
  "created_at": "2026-11-09T04:23:51.569777Z",
  "cached": false,
  "prediction_count": 1,
  "latest_review": null
}
```

Second call, same study:


Response `200`

```json
{
  "notice": "Educational use only. Not for clinical use.",
  "prediction_id": 4,
  "orthanc_study_id": "f27b0b2c-8c0d643e-54be70e7-bffbb02f-adf19d3e",
  "study_instance_uid": "1.2.276.0.7230010.3.1.2.8323329.22597.1517874442.590609",
  "probability": 0.4155385494232178,
  "label": 0,
  "label_meaning": "1 = model score at or above the validation-chosen threshold (pneumonia opacity predicted); 0 = below it. A model output, not a diagnosis.",
  "threshold": 0.480127,
  "threshold_source": "validation split, Youden J",
  "model_name": "densenet121-rsna-pneumonia",
  "checkpoint_sha256": "dfded9ad8bc13b45cc5fff5b4d333326840c87d0a2357ef1b02637ba49ba41e9",
  "created_at": "2026-11-09T04:23:51.569777Z",
  "cached": true,
  "prediction_count": 1,
  "latest_review": null
}
```

Status codes: 200; 404 unknown study; 409 UID mismatch; 422 malformed ID; 502/503 Orthanc;
503 model not loaded.

## GET /studies/{id}/result

The latest stored prediction, with `latest_review` for it.

Request: `GET /studies/{id}/result`

Response `200`

```json
{
  "notice": "Educational use only. Not for clinical use.",
  "prediction_id": 1,
  "orthanc_study_id": "29aa9e33-a3c9c0ba-d412334d-8decdd60-7eedb09b",
  "study_instance_uid": "1.2.276.0.7230010.3.1.2.8323329.25681.1517874466.262025",
  "probability": 0.5555332899093628,
  "label": 1,
  "label_meaning": "1 = model score at or above the validation-chosen threshold (pneumonia opacity predicted); 0 = below it. A model output, not a diagnosis.",
  "threshold": 0.480127,
  "threshold_source": "validation split, Youden J",
  "model_name": "densenet121-rsna-pneumonia",
  "checkpoint_sha256": "dfded9ad8bc13b45cc5fff5b4d333326840c87d0a2357ef1b02637ba49ba41e9",
  "created_at": "2026-11-07T17:31:34.772111Z",
  "cached": true,
  "prediction_count": 1,
  "latest_review": {
    "review_id": 1,
    "prediction_id": 1,
    "decision": "approved",
    "reviewer": "Demo Reviewer",
    "created_at": "2026-11-07T18:01:06.805212Z"
  }
}
```

Status codes: 200; 404 unknown study or not analysed; 422 malformed ID.

## GET /studies/{id}/image

The preprocessed 224x224 grayscale PNG the model sees (pixel-aligned with the heatmap),
built in memory; nothing is written to disk.

Request: `GET /studies/{id}/image`

Response `200` with headers `x-notice: Educational use only. Not for clinical use.`, `cache-control: no-store`

Body: <27282 bytes image/png>

Status codes: 200; 404 unknown study; 422 malformed ID; 502/503 Orthanc.

## GET /studies/{id}/heatmap

The Grad-CAM overlay PNG (224x224 RGB) for the study's latest prediction. Served from an
in-memory cache (`X-Heatmap-Source: cache`) or recomputed after eviction or a restart
(`recomputed`). Grad-CAM shows where the model's evidence came from; it is not a lesion
outline.

Request: `GET /studies/{id}/heatmap`

Response `200` with headers `x-notice: Educational use only. Not for clinical use.`, `cache-control: no-store`, `x-prediction-id: 1`, `x-heatmap-source: recomputed`

Body: <65434 bytes image/png>

Status codes: 200; 404 unknown study or not analysed; 409 checkpoint changed since the
prediction; 422 malformed ID; 502/503 Orthanc; 503 model not loaded.

## POST /studies/{id}/review

Records `approved` or `rejected` for the study's latest prediction. `reviewer` is required
(max 100 characters); `reason` is required for `rejected` and not accepted for `approved`
(max 1000); `comment` is optional (max 1000). Control and invisible formatting characters
are stripped and limits apply after cleaning. Unknown fields are rejected. Every call adds
a new review; none is edited. The review and its `review_submitted` audit event are
committed in one transaction; the audit event records the decision and reviewer but not
the reason or comment text.

**Do not type patient identifiers into `reviewer`, `reason` or `comment`.**

Request: `POST /studies/{id}/review`

```json
{
  "decision": "approved",
  "reviewer": "Demo Reviewer",
  "comment": "Documentation example; not a clinical judgment."
}
```

Response `201`

```json
{
  "notice": "Educational use only. Not for clinical use.",
  "review_id": 3,
  "prediction_id": 4,
  "orthanc_study_id": "f27b0b2c-8c0d643e-54be70e7-bffbb02f-adf19d3e",
  "study_instance_uid": "1.2.276.0.7230010.3.1.2.8323329.22597.1517874442.590609",
  "decision": "approved",
  "reason": null,
  "comment": "Documentation example; not a clinical judgment.",
  "reviewer": "Demo Reviewer",
  "created_at": "2026-11-09T04:23:52.867813Z"
}
```

Rejecting without a reason:

Request: `POST /studies/{id}/review`

```json
{
  "decision": "rejected",
  "reviewer": "Demo Reviewer"
}
```

Response `422`

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": [
        "body"
      ],
      "msg": "Value error, reason is required when the decision is rejected",
      "input": {
        "decision": "rejected",
        "reviewer": "Demo Reviewer"
      },
      "ctx": {
        "error": {}
      }
    }
  ]
}
```

Status codes: 201; 404 unknown study or no prediction yet; 422 invalid body or ID.

## GET /studies/{id}/reviews

Every review of the study's predictions, oldest first, each with its `prediction_id`.
Empty list if none.

Request: `GET /studies/{id}/reviews`

Response `200`

```json
{
  "notice": "Educational use only. Not for clinical use.",
  "orthanc_study_id": "549118cd-77973419-3c4a2bb5-ed3ba7cf-8e9e2a32",
  "count": 1,
  "reviews": [
    {
      "notice": "Educational use only. Not for clinical use.",
      "review_id": 2,
      "prediction_id": 2,
      "orthanc_study_id": "549118cd-77973419-3c4a2bb5-ed3ba7cf-8e9e2a32",
      "study_instance_uid": "1.2.276.0.7230010.3.1.2.8323329.15196.1517874384.263474",
      "decision": "rejected",
      "reason": "Demo review of the rejection path; not a clinical judgment.",
      "comment": null,
      "reviewer": "Demo Reviewer",
      "created_at": "2026-11-07T18:01:06.824020Z"
    }
  ]
}
```

Status codes: 200; 404 unknown study; 422 malformed ID.

## GET /audit

The append-only audit log, newest first (by `created_at`, then `id`), with a `total` for
the filters. Read-only: there are no write routes, and database triggers reject UPDATE,
DELETE and TRUNCATE.

| Parameter | Type | Rules |
|---|---|---|
| `study_instance_uid` | string | digits and dots, max 64 |
| `event_type` | string | `study_synced`, `analysis_completed`, `analysis_returned_cached`, `review_submitted`, `demo_reset` (written by `scripts/reset_demo_state.py`) |
| `since` | ISO 8601 datetime | inclusive; UTC if no timezone |
| `until` | ISO 8601 datetime | exclusive; UTC if no timezone; must not be before `since` |
| `limit` | integer | 1 to 100, default 50 |
| `offset` | integer | 0 or more, default 0 |

Request: `GET /audit?limit=2`

Response `200`

```json
{
  "notice": "Educational use only. Not for clinical use.",
  "total": 89,
  "limit": 2,
  "offset": 0,
  "items": [
    {
      "id": 89,
      "event_type": "review_submitted",
      "study_instance_uid": "1.2.276.0.7230010.3.1.2.8323329.22597.1517874442.590609",
      "detail": {
        "decision": "approved",
        "reviewer": "Demo Reviewer",
        "review_id": 3,
        "prediction_id": 4,
        "orthanc_study_id": "f27b0b2c-8c0d643e-54be70e7-bffbb02f-adf19d3e"
      },
      "created_at": "2026-11-09T04:23:52.867813Z"
    },
    {
      "id": 88,
      "event_type": "analysis_returned_cached",
      "study_instance_uid": "1.2.276.0.7230010.3.1.2.8323329.22597.1517874442.590609",
      "detail": {
        "prediction_id": 4,
        "orthanc_study_id": "f27b0b2c-8c0d643e-54be70e7-bffbb02f-adf19d3e"
      },
      "created_at": "2026-11-09T04:23:52.364813Z"
    }
  ]
}
```

Filtered by event type:

Request: `GET /audit?event_type=review_submitted&limit=1`

Response `200`

```json
{
  "notice": "Educational use only. Not for clinical use.",
  "total": 3,
  "limit": 1,
  "offset": 0,
  "items": [
    {
      "id": 89,
      "event_type": "review_submitted",
      "study_instance_uid": "1.2.276.0.7230010.3.1.2.8323329.22597.1517874442.590609",
      "detail": {
        "decision": "approved",
        "reviewer": "Demo Reviewer",
        "review_id": 3,
        "prediction_id": 4,
        "orthanc_study_id": "f27b0b2c-8c0d643e-54be70e7-bffbb02f-adf19d3e"
      },
      "created_at": "2026-11-09T04:23:52.867813Z"
    }
  ]
}
```

Status codes: 200; 422 invalid parameter, for example:

Request: `GET /audit?limit=101`

Response `422`

```json
{
  "detail": [
    {
      "type": "less_than_equal",
      "loc": [
        "query",
        "limit"
      ],
      "msg": "Input should be less than or equal to 100",
      "input": "101",
      "ctx": {
        "le": 100
      }
    }
  ]
}
```

Request: `GET /audit?event_type=deleted`

Response `422`

```json
{
  "detail": [
    {
      "type": "literal_error",
      "loc": [
        "query",
        "event_type"
      ],
      "msg": "Input should be 'study_synced', 'analysis_completed', 'analysis_returned_cached' or 'review_submitted'",
      "input": "deleted",
      "ctx": {
        "expected": "'study_synced', 'analysis_completed', 'analysis_returned_cached' or 'review_submitted'"
      }
    }
  ]
}
```

## More error examples

Unknown study (valid ID format, not synced):

Request: `GET /studies/00000000-00000000-00000000-00000000-00000000/result`

Response `404`

```json
{
  "detail": "Unknown study; call POST /studies/sync first"
}
```

Malformed study ID:

Request: `GET /studies/bad'id/result`

Response `422`

```json
{
  "detail": [
    {
      "type": "string_pattern_mismatch",
      "loc": [
        "path",
        "orthanc_study_id"
      ],
      "msg": "String should match pattern '^[A-Za-z0-9._-]{1,64}$'",
      "input": "bad'id",
      "ctx": {
        "pattern": "^[A-Za-z0-9._-]{1,64}$"
      }
    }
  ]
}
```

Synced study that has not been analysed:

Request: `GET /studies/8887d147-115546ca-c8cf0f2c-5163c3a9-77c4a74f/heatmap`

Response `404`

```json
{
  "detail": "Study not analysed yet; call POST .../analyse"
}
```

Orthanc rejecting the API's credentials (API started with a wrong `ORTHANC_PASSWORD`):

Request: `GET /studies`

Response `502`

```json
{
  "detail": "Orthanc rejected the credentials (401)"
}
```

Orthanc unreachable:

Request: `GET /studies`

Response `503`

```json
{
  "detail": "Orthanc not reachable: ConnectError"
}
```

DICOM in Orthanc does not match the synced study (test harness):

Request: `POST /studies/{id}/analyse`

Response `409`

```json
{
  "detail": "DICOM StudyInstanceUID does not match the synced study"
}
```

Heatmap would need a different checkpoint (test harness):

Request: `GET /studies/{id}/heatmap`

Response `409`

```json
{
  "detail": "Prediction was made with a different checkpoint; re-run analyse with force=true"
}
```
