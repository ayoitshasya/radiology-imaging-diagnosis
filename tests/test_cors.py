"""CORS: only the viewer's Vite dev origin may call the API from a browser."""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.settings import Settings, load_project_config

VITE = "http://localhost:5173"


def preflight(client: TestClient, origin: str, method: str = "POST"):
    return client.options(
        "/studies/sync",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_allowed_origin_comes_from_config():
    assert load_project_config()["cors_origins"] == [VITE]


def test_preflight_from_vite_origin_is_allowed():
    # Preflights are answered by the middleware, so no lifespan (database, model) is needed.
    r = preflight(TestClient(create_app()), VITE)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == VITE
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in r.headers


@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1:5173", "http://localhost:3000", "https://example.com"]
)
def test_preflight_from_other_origins_is_refused(origin):
    r = preflight(TestClient(create_app()), origin)
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


def test_methods_other_than_get_and_post_are_refused():
    r = preflight(TestClient(create_app()), VITE, method="DELETE")
    assert r.status_code == 400


def test_injected_settings_override_config():
    settings = Settings.model_construct(cors_origins=["http://viewer.test:5173"])
    client = TestClient(create_app(settings=settings))
    assert preflight(client, "http://viewer.test:5173").status_code == 200
    assert preflight(client, VITE).status_code == 400


def test_responses_carry_the_origin_and_expose_the_notice_header(api):
    client, _, _ = api
    allowed = client.get("/audit", headers={"Origin": VITE})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == VITE
    assert "X-Notice" in allowed.headers["access-control-expose-headers"]

    other = client.get("/audit", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in other.headers
