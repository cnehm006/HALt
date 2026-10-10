"""Bounded, single-run pytest supervisor; only allowlisted suites can execute."""

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from halt.web.runtime import ROOT

SUITES = {
    "smoke": "smoke",
    "link": "link",
    "thermal": "thermal",
    "fault": "fault",
    "recovery": "recovery",
    "full": None,
}
ARTIFACTS = {
    "junit.xml",
    "summary.txt",
    "pytest.log",
    "results.jsonl",
    "run.json",
    "events.json",
    "server.log",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_digest():
    """Identify actual source, including uncommitted changes; not just a Git revision."""
    result = hashlib.sha256()
    paths = [ROOT / "CMakeLists.txt", ROOT / "pyproject.toml", ROOT / "requirements-dev.txt"]
    for directory in ("cpp", "proto", "python", "tests/cpp"):
        paths.extend(
            path
            for path in (ROOT / directory).rglob("*")
            if path.suffix in {".py", ".cpp", ".hpp", ".proto"} and "generated" not in path.parts
        )
    for path in sorted(paths):
        result.update(path.relative_to(ROOT).as_posix().encode())
        result.update(b"\0" + path.read_bytes() + b"\0")
    return result.hexdigest()


def read_results(path):
    cases = {}
    total = None
    collection_errors = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # A writer may still be appending the final line.
            if event["type"] == "collected":
                total = event["total"]
            elif event["type"] == "collection_error":
                collection_errors.append(event["detail"])
            elif event["type"] == "result":
                case = cases.setdefault(
                    event["nodeid"],
                    {
                        "name": event["nodeid"],
                        "outcome": "running",
                        "duration_ms": 0,
                        "detail": "",
                        "finished": False,
                    },
                )
                case["duration_ms"] = round(case["duration_ms"] + event["duration_ms"], 2)
                if event["outcome"] == "failed":
                    case["outcome"] = "failed" if event["phase"] == "call" else "error"
                    case["detail"] += event["detail"] + "\n"
                elif event["outcome"] == "skipped" and case["outcome"] == "running":
                    case["outcome"] = "skipped"
                    case["detail"] = event["detail"]
                if event["phase"] == "teardown":
                    case["finished"] = True
                    if case["outcome"] == "running":
                        case["outcome"] = "passed"
    counts = {
        key: sum(c["outcome"] == key for c in cases.values())
        for key in ("passed", "failed", "error", "skipped")
    }
    return {
        "cases": list(cases.values()),
        "total": total,
        "counts": counts,
        "completed": sum(c["finished"] for c in cases.values()),
        "collection_errors": collection_errors,
    }


class RunManager:
    def __init__(self, address, binary, reports, client, server_log=None):
        self.address, self.binary, self.client = address, binary, client
        self.server_log = server_log
        self.directory = Path(reports) / "runs"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.active = None
        self.worker = None
        self.process = None
        self.cancel_requested = False
        self.closed = False
        for path in self.directory.glob("*/run.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["state"] == "running":
                record.update(
                    state="interrupted",
                    finished_at=utc_now(),
                    error="Console stopped before this run completed.",
                )
                self._save(record)

    def _save(self, record):
        path = self.directory / record["id"] / "run.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
        temporary.replace(path)

    def get(self, run_id):
        if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise KeyError("unknown run")
        path = self.directory / run_id / "run.json"
        if not path.is_file():
            raise KeyError("unknown run")
        with self.lock:
            record = json.loads(path.read_text(encoding="utf-8"))
        record.update(read_results(path.parent / "results.jsonl"))
        if record["state"] != "running":
            for case in record["cases"]:
                if case["outcome"] == "running":
                    case["outcome"] = "interrupted"
        record["artifacts"] = sorted(name for name in ARTIFACTS if (path.parent / name).is_file())
        return record

    def history(self):
        paths = sorted(
            self.directory.glob("*/run.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        return [self.get(path.parent.name) for path in paths[:20]]

    def start(self, suite):
        if suite not in SUITES:
            raise ValueError("unknown validation suite")
        with self.lock:
            if self.active or self.closed:
                raise RuntimeError("Validation owns the device; wait for completion or cancel it.")
            run_id = uuid.uuid4().hex
            folder = self.directory / run_id
            folder.mkdir()
            record = {
                "id": run_id,
                "suite": suite,
                "state": "running",
                "started_at": utc_now(),
                "finished_at": None,
                "exit_code": None,
                "duration_ms": None,
                "target": self.address,
                "source_sha256": source_digest(),
                "binary_sha256": digest(self.binary),
                "proto_sha256": digest(ROOT / "proto/halt.proto"),
                "python": sys.version.split()[0],
                "error": None,
                "server_log_offset": self.server_log.stat().st_size if self.server_log else None,
            }
            self._save(record)
            self.active, self.cancel_requested = run_id, False
            self.worker = threading.Thread(target=self._execute, args=(record,), daemon=False)
            self.worker.start()
            return self.get(run_id)

    def _execute(self, record):
        start = time.monotonic()
        folder = self.directory / record["id"]
        command = [
            sys.executable,
            "-m",
            "pytest",
            "python/tests",
            "-v",
            "-p",
            "halt.reporting",
            f"--junitxml={folder / 'junit.xml'}",
            "-o",
            f"cache_dir={folder / 'cache'}",
        ]
        if SUITES[record["suite"]]:
            command.extend(["-m", SUITES[record["suite"]]])
        environment = os.environ.copy()
        environment.update(
            HALT_ADDRESS=self.address,
            HALT_REPORT_DIR=str(folder),
            PYTHONPATH=str(ROOT / "python"),
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        )
        environment.pop("PYTEST_ADDOPTS", None)
        try:
            with (folder / "pytest.log").open("w", encoding="utf-8") as stream:
                with self.lock:
                    self.process = subprocess.Popen(
                        command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT
                    )
                while self.process.poll() is None:
                    if self.cancel_requested or time.monotonic() - start > 180:
                        self.process.terminate()
                        try:
                            self.process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            self.process.kill()
                            self.process.wait(timeout=5)
                        break
                    time.sleep(0.05)
                record["exit_code"] = self.process.returncode
            if self.cancel_requested:
                record["state"] = "cancelled"
            elif time.monotonic() - start > 180:
                record.update(state="error", error="Validation exceeded the 180 second limit.")
            else:
                results = read_results(folder / "results.jsonl")
                complete = results["total"] and results["completed"] == results["total"]
                passed = (
                    record["exit_code"] == 0
                    and complete
                    and (folder / "junit.xml").is_file()
                    and results["counts"]["passed"] > 0
                    and not results["counts"]["failed"]
                    and not results["counts"]["error"]
                    and not results["collection_errors"]
                )
                record["state"] = "passed" if passed else "failed"
            from google.protobuf.json_format import MessageToDict

            events = self.client.call("GetEvents")
            (folder / "events.json").write_text(
                json.dumps(MessageToDict(events), indent=2), encoding="utf-8"
            )
        except Exception as error:
            record.update(state="error", error=str(error))
        finally:
            if self.server_log:
                try:
                    with self.server_log.open("rb") as stream:
                        stream.seek(record["server_log_offset"])
                        (folder / "server.log").write_bytes(stream.read())
                except OSError as error:
                    record.update(state="error", error=f"Could not preserve server log: {error}")
            # Do not reset after testing: keep the final state visible for diagnosis.
            record.update(
                finished_at=utc_now(), duration_ms=round((time.monotonic() - start) * 1000)
            )
            with self.lock:
                try:
                    self._save(record)
                finally:
                    self.active = None
                    self.process = None

    def cancel(self, run_id):
        with self.lock:
            if self.active != run_id:
                raise ValueError("Run is not active.")
            self.cancel_requested = True

    def close(self):
        with self.lock:
            self.closed = True
            self.cancel_requested = True
        if self.worker:
            self.worker.join(timeout=8)
