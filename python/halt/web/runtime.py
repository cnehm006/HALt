"""Own the C++ child process and the console's gRPC client."""

import json
import os
import subprocess
import time
from pathlib import Path

import grpc

from halt.client import DeviceClient

ROOT = Path(__file__).resolve().parents[3]


def find_binary():
    configured = os.environ.get("HALT_SERVER")
    if configured:
        binary = Path(configured).resolve()
    else:
        candidates = [
            ROOT / "build" / "halt_server",
            ROOT / "build-win" / "Release" / "halt_server.exe",
            ROOT / "build" / "Release" / "halt_server.exe",
            ROOT / "build" / "halt_server.exe",
        ]
        binary = next((path for path in candidates if path.is_file()), candidates[0])
    if not binary.is_file():
        raise RuntimeError(f"C++ server not found: {binary}. Build HALt first.")
    return binary


class SimulatorProcess:
    def __init__(self, reports: Path, binary: Path | None = None):
        self.binary = binary or find_binary()
        reports.mkdir(parents=True, exist_ok=True)
        self.log_path = reports / "console-server.log"
        self.stream = self.log_path.open("w", encoding="utf-8")
        self.process = None
        self.client = None
        try:
            self.process = subprocess.Popen(
                [str(self.binary), "--port", "0"], stdout=self.stream, stderr=subprocess.STDOUT
            )
            end = time.monotonic() + 15
            self.address = None
            while time.monotonic() < end:
                if self.process.poll() is not None:
                    raise RuntimeError(f"Simulator exited; inspect {self.log_path}")
                for line in self.log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("component") == "SERVER" and event["message"].startswith(
                        "HALT_PORT="
                    ):
                        self.address = f"127.0.0.1:{int(event['message'].split('=')[1])}"
                        break
                if self.address:
                    break
                time.sleep(0.02)
            if not self.address:
                raise RuntimeError(f"Simulator startup timed out; inspect {self.log_path}")
            self.client = DeviceClient(self.address, timeout=0.4)
            grpc.channel_ready_future(self.client.channel).result(timeout=5)
            self.client.wait_state()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.client:
            self.client.close()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.stream.close()
