"""pytest plugin: append real phase results for the local web console."""

import json
import os
from pathlib import Path


def emit(event):
    destination = os.environ.get("HALT_REPORT_DIR")
    if destination:
        with (Path(destination) / "results.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")


def pytest_collection_finish(session):
    emit({"type": "collected", "total": len(session.items)})


def pytest_runtest_logreport(report):
    emit(
        {
            "type": "result",
            "nodeid": report.nodeid,
            "phase": report.when,
            "outcome": report.outcome,
            "duration_ms": round(report.duration * 1000, 2),
            "detail": str(report.longrepr)[:16000] if report.failed or report.skipped else "",
        }
    )


def pytest_collectreport(report):
    if report.failed:
        emit({"type": "collection_error", "detail": str(report.longrepr)[:16000]})


def pytest_sessionfinish(session, exitstatus):
    emit({"type": "finished", "exit_code": int(exitstatus)})
