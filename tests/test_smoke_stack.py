"""scripts/smoke_stack.py run against the app wired to the fake Orthanc and test database."""

import importlib.util
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("smoke_stack", ROOT / "scripts/smoke_stack.py")
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


def run(client) -> tuple[int, list[str]]:
    lines: list[str] = []
    return smoke.run(client, out=lines.append), lines


def test_all_steps_pass_against_a_working_stack(api, tmp_path):
    client, fake, engine = api
    fake.add_study(tmp_path, "s1")
    code, lines = run(client)
    assert code == 0, lines
    expected = [f"PASS {name}" for name, _ in smoke.STEPS]
    assert [line.split(":")[0] for line in lines[:-1]] == expected
    assert lines[-1] == "Smoke test passed: 8 of 8 steps."
    with engine.connect() as conn:
        reviewer = conn.execute(text("SELECT reviewer FROM reviews")).scalar_one()
    assert reviewer == "smoke test"


def test_stops_at_the_first_failure_with_a_clear_line(api, tmp_path):
    client, fake, _ = api
    fake.add_study(tmp_path, "s1")
    fake.down = True
    code, lines = run(client)
    assert code == 1
    assert lines == [lines[0]] and lines[0].startswith("FAIL health: expected HTTP 200, got 503")


def test_fails_when_there_is_nothing_to_analyse(api):
    client, _, _ = api
    code, lines = run(client)
    assert code == 1
    assert lines[-1] == "FAIL list studies: no studies listed; upload the demo set first"


def test_output_never_contains_credentials(api, tmp_path):
    client, fake, engine = api
    fake.add_study(tmp_path, "s1")
    _, lines = run(client)
    password = engine.url.password
    assert password and all(password not in line for line in lines)


def test_unreachable_api_is_reported_without_a_traceback(capsys):
    assert smoke.main(["--base-url", "http://127.0.0.1:9", "--timeout", "2"]) == 1
    out = capsys.readouterr().out
    # Linux refuses a closed port at once (ConnectError); Windows times out (ConnectTimeout).
    assert "FAIL health: cannot reach the API (Connect" in out
    assert "Traceback" not in out
