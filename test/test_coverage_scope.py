"""Tests for the coverage scope guard: which files it tracks and how it reports a gap."""

from pathlib import Path

import coverage_scope
import pytest
from conftest import ROOT


def test_tracked_python_files_includes_extensionless_scripts():
    tracked = coverage_scope.tracked_python_files()

    assert "obs-pr-repair" in tracked
    assert "gh-pr-triage" in tracked
    assert "bluelinktoken.py" in tracked


def test_tracked_python_files_skips_the_test_directory_and_non_python_files():
    tracked = coverage_scope.tracked_python_files()

    assert not [name for name in tracked if name.startswith("test/")]
    assert "Makefile" not in tracked
    assert "git-review" not in tracked


def test_is_python_accepts_a_suffix_and_a_shebang(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage_scope, "ROOT", tmp_path)
    (tmp_path / "script").write_text("#!/usr/bin/env python3\n")
    (tmp_path / "module.py").write_text("x = 1\n")
    (tmp_path / "shell").write_text("#!/bin/bash\n")

    assert coverage_scope.is_python("script") is True
    assert coverage_scope.is_python("module.py") is True
    assert coverage_scope.is_python("shell") is False


def summary(*, missing: int = 0, partial: int = 0) -> dict:
    return {"summary": {"missing_lines": missing, "num_partial_branches": partial}}


def test_problems_is_empty_for_fully_covered_files():
    files = {str(ROOT / "script"): summary()}

    assert coverage_scope.problems(["script"], files, {str(ROOT / "script")}) == []


def test_problems_names_a_file_that_was_never_imported():
    assert coverage_scope.problems(["script"], {}, set()) == [
        "script: never imported, so this file escapes the coverage gate"
    ]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (summary(missing=3), "script: 3 uncovered statements, 0 partially covered branches"),
        (summary(partial=2), "script: 0 uncovered statements, 2 partially covered branches"),
    ],
)
def test_problems_counts_statements_and_partial_branches(entry, expected):
    files = {str(ROOT / "script"): entry}

    assert coverage_scope.problems(["script"], files, {str(ROOT / "script")}) == [expected]


def test_report_reads_the_loaded_coverage_data(mocker):
    cov = mocker.MagicMock()
    cov.get_data.return_value.measured_files.return_value = {str(ROOT / "script")}
    payload = (
        '{"files": {"' + str(ROOT / "script") + '": {"summary": {"missing_lines": 0, "num_partial_branches": 0}}}}'
    )
    cov.json_report.side_effect = lambda outfile, **_kwargs: Path(outfile).write_text(payload, encoding="utf-8")

    assert coverage_scope.report(cov, ["script"]) == []


def test_main_reports_a_gap_and_exits_one(mocker, capsys):
    mocker.patch.object(coverage_scope, "tracked_python_files", return_value=["script"])
    mocker.patch.object(coverage_scope, "report", return_value=["script: never imported"])
    cov = mocker.patch.object(coverage_scope.coverage, "Coverage")

    assert coverage_scope.main() == 1
    assert cov.return_value.load.called
    assert "script: never imported" in capsys.readouterr().err


def test_main_passes_and_names_the_file_count(mocker, capsys):
    mocker.patch.object(coverage_scope, "tracked_python_files", return_value=["script", "other"])
    mocker.patch.object(coverage_scope, "report", return_value=[])
    mocker.patch.object(coverage_scope.coverage, "Coverage")

    assert coverage_scope.main() == 0
    assert "coverage scope: 2 tracked Python files at 100%" in capsys.readouterr().out


def test_the_makefile_runs_the_scope_check_after_the_tests():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-coverage-scope:" in makefile
    assert "$(MAKE) check-coverage-scope" in makefile


def test_main_without_coverage_data_explains_what_to_run(mocker, capsys):
    cov = mocker.patch.object(coverage_scope.coverage, "Coverage")
    cov.return_value.get_data.return_value.measured_files.return_value = set()
    report = mocker.patch.object(coverage_scope, "report")

    assert coverage_scope.main() == 2
    assert "no coverage data: run make test-unit first" in capsys.readouterr().err
    report.assert_not_called()
