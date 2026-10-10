"""HTTP integration checks backed by a real C++ gRPC process and actual pytest runs."""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from halt.web.app import create_app
from halt.web.runs import RunManager, read_results
from halt.web.runtime import ROOT


def wait_ready(api):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        data = api.get("/api/state").json()
        if data["status"]["state"] == "READY":
            return data
        time.sleep(0.02)
    pytest.fail("device did not recover")


def wait_run(api, run_id):
    end = time.monotonic() + 90
    while time.monotonic() < end:
        result = api.get(f"/api/runs/{run_id}").json()
        if result["state"] != "running":
            return result
        time.sleep(0.1)
    pytest.fail("validation did not finish")


@pytest.fixture(scope="module")
def api():
    # Keep HTTP test subprocess evidence inside the CI artifact directory.
    app = create_app(reports=ROOT / "reports" / "web-integration" / uuid.uuid4().hex)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.headers["X-Halt-Token"] = client.get("/api/session").json()["token"]
        yield client


@pytest.fixture(autouse=True)
def reset(api):
    active = api.get("/api/runs").json()["active_run"]
    if active:
        api.post(f"/api/runs/{active}/cancel")
        wait_run(api, active)
    for action, value in (("temperature", 25), ("attenuation", 0)):
        assert api.post("/api/command", json={"action": action, "value": value}).status_code == 200
    assert api.post("/api/command", json={"action": "reset"}).status_code == 200
    wait_ready(api)


def test_pages_assets_and_security_headers(api):
    for path in ("/", "/validation", "/architecture"):
        response = api.get(path)
        assert response.status_code == 200
        assert "Hardware Abstraction Layer Tester" in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    for path in ("/static/app.js", "/static/style.css", "/static/favicon.svg", "/readme"):
        assert api.get(path).status_code == 200


def test_controls_change_real_telemetry(api):
    assert api.post("/api/command", json={"action": "enable_tx"}).status_code == 200
    data = api.get("/api/state").json()
    assert data["status"]["tx_enabled"]
    assert data["telemetry"]["tx_power_dbm"] == 0
    assert data["telemetry"]["bias_current_ma"] == 35
    api.post("/api/command", json={"action": "disable_tx"})
    assert api.get("/api/state").json()["telemetry"]["tx_power_dbm"] == -80
    api.post("/api/command", json={"action": "mode", "mode": "SAFE"})
    denied = api.post("/api/command", json={"action": "enable_tx"})
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "FAILED_PRECONDITION"


def test_attenuation_loss_and_recovery(api):
    api.post("/api/command", json={"action": "attenuation", "value": 16})
    data = api.get("/api/state").json()
    assert data["status"]["state"] == "DEGRADED"
    assert data["telemetry"]["rx_power_dbm"] == -21
    api.post("/api/command", json={"action": "attenuation", "value": 2})
    assert api.get("/api/state").json()["status"]["link_up"]


def test_thermal_latch_and_recovery(api):
    api.post("/api/command", json={"action": "temperature", "value": 85})
    assert api.get("/api/state").json()["status"]["state"] == "FAULT"
    api.post("/api/command", json={"action": "clear_fault"})
    assert api.get("/api/state").json()["status"]["state"] == "FAULT"
    api.post("/api/command", json={"action": "temperature", "value": 25})
    api.post("/api/command", json={"action": "clear_fault"})
    assert not wait_ready(api)["status"]["tx_enabled"]


@pytest.mark.parametrize(
    "fault",
    [
        "SENSOR_FAILURE",
        "COMMUNICATION_TIMEOUT",
        "OVER_TEMPERATURE",
        "INVALID_TELEMETRY",
        "LASER_FAULT",
        "POWER_SUPPLY_FAULT",
    ],
)
def test_all_faults_and_invalid_telemetry_serialization(api, fault):
    response = api.post("/api/command", json={"action": "inject_fault", "fault": fault})
    assert response.status_code == 200
    response = api.get("/api/state")
    assert response.status_code == 200
    data = response.json()
    assert data["status"]["fault"] == fault
    assert data["status"]["state"] == "FAULT"
    if fault == "COMMUNICATION_TIMEOUT":
        assert data["telemetry"] is None
        assert data["telemetry_error"]["code"] == "UNAVAILABLE"
    elif fault in {"INVALID_TELEMETRY", "SENSOR_FAILURE"}:
        assert not data["telemetry"]["valid"]
        assert None in data["telemetry"].values()
        assert "NaN" not in response.text
    api.post("/api/command", json={"action": "clear_fault"})
    assert wait_ready(api)["status"]["fault"] == "NONE"


def test_meter_and_timeouts(api):
    assert api.post("/api/measure", json={"channel": "RX"}).json()["power_dbm"] == -5
    assert api.post("/api/measure", json={"simulate_timeout": True}).status_code == 504
    assert api.post("/api/measure", json={"simulate_error": True}).status_code == 503
    assert api.post("/api/measure", json={"channel": "RX"}).status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "attenuation", "value": -1},
        {"action": "temperature", "value": 126},
        {"action": "attenuation", "value": "NaN"},
        {"action": "inject_fault", "fault": "NONE"},
        {"action": "mode", "mode": "BOGUS"},
        {"action": "shell", "value": "echo injected"},
        {"action": "temperature"},
        {"action": "reset", "extra": "ignored?"},
    ],
)
def test_invalid_inputs_are_rejected_without_mutation(api, payload):
    assert api.post("/api/command", json=payload).status_code == 422
    assert api.get("/api/state").json()["status"]["state"] == "READY"


def test_non_json_finite_number_error_is_serializable(api):
    response = api.post(
        "/api/command",
        content='{"action":"attenuation","value":NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "detail" in response.json()


def test_local_session_and_origin_protection(api):
    assert (
        api.post(
            "/api/command", json={"action": "reset"}, headers={"X-Halt-Token": "wrong"}
        ).status_code
        == 403
    )
    assert (
        api.post(
            "/api/command",
            json={"action": "reset"},
            headers={"Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    assert api.get("/api/state", headers={"Host": "untrusted.example"}).status_code == 400
    assert api.post("/api/command", content="x" * 5000).status_code == 413


def test_events_come_from_simulator(api):
    initial = api.get("/api/events").json()["events"][-1]["sequence"]
    api.post("/api/command", json={"action": "attenuation", "value": 20})
    events = api.get(f"/api/events?after={initial}").json()["events"]
    assert any("attenuation_db=20" in event["message"] for event in events)
    assert any("RX_LOS" in event["message"] for event in events)
    assert all(event["sequence"] > initial for event in events)


@pytest.mark.parametrize("suite", ["smoke", "link", "thermal", "fault", "recovery", "full"])
def test_real_validation_suites_and_downloads(api, suite):
    response = api.post("/api/runs", json={"suite": suite})
    assert response.status_code == 202
    run = response.json()
    assert api.post("/api/command", json={"action": "reset"}).status_code == 409
    assert api.post("/api/measure", json={}).status_code == 409
    assert api.post("/api/runs", json={"suite": "smoke"}).status_code == 409
    result = wait_run(api, run["id"])
    assert result["state"] == "passed", result
    assert result["exit_code"] == 0
    assert result["counts"]["passed"] > 0
    assert result["completed"] == result["total"]
    assert all(case["duration_ms"] > 0 for case in result["cases"])
    assert result["target"] == api.get("/api/session").json()["target"]
    for name in (
        "junit.xml",
        "pytest.log",
        "run.json",
        "events.json",
        "results.jsonl",
        "server.log",
    ):
        artifact = api.get(f"/api/runs/{run['id']}/artifacts/{name}")
        assert artifact.status_code == 200
        assert len(artifact.content) > 20
    assert len(result["binary_sha256"]) == 64
    assert api.get(f"/api/runs/{run['id']}/artifacts/app.py").status_code == 404
    assert api.post(f"/api/runs/{run['id']}/cancel").status_code == 409


def test_cancellation_releases_exclusive_lease_and_retains_evidence(api):
    run = api.post("/api/runs", json={"suite": "full"}).json()
    assert api.post(f"/api/runs/{run['id']}/cancel").status_code == 202
    result = wait_run(api, run["id"])
    assert result["state"] == "cancelled"
    assert api.post("/api/command", json={"action": "reset"}).status_code == 200
    assert "run.json" in result["artifacts"]


def test_allowlisted_suites_and_run_paths(api):
    assert api.post("/api/runs", json={"suite": "full; echo injected"}).status_code == 422
    assert api.get("/api/runs/not-a-run").status_code == 404


def test_real_pytest_failure_and_teardown_are_reported(tmp_path):
    test_file = tmp_path / "test_deliberate.py"
    test_file.write_text(
        "import pytest\n"
        "def test_pass(): assert 2 + 2 == 4\n"
        "def test_fail(): assert 1 == 2\n"
        "@pytest.fixture\ndef bad_teardown():\n    yield\n"
        "    raise RuntimeError('teardown failed')\n"
        "def test_teardown(bad_teardown): pass\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        HALT_REPORT_DIR=str(tmp_path),
        PYTHONPATH=str(ROOT / "python"),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "-p",
            "halt.reporting",
            "-o",
            "addopts=",
            "-q",
        ],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1
    report = read_results(tmp_path / "results.jsonl")
    assert report["counts"] == {"passed": 1, "failed": 1, "error": 1, "skipped": 0}
    assert report["completed"] == 3
    assert "teardown failed" in report["cases"][-1]["detail"]


def test_run_history_marks_abandoned_execution_interrupted(tmp_path):
    run_id = "a" * 32
    folder = tmp_path / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(
        json.dumps({"id": run_id, "state": "running"}), encoding="utf-8"
    )
    manager = RunManager("unused", Path("unused"), tmp_path, None)
    assert manager.get(run_id)["state"] == "interrupted"
    manager.close()


def test_unavailable_device_returns_error_instead_of_old_values(tmp_path):
    app = create_app(reports=tmp_path)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/state").status_code == 200
        app.state.runtime.process.terminate()
        app.state.runtime.process.wait(timeout=5)
        response = client.get("/api/state")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "UNAVAILABLE"
        assert "telemetry" not in response.json()
