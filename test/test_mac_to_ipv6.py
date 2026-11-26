"""Tests for mac-to-ipv6: the EUI-64 derivation and the argv/stdin entry point."""

import pytest


@pytest.fixture
def sut(load_script):
    return load_script("mac-to-ipv6")


@pytest.mark.parametrize(
    ("mac", "expected"),
    [
        ("00:1a:2b:3c:4d:5e", "021a:2bff:fe3c:4d5e"),
        ("00:00:00:00:00:00", "0200:00ff:fe00:0000"),
        ("52:54:00:12:34:56", "5054:00ff:fe12:3456"),
        ("de:ad:be:ef:00:01", "dcad:beff:feef:0001"),
    ],
)
def test_mac_to_ipv6_flips_the_universal_bit_and_inserts_fffe(sut, mac, expected):
    assert sut.mac_to_ipv6(mac) == expected


def test_main_prefixes_the_argument_with_the_environment_prefix(sut, monkeypatch, capsys):
    monkeypatch.setenv("prefix", "fe80::")
    monkeypatch.setattr("sys.argv", ["mac-to-ipv6", "00:1a:2b:3c:4d:5e"])

    sut.main()

    assert capsys.readouterr().out.strip() == "fe80::021a:2bff:fe3c:4d5e"


def test_main_reads_the_mac_from_stdin_when_argv_is_short(sut, monkeypatch, capsys):
    monkeypatch.delenv("prefix", raising=False)
    monkeypatch.setattr("sys.argv", ["mac-to-ipv6"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "00:1a:2b:3c:4d:5e")

    sut.main()

    out = capsys.readouterr().out
    assert out.endswith("021a:2bff:fe3c:4d5e\n")
