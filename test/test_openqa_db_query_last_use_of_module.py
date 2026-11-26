"""Tests for openqa-db_query_last_use_of_module: SQL assembly, the ssh call and argument handling."""

import pytest


@pytest.fixture
def sut(load_script):
    return load_script("openqa-db_query_last_use_of_module")


@pytest.mark.parametrize(("verbose_flags", "expected"), [([], 40), (["-v"], 30), (["-v", "-v", "-v"], 10)])
def test_verbose_sets_the_log_level(sut, mocker, verbose_flags, expected):
    mocker.patch.object(sut.sys, "argv", ["openqa-db_query_last_use_of_module", *verbose_flags])
    mocker.patch.object(sut.log, "setLevel")

    sut.parse_args()

    sut.log.setLevel.assert_called_once_with(expected)


def test_parse_args_defaults(sut, mocker):
    mocker.patch.object(sut.sys, "argv", ["openqa-db_query_last_use_of_module"])

    args = sut.parse_args()

    assert args.openqa_host == "openqa.opensuse.org"
    assert args.limit == 30
    assert args.age == "90 days"
    assert args.dry_run is False


def test_call_runs_the_command(sut, fake_subprocess):
    fake_subprocess.on(["ssh"])

    assert sut.call(["ssh", "host", "true"]) == 0
    assert fake_subprocess.commands(["ssh"]) == [["ssh", "host", "true"]]


def test_call_echoes_the_command_in_dry_run_mode(sut, fake_subprocess):
    fake_subprocess.on(["echo"])

    sut.call(["ssh", "host", "true"], dry_run=True)

    assert fake_subprocess.commands(["echo"]) == [["echo", "Simulating: ", "ssh", "host", "true"]]


def test_main_queries_the_database_over_ssh(sut, mocker, monkeypatch):
    call = mocker.patch.object(sut, "call")
    monkeypatch.setattr(
        "sys.argv",
        ["openqa-db_query_last_use_of_module", "--module", "boot_to_desktop", "--limit", "5", "--age", "7 days"],
    )

    sut.main()

    command = call.call_args.args[0]
    assert command[:2] == ["ssh", "openqa.opensuse.org"]
    assert "name='boot_to_desktop'" in command[2]
    assert "interval '7 days'" in command[2]
    assert "limit 5" in command[2]
    assert call.call_args.kwargs["dry_run"] is False


def test_main_forwards_the_dry_run_flag(sut, mocker, monkeypatch):
    call = mocker.patch.object(sut, "call")
    monkeypatch.setattr("sys.argv", ["openqa-db_query_last_use_of_module", "--module", "m", "--dry-run"])

    sut.main()

    assert call.call_args.kwargs["dry_run"] is True
