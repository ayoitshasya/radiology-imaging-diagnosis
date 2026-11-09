"""Shared test helpers: synthetic DICOM files, a fake Orthanc and a throwaway API database.

Tests never need real patient data, never touch the dev database and never reach the
network.
"""

import os
import re
from pathlib import Path

import httpx
import numpy as np
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid


def write_dicom(
    path: Path,
    pixels: np.ndarray,
    photometric: str = "MONOCHROME2",
    view: str = "PA",
    sex: str = "F",
    age: str = "045Y",
) -> Path:
    """Write a minimal, valid, uncompressed 8-bit grayscale DICOM file.

    Args:
        path: Destination file.
        pixels: 2D array of values 0-255.
        photometric: ``MONOCHROME1`` or ``MONOCHROME2``.
        view: ViewPosition tag value.
        sex: PatientSex tag value.
        age: PatientAge tag value in DICOM ``nnnY`` form.

    Returns:
        The path written.
    """
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "CR"
    ds.ViewPosition = view
    ds.PatientSex = sex
    ds.PatientAge = age
    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = pixels.astype(np.uint8).tobytes()
    ds.save_as(path, enforce_file_format=True)
    return path


# Fake Orthanc --------------------------------------------------------------------------


class FakeOrthanc:
    """In-memory stand-in for the Orthanc REST endpoints the backend uses."""

    def __init__(self) -> None:
        self.studies: dict[str, dict] = {}
        self.down = False
        self.requests: list[str] = []  # every path asked for, to prove what was contacted
        self.file_status: dict[str, int] = {}  # study ID -> HTTP status for its file

    def add_study(self, tmp_path: Path, orthanc_id: str, pixels=None, photometric="MONOCHROME2"):
        """Store a synthetic DICOM under ``orthanc_id``; returns its StudyInstanceUID."""
        import pydicom

        if pixels is None:
            pixels = np.random.default_rng(len(self.studies)).integers(0, 256, (256, 256))
        path = write_dicom(tmp_path / f"{orthanc_id}.dcm", pixels, photometric=photometric)
        uid = str(pydicom.dcmread(path).StudyInstanceUID)
        self.studies[orthanc_id] = {"uid": uid, "dicom": path.read_bytes()}
        return uid

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == "/system":
            return httpx.Response(200, json={"Version": "fake"})
        if path == "/studies":
            if "expand" in request.url.params:
                return httpx.Response(
                    200,
                    json=[
                        {
                            "ID": oid,
                            "MainDicomTags": {"StudyInstanceUID": s["uid"]},
                            "PatientMainDicomTags": {"PatientName": "Anonymous"},
                        }
                        for oid, s in self.studies.items()
                    ],
                )
            return httpx.Response(200, json=list(self.studies))
        m = re.fullmatch(r"/studies/([^/]+)(/instances)?", path)
        if m and m.group(1) in self.studies:
            oid = m.group(1)
            if m.group(2):
                return httpx.Response(200, json=[{"ID": f"inst-{oid}"}])
            return httpx.Response(
                200,
                json={"ID": oid, "MainDicomTags": {"StudyInstanceUID": self.studies[oid]["uid"]}},
            )
        m = re.fullmatch(r"/instances/inst-([^/]+)/file", path)
        if m and m.group(1) in self.studies:
            status = self.file_status.get(m.group(1), 200)
            if status != 200:
                return httpx.Response(status, json={"error": "injected"})
            return httpx.Response(200, content=self.studies[m.group(1)]["dicom"])
        return httpx.Response(404, json={"error": "not found"})

    def client(self):
        from backend.app.orthanc import OrthancClient

        return OrthancClient(
            "http://orthanc.test", "u", "p", 2.0, transport=httpx.MockTransport(self.handler)
        )


# Throwaway API database ------------------------------------------------------------------

API_TEST_DB = "radiology_test_api"


def database_unavailable(reason: str) -> None:
    """Skip a database test locally, but fail it in CI.

    Locally, running without the compose Postgres is a normal choice. In CI (GitHub sets
    CI=true) a missing database would turn every database test into a silent skip and the
    job would still pass, so it must fail instead.
    """
    if os.environ.get("CI"):
        pytest.fail(f"{reason}; CI must run the database tests", pytrace=False)
    pytest.skip(reason)


@pytest.fixture
def api_engine():
    """A fresh database with all migrations applied, dropped after the test."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError

    from backend.app.settings import ROOT, get_settings

    try:
        url = make_url(get_settings().database_url.get_secret_value())
    except Exception:  # noqa: BLE001 - no settings means the database tests cannot run
        database_unavailable("DATABASE_URL not configured")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{API_TEST_DB}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{API_TEST_DB}"'))
    except DBAPIError:
        database_unavailable("Postgres not reachable")
    test_url = url.set(database=API_TEST_DB).render_as_string(hide_password=False)
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.attributes["database_url"] = test_url
    command.upgrade(cfg, "head")
    engine = create_engine(test_url)
    yield engine
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{API_TEST_DB}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def test_model_service():
    """A randomly initialised DenseNet121 behind the real ModelService interface."""
    import torch

    from backend.app.model_service import ModelService
    from ml.classification.common import build_model

    torch.manual_seed(0)
    return ModelService(
        model=build_model(pretrained=False).eval(),
        model_name="test-densenet",
        checkpoint_sha256="b" * 64,
        threshold=0.5,
        device="cpu",
        target_layer="features.denseblock4",
    )


@pytest.fixture
def api(api_engine, test_model_service):
    """(TestClient, FakeOrthanc, engine) for an app wired to the fakes."""
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    fake = FakeOrthanc()
    app = create_app(orthanc=fake.client(), engine=api_engine, model_service=test_model_service)
    with TestClient(app) as client:
        yield client, fake, api_engine
