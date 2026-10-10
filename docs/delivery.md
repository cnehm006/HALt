# Phase 1 handoff (initial delivery)

Phase 2 has since been completed. See [the web console guide](web-console.md), [demo walkthrough](demo-guide.md), and [Phase 2 verification](web-verification.md). The record below preserves the initial engineering-core handoff.

This project was created in its own `HALt` directory. Phase 2 is intentionally not started: the brief explicitly says to stop after Phase 1 initially. All measurements and instruments represent a GENERIC SIMULATED OPTICAL COMMUNICATIONS MODULE.

## Repository tree

Generated build directories, virtual environments, caches, and report files are omitted here. Reports are created by actual runs and ignored by Git.

```text
HALt/
├── .clang-format
├── .clang-tidy
├── .gitattributes
├── .gitignore
├── .github/workflows/
│   ├── ci.yml
│   └── codeql.yml
├── CMakeLists.txt
├── LICENSE
├── README.md
├── pyproject.toml
├── requirements-dev.txt
├── vcpkg.json
├── proto/halt.proto
├── cpp/
│   ├── include/halt/
│   │   ├── device.hpp
│   │   ├── events.hpp
│   │   ├── hal.hpp
│   │   ├── instruments.hpp
│   │   ├── service.hpp
│   │   └── types.hpp
│   └── src/
│       ├── device.cpp
│       ├── events.cpp
│       ├── instruments.cpp
│       ├── main.cpp
│       ├── service.cpp
│       └── types.cpp
├── python/
│   ├── halt/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── client.py
│   │   └── generated/__init__.py
│   └── tests/
│       ├── conftest.py
│       ├── test_link.py
│       ├── test_smoke_state.py
│       ├── test_thermal_faults.py
│       └── test_timeout_robustness.py
├── tests/cpp/core_test.cpp
├── scripts/
│   ├── build.sh
│   ├── build.ps1
│   ├── test.sh
│   ├── test.ps1
│   ├── generate_proto.py
│   ├── check_quality.py
│   └── verify_clean.py
├── reports/.gitkeep
└── docs/
    ├── architecture.md
    ├── delivery.md
    ├── interview-guide.md
    └── verification.md
```

## Run on this machine

Open WSL Ubuntu and run:

```bash
cd /mnt/c/Users/metal/Desktop/projects/coding/HALt
source .venv/bin/activate
bash scripts/test.sh
```

That command rebuilds, runs GoogleTest, generates the Python bindings, starts a simulator, runs pytest, and stops the simulator. The existing `.venv` is a Linux environment, not a Windows environment.

Run the simulator interactively:

```bash
./build/halt_server --port 50051
```

From a second terminal in the same directory:

```bash
source .venv/bin/activate
PYTHONPATH=python python -m halt
```

Exact independent build/test commands and fresh-machine prerequisites are in [README.md](../README.md). Test subsets use `pytest -v -m smoke`, `link`, `thermal`, `fault`, `timeout`, `recovery`, `robustness`, or `concurrency`.

## Implemented test scenarios

- **Communication:** device identity, state, numeric telemetry fields, and uptime progression.
- **State:** boot transition sequence, SAFE/NORMAL changes, forbidden TX enable in standby, and reset state.
- **Optical:** enabled and disabled TX power, bias and laser temperature, meter agreement, attenuation delta, RX boundaries on both sides of -20 dBm, signal return, and configurable noise distribution.
- **Thermal:** normal/low temperature, exact 85 °C threshold, above-threshold fault/interlock, cooling followed by acknowledgement, and inability to bypass a hot environment by reset.
- **Faults:** all six faults assert their own alarms, enter FAULT, select SAFE, disable TX, reject unsafe enable, clear, recover, and require an explicit re-enable. Raw sensor/invalid-telemetry corruption is detected by the client. Supply and thermal injection alter actual modeled values.
- **Timeouts:** real RPC and instrument deadline expiry, instrument UNAVAILABLE, recovery after expiry, and recovery during a pending delayed telemetry call.
- **Robustness:** finite/range checks, unknown and negative enums, enum values wider than one byte, invalid noise, malformed protobuf, oversized requests, and bounded ordered event retention.
- **Concurrency:** eight workers issue 120 telemetry reads while toggling TX and verify that each snapshot's enable, power, and bias agree.
- **C++ unit tests:** transition rules, validation, HAL substitution with a fake provider, channel isolation, invalid measurements, device defaults, threshold calculations, and event bounds.

The final suite contains 8 GoogleTest cases and 63 parameterized pytest cases. The same tests run against ordinary and sanitizer builds. See [verification.md](verification.md) for evidence and limitations.

## Architecture in one paragraph

The Python harness speaks protobuf over gRPC to a C++ service. That service depends on a hardware interface implemented by a thread-safe simulator. A background thread advances time and states. Instruments read coherent snapshots or modify the external environment. Tests validate outputs, state transitions, alarms, errors, deadlines, and recovery without importing simulator internals.

## Resume claims

**Demonstrated locally:** “Built a C++ embedded-device simulator and Python firmware-validation framework covering command handling, state transitions, fault injection, timeouts, and recovery.” The source and executed tests support every part of this statement; explain that the device is simulated.

**Demonstrated locally:** automated compilation and test execution with CMake and Bash. Ubuntu/Windows GitHub Actions CI is configured and its workflow syntax is validated. A hosted GitHub Actions run has not occurred because there is no remote repository attached.

Until the first hosted run succeeds, the precise wording is: **“Automated compilation and test execution with CMake and Bash, and configured Ubuntu/Windows GitHub Actions CI.”** After publishing and a successful run, the original CI claim can be backed by a hosted run URL.

## Five interview questions

1. **Why a HAL?** It lets the service use a stable device contract while simulation or a later hardware adapter supplies the implementation.
2. **How do you prevent torn telemetry?** Mutations and full snapshot copies use the same mutex, so enabled TX, power, and bias stay consistent within a read.
3. **How are timeout tests genuine?** A real gRPC response is delayed beyond a client deadline, producing a verified DEADLINE_EXCEEDED status.
4. **Why two test languages?** C++ tests deterministic model components and seams; Python tests the full compiled process and network API.
5. **What would change with hardware?** Physical transport and calibrated instrument adapters, exclusive access, real safety mechanisms, and realistic timing budgets; the public RPC contract can remain stable.

The [interview guide](interview-guide.md) expands these answers and covers tradeoffs and examples of bugs the tests catch.
