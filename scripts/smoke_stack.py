"""Smoke test a running stack end to end through the API. Educational use only.

Checks, in order: /health, sync, the study list, analysing one study, submitting one
review, finding that review in the audit log, and fetching the study's image and
heatmap. Prints one PASS or FAIL line per step and exits 1 at the first failure (later
steps depend on earlier ones), 0 when every step passes.

It writes to the stack it tests: one prediction (for the first pending study; if every
study is already analysed the stored result is returned instead), one review signed
"smoke test", and the matching audit events. Run it against a demo stack only.

The API needs no credentials, so this script never reads .env and holds no secrets; it
prints studies by the last 12 characters of their UID only.

Usage:
    python scripts/smoke_stack.py                          # http://127.0.0.1:8000
    python scripts/smoke_stack.py --base-url http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

import httpx

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
NOTICE = "Educational use only. Not for clinical use."
REVIEWER = "smoke test"


class SmokeFailure(Exception):
    """A step's check failed; the message says what was expected."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def short(uid: str) -> str:
    return uid[-12:]


def expect(resp: httpx.Response, status: int) -> httpx.Response:
    """Fail with the status and the API's short `detail` (never a raw body)."""
    if resp.status_code != status:
        detail = ""
        try:
            detail = str(resp.json().get("detail", ""))[:200]
        except ValueError:
            pass
        raise SmokeFailure(f"expected HTTP {status}, got {resp.status_code} {detail}".rstrip())
    return resp


def step_health(client: httpx.Client, ctx: dict) -> str:
    body = expect(client.get("/health"), 200).json()
    check(body.get("status") == "ok", f"status is {body.get('status')!r}")
    model = body["checks"]["model"]
    ctx["threshold"] = model["threshold"]
    return (
        f"orthanc {body['checks']['orthanc'].get('version')}, database ok, model "
        f"{model['model_name']} (sha256 {model['checkpoint_sha256'][:12]}, threshold "
        f"{model['threshold']})"
    )


def step_sync(client: httpx.Client, ctx: dict) -> str:
    body = expect(client.post("/studies/sync"), 200).json()
    return (
        f"{body['orthanc_studies']} in Orthanc, {body['added']} added, "
        f"{body['already_synced']} already synced"
    )


def step_list(client: httpx.Client, ctx: dict) -> str:
    studies = expect(client.get("/studies"), 200).json()["studies"]
    check(len(studies) > 0, "no studies listed; upload the demo set first")
    pending = [s for s in studies if s["status"] == "pending"]
    synced = [s for s in studies if s["status"] in ("pending", "analysed")]
    check(len(synced) > 0, "no synced study to analyse")
    chosen = (pending or synced)[0]
    ctx["study"] = chosen
    return (
        f"{len(studies)} studies ({len(pending)} pending); using study ending "
        f"{short(chosen['study_instance_uid'])}"
    )


def step_analyse(client: httpx.Client, ctx: dict) -> str:
    oid = ctx["study"]["orthanc_study_id"]
    body = expect(client.post(f"/studies/{oid}/analyse"), 200).json()
    p, label, threshold = body["probability"], body["label"], body["threshold"]
    check(0.0 <= p <= 1.0, f"probability {p} outside [0, 1]")
    check(label == int(p >= threshold), f"label {label} disagrees with {p} vs {threshold}")
    check(body.get("notice") == NOTICE, "educational-use notice missing")
    ctx["prediction_id"] = body["prediction_id"]
    return (
        f"prediction {body['prediction_id']}, probability {p:.4f}, label {label}"
        f"{' (stored result returned)' if body.get('cached') else ''}"
    )


def step_review(client: httpx.Client, ctx: dict) -> str:
    oid = ctx["study"]["orthanc_study_id"]
    body = expect(
        client.post(
            f"/studies/{oid}/review",
            json={
                "decision": "approved",
                "reviewer": REVIEWER,
                "comment": "Automated stack smoke test.",
            },
        ),
        201,
    ).json()
    check(body["prediction_id"] == ctx["prediction_id"], "review attached to another prediction")
    ctx["review_id"] = body["review_id"]
    return f"review {body['review_id']} on prediction {body['prediction_id']}"


def step_audit(client: httpx.Client, ctx: dict) -> str:
    params = {
        "study_instance_uid": ctx["study"]["study_instance_uid"],
        "event_type": "review_submitted",
        "limit": 10,
    }
    body = expect(client.get("/audit", params=params), 200).json()
    ids = [item["detail"].get("review_id") for item in body["items"]]
    check(ctx["review_id"] in ids, f"review {ctx['review_id']} not in the audit log")
    return f"review_submitted event for review {ctx['review_id']} found ({body['total']} for study)"


def png_step(kind: str) -> Callable[[httpx.Client, dict], str]:
    def step(client: httpx.Client, ctx: dict) -> str:
        resp = expect(client.get(f"/studies/{ctx['study']['orthanc_study_id']}/{kind}"), 200)
        check(resp.headers.get("content-type") == "image/png", "content type is not image/png")
        check(resp.content.startswith(PNG_SIGNATURE), "body is not a PNG")
        check(resp.headers.get("x-notice") == NOTICE, "X-Notice header missing")
        return f"{len(resp.content)} bytes PNG with notice header"

    return step


STEPS: list[tuple[str, Callable[[httpx.Client, dict], str]]] = [
    ("health", step_health),
    ("sync", step_sync),
    ("list studies", step_list),
    ("analyse", step_analyse),
    ("review", step_review),
    ("audit log", step_audit),
    ("image", png_step("image")),
    ("heatmap", png_step("heatmap")),
]


def run(client: httpx.Client, out: Callable[[str], None] = print) -> int:
    """Run every step in order; return 0 if all pass, 1 at the first failure."""
    ctx: dict = {}
    for name, step in STEPS:
        try:
            out(f"PASS {name}: {step(client, ctx)}")
        except SmokeFailure as exc:
            out(f"FAIL {name}: {exc}")
            return 1
        except httpx.HTTPError as exc:
            out(f"FAIL {name}: cannot reach the API ({type(exc).__name__})")
            return 1
    out(f"Smoke test passed: {len(STEPS)} of {len(STEPS)} steps.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Smoke test a running stack through the API.")
    p.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    p.add_argument("--timeout", type=float, default=120.0, help="seconds per request")
    args = p.parse_args(argv)
    print(f"Smoke testing {args.base_url} (educational use only)")
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        return run(client)


if __name__ == "__main__":
    sys.exit(main())
