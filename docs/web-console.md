# HALt web console

The console is a local lab utility for the GENERIC SIMULATED OPTICAL COMMUNICATIONS MODULE. Plain HTML, CSS, and JavaScript talk to a small FastAPI backend. All device behavior remains in the compiled C++ simulator behind gRPC.

## Start

Build the core using the README instructions, then from the HALt directory:

```bash
source .venv/bin/activate
python -m pip install -r requirements-web.txt
python scripts/generate_proto.py
bash scripts/serve.sh --port 8051
```

Open http://127.0.0.1:8051. The API owns and starts a C++ simulator on an available loopback port. There is no separate simulator-launch step. Ctrl+C stops the API, any active pytest run, and the simulator.

On Windows, after building with the documented native toolchain:

```powershell
./.venv-win/Scripts/python.exe -m pip install -r requirements-web.txt
./.venv-win/Scripts/python.exe scripts/generate_proto.py
./scripts/serve.ps1 -Python ./.venv-win/Scripts/python.exe -Port 8051
```

Set `HALT_SERVER` to an absolute executable path to use an alternate build. Native Windows execution remains unverified locally. Run a single API process; multiple API workers are not supported.

## Workbench

The workbench displays device state, mode, uptime, fault, receive link, six telemetry fields, and active alarms. The RX trace contains only observed samples and leaves gaps for invalid or unavailable telemetry. Measurements refresh approximately once per second and immediately after commands. The displayed setpoint inputs are values to submit; telemetry is the authoritative observation, especially after tests reset the device.

Controls expose TX enable/disable, NORMAL/SAFE mode, reset, attenuation, temperature, six fault types, and clear-fault. The optical meter supports TX/RX selection, measurement noise, and explicit timeout/error simulation. Error responses retain the underlying gRPC error code. Non-finite telemetry becomes JSON null and is labeled invalid rather than replaced with a plausible value.

The event panel displays actual timestamped simulator events, filtered by severity. It retains 512 entries and indicates gaps if older server events have been overwritten. Export JSON downloads the events currently retained by the browser.

## Validation and ownership

Smoke, link, thermal, fault, recovery, and full validation launch the existing pytest suite in a supervised subprocess against **the same gRPC endpoint as the workbench**. The suite does not create a second simulator. Each case establishes known environmental conditions and resets the device.

An exclusive lease blocks manual HTTP commands and meter requests while validation runs. Telemetry and logs remain readable. A second run is rejected. Cancellation terminates pytest and releases the lease; a 180-second limit bounds execution. The final device state is preserved for debugging rather than silently reset.

The lease applies to this API's clients. A separate program directly accessing the loopback gRPC endpoint can bypass it; this is a trusted local development environment, not a multi-user lab scheduler.

## Evidence

The pytest plugin emits setup, call, and teardown reports. A case is not marked passed until teardown completes. Timings include all three phases. Failed assertions and teardown errors appear in expandable rows. Overall success additionally requires a zero process exit code, completed cases, at least one passing case, and an actual JUnit report. Cancelled/incomplete execution is never promoted to success.

Each run has its own directory under `reports/web/runs/<id>/` containing available artifacts:

- `run.json`: identity, suite, UTC timestamps, target address, exit code, and source/binary/protocol SHA-256 fingerprints.
- `results.jsonl`: incremental pytest phase evidence.
- `junit.xml`: original pytest XML, if pytest completed far enough to produce it.
- `pytest.log` and `summary.txt`: original output and counts.
- `events.json`: bounded event snapshot after execution.
- `server.log`: simulator output spanning this run, including events older than the in-memory ring buffer.

The UI shows the latest 20 runs; files persist across API restarts. An unfinished run from a prior session is marked interrupted. There is no automatic deletion policy. Fingerprints identify the captured files; they are not signatures or proof of reproducible compilation. The source digest covers core and harness source, not the browser presentation files.

## Architecture and source link

`/architecture` explains the browser, API, harness, gRPC, HAL, simulator, and instruments. `/readme` serves the actual project README. No GitHub URL is invented for this local checkout. Once a repository is published, set `HALT_SOURCE_URL=https://github.com/OWNER/REPOSITORY` before starting the console to expose the source link.

## Local boundary

The API binds to IPv4 loopback, validates Host headers, and requires an unpredictable session token and matching browser origin for mutations. No cross-origin access is enabled. Command and suite names are allowlisted; subprocess arguments are passed as arrays without shell evaluation. Artifact names and run IDs are validated. A restrictive content security policy avoids third-party scripts and inline executable content.

This is not authenticated remote access. Do not expose the HTTP or gRPC listeners publicly. There are no hardware, calibration, vendor-protocol, or physical safety claims.

## Verify

```bash
bash scripts/test.sh
python -m pytest tests/web -v --junitxml=reports/web-junit.xml
python scripts/check_quality.py
python scripts/verify_clean.py --web
```

Web integration checks launch real C++ processes and execute every validation suite. They also verify cancellation, exclusive ownership, malformed inputs, artifact access, origin/token checks, device unavailability, and reporting of a genuinely failing pytest case and teardown error. CI uploads the web test subprocess evidence from `reports/web-integration/` alongside ordinary reports.

See [the demo guide](demo-guide.md) and [Phase 2 verification](web-verification.md).
