# Local verification record

Verified on **October 1, 2026 (America/Toronto)**. Log timestamps use UTC and therefore fall on October 2. These results come from actual builds and test runs, not sample reports.

## Environment

Windows host, with the C++ project built in WSL Ubuntu 24.04. The available Windows installation had no native C++ compiler. Linux prerequisites were installed before the first build, and Python dependencies were installed into a new project virtual environment.

- GCC 13.3.0 for the ordinary and clean builds.
- Clang 18.1.3 for the sanitizer build.
- CMake 3.28.3, protobuf compiler 3.21.12, distribution C++ gRPC 1.51.1.
- Python 3.12.3, grpcio/grpcio-tools 1.71.0, protobuf 5.29.4, pytest 8.3.5.
- clang-format/clang-tidy 18, Ruff 0.11.2, Black 25.1.0.
- actionlint 1.7.12, downloaded from its official release and checked against its published SHA-256 checksum list.

## Executed checks

1. **Ordinary CMake/Bash build and tests:** success, 8 C++ tests and 63 Python tests, zero failures/errors/skips. Last pytest run took about 18 seconds; timing is not a performance benchmark.
2. **Fresh-source build:** success, 8 C++ tests and 63 Python tests. `scripts/verify_clean.py` exported only non-ignored working source into a new temporary directory, with no generated bindings, object files, CMake cache, or server binary. It rebuilt everything and saved reports back to the original project. Installed system packages and the Python environment were reused. This was a fresh source export, not a checkout from a remote repository.
3. **ASan and UBSan:** success, 8 C++ tests and 63 Python tests, with leak detection and halt-on-error enabled. The process exited cleanly. Prebuilt gRPC/protobuf system libraries were not sanitizer-instrumented.
4. **clang-tidy build:** success with enabled project warnings treated as errors. The enum-size performance suggestion is disabled intentionally: preserving integer-sized enums prevents unknown protobuf values from narrowing into valid byte-sized values.
5. **Ruff, Black, clang-format, Bash syntax, workflow YAML structure:** passed through `scripts/check_quality.py`.
6. **GitHub Actions syntax:** actionlint accepted both workflows with exit code 0 and no diagnostics. Parsing a workflow does not establish hosted execution success.
7. **PowerShell syntax:** both scripts passed the native PowerShell parser. They have not compiled or tested the project with a Windows C++ toolchain locally.
8. **Logs inspected:** the ordinary run produced 1,170 JSON event records, including the boot sequence, instrument adjustments, alarms, fault recovery, and delayed telemetry requests. There were no non-JSON simulator lines in that run. The RPC event endpoint separately limits retained history to 512 entries, verified by tests.

## Reproduce

From the HALt directory in WSL, after installing README prerequisites:

```bash
HALT_PYTHON=.venv/bin/python bash scripts/test.sh
.venv/bin/python scripts/check_quality.py
cmake -S . -B build-tidy -DHALT_TIDY=ON -DCMAKE_BUILD_TYPE=Debug
cmake --build build-tidy --parallel 2
CC=clang-18 CXX=clang++-18 HALT_BUILD_DIR=build-asan \
  bash scripts/build.sh -DHALT_SANITIZERS=ON
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
HALT_BUILD_DIR=build-asan HALT_PYTHON=.venv/bin/python bash scripts/test.sh
.venv/bin/python scripts/verify_clean.py
```

The standard README uses the unversioned `clang++` command supplied by the `clang` package. This local run used the installed `clang++-18` executable explicitly.

## Evidence files

- `reports/validation.log`: ordinary build and test console output.
- `reports/junit.xml`: 63 pytest cases with zero failures/errors.
- `reports/cpp-junit.xml`: 8 C++ cases with zero failures.
- `reports/summary.txt`: human-readable pytest totals.
- `reports/server.log`: actual ordinary-run simulator events.
- `reports/clean-build.log` and `reports/clean/`: fresh-source run and its XML/logs.
- `reports/sanitizer-build.log`, `reports/sanitizer-test.log`, and `reports/sanitizers/`: sanitizer build/run and preserved XML/logs.
- `reports/clang-tidy.log`, `reports/quality.log`, `reports/actionlint.log`, `reports/powershell-syntax.log`: analysis evidence. Empty actionlint output indicates no diagnostics; its process returned 0.

Reports are deliberately ignored by Git. The CI workflow uploads run-specific reports as artifacts instead of committing changing results. A later local test run overwrites the ordinary report files.

## Not verified or not performed

- Native Windows C++ compilation, Windows end-to-end execution, and actual PowerShell build/test execution. The Windows CI job is configured but has not run here.
- Hosted GitHub Actions and CodeQL execution. The new local Git repository has no remote, and nothing has been committed or published. Do not show a passing hosted CI badge until a real run exists.
- Physical hardware, optical calibration, real firmware timing, vendor protocols, or physical safety. HALt models generic simulated behavior only.
- Website work: deliberately not started, following the brief's explicit instruction to stop after Phase 1 initially.

## Reference documentation used

The CMake/gRPC integration follows the generated-service approach documented in the [official gRPC C++ tutorial](https://grpc.io/docs/languages/cpp/basics/) and [CMake example](https://github.com/grpc/grpc/blob/master/examples/cpp/cmake/common.cmake). Workflow linting uses [actionlint](https://github.com/rhysd/actionlint). The CodeQL configuration uses the [documented manual-build workflow](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/manage-your-configuration/codeql-for-compiled-languages).
