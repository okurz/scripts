"""Fail when a tracked Python file is not imported, or below 100% statement and branch coverage.

The check needs the combined data of the whole run, so it runs after pytest (see the
`check-coverage-scope` target) instead of as a test inside it: with `pytest -n auto` every worker
only sees its own lines, which would make an in-session assertion meaningless.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import coverage

ROOT = Path(__file__).resolve().parent.parent
OMITTED_PREFIXES = ("test/",)
PYTHON_SHEBANGS = ("#!/usr/bin/env python", "#!/usr/bin/python")
SUMMARY_KEYS = ("missing_lines", "num_partial_branches")


def tracked_python_files() -> list[str]:
    """Return every tracked file that is Python by suffix or by python shebang."""
    names = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.split()
    return [name for name in names if not name.startswith(OMITTED_PREFIXES) and is_python(name)]


def is_python(name: str) -> bool:
    """Return whether a tracked path is Python, by suffix or by its python shebang."""
    head = (ROOT / name).read_text(encoding="utf-8", errors="ignore").split("\n", 1)[0]
    return name.endswith(".py") or head.startswith(PYTHON_SHEBANGS)


def resolve(path: str) -> str:
    """Return the absolute path of a coverage filename, which the report may state relative."""
    return str((ROOT / path).resolve())


def problems(paths: list[str], files: dict[str, dict], measured: set[str]) -> list[str]:
    """Return one reason per path that is unmeasured or not fully covered."""
    files = {resolve(name): entry for name, entry in files.items()}
    measured = {resolve(name) for name in measured}
    found = []
    for path in paths:
        filename = resolve(path)
        summary = files.get(filename, {}).get("summary")
        if filename not in measured or summary is None:
            found.append(f"{path}: never imported, so this file escapes the coverage gate")
            continue
        if any(summary.get(key) for key in SUMMARY_KEYS):
            found.append(
                f"{path}: {summary['missing_lines']} uncovered statements, "
                f"{summary['num_partial_branches']} partially covered branches"
            )
    return found


def report(cov: coverage.Coverage, paths: list[str]) -> list[str]:
    """Return the coverage problems of paths, read from the loaded coverage data."""
    with tempfile.TemporaryDirectory() as directory:
        reporter = Path(directory) / "coverage.json"
        cov.json_report(outfile=str(reporter), ignore_errors=True)
        files = json.loads(reporter.read_text(encoding="utf-8"))["files"]
    return problems(paths, files, cov.get_data().measured_files())


def main() -> int:
    """Print every tracked Python file below 100% and exit non-zero when there is one."""
    cov = coverage.Coverage(config_file=True)
    cov.load()
    paths = tracked_python_files()
    found = report(cov, paths)
    if not found:
        print(f"coverage scope: {len(paths)} tracked Python files at 100% statement and branch coverage")
        return 0
    print("tracked Python files below 100% statement and branch coverage:", file=sys.stderr)
    for line in found:
        print(f"  {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
