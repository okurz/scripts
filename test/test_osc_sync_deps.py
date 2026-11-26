"""Tests for osc-sync-deps: the binary-to-source mapping and the three input modes."""

import pytest
from typer.testing import CliRunner

UNRESOLVABLES = """\
nothing provides python313-foo needed by bar
nothing provides python313-foo needed by baz
nothing provides (libqux >= 1.2) needed by bar
"""


@pytest.fixture
def sut(load_script):
    return load_script("osc-sync-deps")


@pytest.mark.parametrize(
    ("binary", "expected"),
    [
        ("python313-foo", "python-foo"),
        ("python311-bar-baz", "python-bar-baz"),
        ("libqux", "libqux"),
        ("(libqux", "libqux"),
        ("python3", "python3"),
    ],
)
def test_get_source_pkg_maps_the_binary_name(sut, binary, expected):
    assert sut.get_source_pkg(binary) == expected


def test_suggest_reads_the_input_file(sut, tmp_path):
    input_file = tmp_path / "unresolvables.txt"
    input_file.write_text(UNRESOLVABLES)

    result = CliRunner().invoke(sut.app, [str(input_file)])

    assert result.exit_code == 0
    assert "--- Identified Source Packages to Sync ---" in result.output
    assert "python-foo" in result.output
    assert "libqux" in result.output


def test_suggest_reads_stdin_when_it_is_piped(sut):
    result = CliRunner().invoke(sut.app, [], input=UNRESOLVABLES)

    assert result.exit_code == 0
    assert "python-foo" in result.output


def test_suggest_lists_every_source_package_once_and_sorted(sut, tmp_path):
    input_file = tmp_path / "unresolvables.txt"
    input_file.write_text(UNRESOLVABLES)

    result = CliRunner().invoke(sut.app, [str(input_file)])

    source_section = result.output.split("--- Suggested Commands ---")[0]
    assert source_section.count("python-foo") == 1
    assert source_section.index("libqux") < source_section.index("python-foo")


def test_suggest_prints_the_command_hints_per_package(sut, tmp_path):
    input_file = tmp_path / "unresolvables.txt"
    input_file.write_text(UNRESOLVABLES)

    result = CliRunner().invoke(sut.app, [str(input_file)])

    assert "# For python-foo:" in result.output
    assert "  # 1. Ensure you have a fork and clone of pool/python-foo" in result.output
    assert "  # 3. osc-sync-leap" in result.output


def test_suggest_reports_when_the_input_has_no_dependencies(sut, tmp_path):
    input_file = tmp_path / "empty.txt"
    input_file.write_text("all good\n")

    result = CliRunner().invoke(sut.app, [str(input_file)])

    assert result.exit_code == 0
    assert "No dependencies found in input." in result.output


def test_suggest_without_input_on_a_tty_exits_one(sut, mocker):
    stdin = mocker.MagicMock()
    stdin.isatty.return_value = True
    mocker.patch.object(sut.sys, "stdin", stdin)

    with pytest.raises(sut.typer.Exit) as excinfo:
        sut.suggest(None)

    assert excinfo.value.exit_code == 1
