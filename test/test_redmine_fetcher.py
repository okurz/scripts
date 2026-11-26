"""Tests for redmine-fetcher: ticket id parsing, markdown rendering and the request failure path."""

import pytest
import requests


@pytest.fixture
def sut(load_script, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("REDMINE_HOST", raising=False)
    monkeypatch.delenv("REDMINE_API_TOKEN", raising=False)
    return load_script("redmine-fetcher")


ISSUE = {
    "id": 249076,
    "subject": "Keep Tumbleweed in sync with Factory",
    "status": {"name": "Feedback"},
    "priority": {"name": "Normal"},
    "assigned_to": {"name": "Oliver Kurz"},
    "description": "Release Team wants the Leap branches synced.",
}


def test_normalize_ticket_id_keeps_a_bare_id(sut):
    assert sut.normalize_ticket_id("249076") == "249076"


def test_normalize_ticket_id_extracts_the_id_from_a_url(sut):
    assert sut.normalize_ticket_id("https://progress.opensuse.org/issues/249076/") == "249076"


def test_normalize_ticket_id_strips_the_json_suffix(sut):
    assert sut.normalize_ticket_id("https://progress.opensuse.org/issues/249076.json") == "249076"


def test_clean_host_drops_a_configured_scheme(sut):
    assert sut.clean_host("https://progress.opensuse.org") == "progress.opensuse.org"


def test_print_issue_writes_the_header_and_description(sut, capsys):
    sut.print_issue(ISSUE, "249076", "progress.opensuse.org")
    out = capsys.readouterr().out
    assert out.startswith("## Issue #249076: Keep Tumbleweed in sync with Factory")
    assert "- URL: https://progress.opensuse.org/issues/249076" in out
    assert "Release Team wants the Leap branches synced." in out


def test_print_journals_skips_entries_without_notes(sut, capsys):
    journals = [{"notes": "Build is green."}, {"user": {"name": "Anne"}, "created_on": "2026-01-02"}]
    sut.print_journals(journals)
    out = capsys.readouterr().out
    assert "### Journals" in out
    assert "Build is green." in out
    assert out.count("####") == 1


def test_print_journals_prints_nothing_for_an_empty_list(sut, capsys):
    sut.print_journals([])
    assert not capsys.readouterr().out


def test_fetch_ticket_exits_one_on_request_error(sut, capsys, mocker):
    mocker.patch.object(sut.requests, "get", side_effect=requests.RequestException("502 Bad Gateway"))
    with pytest.raises(SystemExit):
        sut.fetch_ticket("249076")
    assert "Error fetching ticket 249076: 502 Bad Gateway" in capsys.readouterr().out


def test_fetch_ticket_prints_the_issue_and_its_journals(sut, capsys, mocker):
    response = mocker.MagicMock()
    response.json.return_value = {
        "issue": {**ISSUE, "journals": [{"notes": "Done", "user": {"name": "Anne"}, "created_on": "2026-01-02"}]}
    }
    mocker.patch.object(sut.requests, "get", return_value=response)
    sut.fetch_ticket("249076")
    out = capsys.readouterr().out
    assert "## Issue #249076" in out
    assert "#### Anne at 2026-01-02" in out
    assert out.count("- URL: https://progress.opensuse.org/issues/249076") == 1


def test_main_exits_one_without_ticket_id(sut, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["redmine-fetcher"])
    with pytest.raises(SystemExit):
        sut.main()
    assert "Usage:" in capsys.readouterr().out


def test_load_config_reads_host_and_token_from_the_config_file(sut, tmp_path):
    (tmp_path / ".query_redminerc").write_text("redmine-host = progress.example.org\nredmine-token=t0ken\n")

    assert sut.load_config() == ("progress.example.org", "t0ken")


def test_load_config_ignores_lines_without_a_separator(sut, tmp_path):
    (tmp_path / ".query_redminerc").write_text("garbage\nredmine-token=t0ken\n")

    assert sut.load_config() == (None, "t0ken")


def test_load_config_without_a_config_file_is_empty(sut):
    assert sut.load_config() == (None, None)


def test_load_config_of_an_empty_file_is_empty(sut, tmp_path):
    (tmp_path / ".query_redminerc").write_text("")

    assert sut.load_config() == (None, None)


def test_resolve_credentials_prefers_the_environment(sut, tmp_path, monkeypatch):
    (tmp_path / ".query_redminerc").write_text("redmine-host=config.example.org\nredmine-token=config-token\n")
    monkeypatch.setenv("REDMINE_HOST", "env.example.org")
    monkeypatch.setenv("REDMINE_API_TOKEN", "env-token")

    assert sut.resolve_credentials() == ("env.example.org", "env-token")


def test_resolve_credentials_falls_back_to_the_default_host(sut):
    assert sut.resolve_credentials() == (sut.DEFAULT_HOST, None)


def test_fetch_ticket_without_a_token_sends_no_api_key_header(sut, mocker):
    get = mocker.patch.object(sut.requests, "get", return_value=mocker.MagicMock())

    sut.fetch_ticket("249076")

    assert "X-Redmine-API-Key" not in get.call_args.kwargs["headers"]


def test_main_fetches_the_normalized_ticket_id(sut, mocker, monkeypatch):
    fetch_ticket = mocker.patch.object(sut, "fetch_ticket")
    monkeypatch.setattr("sys.argv", ["redmine-fetcher", "https://progress.opensuse.org/issues/249076/"])

    sut.main()

    fetch_ticket.assert_called_once_with("249076")
