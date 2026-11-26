"""Tests for gh-pr-triage."""

import argparse
import json
import subprocess
from typing import Any

import pytest


@pytest.fixture
def sut(load_script):
    return load_script("gh-pr-triage")


def test_analyze_checks_none(sut):
    assert sut.analyze_checks({}) == "NONE"
    assert sut.analyze_checks({"statusCheckRollup": []}) == "NONE"


def test_analyze_checks_pass(sut):
    pr = {"statusCheckRollup": [{"conclusion": "SUCCESS"}]}
    assert sut.analyze_checks(pr) == "PASS"


def test_analyze_checks_fail(sut):
    pr = {"statusCheckRollup": [{"conclusion": "FAILURE"}, {"conclusion": "SUCCESS"}]}
    assert sut.analyze_checks(pr) == "FAIL"


def test_analyze_checks_pending(sut):
    pr = {"statusCheckRollup": [{"state": "PENDING"}]}
    assert sut.analyze_checks(pr) == "PENDING"


def test_triage_pr(sut):
    pr = {
        "number": 42,
        "title": "Fix bug",
        "author": {"login": "alice"},
        "createdAt": "2026-11-20T10:00:00Z",
        "updatedAt": "2026-11-20T11:00:00Z",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "reviews": [
            {"author": {"login": "bot"}, "state": "APPROVED"},
            {"author": {"login": "bob"}, "state": "CHANGES_REQUESTED"},
        ],
        "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        "url": "https://github.com/org/repo/pull/42",
    }
    triaged = sut.triage_pr(pr, "bot")
    assert triaged["number"] == 42
    assert triaged["approvals"] == 1
    assert triaged["changes_requested"] == 1
    assert triaged["bot_reviewed"] is True
    assert triaged["checks"] == "PASS"


def test_main_infers_repo_from_origin(sut, mocker):
    mocker.patch.object(
        sut.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            args=["git", "remote", "get-url", "origin"],
            returncode=0,
            stdout="git@github.com:os-autoinst/openQA.git\n",
            stderr="",
        ),
    )
    mocker.patch.object(sut, "get_current_bot_login", return_value="bot")
    mocker.patch.object(sut, "fetch_prs", return_value=[])
    mocker.patch.object(sut.sys, "argv", ["gh-pr-triage"])

    sut.main()
    sut.fetch_prs.assert_called_once_with("os-autoinst/openQA", limit=30)


def triaged(**fields: Any) -> dict[str, Any]:
    entry = {
        "number": 1,
        "title": "Fix the thing",
        "author": "alice",
        "createdAt": "2026-11-20T10:00:00Z",
        "updatedAt": "2026-11-20T11:00:00Z",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "approvals": 1,
        "approvers": ["bob"],
        "changes_requested": 0,
        "reviewers": ["bob"],
        "bot_reviewed": True,
        "checks": "PASS",
        "url": "https://github.com/org/repo/pull/1",
        "repo": "org/repo",
    }
    return {**entry, **fields}


def test_run_gh_as_bot_returns_code_stdout_and_stderr(sut, fake_subprocess):
    fake_subprocess.on(["gh-as-bot"], stdout="alice\n", stderr="warn\n", returncode=0)

    assert sut.run_gh_as_bot(["api", "user"]) == (0, "alice\n", "warn\n")
    assert fake_subprocess.commands(["gh-as-bot"]) == [["gh-as-bot", "api", "user"]]


def test_get_current_bot_login_returns_the_login(sut, fake_subprocess):
    fake_subprocess.on(["gh-as-bot"], stdout="os-autoinst-review\n")

    assert sut.get_current_bot_login() == "os-autoinst-review"


def test_get_current_bot_login_falls_back_to_the_default(sut, fake_subprocess):
    fake_subprocess.on(["gh-as-bot"], returncode=1)

    assert sut.get_current_bot_login() == sut.DEFAULT_BOT


def test_fetch_prs_returns_the_parsed_list(sut, fake_subprocess):
    fake_subprocess.on(["gh-as-bot", "pr", "list"], stdout=json.dumps([{"number": 1}]))

    assert sut.fetch_prs("org/repo", limit=5) == [{"number": 1}]
    assert fake_subprocess.commands(["gh-as-bot"])[0][-2:] == ["--limit", "5"]


def test_fetch_prs_reports_a_gh_failure(sut, fake_subprocess, capsys):
    fake_subprocess.on(["gh-as-bot", "pr", "list"], stderr="not found", returncode=1)

    assert sut.fetch_prs("org/repo") == []
    assert "Error fetching PRs for org/repo: not found" in capsys.readouterr().err


def test_fetch_prs_reports_invalid_json(sut, fake_subprocess, capsys):
    fake_subprocess.on(["gh-as-bot", "pr", "list"], stdout="not json")

    assert sut.fetch_prs("org/repo") == []
    assert "Error parsing JSON for org/repo" in capsys.readouterr().err


def test_infer_repos_exits_one_without_a_github_remote(sut, fake_subprocess, capsys):
    fake_subprocess.on(["git", "remote", "get-url"], stdout="https://gitlab.com/org/repo\n")

    with pytest.raises(SystemExit) as excinfo:
        sut.infer_repos()

    assert excinfo.value.code == 1
    assert "No repository specified" in capsys.readouterr().err


def test_infer_repos_reads_the_github_remote(sut, fake_subprocess):
    fake_subprocess.on(["git", "remote", "get-url"], stdout="git@github.com:org/repo.git\n")

    assert sut.infer_repos() == ["org/repo"]


def test_collect_annotates_every_entry_with_its_repo(sut, mocker):
    mocker.patch.object(
        sut, "fetch_prs", side_effect=lambda *_args, **_kwargs: [{"number": 1, "title": "t", "createdAt": "c"}]
    )
    mocker.patch.object(sut, "triage_pr", side_effect=lambda *_args: triaged())

    collected = sut.collect(["org/repo", "org/other"], "bot", 10)

    assert [entry["repo"] for entry in collected] == ["org/repo", "org/other"]


@pytest.mark.parametrize(
    ("fields", "unreviewed", "expected"),
    [
        ({"isDraft": True}, False, False),
        ({"bot_reviewed": True}, True, False),
        ({"mergeable": "CONFLICTING"}, False, False),
        ({"checks": "FAIL"}, False, False),
        ({"approvals": 0}, False, False),
        ({"changes_requested": 1}, False, False),
        ({}, False, True),
    ],
)
def test_matches_applies_the_filters(sut, fields, unreviewed, expected):
    options = argparse.Namespace(unreviewed=unreviewed, ready_to_approve=True)

    assert sut.matches(triaged(**fields), options) is expected


def test_matches_keeps_everything_without_the_ready_filter(sut):
    options = argparse.Namespace(unreviewed=False, ready_to_approve=False)

    assert sut.matches(triaged(mergeable="CONFLICTING", checks="FAIL"), options) is True


def test_print_table_prints_a_header_and_a_row(sut, capsys):
    sut.print_table([triaged()])

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("CREATED")
    assert lines[2].startswith("2026-11-20")
    assert lines[2].endswith("Fix the thing")


def test_main_prints_json(sut, mocker, capsys):
    mocker.patch.object(sut, "infer_repos", return_value=["org/repo"])
    mocker.patch.object(sut, "get_current_bot_login", return_value="bot")
    mocker.patch.object(sut, "collect", return_value=[triaged()])
    mocker.patch.object(sut.sys, "argv", ["gh-pr-triage", "--json"])

    sut.main()

    assert json.loads(capsys.readouterr().out) == [triaged()]


def test_main_prints_the_table(sut, mocker, capsys):
    mocker.patch.object(sut, "infer_repos", return_value=["org/repo"])
    mocker.patch.object(sut, "get_current_bot_login", return_value="bot")
    mocker.patch.object(sut, "collect", return_value=[triaged()])
    mocker.patch.object(sut.sys, "argv", ["gh-pr-triage"])

    sut.main()

    assert "Fix the thing" in capsys.readouterr().out


def test_main_reports_when_nothing_matches(sut, mocker, capsys):
    mocker.patch.object(sut, "infer_repos", return_value=["org/repo"])
    mocker.patch.object(sut, "get_current_bot_login", return_value="bot")
    mocker.patch.object(sut, "collect", return_value=[])
    mocker.patch.object(sut.sys, "argv", ["gh-pr-triage"])

    sut.main()

    assert "No matching pull requests found." in capsys.readouterr().err
