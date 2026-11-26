"""Tests for osc-get-pr-status: osc failure handling, the unresolvable parser and the CLI output."""

import pytest
from typer.testing import CliRunner

RESULTS = """\
home:okurz:matrix  matrix-synapse  x86_64  unresolvable: nothing provides python3-foo
home:okurz:matrix  matrix-synapse  x86_64  succeeded
home:okurz:matrix  matrix-synapse  x86_64  nothing provides python3-foo
"""


@pytest.fixture
def sut(load_script):
    return load_script("osc-get-pr-status")


def test_get_detailed_results_returns_the_osc_output(sut, fake_subprocess):
    fake_subprocess.on(["osc", "results"], stdout=RESULTS)

    assert sut.get_detailed_results("home:okurz:matrix", "matrix-synapse") == RESULTS


def test_get_detailed_results_reports_a_failing_osc(sut, fake_subprocess, capsys):
    fake_subprocess.on(["osc", "results"], stderr="Server returned an error: 404", returncode=1)

    assert not sut.get_detailed_results("home:okurz:matrix", "matrix-synapse")
    assert "Error running osc: Server returned an error: 404" in capsys.readouterr().err


def test_parse_unresolvables_returns_the_sorted_unique_lines(sut):
    assert sut.parse_unresolvables(RESULTS) == [
        "home:okurz:matrix  matrix-synapse  x86_64  nothing provides python3-foo",
        "home:okurz:matrix  matrix-synapse  x86_64  unresolvable: nothing provides python3-foo",
    ]


def test_parse_unresolvables_of_a_clean_output_is_empty(sut):
    assert sut.parse_unresolvables("home:okurz:matrix  pkg  x86_64  succeeded\n") == []


def test_cli_prints_every_unresolvable(sut, mocker):
    mocker.patch.object(sut, "get_detailed_results", return_value=RESULTS)

    result = CliRunner().invoke(sut.app, ["home:okurz:matrix", "matrix-synapse"])

    assert result.exit_code == 0
    assert "--- Unresolvable Dependencies ---" in result.output
    assert result.output.count("nothing provides python3-foo") == 2


def test_cli_prints_the_full_output_with_verbose(sut, mocker):
    mocker.patch.object(sut, "get_detailed_results", return_value=RESULTS)

    result = CliRunner().invoke(sut.app, ["home:okurz:matrix", "matrix-synapse", "--verbose"])

    assert result.exit_code == 0
    assert RESULTS.strip() in result.output
    assert "--- Unresolvable Dependencies ---" not in result.output


def test_cli_reports_a_pending_build(sut, mocker):
    mocker.patch.object(sut, "get_detailed_results", return_value="home:okurz:matrix  pkg  x86_64  scheduled\n")

    result = CliRunner().invoke(sut.app, ["home:okurz:matrix"])

    assert result.exit_code == 0
    assert "No unresolvable issues found or build is still pending." in result.output


def test_cli_exits_one_without_osc_output(sut, mocker):
    mocker.patch.object(sut, "get_detailed_results", return_value="")

    result = CliRunner().invoke(sut.app, ["home:okurz:matrix"])

    assert result.exit_code == 1
