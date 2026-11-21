"""Tests for gh-pr-triage."""

import subprocess

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
