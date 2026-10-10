"""Export non-ignored Git working files and validate a fresh out-of-tree build (Linux)."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--web", action="store_true", help="Also run HTTP integration tests")
args = parser.parse_args()
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)
files = (
    subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT
    )
    .decode()
    .split("\0")
)
with tempfile.TemporaryDirectory(prefix="halt-clean-") as temporary:
    target = Path(temporary)
    for name in sorted(set(files) - {""}):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe source path: {name}")
        source = ROOT / relative
        if source.is_file():
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    environment = os.environ.copy()
    environment["HALT_PYTHON"] = sys.executable
    environment.pop("HALT_BUILD_DIR", None)
    environment.pop("HALT_SERVER", None)
    environment.pop("HALT_ADDRESS", None)
    environment.pop("HALT_REPORT_DIR", None)
    with (REPORTS / "clean-build.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(
            ["bash", "scripts/test.sh"],
            cwd=target,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode == 0 and args.web:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/web",
                    "-v",
                    "--junitxml=reports/web-junit.xml",
                ],
                cwd=target,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
    if (target / "reports").exists():
        shutil.copytree(target / "reports", REPORTS / "clean", dirs_exist_ok=True)
    if result.returncode:
        print((REPORTS / "clean-build.log").read_text(encoding="utf-8"))
        raise SystemExit(result.returncode)
print("Fresh-source build and tests passed; evidence: reports/clean and reports/clean-build.log")
