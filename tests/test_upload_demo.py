"""Tests for the anonymisation applied before demo studies are uploaded to Orthanc."""

import copy
import importlib.util
import io
from pathlib import Path

import numpy as np
import pydicom
from conftest import write_dicom

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "upload_demo_to_orthanc", ROOT / "scripts" / "upload_demo_to_orthanc.py"
)
upload = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(upload)

PATIENT_KEY = "rsna-patient-key-123"


def identified_dicom(tmp_path, age="095Y"):
    path = write_dicom(tmp_path / "x.dcm", np.zeros((8, 8)), age=age)
    ds = pydicom.dcmread(path)
    ds.PatientName = PATIENT_KEY
    ds.PatientID = PATIENT_KEY
    ds.PatientBirthDate = "19300101"
    ds.ReferringPhysicianName = "Dr Example"
    ds.AccessionNumber = "ACC1"
    ds.StudyDate = "20200101"
    return ds


def test_anonymise_replaces_and_removes_identifiers(tmp_path):
    ds = identified_dicom(tmp_path)
    study_uid = str(ds.StudyInstanceUID)
    out = upload.anonymise(ds)
    assert str(out.PatientName) == "Anonymous"
    assert out.PatientID.startswith("ANON-") and PATIENT_KEY not in out.PatientID
    assert "PatientBirthDate" not in out
    assert str(out.ReferringPhysicianName) == "" and out.AccessionNumber == ""
    assert out.StudyDate == ""
    assert out.PatientIdentityRemoved == "YES"
    assert str(out.StudyInstanceUID) == study_uid  # links Orthanc to the manifests


def test_anonymised_bytes_contain_no_patient_key_and_round_trip(tmp_path):
    body = upload.to_bytes(upload.anonymise(identified_dicom(tmp_path)))
    assert PATIENT_KEY.encode() not in body
    assert b"19300101" not in body
    assert pydicom.dcmread(io.BytesIO(body)).PatientName == "Anonymous"


def test_pseudonym_is_deterministic_per_study(tmp_path):
    ds = identified_dicom(tmp_path)
    first = upload.anonymise(copy.deepcopy(ds)).PatientID
    again = upload.anonymise(copy.deepcopy(ds)).PatientID  # same study, as on a re-run
    assert first == again
    other = copy.deepcopy(ds)
    other.StudyInstanceUID = "1.2.3.4"
    assert upload.anonymise(other).PatientID != first


def test_ages_over_89_are_capped_and_others_kept(tmp_path):
    assert upload.anonymise(identified_dicom(tmp_path, "095Y")).PatientAge == "090Y"
    assert upload.anonymise(identified_dicom(tmp_path, "045Y")).PatientAge == "045Y"
