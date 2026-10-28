"""Tests for gitea-review-cleanup: select validation, dry-run listing, unassign counts and the summary."""

from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner


@pytest.fixture
def sut(load_script):
    return load_script("gitea-review-cleanup")


def make_match(sut, *, number: int = 1, draft: bool = True, title: str = "Fix the spec") -> object:
    return sut.PullMatch(repo="pool/pkg", number=number, title=title, draft=draft)


def test_select_keys_are_the_documented_values(sut):
    assert set(sut.SELECTORS) == {"drafts", "forwarded", "both"}


def test_cli_rejects_an_unknown_select(sut):
    result = CliRunner().invoke(sut.app, ["--select", "bogus"])
    assert result.exit_code == 2
    assert "--select must be one of" in result.output


def test_cli_dry_run_lists_matches_without_changing_anything(sut, mocker):
    mocker.patch.object(sut, "load_token", return_value="tok")
    mocker.patch.object(sut.httpx, "Client", return_value=MagicMock())
    mocker.patch.object(sut, "request", return_value=(200, {"login": "okurz"}))
    mocker.patch.object(sut, "search_review_requested", return_value=[make_match(sut)])
    result = CliRunner().invoke(sut.app, ["--dry-run"])
    assert result.exit_code == 0
    assert "would unassign pool/pkg!1 [draft]" in result.output


def test_unassign_counts_skipped_and_failed(sut, mocker, capsys):
    mocker.patch.object(
        sut,
        "request",
        side_effect=[(404, None), (200, None), sut.APIError("403: rate limit"), (200, None)],
    )
    matches = [make_match(sut, number=n) for n in (1, 2, 3, 4)]
    unassigned, skipped, failed = sut.unassign_review_requests(MagicMock(), "okurz", matches, 0)
    assert (unassigned, skipped, failed) == (2, 1, ["pool/pkg!3: 403: rate limit"])
    out, err = capsys.readouterr()
    assert "skip pool/pkg!1" in out
    assert "unassigned pool/pkg!2" in out
    assert "FAILED 403: rate limit" in err


def test_report_result_exits_one_when_a_pr_still_requests_review(sut, mocker, capsys):
    match = make_match(sut)
    mocker.patch.object(sut, "search_review_requested", return_value=[match])
    with pytest.raises(typer.Exit):
        sut.report_result(MagicMock(), sut.SELECTORS["both"], [match], (1, 0, []))
    out, err = capsys.readouterr()
    assert "done: unassigned=1 skipped=0 failed=0 | still requesting my review: 1" in out
    assert "  remaining: pool/pkg!1" in out
    assert not err


def test_report_result_prints_the_failures_and_exits_one(sut, mocker, capsys):
    mocker.patch.object(sut, "search_review_requested", return_value=[])
    with pytest.raises(typer.Exit):
        sut.report_result(MagicMock(), sut.SELECTORS["drafts"], [], (0, 0, ["pool/pkg!1: boom"]))
    _out, err = capsys.readouterr()
    assert "failures:" in err
    assert "  pool/pkg!1: boom" in err


def test_report_result_returns_when_everything_is_unassigned(sut, mocker):
    mocker.patch.object(sut, "search_review_requested", return_value=[])
    sut.report_result(MagicMock(), sut.SELECTORS["both"], [make_match(sut)], (1, 0, []))
