#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/python"
exec "${HALT_PYTHON:-python3}" -m halt.web "$@"
