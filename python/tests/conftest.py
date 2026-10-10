"""Own the server process, preserve logs, and reset external conditions between tests."""

import json
import os
import subprocess
import time
from pathlib import Path

import grpc
import pytest
from google.protobuf.json_format import MessageToDict
from halt.client import DeviceClient
from halt.generated import halt_pb2 as pb

ROOT = Path(__file__).resolve().parents[2]
REPORTS = Path(os.environ.get("HALT_REPORT_DIR", ROOT / "reports"))


@pytest.fixture(scope="session")
def server_address():
    external = os.environ.get("HALT_ADDRESS")
    if external:
        # The web runner holds the exclusive control lease for this entire session.
        # Never launch or terminate the live console's server from a test fixture.
        REPORTS.mkdir(parents=True, exist_ok=True)
        with grpc.insecure_channel(external) as channel:
            grpc.channel_ready_future(channel).result(timeout=5)
        yield external
        return
    configured = os.environ.get("HALT_SERVER")
    candidates = [ROOT / "build" / "halt_server", ROOT / "build" / "Release" / "halt_server.exe"]
    binary = (
        Path(configured)
        if configured
        else next((p for p in candidates if p.exists()), candidates[0])
    )
    if not binary.is_file():
        pytest.fail(f"Build the C++ server first; executable missing: {binary}")
    REPORTS.mkdir(parents=True, exist_ok=True)
    log_path = REPORTS / "server.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(binary), "--port", "0"], stdout=log, stderr=subprocess.STDOUT
        )
        try:
            end = time.monotonic() + 15
            address = None
            while time.monotonic() < end:
                if process.poll() is not None:
                    pytest.fail(f"server exited with {process.returncode}: {log_path.read_text()}")
                for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("component") == "SERVER" and event["message"].startswith(
                        "HALT_PORT="
                    ):
                        address = f"127.0.0.1:{int(event['message'].split('=')[1])}"
                        break
                if address:
                    break
                time.sleep(0.02)
            if not address:
                pytest.fail(f"server did not announce its port; inspect {log_path}")
            with grpc.insecure_channel(address) as channel:
                grpc.channel_ready_future(channel).result(timeout=5)
            yield address
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                pytest.fail("server failed to shut down within 5 seconds")
            if os.name != "nt" and process.returncode != 0:
                pytest.fail(f"server shutdown failed ({process.returncode}); inspect {log_path}")


@pytest.fixture
def client(server_address):
    device = DeviceClient(server_address)
    try:
        device.call("SetTemperature", pb.Scalar(value=25))
        device.call("SetAttenuation", pb.Scalar(value=0))
        device.call("Reset")
        device.wait_state()
        yield device
    finally:
        device.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed and "client" in item.funcargs:
        try:
            events = item.funcargs["client"].call("GetEvents")
            safe_name = "".join(c if c.isalnum() else "_" for c in item.nodeid)
            (REPORTS / f"failure_{safe_name}.json").write_text(
                json.dumps(MessageToDict(events), indent=2), encoding="utf-8"
            )
        except grpc.RpcError:
            pass  # server.log remains available if the transport itself failed.


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    REPORTS.mkdir(parents=True, exist_ok=True)
    counts = {
        name: len(terminalreporter.stats.get(name, []))
        for name in ("passed", "failed", "error", "skipped")
    }
    lines = ["HALt validation summary", f"pytest exit status: {exitstatus}"]
    lines.extend(f"{name}: {count}" for name, count in counts.items())
    (REPORTS / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
