# HALt
Hardware Abstraction Layer Tester

A simulated embedded-device and instrumentation environment for developing and validating automated firmware test workflows.

**HALt uses simulated hardware and generic optical-communications concepts. It does not emulate or interface with any proprietary commercial hardware.**

The device is a **GENERIC SIMULATED OPTICAL COMMUNICATIONS MODULE**. C++ implements the device and laboratory model; Python drives its gRPC interface. Nothing measures physical hardware. This is a host-side firmware-validation environment, not firmware running on a microcontroller.

## Architecture

```text
Python automation / pytest
          |
     gRPC + Protobuf                 C++ process
          v
    ControlService ----------------> EventLog (bounded, UTC JSON lines)
          |
          +-- IDevice / ITelemetryProvider
          |           |
          |     SimulatedDevice <----- background update thread (10 ms)
          |           ^
          +-- ISimulatedEnvironment -- OpticalAttenuator / temperature input
          |
          +-- OpticalPowerMeter ------ ITelemetryProvider
```

The service accepts `IDevice` rather than the concrete simulator. Tests only know the protobuf API. The optical meter also accepts an abstract telemetry source; C++ tests substitute a fixed fake to verify this separation. Simulation environmental controls have a separate interface because setting room temperature is not a device firmware command. See [architecture](docs/architecture.md) for concurrency, state transitions, and replacement boundaries.

## Build and test on Ubuntu 24.04 / WSL Ubuntu

Install prerequisites once:

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build libgrpc++-dev \
  libprotobuf-dev protobuf-compiler-grpc libgtest-dev python3-venv \
  clang clang-format clang-tidy
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

From the HALt folder:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
python scripts/generate_proto.py
pytest -v
```

Or use the automation, which configures, compiles, generates bindings, runs C++ tests, starts its own simulator, runs Python tests, and tears it down:

```bash
bash scripts/test.sh
```

`HALT_PYTHON` selects Python when a virtual environment is not activated. `HALT_BUILD_DIR` selects an alternate build directory. The Bash build script accepts additional CMake arguments. The test script accepts pytest arguments.

## Build and test on Windows

Prerequisites: Visual Studio 2022 Build Tools with the C++ workload and Windows SDK, CMake 3.22+, Git, Python 3.12, and [vcpkg](https://github.com/microsoft/vcpkg). Run from a Developer PowerShell. If vcpkg is not installed:

```powershell
git clone https://github.com/microsoft/vcpkg ../vcpkg
../vcpkg/bootstrap-vcpkg.bat
```

Configure the toolchain once (the manifest installs gRPC, protobuf, and GoogleTest):

```powershell
python -m venv .venv-win
./.venv-win/Scripts/python.exe -m pip install -r requirements-dev.txt
cmake -S . -B build-win -DCMAKE_TOOLCHAIN_FILE="$PWD/../vcpkg/scripts/buildsystems/vcpkg.cmake" -DVCPKG_TARGET_TRIPLET=x64-windows
./scripts/test.ps1 -BuildDir build-win -Python ./.venv-win/Scripts/python.exe
```

Do not share a CMake build directory or Python venv between Windows and Linux. Native Windows execution is covered by the CI configuration; see [local verification](docs/verification.md) for what has actually been run. vcpkg resolves against its checked-out registry; pin that checkout when adopting the project in a controlled environment.

## Run the simulator and read telemetry

```bash
./build/halt_server --port 50051
# In another terminal, with the Python environment active:
PYTHONPATH=python python -m halt --address 127.0.0.1:50051
```

Windows: run `./build-win/Release/halt_server.exe`, then set `$env:PYTHONPATH='python'` and use `./.venv-win/Scripts/python.exe -m halt`.

The server binds only IPv4 loopback. Port `0` requests an available port, reported as `HALT_PORT=<number>`. Ctrl+C shuts down the Linux server gracefully. The integration fixture never attaches to an unrelated existing simulator.

## State machine and safety

```text
POWERED_OFF -> BOOTING -> INITIALIZING -> READY
                                         |  ^
                        RX loss          v  | signal returns
                                      DEGRADED
READY / DEGRADED -> STANDBY (SAFE mode) -> READY (NORMAL)
Operational / INITIALIZING / RECOVERING -> FAULT
FAULT -> RECOVERING -> READY
Any state -> BOOTING (RESET)
```

Boot and initialization each take at least 100 ms; recovery takes at least 100 ms. Background scheduling is approximate, so tests poll with a deadline. Faults disable TX and select SAFE. Cooling alone does not clear a latched fault: `ClearFault` acknowledges it after the unsafe condition is removed. Recovery never re-enables TX automatically. Reset clears injected faults and TX enable but retains external lab conditions. Illegal commands return `FAILED_PRECONDITION`.

## Simulated ranges and instruments

- Supply is 3.3 V normally and 2.5 V under injected supply failure.
- External temperature accepts -40 through 125 °C. At **85 °C or above**, the thermal alarm/interlock trips.
- TX enabled produces 0 dBm, 35 mA bias, and a +3 °C laser-temperature offset. Disabled TX is represented by a -80 dBm floor and zero bias, not mathematical negative infinity.
- RX power is `-5 dBm - attenuation`. Attenuation accepts 0 through 60 dB. **Below -20 dBm** asserts loss of signal; exactly -20 dBm remains valid.
- Link state describes a simulated external receive path. RX can be up while the local transmitter is disabled; it is not an optical loopback.
- The meter selects TX/RX, with configurable 0–2 dB Gaussian standard deviation. A seeded generator makes runs repeatable, not calibration-accurate. Zero noise gives exact measurements. Timeout and instrument error injection are separate request controls.
- The temperature controller is a direct simulated setpoint, not a physical thermal plant. No SCPI parser is needed; instruments use structured gRPC commands.

## gRPC commands

`proto/halt.proto` is the contract. CMake generates C++ bindings, and `scripts/generate_proto.py` generates Python bindings. Generated files are not maintained manually.

`Ping`, `GetStatus`, and `GetTelemetry` provide identity, state, and all scalar measurements (temperature, voltage, powers, bias, and link state). `SetMode`, `EnableTransmitter`, `DisableTransmitter`, `Reset`, `InjectFault`, and `ClearFault` control the device. `SetAttenuation`, `SetTemperature`, and `MeasurePower` drive the lab model. `GetEvents` retrieves the latest 512 actual simulator events.

Python example (with `PYTHONPATH=python`):

```python
from halt.client import DeviceClient
from halt.generated import halt_pb2 as pb

device = DeviceClient("127.0.0.1:50051")
try:
    device.wait_state()
    device.call("EnableTransmitter")
    device.call("SetAttenuation", pb.Scalar(value=16))
    assert not device.call("GetStatus").link_up
    print(device.call("MeasurePower", pb.MeterRequest(channel=pb.RX)))
finally:
    device.close()
```

## Fault injection and timeouts

Six typed faults are supported: `SENSOR_FAILURE`, `COMMUNICATION_TIMEOUT`, `OVER_TEMPERATURE`, `INVALID_TELEMETRY`, `LASER_FAULT`, `POWER_SUPPLY_FAULT`. Each asserts its alarm and the TX interlock. Sensor and invalid-telemetry faults also mark telemetry invalid and corrupt the relevant field with NaN; the validating Python client rejects it.

Communication timeout delays `Ping` and `GetTelemetry` by up to 300 ms. Short client deadlines therefore cause real gRPC `DEADLINE_EXCEEDED`, while a longer deadline yields `UNAVAILABLE`. Diagnostic status and recovery RPCs intentionally remain available, modeling a separate management path. Delays do not hold device locks and check cancellation every 5 ms. This is fault simulation, not a dropped physical bus.

## Tests and reports

C++ GoogleTest exercises transition rules, numeric validation, the HAL/meter seam, alarm boundaries, and the bounded event buffer. Python pytest tests the compiled server end to end through gRPC, including all six faults and concurrent client requests.

```bash
pytest -v                             # all system tests; owns a fresh simulator
pytest -v -m smoke
pytest -v -m link
pytest -v -m thermal
pytest -v -m fault
pytest -v -m timeout
pytest -v -m recovery
pytest -v -m concurrency
```

Reports are generated from execution: `reports/junit.xml`, `reports/cpp-junit.xml` (automation), `reports/summary.txt`, and `reports/server.log`. Failed test events are saved as individual JSON files. Simulator logs are JSON lines, including the startup port handshake. Every normal test gets a reset device and known external conditions. Tests intentionally share one server sequentially; pytest-xdist is not supported for this suite.

## Quality and CI

```bash
python scripts/check_quality.py
cmake -S . -B build-tidy -DHALT_TIDY=ON
cmake --build build-tidy --parallel 2
CC=clang CXX=clang++ HALT_BUILD_DIR=build-asan bash scripts/build.sh -DHALT_SANITIZERS=ON
HALT_BUILD_DIR=build-asan bash scripts/test.sh
```

`ci.yml` configures Ubuntu and Windows builds, runs both test layers, and uploads reports even when tests fail. Linux also runs Ruff, Black, clang-format, clang-tidy, and ASan/UBSan. `codeql.yml` configures C++ and Python security analysis; hosted execution requires a repository with CodeQL available. There is no deployment step because Phase 1 is an engineering harness. No hosted CI success is claimed until the workflows actually run.

## Robustness and limitations

Inputs reject NaN, infinity, invalid enums, and out-of-range lab settings. RAII owns the server, threads, locks, and channel lifetime. Snapshot copies are atomic under a mutex. Telemetry calculations never race a mutation. No command passes user input to a shell. Receive messages are capped at 64 KiB; events at 512 entries. The loopback RPC listener uses plaintext and no authentication; it is a local trusted development tool and must not be exposed as a production service.

The simulator is intentionally deterministic and simplified. It has no register map, real driver, hardware timing guarantees, BER model, wavelength control, or vendor protocol. Sanitizers instrument project code, not prebuilt system gRPC libraries. Different gRPC dependency versions are allowed across native C++ and Python because they share the protobuf wire contract.

Read [the initial project handoff and tree](docs/delivery.md), [interview guide](docs/interview-guide.md), [architecture details](docs/architecture.md), and [core verification record](docs/verification.md).

## Web console

Phase 2 adds a small, local engineering console with live telemetry, actual device events, transmitter and instrument controls, fault injection, and real pytest execution. Plain HTML/CSS/JavaScript talks to FastAPI, which uses the same C++ gRPC service. Validation takes exclusive ownership of the displayed device and retains per-run evidence.

```bash
source .venv/bin/activate
python -m pip install -r requirements-web.txt
python scripts/generate_proto.py
bash scripts/serve.sh --port 8051
```

Open http://127.0.0.1:8051. The launcher starts and owns the simulator automatically. Use Ctrl+C to shut it down.

```bash
python -m pytest tests/web -v --junitxml=reports/web-junit.xml
python scripts/verify_clean.py --web
```

See [console operation and architecture](docs/web-console.md), [the five-minute interview demo](docs/demo-guide.md), and [Phase 2 verification](docs/web-verification.md). The console is not publicly deployed and does not claim hosted CI or physical-hardware validation.
