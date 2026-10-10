# Phase 2 verification — October 2, 2026

The local web console was implemented and exercised against the actual compiled C++ simulator in WSL Ubuntu. No telemetry or validation results are hardcoded.

## Executed

- Original core regression: **8 C++ tests and 63 Python firmware scenarios passed**.
- HTTP/API integration: **33 tests passed**, including actual execution of all six validation suites against the live console device.
- Fresh-source export: CMake rebuilt the simulator and generated bindings, then **8 C++ + 63 firmware + 33 web tests passed** without reusing build output.
- Ruff, Black, clang-format, Bash syntax, and workflow YAML structural checks passed. JavaScript passed Node syntax checking. Web source was formatted with Prettier.
- Browser interaction confirmed TX enable changed power, bias, and laser temperature; 16 dB attenuation produced -21 dBm RX, DEGRADED, and RX_LOS; the meter agreed with the simulated RX power.
- Browser interaction confirmed the thermal interlock rejected TX enable, explicit cooling/clear recovered the device, and invalid telemetry displayed a missing voltage with an invalid-sample label.
- A full validation launched from the browser completed with **63/63 passing cases** and actual timings and downloadable artifacts.
- Responsive workbench inspection at desktop and 390-pixel mobile widths found no horizontal overflow at the tested mobile width.

The web suite also verifies real timeout responses, all six faults, exclusive ownership, cancellation, unknown suite rejection, malformed values, session/origin checks, unavailable-device errors, persistent interrupted-run handling, and correct classification of a real failing pytest case and teardown error.

## Evidence

`reports/web-junit.xml` and `reports/web-tests.log` contain the API suite results. `reports/phase2-core.log` contains the original suite regression. `reports/phase2-quality.log` records quality checks. `reports/clean-build.log` and `reports/clean/` preserve the clean export's reports, including its web JUnit XML and individual validation-run subprocess artifacts. Browser-triggered runs are stored under `reports/web/runs/`.

One third-party Starlette/AnyIO deprecation warning appeared during TestClient execution; it did not fail any test. It is retained in the logs rather than suppressed.

## Remaining limitations

Native Windows compilation and actual PowerShell execution remain unverified locally; the scripts are provided and PowerShell syntax is checked. Hosted GitHub Actions and CodeQL have not run because this local Git repository has no remote. CI now includes the HTTP integration suite on both configured OS runners. This console is local-only, single-process, and uses entirely simulated hardware.

Phase 1 sanitizer and clang-tidy evidence remains in [verification.md](verification.md). No C++ model changes were required for Phase 2.
