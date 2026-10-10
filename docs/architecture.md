# Architecture and engineering decisions

HALt models a GENERIC SIMULATED OPTICAL COMMUNICATIONS MODULE. It implements generic concepts, without physical hardware or a proprietary protocol.

## Boundaries

The protobuf contract is the public boundary. Python cannot access a device object in C++; every system-test observation and action crosses a real gRPC channel. `ControlService` maps typed requests to `IDevice`, maps exceptions to gRPC status codes, and serializes coherent snapshots.

`IDevice` extends `ITelemetryProvider`. It covers normal device operations, reset, and test fault controls. `SimulatedDevice` implements those operations and a separate `ISimulatedEnvironment` interface. The environment interface drives test-only external temperature and attenuation. A real deployment would restrict or remove fault injection and map environmental controls to actual lab instruments.

`IInstrument` supplies identification. The optical meter takes `ITelemetryProvider`; the attenuator takes `ISimulatedEnvironment`. This small hierarchy provides useful seams without introducing a transport interface that duplicates gRPC. A real serial or I2C driver would belong below a new `IDevice` implementation.

## State and time

State transitions are enumerated in `legal_transition` and enforced by `transition`. Reset can enter BOOTING from any state. The model starts POWERED_OFF, then immediately boots. Boot, initialization, and recovery use monotonic timestamps; wall-clock changes cannot accelerate them. FAULT is latched until an explicit recovery command, and ENABLE_TX is legal only in NORMAL mode in READY or DEGRADED.

SAFE maps to STANDBY for normal operator commands. A safety fault selects SAFE and FAULT. READY becomes DEGRADED on loss of signal and returns when RX crosses back to the valid side of the threshold. No hysteresis is modeled: the exact boundary is part of the test contract.

## Thread ownership and locking

One thread refreshes state and telemetry about every 10 ms. gRPC dispatches simultaneous calls on its own worker threads. A single device mutex protects all state, setpoints, timestamps, and telemetry. Every mutator recalculates telemetry before releasing it, so a reader never sees TX enabled alongside disabled-TX power. `snapshot()` returns a copy rather than a reference to protected storage.

The condition variable allows immediate worker shutdown; the destructor signals it and joins the thread. The meter has its own mutex around its pseudo-random generator. The event log has a separate mutex; lock order is device then event log. Event readers never acquire the device mutex, avoiding reverse-order deadlock. Power measurements snapshot the source before locking the random generator.

Timeout simulation sleeps outside all model locks and is bounded to 300 ms. It observes RPC cancellation every 5 ms. A timed-out request can coexist with a recovery call without blocking the device update thread.

A mutation RPC's returned status is a snapshot taken after the mutation. Concurrent clients may change the device between those two operations; it is not a transaction receipt. Each snapshot itself is coherent. Tests verify snapshot invariants rather than assuming concurrent commands have exclusive ownership.

## Error semantics

- Invalid enum, non-finite value, or range violation: INVALID_ARGUMENT.
- Command disallowed by state or interlock: FAILED_PRECONDITION.
- Simulated measurement/communications failure: UNAVAILABLE, unless the client deadline expires first.
- Invalid telemetry remains available for diagnostics with `valid=false`; the Python validating accessor rejects it.
- Protobuf decode failure is handled by gRPC, and a subsequent valid RPC must still work.

GetStatus and recovery remain functional under communication timeout by design. They represent an out-of-band diagnostic channel within this simplified single-service model. This limitation is explicit rather than claiming a complete transport outage.

## Replacing simulation with hardware

Implement IDevice using a physical-device transport and convert raw units into Snapshot fields. Keep the protobuf boundary stable so most Python tests still run. Replace the meter with an instrument adapter (for example, a documented VISA/SCPI driver), and the environmental controls with lab-safe attenuator and thermal-controller operations. Move simulator-only tests behind capability flags. Add authentication, exclusive test leases, calibration, electrical/laser interlocks, realistic time budgets, and serial-number attribution. An actual hardware project must establish safety limits separately; HALt's thresholds are illustrative.

## Dependency choices

CMake consumes installed protobuf/gRPC and GoogleTest packages. Linux uses distribution packages and Windows uses vcpkg. Generated C++ and Python bindings share the same source schema. Tests do not fake an RPC server. The Python runner owns its child process, waits for a readiness handshake, and terminates it even after failure. C++ and Python test reports serve different purposes and are retained separately.
