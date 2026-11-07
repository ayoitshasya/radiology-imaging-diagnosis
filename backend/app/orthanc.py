"""Thin Orthanc REST client with timeouts and project-specific errors."""

from __future__ import annotations

from typing import Any

import httpx


class OrthancError(Exception):
    """Orthanc answered, but not with a usable response."""


class OrthancUnavailable(OrthancError):
    """Orthanc could not be reached in time (connection refused, DNS, timeout)."""


class OrthancNotFound(OrthancError):
    """Orthanc has no resource with the requested ID."""


class OrthancClient:
    """Minimal client for the Orthanc endpoints the backend needs.

    The backend only reads from Orthanc; images are fetched per request and never stored
    by the backend.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            auth=(username, password),
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise OrthancUnavailable(f"Orthanc not reachable: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise OrthancError(f"Orthanc request failed: {type(exc).__name__}") from exc
        if response.status_code == 404:
            raise OrthancNotFound(f"Orthanc resource not found: {path}")
        if response.status_code == 401:
            raise OrthancError("Orthanc rejected the credentials (401)")
        if not response.is_success:
            raise OrthancError(f"Orthanc returned HTTP {response.status_code} for {path}")
        return response

    def system(self) -> dict:
        """Orthanc's /system information; used as a health check."""
        return self._request("GET", "/system").json()

    def list_study_ids(self) -> list[str]:
        """Orthanc IDs of all stored studies."""
        return self._request("GET", "/studies").json()

    def list_studies(self) -> list[dict[str, str]]:
        """Every study as ``{"orthanc_study_id", "study_instance_uid"}``, in one request.

        Uses ``?expand`` and keeps only the two identifiers the project may store;
        patient-level tags in Orthanc's response are dropped here.
        """
        studies = self._request("GET", "/studies", params={"expand": ""}).json()
        return [
            {
                "orthanc_study_id": s["ID"],
                "study_instance_uid": s["MainDicomTags"]["StudyInstanceUID"],
            }
            for s in studies
        ]

    def get_study(self, study_id: str) -> dict:
        """Study resource, including MainDicomTags and its series."""
        return self._request("GET", f"/studies/{study_id}").json()

    def first_instance_id(self, study_id: str) -> str:
        """ID of the first instance of a study (the demo studies have one image each)."""
        instances = self._request("GET", f"/studies/{study_id}/instances").json()
        if not instances:
            raise OrthancNotFound(f"Study {study_id} has no instances")
        return instances[0]["ID"]

    def instance_file(self, instance_id: str) -> bytes:
        """Raw DICOM bytes of one instance."""
        return self._request("GET", f"/instances/{instance_id}/file").content
