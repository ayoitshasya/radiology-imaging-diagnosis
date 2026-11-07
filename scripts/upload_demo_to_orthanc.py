"""Upload the leakage-safe demo studies to Orthanc, anonymised, without duplicates.

Educational use only; never real patient data. Reads data/demo/test_studies.csv, finds
each study's DICOM under data/raw by StudyInstanceUID, replaces identifying tags in
memory (files on disk are not modified) and uploads it to Orthanc's REST API.

Safe to re-run: a study already in Orthanc (looked up by StudyInstanceUID) is skipped,
and Orthanc itself is configured with OverwriteInstances false, so a duplicate upload is
answered "AlreadyStored" and changes nothing.

Credentials come from the environment or .env (ORTHANC_URL, ORTHANC_USERNAME,
ORTHANC_PASSWORD). Prints counts only; no identifiers.

Usage:
    python scripts/upload_demo_to_orthanc.py
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
from pathlib import Path

import httpx
import pandas as pd
import pydicom
import yaml
from pydicom.dataset import Dataset

ROOT = Path(__file__).resolve().parents[1]

# Tags holding identity, dates or staff names in the RSNA files, cleared before upload.
BLANKED_TAGS = ("ReferringPhysicianName", "AccessionNumber", "StudyID", "StudyDate", "StudyTime")
REMOVED_TAGS = ("PatientBirthDate", "OtherPatientIDs", "OtherPatientNames")
MAX_REPORTED_AGE = 89


def read_env(path: Path) -> dict[str, str]:
    """Environment variables, falling back to KEY=VALUE lines in ``path`` if present."""
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values | {k: v for k, v in os.environ.items() if k in values or k.startswith("ORTHANC_")}


def anonymise(ds: Dataset) -> Dataset:
    """Replace or remove identifying tags in place and return the dataset.

    PatientID becomes a hash of the StudyInstanceUID, so it is identical on every run (no
    duplicate patients in Orthanc) and cannot be traced back to the RSNA patient key.
    StudyInstanceUID is kept because it links Orthanc to the project's manifests. Ages
    above 89 are capped, following the HIPAA safe-harbour rule for ages.
    """
    study_uid = str(ds.StudyInstanceUID)
    ds.PatientName = "Anonymous"
    ds.PatientID = "ANON-" + hashlib.sha256(study_uid.encode()).hexdigest()[:16]
    for keyword in REMOVED_TAGS:
        if keyword in ds:
            delattr(ds, keyword)
    for keyword in BLANKED_TAGS:
        if keyword in ds:
            setattr(ds, keyword, "")
    age = str(ds.get("PatientAge", "")).strip().upper().rstrip("Y")
    if age.isdigit() and int(age) > MAX_REPORTED_AGE:
        ds.PatientAge = "090Y"
    ds.PatientIdentityRemoved = "YES"
    ds.DeidentificationMethod = "Patient name and ID replaced, dates and staff names cleared"
    return ds


def to_bytes(ds: Dataset) -> bytes:
    """Serialise a dataset to DICOM Part 10 bytes."""
    buffer = io.BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def index_dicoms(pattern: str, wanted: set[str]) -> dict[str, Path]:
    """Map StudyInstanceUID to DICOM path for the wanted studies (headers only, in memory)."""
    found: dict[str, Path] = {}
    for path in sorted(ROOT.glob(pattern)):
        uid = str(pydicom.dcmread(path, stop_before_pixels=True).StudyInstanceUID)
        if uid in wanted:
            found[uid] = path
    return found


def study_in_orthanc(client: httpx.Client, study_uid: str) -> bool:
    """True if Orthanc already holds a study with this StudyInstanceUID."""
    response = client.post("/tools/lookup", content=study_uid)
    response.raise_for_status()
    return any(item.get("Type") == "Study" for item in response.json())


def main() -> int:
    """Upload every demo study not yet in Orthanc and print counts."""
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    env = read_env(ROOT / ".env")
    missing_vars = [
        k for k in ("ORTHANC_URL", "ORTHANC_USERNAME", "ORTHANC_PASSWORD") if not env.get(k)
    ]
    if missing_vars:
        raise SystemExit(f"Set {', '.join(missing_vars)} in the environment or .env")

    demo = pd.read_csv(ROOT / cfg["demo"]["output"])
    paths = index_dicoms(cfg["orthanc_upload"]["raw_glob"], set(demo["image_id"]))
    counts = {
        "rows": len(demo),
        "dicom_found": len(paths),
        "dicom_missing": 0,
        "already_in_orthanc": 0,
        "uploaded": 0,
        "failed": 0,
    }
    failed_rows: list[int] = []

    with httpx.Client(
        base_url=env["ORTHANC_URL"],
        auth=(env["ORTHANC_USERNAME"], env["ORTHANC_PASSWORD"]),
        timeout=cfg["orthanc_upload"]["timeout_seconds"],
    ) as client:
        try:
            client.get("/system").raise_for_status()
        except httpx.HTTPError as exc:
            raise SystemExit(f"Orthanc not reachable at {env['ORTHANC_URL']}: {exc}") from exc

        for row, uid in enumerate(demo["image_id"]):
            if uid not in paths:
                counts["dicom_missing"] += 1
                failed_rows.append(row)
                continue
            if study_in_orthanc(client, uid):
                counts["already_in_orthanc"] += 1
                continue
            body = to_bytes(anonymise(pydicom.dcmread(paths[uid])))
            response = client.post(
                "/instances", content=body, headers={"Content-Type": "application/dicom"}
            )
            if response.is_success and response.json().get("Status") == "Success":
                counts["uploaded"] += 1
            elif response.is_success and response.json().get("Status") == "AlreadyStored":
                counts["already_in_orthanc"] += 1
            else:
                counts["failed"] += 1
                failed_rows.append(row)

        counts["orthanc_studies_total"] = len(client.get("/studies").json())

    for key, value in counts.items():
        print(f"{key:<22} {value}")
    if failed_rows:
        print(f"failed demo CSV rows: {failed_rows}")
    return 1 if failed_rows else 0


if __name__ == "__main__":
    sys.exit(main())
