"""Local HTTP adapter. Device behavior remains exclusively in the C++ service."""

import math
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import grpc
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from halt.generated import halt_pb2 as pb
from halt.web.runs import ARTIFACTS, SUITES, RunManager, utc_now
from halt.web.runtime import ROOT, SimulatorProcess

STATIC = ROOT / "web"


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "enable_tx",
        "disable_tx",
        "reset",
        "clear_fault",
        "mode",
        "attenuation",
        "temperature",
        "inject_fault",
    ]
    value: float | None = Field(default=None, allow_inf_nan=False, strict=True)
    mode: Literal["NORMAL", "SAFE"] | None = None
    fault: (
        Literal[
            "SENSOR_FAILURE",
            "COMMUNICATION_TIMEOUT",
            "OVER_TEMPERATURE",
            "INVALID_TELEMETRY",
            "LASER_FAULT",
            "POWER_SUPPLY_FAULT",
        ]
        | None
    ) = None


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Literal["TX", "RX"] = "RX"
    noise: float = Field(default=0, ge=0, le=2, allow_inf_nan=False, strict=True)
    simulate_timeout: bool = False
    simulate_error: bool = False


class Validation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite: Literal["smoke", "link", "thermal", "fault", "recovery", "full"]


def status_json(status):
    return {
        "state": pb.State.Name(status.state),
        "mode": pb.Mode.Name(status.mode),
        "fault": pb.Fault.Name(status.fault),
        "link_up": status.link_up,
        "tx_enabled": status.tx_enabled,
        "uptime_ms": status.uptime_ms,
        "alarms": list(status.alarms),
    }


def rpc_error(error):
    return {"code": error.code().name, "message": error.details()}


def create_app(reports: Path | None = None, binary: Path | None = None):
    reports = reports or ROOT / "reports" / "web"
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        runtime = SimulatorProcess(reports, binary)
        try:
            manager = RunManager(
                runtime.address, runtime.binary, reports, runtime.client, runtime.log_path
            )
        except BaseException:
            runtime.close()
            raise
        app.state.runtime, app.state.runs = runtime, manager
        try:
            yield
        finally:
            manager.close()
            runtime.close()

    app = FastAPI(
        title="HALt local lab API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in {"GET", "HEAD"}:
            supplied = request.headers.get("x-halt-token", "")
            origin = request.headers.get("origin")
            same_origin = (
                not origin or origin == f"{request.url.scheme}://{request.headers.get('host')}"
            )
            if not secrets.compare_digest(supplied, token) or not same_origin:
                return JSONResponse(
                    {"detail": "Local session token and same origin required."}, 403
                )
            length = request.headers.get("content-length")
            if length and (not length.isdecimal() or int(length) > 4096):
                return JSONResponse({"detail": "Request body exceeds 4096 bytes."}, 413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(grpc.RpcError)
    async def grpc_failure(request, error):
        status = {
            grpc.StatusCode.INVALID_ARGUMENT: 422,
            grpc.StatusCode.FAILED_PRECONDITION: 409,
            grpc.StatusCode.DEADLINE_EXCEEDED: 504,
        }.get(error.code(), 503)
        return JSONResponse({"detail": rpc_error(error)}, status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # Do not echo arbitrary inputs (including non-JSON floats) into error responses.
        return JSONResponse(
            {
                "detail": [
                    {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                    for item in error.errors()
                ]
            },
            422,
        )

    @app.get("/api/session")
    def session():
        source = os.environ.get("HALT_SOURCE_URL", "")
        parsed = urlsplit(source)
        source = source if parsed.scheme == "https" and parsed.hostname == "github.com" else None
        return {
            "token": token,
            "target": app.state.runtime.address,
            "suites": list(SUITES),
            "source_url": source,
            "simulation": True,
        }

    @app.get("/api/state")
    def state():
        client = app.state.runtime.client
        status = client.call("GetStatus")
        result = {
            "status": status_json(status),
            "telemetry": None,
            "telemetry_error": None,
            "sampled_at": utc_now(),
            "active_run": app.state.runs.active,
        }
        try:
            telemetry = client.call("GetTelemetry")
            result["status"] = status_json(telemetry.status)
            fields = (
                "voltage_v",
                "module_temperature_c",
                "laser_temperature_c",
                "tx_power_dbm",
                "rx_power_dbm",
                "bias_current_ma",
            )
            result["telemetry"] = {
                field: (
                    getattr(telemetry, field) if math.isfinite(getattr(telemetry, field)) else None
                )
                for field in fields
            }
            result["telemetry"]["valid"] = telemetry.valid
        except grpc.RpcError as error:
            result["telemetry_error"] = rpc_error(error)
        return result

    @app.get("/api/events")
    def events(after: int = Query(default=0, ge=0)):
        entries = app.state.runtime.client.call("GetEvents").events
        return {
            "events": [
                {
                    "sequence": e.sequence,
                    "timestamp": e.timestamp,
                    "level": e.level,
                    "component": e.component,
                    "message": e.message,
                }
                for e in entries
                if e.sequence > after
            ],
            "gap": bool(after and entries and entries[0].sequence > after + 1),
        }

    @app.post("/api/command")
    def command(body: Command):
        simple = {
            "enable_tx": "EnableTransmitter",
            "disable_tx": "DisableTransmitter",
            "reset": "Reset",
            "clear_fault": "ClearFault",
        }
        with app.state.runs.lock:
            if app.state.runs.active:
                raise HTTPException(409, "Validation owns the device. Wait or cancel the run.")
            request = None
            if body.action in simple:
                method = simple[body.action]
            elif body.action == "mode" and body.mode:
                method, request = "SetMode", pb.ModeRequest(mode=pb.Mode.Value(body.mode))
            elif body.action == "inject_fault" and body.fault:
                method, request = "InjectFault", pb.FaultRequest(fault=pb.Fault.Value(body.fault))
            elif body.action in {"attenuation", "temperature"} and body.value is not None:
                method = "SetAttenuation" if body.action == "attenuation" else "SetTemperature"
                request = pb.Scalar(value=body.value)
            else:
                raise HTTPException(422, "This command requires its corresponding value.")
            status = app.state.runtime.client.call(method, request)
            return {"status": status_json(status), "at": utc_now()}

    @app.post("/api/measure")
    def measure(body: Measurement):
        with app.state.runs.lock:
            if app.state.runs.active:
                raise HTTPException(409, "Validation owns the instruments. Wait or cancel the run.")
            reading = app.state.runtime.client.call(
                "MeasurePower",
                pb.MeterRequest(
                    channel=pb.Channel.Value(body.channel),
                    noise_stddev_db=body.noise,
                    simulate_timeout=body.simulate_timeout,
                    simulate_error=body.simulate_error,
                ),
                timeout=0.15,
            )
            return {
                "power_dbm": reading.power_dbm,
                "instrument": reading.instrument,
                "channel": body.channel,
                "at": utc_now(),
            }

    @app.get("/api/runs")
    def history():
        return {"runs": app.state.runs.history(), "active_run": app.state.runs.active}

    @app.post("/api/runs", status_code=202)
    def start_run(body: Validation):
        try:
            return app.state.runs.start(body.suite)
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    def get_run(run_id):
        try:
            return app.state.runs.get(run_id)
        except KeyError as error:
            raise HTTPException(404, "Unknown run.") from error

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        return get_run(run_id)

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    def cancel_run(run_id: str):
        get_run(run_id)
        try:
            app.state.runs.cancel(run_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"state": "cancelling"}

    @app.get("/api/runs/{run_id}/artifacts/{name}")
    def artifact(run_id: str, name: str):
        run = get_run(run_id)
        if name not in ARTIFACTS or name not in run["artifacts"]:
            raise HTTPException(404, "Artifact is not available.")
        return FileResponse(app.state.runs.directory / run_id / name, filename=f"{run_id}-{name}")

    @app.get("/readme", response_class=PlainTextResponse)
    def readme():
        return (ROOT / "README.md").read_text(encoding="utf-8")

    @app.get("/")
    @app.get("/validation")
    @app.get("/architecture")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
