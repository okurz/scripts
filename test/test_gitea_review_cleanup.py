"""Tests for gitea-review-cleanup: select validation, dry-run listing, unassign counts and the summary."""

from typing import Any
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
    assert "must be one of: drafts, forwarded, both" in result.output


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


def make_response(status_code: int, *, json_body: Any = None, content_type: str = "application/json") -> object:
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": content_type}
    response.json.return_value = json_body
    response.content = json_body is not None
    return response


def test_load_token_rejects_a_missing_file(sut, tmp_path, capsys):
    with pytest.raises(typer.Exit) as excinfo:
        sut.load_token(tmp_path / "absent")

    assert excinfo.value.exit_code == 2
    assert "error: token file not found" in capsys.readouterr().err


def test_load_token_rejects_an_empty_file(sut, tmp_path, capsys):
    token_file = tmp_path / "token"
    token_file.write_text("  \n")

    with pytest.raises(typer.Exit) as excinfo:
        sut.load_token(token_file)

    assert excinfo.value.exit_code == 2
    assert "error: token file is empty" in capsys.readouterr().err


def test_load_token_returns_the_stripped_token(sut, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text(" s3cret\n")

    assert sut.load_token(token_file) == "s3cret"


@pytest.mark.parametrize("status", [403, 429, 502, 503])
def test_is_throttled_for_every_throttle_status(sut, status):
    assert sut.is_throttled(make_response(status)) is True


def test_is_throttled_for_a_non_json_reply(sut):
    assert sut.is_throttled(make_response(200, json_body={}, content_type="text/html")) is True


def test_is_throttled_is_false_for_a_json_reply(sut):
    assert sut.is_throttled(make_response(200, json_body={})) is False


def test_request_sleeps_with_exponential_backoff_then_returns(sut, mocker):
    client = MagicMock()
    client.request.side_effect = [make_response(429), make_response(503), make_response(200, json_body={"ok": True})]
    clock = mocker.Mock()
    mocker.patch.object(sut, "time", clock)

    assert sut.request(client, "GET", "/api/v1/user") == (200, {"ok": True})
    assert [entry.args[0] for entry in clock.sleep.call_args_list] == [2.0, 4.0]


def test_request_returns_none_for_a_skippable_status(sut):
    client = MagicMock()
    client.request.return_value = make_response(404, json_body={"message": "Not Found"})

    assert sut.request(client, "DELETE", "/x") == (404, None)


def test_request_raises_with_the_body_for_a_bad_request(sut):
    client = MagicMock()
    client.request.return_value = make_response(422, json_body={"message": "reviewer not requested"})

    with pytest.raises(sut.APIError, match="DELETE /x -> 422"):
        sut.request(client, "DELETE", "/x")


def test_request_raises_when_every_attempt_is_throttled(sut, mocker):
    client = MagicMock()
    client.request.return_value = make_response(429)
    clock = mocker.Mock()
    mocker.patch.object(sut, "time", clock)

    with pytest.raises(sut.APIError, match=f"still throttled after {sut.MAX_RETRIES} attempts"):
        sut.request(client, "GET", "/x")

    assert client.request.call_count == sut.MAX_RETRIES


def test_item_to_match_maps_the_search_item(sut):
    item = {
        "repository": {"full_name": "pool/pkg"},
        "number": 7,
        "title": "Forwarded PRs: batch",
        "pull_request": {"draft": True},
    }

    match = sut.item_to_match(item)

    assert (match.repo, match.number, match.draft) == ("pool/pkg", 7, True)
    assert sut.is_forwarded(match) is True


def test_search_review_requested_follows_pagination(sut, mocker):
    full_page = [{"repository": {"full_name": "pool/pkg"}, "number": n, "title": "t"} for n in range(sut.PAGE_SIZE)]
    tail_page = [{"repository": {"full_name": "pool/pkg"}, "number": 100, "title": "t"}]
    mocker.patch.object(sut, "request", side_effect=[(200, full_page), (200, {"data": tail_page})])

    matches = sut.search_review_requested(MagicMock())

    assert len(matches) == sut.PAGE_SIZE + 1
    assert matches[-1].number == 100


def test_unassign_sleeps_between_requests(sut, mocker):
    mocker.patch.object(sut, "request", return_value=(204, None))
    clock = mocker.Mock()
    mocker.patch.object(sut, "time", clock)

    sut.unassign_review_requests(MagicMock(), "okurz", [make_match(sut)], 0.5)

    clock.sleep.assert_called_once_with(0.5)


def test_cli_unassigns_and_reports(sut, mocker):
    mocker.patch.object(sut, "load_token", return_value="tok")
    mocker.patch.object(sut.httpx, "Client", return_value=MagicMock())
    mocker.patch.object(sut, "request", return_value=(200, {"login": "okurz"}))
    mocker.patch.object(sut, "search_review_requested", return_value=[make_match(sut)])
    unassign = mocker.patch.object(sut, "unassign_review_requests", return_value=(1, 0, []))
    report = mocker.patch.object(sut, "report_result")

    result = CliRunner().invoke(sut.app, ["--select", "drafts", "--limit", "1"])

    assert result.exit_code == 0
    assert "capped to 1" in result.output
    unassign.assert_called_once()
    report.assert_called_once()
