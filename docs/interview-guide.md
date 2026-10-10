# HALt interview guide

## 1. Architecture in plain English

Python asks a compiled C++ program to perform device operations over gRPC. The C++ program updates a simulated optical module and instruments. Python checks the resulting state, measurements, errors, and recovery. Interfaces keep the control service independent of the concrete model.

## 2. Why C++?

It demonstrates typed device logic, RAII ownership, virtual interfaces, synchronization, and a background update thread. The program runs on a desktop OS; it is not microcontroller firmware. C++17 is sufficient and widely supported.

## 3. Why Python?

pytest makes scenarios, parameterized boundaries, fixtures, and JUnit output easy to read. The client sets explicit RPC deadlines and rejects telemetry marked invalid. Python orchestrates tests rather than duplicating the C++ device model.

## 4. Why gRPC?

The proto schema provides structured commands, generated clients, typed telemetry, and deadlines. It isolates the harness from C++ memory and implementation details. Its dependency and build cost is a tradeoff compared with a simple line protocol.

## 5. How does the HAL separate hardware from tests?

The service depends on IDevice and ITelemetryProvider. A replacement device implements the same operations and snapshots. The Python tests continue using the same RPCs. Instrument automation and simulator fault controls need additional capability handling when hardware replaces simulation.

## 6. How does fault injection work?

A typed RPC sets one enumerated fault. The next calculation (performed synchronously by the mutator) raises an alarm, disables TX, and enters a fault state. Sensor/invalid-telemetry faults corrupt a field; communication faults delay particular reads. Tests verify the effects, reject unsafe operations, then clear or reset and observe recovery.

## 7. How does the state machine work?

A transition function checks an explicit legal-edge function. The update thread advances timed states using a monotonic clock. Environmental thresholds can produce degradation or latched faults. Recovery requires acknowledgement and does not automatically enable TX. A hot environment persists across reset.

## 8. How does instrument automation work?

The attenuator modifies the external receive path; RX is -5 dBm minus attenuation. The meter reads a coherent telemetry snapshot and optionally adds Gaussian noise. Its timeout and error controls exercise automation failures. A temperature setpoint tests inclusive thermal limits. These are entirely simulated instruments.

## 9. How does CI work?

GitHub Actions is configured to build Ubuntu and Windows, generate bindings, run C++ and Python tests, and upload logs and XML even on failure. Linux adds formatting, static analysis, and sanitizers. A separate workflow configures CodeQL. Distinguish a workflow that exists from a hosted run that has actually succeeded; consult verification.md.

## 10. What bugs would these tests catch?

- A reversed `<` versus `<=` on RX loss or temperature limits.
- TX remaining enabled after a laser or sensor fault.
- An unchecked NaN bypassing range validation.
- Reset incorrectly erasing the external hot environment.
- A torn telemetry snapshot during concurrent TX toggles.
- A timeout blocking recovery because a service handler holds the device mutex.
- An unbounded diagnostic buffer growing during long test runs.

## 11. Three design tradeoffs

1. One mutex is easy to explain and protects snapshot consistency, but would limit throughput in a high-rate instrument system.
2. Deterministic telemetry and seeded measurement noise simplify repeatable tests, but do not model a real optical link's physics or timing.
3. Keeping diagnostic/recovery RPCs available during a communication fault makes recovery testable, but only simulates a partial transport failure.

## 12. What changes for real hardware?

Introduce an actual device adapter, documented physical transport, calibrated instrument drivers, unique device identity, and exclusive access. Separate injection capabilities from production commands, widen timing budgets, and add real safety interlocks and authorization. Do not claim simulated passing tests establish physical-device performance or safety.

## Five likely questions and concise answers

**How do you prevent races?** A device mutex covers mutations and whole snapshots; the meter RNG and event buffer have separate locks with a fixed acquisition order.

**How is a timeout test real?** The server delays a real gRPC response beyond the client's deadline, and the test checks DEADLINE_EXCEEDED before verifying that recovery RPCs still work.

**Why test at two layers?** GoogleTest verifies deterministic calculations and interface seams cheaply. pytest verifies generated bindings, the service, process lifecycle, and stateful scenarios together.

**What happens exactly at the thresholds?** -20 dBm RX remains valid; lower values assert RX_LOS. A module temperature of 85 °C already trips the thermal interlock.

**What is the biggest limitation?** It validates control and automation logic against a model, not an actual optical module. Hardware-specific timing, drivers, calibration, and safety remain separate engineering work.
