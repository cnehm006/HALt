#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
build_dir="${HALT_BUILD_DIR:-build}"
cmake -S . -B "$build_dir" -DCMAKE_BUILD_TYPE=Debug "$@"
cmake --build "$build_dir" --parallel "${HALT_BUILD_JOBS:-2}"
