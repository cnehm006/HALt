"""Run formatting, Python lint, shell syntax and workflow structure checks."""

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


run(sys.executable, "-m", "ruff", "check", "python", "scripts", "tests/web")
run(sys.executable, "-m", "black", "--check", "python", "scripts", "tests/web")
sources = sorted((ROOT / "cpp").rglob("*.cpp")) + sorted((ROOT / "cpp").rglob("*.hpp"))
sources += sorted((ROOT / "tests" / "cpp").glob("*.cpp"))
run("clang-format", "--dry-run", "--Werror", *(str(path) for path in sources))
run("bash", "-n", "scripts/build.sh", "scripts/test.sh", "scripts/serve.sh")
# BaseLoader avoids YAML 1.1 interpreting the Actions 'on' key as a boolean.
for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
    data = yaml.load(workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert {"push", "pull_request"} <= set(data["on"]), workflow
    assert data["jobs"], workflow
    for job in data["jobs"].values():
        assert "runs-on" in job and job["steps"], workflow
print("Quality checks passed (workflow parsing is not a hosted Actions run).")
