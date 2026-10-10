#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
build_dir="${HALT_BUILD_DIR:-build}"
python_bin="${HALT_PYTHON:-python3}"
mkdir -p reports
bash scripts/build.sh
ctest --test-dir "$build_dir" --output-on-failure --output-junit "$PWD/reports/cpp-junit.xml"
"$python_bin" scripts/generate_proto.py
export HALT_SERVER="$PWD/$build_dir/halt_server"
"$python_bin" -m pytest -v "$@"
