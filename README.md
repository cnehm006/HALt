# HALt

Hardware Abstraction Layer Tester.

HALt is a local test bench for a simulated optical communications module. The device runs in C++, Python tests control it over gRPC, and a browser console lets you watch telemetry, change lab conditions, and inject faults.

The idea is to test what happens when things go wrong: a sensor returns bad data, a request times out, a link drops, or the device overheats. Everything runs without physical hardware.

## Try it

These commands target Ubuntu 24.04, including Ubuntu in WSL. Run them from the project directory.

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build libgrpc++-dev \
  libprotobuf-dev protobuf-compiler-grpc libgtest-dev python3-venv \
  clang clang-format clang-tidy

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-web.txt
bash scripts/test.sh
bash scripts/serve.sh --port 8051
```

Open <http://127.0.0.1:8051>. The launcher starts the simulator and shuts it down when you press Ctrl+C.

A useful first run: enable the transmitter, increase attenuation until the receive link drops, then raise the temperature to 85 °C. The thermal fault disables TX. Lower the temperature and clear the fault to recover; TX stays off until you explicitly enable it again.

The [demo guide](docs/demo-guide.md) walks through a longer session. See [console setup](docs/web-console.md) for configuration and how test runs share the device with the UI.

## What's inside

```text
Browser console -- FastAPI --+
                            +-- gRPC / Protobuf -- C++ simulator
Python client / pytest -----+                          |
                                            device state machine
                                            telemetry and event log
                                            simulated instruments
```

- **C++17 device model:** boot, initialization, normal operation, standby, faults, and recovery, with a background update loop.
- **Hardware abstraction:** the service uses device interfaces rather than depending on the simulator directly. The optical meter reads through a separate telemetry interface.
- **Lab controls:** attenuation, temperature, and a TX/RX power meter with optional seeded noise.
- **Python tests:** state transitions, alarm thresholds, fault recovery, timeouts, and concurrent requests against the compiled server.
- **Web console:** live telemetry, device controls, event history, and pytest runs with saved logs and reports.

The model uses generic optical communications concepts. It doesn't implement a vendor protocol or connect to real hardware. The [architecture notes](docs/architecture.md) cover the interfaces, threading, and state transitions.

## Build on Windows

Use a Developer PowerShell with Visual Studio 2022 Build Tools (C++ workload and Windows SDK), CMake 3.22+, Git, Python 3.12, and [vcpkg](https://github.com/microsoft/vcpkg).

```powershell
# Skip these two commands if you already have vcpkg.
git clone https://github.com/microsoft/vcpkg ../vcpkg
../vcpkg/bootstrap-vcpkg.bat

python -m venv .venv-win
./.venv-win/Scripts/python.exe -m pip install -r requirements-web.txt
cmake -S . -B build-win -DCMAKE_TOOLCHAIN_FILE="$PWD/../vcpkg/scripts/buildsystems/vcpkg.cmake" -DVCPKG_TARGET_TRIPLET=x64-windows
./scripts/test.ps1 -BuildDir build-win -Python ./.venv-win/Scripts/python.exe
```

Use separate build directories and virtual environments for Windows and WSL. The vcpkg manifest installs gRPC, Protobuf, and GoogleTest; dependency versions follow your vcpkg checkout.

## Run tests

```bash
bash scripts/test.sh                   # build, C++ tests, and gRPC integration tests
pytest -v -m smoke                     # quick device checks after building
pytest -v -m thermal
pytest -v -m fault
pytest -v -m timeout
python -m pytest tests/web -v --junitxml=reports/web-junit.xml
python scripts/verify_clean.py --web   # check a fresh source copy
```

Other pytest markers include `link`, `recovery`, and `concurrency`. The integration suite starts its own simulator and resets device state and lab conditions between tests. Tests share that server sequentially, so don't run this suite with pytest-xdist.

Reports go in `reports/`: JUnit XML, a text summary, server logs, and event records for failed tests. Web-console runs keep their own reports. Generated reports and build outputs stay out of Git.

Set `HALT_PYTHON` to select a Python executable or `HALT_BUILD_DIR` to use a different build directory. The Bash build script accepts CMake arguments; the test script accepts pytest arguments.

## Use the Python client

Start the server in one terminal:

```bash
./build/halt_server --port 50051
```

In another terminal, activate the virtual environment and set `PYTHONPATH=python`. Then:

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

For a telemetry readout, use `PYTHONPATH=python python -m halt --address 127.0.0.1:50051`.

On Windows, the server is `./build-win/Release/halt_server.exe`. Set `$env:PYTHONPATH='python'` before using the client.

The RPC contract is in [`proto/halt.proto`](proto/halt.proto). CMake generates the C++ bindings; `python scripts/generate_proto.py` generates the Python bindings.

## Device behavior

Boot and initialization each take at least 100 ms. Tests poll for state changes with a deadline rather than relying on exact sleep durations.

- Temperature accepts -40 to 125 °C. The thermal interlock trips at 85 °C.
- RX power is `-5 dBm - attenuation`. Attenuation ranges from 0 to 60 dB; RX loss starts below -20 dBm.
- Enabled TX produces 0 dBm and 35 mA bias. Disabled TX reads -80 dBm with zero bias.
- Faults disable TX and select SAFE mode. Removing the cause isn't enough: `ClearFault` acknowledges the fault, and recovery leaves TX disabled.
- Reset clears injected faults and TX enable while keeping external lab conditions.

The six injectable faults are sensor failure, communication timeout, over-temperature, invalid telemetry, laser fault, and power-supply fault. Invalid sensor data is rejected by the Python client. Timeout injection delays RPCs so tests exercise actual gRPC deadlines; status and recovery commands remain available.

## Checks and CI

```bash
python scripts/check_quality.py
cmake -S . -B build-tidy -DHALT_TIDY=ON
cmake --build build-tidy --parallel 2
CC=clang CXX=clang++ HALT_BUILD_DIR=build-asan bash scripts/build.sh -DHALT_SANITIZERS=ON
HALT_BUILD_DIR=build-asan bash scripts/test.sh
```

The [GitHub workflows](https://github.com/cnehm006/HALt/actions) define Ubuntu and Windows builds, test reports, Python and C++ style checks, clang-tidy, ASan/UBSan, and CodeQL. CodeQL requires repository support. Local results are recorded in the [core verification notes](docs/verification.md) and [web verification notes](docs/web-verification.md).

## Limits

This is a host-side simulator, not embedded firmware. There's no register map, real driver, BER model, wavelength control, or hardware timing guarantee. Meter noise is repeatable test input, not a calibrated instrument model.

The services are intended for local use. The gRPC listener binds to loopback and has no authentication or TLS. Keep it off public interfaces.
