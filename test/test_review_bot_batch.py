"""Tests for review-bot-batch: scope parsing, selection, checkout mapping and dispatch."""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def sut(load_script):
    return load_script("review-bot-batch")


def make_candidate(sut, *, number=1, repo="os-autoinst/openQA", author="okurz", draft=False, created="2026-01-01"):
    return sut.Candidate(
        repo=repo,
        number=number,
        title="A change",
        author=author,
        created_at=created,
        is_draft=draft,
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:os-autoinst/openQA.git", "os-autoinst/openQA"),
        ("https://github.com/os-autoinst/openQA", "os-autoinst/openQA"),
        ("https://github.com/os-autoinst/openQA.git", "os-autoinst/openQA"),
        ("https://gitlab.com/os-autoinst/openQA", None),
        ("", None),
    ],
)
def test_parse_github_repo(sut, url, expected):
    assert sut.parse_github_repo(url) == expected


def test_candidate_url_and_slug(sut):
    cand = make_candidate(sut, number=8141, repo="os-autoinst/openQA")
    assert cand.url == "https://github.com/os-autoinst/openQA/pull/8141"
    assert cand.slug == "os-autoinst-openQA-8141"


def test_search_candidates_uses_owner_scope(sut, mocker):
    run = mocker.patch.object(sut, "run")
    run.return_value = MagicMock(
        returncode=0,
        stderr="",
        stdout='[{"number": 1, "title": "t", "isDraft": false, "author": {"login": "okurz"}, '
        '"createdAt": "2026-01-01T00:00:00Z", "repository": {"nameWithOwner": "os-autoinst/openQA"}}]',
    )
    got = sut.search_candidates(["os-autoinst"], [], 2)
    cmd = run.call_args.args[0]
    assert cmd[:2] == ["gh-as-bot", "search"]
    assert "--owner" in cmd
    assert cmd[cmd.index("--owner") + 1] == "os-autoinst"
    assert cmd[cmd.index("--sort") + 1] == "created"
    assert cmd[cmd.index("--order") + 1] == "desc"
    assert "os-autoinst/openQA" not in cmd
    assert got[0].repo == "os-autoinst/openQA"
    assert got[0].is_draft is False


def test_search_window_defaults_and_override(sut):
    assert sut.search_window(10) == 100
    assert sut.search_window(1) == 50
    assert sut.search_window(10, 20) == 20
    assert sut.search_window(10, 5000) == sut.MAX_SEARCH_LIMIT


def test_search_candidates_oldest_scope(sut, mocker):
    run = mocker.patch.object(sut, "run")
    run.return_value = MagicMock(returncode=0, stderr="", stdout="[]")
    sut.search_candidates(["os-autoinst"], [], 1, oldest=True)
    cmd = run.call_args.args[0]
    assert cmd[cmd.index("--order") + 1] == "asc"


def test_search_candidates_uses_repo_scope(sut, mocker):
    run = mocker.patch.object(sut, "run")
    run.return_value = MagicMock(returncode=0, stderr="", stdout="[]")
    sut.search_candidates([], ["os-autoinst/openQA", "os-autoinst/os-autoinst"], 1)
    cmd = run.call_args.args[0]
    assert cmd.count("-R") == 2
    assert "--owner" not in cmd


def test_search_candidates_unions_owners_and_repos(sut, mocker):
    run = mocker.patch.object(sut, "run")
    owner_item = '{"number": 1, "title": "t", "isDraft": false, "author": {"login": "a"}, "createdAt": "2026-01-01", "repository": {"nameWithOwner": "os-autoinst/openQA"}}'
    repo_item = '{"number": 2, "title": "t", "isDraft": false, "author": {"login": "b"}, "createdAt": "2026-01-02", "repository": {"nameWithOwner": "openSUSE/qem-bot"}}'
    run.side_effect = [
        MagicMock(returncode=0, stderr="", stdout=f"[{owner_item}]"),
        MagicMock(returncode=0, stderr="", stdout=f"[{repo_item}]"),
    ]
    got = sut.search_candidates(["os-autoinst"], ["openSUSE/qem-bot"], 5)
    assert run.call_count == 2
    assert run.call_args_list[0].args[0][-2:] == ["--owner", "os-autoinst"]
    assert run.call_args_list[1].args[0][-2:] == ["-R", "openSUSE/qem-bot"]
    assert {c.repo for c in got} == {"os-autoinst/openQA", "openSUSE/qem-bot"}


def test_search_candidates_reports_gh_failure(sut, mocker):
    mocker.patch.object(sut, "run", return_value=MagicMock(returncode=1, stderr="boom", stdout=""))
    with pytest.raises(RuntimeError, match="gh search prs failed: boom"):
        sut.search_candidates(["os-autoinst"], [], 1)


def make_state(sut, *, head="h", **fields: Any):
    return sut.PrState(head=head, **fields)


def test_pr_state_marks_head_review_and_counts_humans(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123\n", stderr="")
    reviews = MagicMock(
        returncode=0,
        stdout=(
            "os-autoinst-review\tCOMMENTED\tabc123\n"
            "os-autoinst-review\tAPPROVED\told\n"
            "alice\tAPPROVED\tabc123\n"
            "alice\tCOMMENTED\told\n"
            "dependabot[bot]\tAPPROVED\tabc123\n"
        ),
        stderr="",
    )
    run = mocker.patch.object(sut, "run", side_effect=[view, reviews])
    state = sut.pr_state(make_candidate(sut), "os-autoinst-review")
    assert state.reviewed_on_head is True
    assert state.has_bot_review is True
    assert state.has_bot_block is False
    assert state.human_reviewers == 1
    assert "--paginate" in run.call_args_list[1].args[0]
    assert "?per_page=100" in run.call_args_list[1].args[0][3]


def test_pr_state_detects_stale_block(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123", stderr="")
    reviews = MagicMock(returncode=0, stdout="os-autoinst-review\tCHANGES_REQUESTED\told\n", stderr="")
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    state = sut.pr_state(make_candidate(sut), "os-autoinst-review")
    assert state.reviewed_on_head is False
    assert state.has_bot_block is True


def test_pr_state_detects_block_on_head(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123", stderr="")
    reviews = MagicMock(returncode=0, stdout="os-autoinst-review\tCHANGES_REQUESTED\tabc123\n", stderr="")
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    state = sut.pr_state(make_candidate(sut), "os-autoinst-review")
    assert state.reviewed_on_head is True
    assert state.has_bot_block is True


def test_pr_state_lifts_the_block_when_the_bot_approves_later(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123", stderr="")
    reviews = MagicMock(
        returncode=0,
        stdout="os-autoinst-review\tCHANGES_REQUESTED\tabc123\nos-autoinst-review\tAPPROVED\tabc123\n",
        stderr="",
    )
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    state = sut.pr_state(make_candidate(sut), "os-autoinst-review")
    assert state.reviewed_on_head is True
    assert state.has_bot_block is False


def test_pr_state_keeps_the_block_across_a_later_bot_comment(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123", stderr="")
    reviews = MagicMock(
        returncode=0,
        stdout="os-autoinst-review\tCHANGES_REQUESTED\tabc123\nos-autoinst-review\tCOMMENTED\tabc123\n",
        stderr="",
    )
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    state = sut.pr_state(make_candidate(sut), "os-autoinst-review")
    assert state.has_bot_block is True


def test_pr_state_raises_when_reviews_cannot_be_read(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123", stderr="")
    reviews = MagicMock(returncode=1, stdout="", stderr="rate limited")
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    with pytest.raises(RuntimeError, match="cannot read reviews of os-autoinst/openQA#1: rate limited"):
        sut.pr_state(make_candidate(sut), "os-autoinst-review")


@pytest.mark.parametrize(
    ("humans", "expected"), [("alice\tAPPROVED\tabc123", 1), ("alice\tAPPROVED\ta\nbob\tAPPROVED\tb", 2)]
)
def test_pr_state_counts_other_humans_only(sut, mocker, humans, expected):
    view = MagicMock(returncode=0, stdout="abc123", stderr="")
    reviews = MagicMock(
        returncode=0,
        stdout=f"os-autoinst-review\tAPPROVED\tabc123\nokurz\tCOMMENTED\tabc123\n{humans}\n",
        stderr="",
    )
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    state = sut.pr_state(make_candidate(sut, author="okurz"), "os-autoinst-review")
    assert state.human_reviewers == expected


def test_filter_candidates_drops_drafts_bot_author_and_reviewed(sut):
    cands = [
        make_candidate(sut, number=1, author="okurz"),
        make_candidate(sut, number=2, author="os-autoinst-review"),
        make_candidate(sut, number=3, draft=True),
        make_candidate(sut, number=4, author="perlpunk"),
    ]
    kept, states = sut.filter_candidates(
        cands,
        "os-autoinst-review",
        skip_reviewed=True,
        state_lookup=lambda c, _l: make_state(sut, reviewed_on_head=c.number == 1),
    )
    assert [c.number for c in kept] == [4]
    assert set(states) == {("os-autoinst/openQA", 1), ("os-autoinst/openQA", 4)}


def test_filter_candidates_skips_dependency_bots_by_default(sut):
    cands = [make_candidate(sut, number=1, author="dependabot[bot]"), make_candidate(sut, number=2)]
    kept, _ = sut.filter_candidates(
        cands, "os-autoinst-review", skip_reviewed=False, state_lookup=lambda _c, _l: make_state(sut)
    )
    assert [c.number for c in kept] == [2]
    kept, _ = sut.filter_candidates(
        cands,
        "os-autoinst-review",
        skip_reviewed=False,
        include_bots=True,
        state_lookup=lambda _c, _l: make_state(sut),
    )
    assert [c.number for c in kept] == [1, 2]


def test_filter_candidates_skips_candidate_with_unreadable_state(sut, capsys):
    cands = [make_candidate(sut, number=1), make_candidate(sut, number=2)]

    def lookup(cand: Any, _login: str) -> Any:
        if cand.number == 1:
            msg = "api down"
            raise RuntimeError(msg)
        return make_state(sut)

    kept, _ = sut.filter_candidates(cands, "os-autoinst-review", skip_reviewed=True, state_lookup=lookup)
    assert [c.number for c in kept] == [2]
    assert "skip os-autoinst/openQA#1: api down" in capsys.readouterr().err


def test_filter_candidates_only_blocked_keeps_the_bot_block(sut):
    cands = [make_candidate(sut, number=1), make_candidate(sut, number=2), make_candidate(sut, number=3)]
    kept, _ = sut.filter_candidates(
        cands,
        "os-autoinst-review",
        skip_reviewed=False,
        only_blocked=True,
        state_lookup=lambda c, _l: make_state(sut, has_bot_review=c.number != 3, has_bot_block=c.number == 2),
    )
    assert [c.number for c in kept] == [2]


def test_filter_candidates_recheck_keeps_reviewed(sut):
    cand = make_candidate(sut, number=1)
    kept, _ = sut.filter_candidates(
        [cand],
        "os-autoinst-review",
        skip_reviewed=False,
        state_lookup=lambda _c, _l: make_state(sut, reviewed_on_head=True),
    )
    assert kept == [cand]


def test_filter_candidates_keeps_all_eligible_so_priority_can_sort(sut):
    cands = [make_candidate(sut, number=n) for n in range(1, 6)]
    kept, _ = sut.filter_candidates(
        cands,
        "os-autoinst-review",
        skip_reviewed=True,
        state_lookup=lambda c, _l: make_state(sut, reviewed_on_head=c.number == 1),
    )
    assert [c.number for c in kept] == [2, 3, 4, 5]


def test_select_candidates_orders_by_priority_then_date(sut):
    cands = [
        make_candidate(sut, number=1, created="2026-02-01"),
        make_candidate(sut, number=2, created="2026-01-01"),
        make_candidate(sut, number=3, created="2026-03-01"),
        make_candidate(sut, number=4, created="2025-12-01"),
    ]
    states = {
        ("os-autoinst/openQA", 1): make_state(sut, has_bot_block=True),
        ("os-autoinst/openQA", 2): make_state(sut),
        ("os-autoinst/openQA", 3): make_state(sut, has_bot_review=True),
        ("os-autoinst/openQA", 4): make_state(sut),
    }
    assert [c.number for c in sut.select_candidates(cands, 4, states=states)] == [1, 2, 4, 3]
    assert [c.number for c in sut.select_candidates(cands, 4, oldest=True, states=states)] == [1, 4, 2, 3]


def test_select_candidates_newest_first_and_limited(sut):
    cands = [
        make_candidate(sut, number=1, created="2026-02-01"),
        make_candidate(sut, number=2, created="2026-01-01"),
        make_candidate(sut, number=3, created="2026-03-01"),
    ]
    assert [c.number for c in sut.select_candidates(cands, 2)] == [3, 1]
    assert [c.number for c in sut.select_candidates(cands, 2, oldest=True)] == [2, 1]


def test_review_command_pi_is_default_and_forwards_model_and_extra_args(sut, tmp_path):
    cand = make_candidate(sut, number=7)
    assert sut.review_command(cand, tmp_path, dry_run=False) == [
        "pi",
        "-p",
        "/review-as-bot https://github.com/os-autoinst/openQA/pull/7 --post",
    ]
    assert sut.review_command(cand, tmp_path, dry_run=True, model="provider/model", extra_args=["--verbose"]) == [
        "pi",
        "--model",
        "provider/model",
        "--verbose",
        "-p",
        "/review-as-bot https://github.com/os-autoinst/openQA/pull/7 --dry-run",
    ]


def test_review_command_opencode_uses_command_flag_and_bare_prompt(sut, tmp_path):
    cand = make_candidate(sut, number=7)
    assert sut.review_command(
        cand,
        tmp_path,
        runner="opencode",
        dry_run=True,
        model="google/gemini-3-flash-preview",
        auto=True,
    ) == [
        "opencode",
        "run",
        "--dir",
        str(tmp_path),
        "--auto",
        "-m",
        "google/gemini-3-flash-preview",
        "--command",
        "review-as-bot",
        "https://github.com/os-autoinst/openQA/pull/7 --dry-run",
    ]


def test_review_command_opencode_without_auto_or_model_keeps_flags_absent(sut, tmp_path):
    cand = make_candidate(sut, number=7)
    cmd = sut.review_command(cand, tmp_path, runner="opencode", dry_run=False)
    assert cmd == [
        "opencode",
        "run",
        "--dir",
        str(tmp_path),
        "--command",
        "review-as-bot",
        "https://github.com/os-autoinst/openQA/pull/7 --post",
    ]


def test_review_command_comment_only_appends_comment_flag(sut, tmp_path):
    cand = make_candidate(sut, number=7)
    assert sut.review_command(cand, tmp_path, dry_run=False, comment_only=True)[-1].endswith("--post --comment")
    assert sut.review_command(cand, tmp_path, runner="opencode", dry_run=True, comment_only=True)[-1].endswith(
        "--dry-run --comment"
    )


@pytest.mark.parametrize(
    ("returncode", "output", "expected"),
    [
        (0, "submitted", True),
        (1, "submitted", False),
        (0, "--- REVIEW FAILED (github x) ---", False),
        (0, "--- REVIEW BLOCKED (write gate, not posted) ---", False),
    ],
)
def test_review_succeeded(sut, returncode, output, expected):
    assert sut.review_succeeded(returncode, output) is expected


def test_discover_checkouts_maps_only_github_remotes(sut, tmp_path, mocker):
    first = tmp_path / "openQA-a"
    second = tmp_path / "openQA-b"
    other = tmp_path / "gitlab"
    for checkout in (first, second, other):
        (checkout / ".git").mkdir(parents=True)
        (checkout / ".git" / "config").write_text("[core]\n")
    remotes = {
        str(first): "git@github.com:os-autoinst/openQA.git",
        str(second): "https://github.com/os-autoinst/openQA.git",
        str(other): "https://gitlab.com/x/y.git",
    }
    mocker.patch.object(
        sut,
        "run",
        side_effect=lambda cmd, **_kw: MagicMock(returncode=0, stdout=remotes[str(Path(cmd[2]))], stderr=""),
    )
    found = sut.discover_checkouts([tmp_path])
    assert found == {"os-autoinst/openQA": first}


def test_ensure_checkout_prefers_local_and_can_refuse_clone(sut, tmp_path):
    local = tmp_path / "local"
    assert sut.ensure_checkout("o/r", {"o/r": local}, tmp_path / "cache", allow_clone=False) == local
    cached = tmp_path / "cache" / "o-r"
    cached.mkdir(parents=True)
    assert sut.ensure_checkout("o/r", {}, tmp_path / "cache", allow_clone=False) == cached
    with pytest.raises(RuntimeError, match="no local checkout"):
        sut.ensure_checkout("o/missing", {}, tmp_path / "cache", allow_clone=False)


def test_ensure_checkout_clones_when_allowed(sut, tmp_path, mocker):
    run = mocker.patch.object(sut, "run", return_value=MagicMock(returncode=0, stderr=""))
    target = sut.ensure_checkout("o/r", {}, tmp_path / "cache", allow_clone=True)
    assert target == tmp_path / "cache" / "o-r"
    assert run.call_args.args[0][:2] == ["git", "clone"]


def test_fetch_pr_head_uses_pull_ref_and_reports_failure(sut, tmp_path, mocker):
    run = mocker.patch.object(sut, "run", return_value=MagicMock(returncode=0))
    sut.fetch_pr_head(tmp_path, 8141)
    assert "refs/pull/8141/head" in run.call_args.args[0]
    run.return_value = MagicMock(returncode=1, stderr="denied")
    with pytest.raises(RuntimeError, match="cannot fetch PR head"):
        sut.fetch_pr_head(tmp_path, 8141)


def test_review_command_opencode_resolves_relative_checkout_for_dir(sut, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cmd = sut.review_command(make_candidate(sut, number=7), Path("rel"), runner="opencode", dry_run=False)
    assert cmd[cmd.index("--dir") + 1] == str(tmp_path / "rel")


def test_run_review_writes_log_and_detects_block(sut, tmp_path, mocker):
    mocker.patch.object(sut, "fetch_pr_head")
    mocker.patch.object(sut.subprocess, "run", return_value=MagicMock(returncode=0))
    log = tmp_path / "logs"
    ok, path = sut.run_review(make_candidate(sut), tmp_path, dry_run=False, log_dir=log, timeout=5)
    assert ok is True
    assert path == log / "os-autoinst-openQA-1.log"
    assert path.exists()


def test_run_review_dispatches_to_the_selected_runner(sut, tmp_path, mocker):
    mocker.patch.object(sut, "fetch_pr_head")
    proc = mocker.patch.object(sut.subprocess, "run", return_value=MagicMock(returncode=0))
    sut.run_review(
        make_candidate(sut),
        tmp_path,
        runner="opencode",
        dry_run=True,
        model="google/gemini-3-flash-preview",
        auto=True,
        log_dir=tmp_path,
        timeout=5,
    )
    cmd = proc.call_args.args[0]
    assert cmd[:2] == ["opencode", "run"]
    assert cmd[cmd.index("--command") + 1] == "review-as-bot"
    assert proc.call_args.kwargs["cwd"] == tmp_path


def test_run_review_kills_and_records_a_timeout(sut, tmp_path, mocker):
    mocker.patch.object(sut, "fetch_pr_head")
    mocker.patch.object(sut.subprocess, "run", side_effect=subprocess.TimeoutExpired(["pi"], 5))
    ok, path = sut.run_review(make_candidate(sut), tmp_path, dry_run=False, log_dir=tmp_path, timeout=5)
    assert ok is False
    assert "REVIEW FAILED (timeout after 5s)" in path.read_text()


def test_parse_args_defaults(sut):
    args = sut.parse_args([])
    assert args.limit == sut.DEFAULT_LIMIT
    assert args.dry_run is False
    assert args.list is False
    assert args.oldest is False
    assert args.window == 0
    assert args.timeout == sut.DEFAULT_TIMEOUT
    assert args.include_bots is False
    assert args.recheck is False
    assert args.only_blocked is False
    assert args.runner == "pi"
    assert not args.model
    assert args.auto is False
    assert args.runner_args == []
    assert args.watch is False
    assert args.interval == sut.DEFAULT_INTERVAL


def test_parse_args_rejects_unknown_runner(sut):
    with pytest.raises(SystemExit):
        sut.parse_args(["--runner", "nope"])


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--runner", "opencode", "--auto"], ["opencode", "run", "--dir"]),
        (["--pi-arg=--verbose"], ["pi", "--verbose"]),
        (["--runner-arg=--verbose"], ["pi", "--verbose"]),
    ],
)
def test_parse_args_runner_options_reach_the_command(sut, argv, expected, tmp_path):
    args = sut.parse_args(["--owner", "os-autoinst", *argv])
    cmd = sut.review_command(
        make_candidate(sut, number=1),
        tmp_path,
        runner=args.runner,
        dry_run=False,
        model=args.model,
        auto=args.auto,
        extra_args=args.runner_args,
    )
    assert cmd[: len(expected)] == expected


def test_main_list_prints_selection_without_reviewing(sut, mocker, capsys):
    cands = [make_candidate(sut, number=1)]
    states = {("os-autoinst/openQA", 1): make_state(sut)}
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "search_candidates", return_value=cands)
    mocker.patch.object(sut, "filter_candidates", return_value=(cands, states))
    run_review = mocker.patch.object(sut, "run_review")
    assert sut.main(["--owner", "os-autoinst", "--list"]) == 0
    out = capsys.readouterr().out
    assert "os-autoinst/openQA#1" in out
    run_review.assert_not_called()


def test_main_reports_the_searched_window_when_empty(sut, mocker, capsys):
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "search_candidates", return_value=[])
    assert sut.main(["--owner", "os-autoinst", "--limit", "2"]) == 0
    err = capsys.readouterr().err
    assert "newest 50 open PRs" in err
    assert "--oldest" in err


def test_main_requires_a_scope(sut, mocker, capsys):
    mocker.patch.object(sut, "infer_owner", return_value="")
    assert sut.main([]) == 2
    assert "give --owner" in capsys.readouterr().err


def test_main_reports_a_search_failure_without_a_traceback(sut, mocker, capsys):
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "search_candidates", side_effect=RuntimeError("gh down"))
    assert sut.main(["--owner", "os-autoinst"]) == 1
    assert "search failed: gh down" in capsys.readouterr().err


def states_for(sut, cands, **fields: Any):
    return {(cand.repo, cand.number): make_state(sut, **fields) for cand in cands}


def test_main_runs_each_selected_pr(sut, tmp_path, mocker, capsys):
    cands = [make_candidate(sut, number=1), make_candidate(sut, number=2)]
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "search_candidates", return_value=cands)
    mocker.patch.object(sut, "filter_candidates", return_value=(cands, states_for(sut, cands)))
    mocker.patch.object(sut, "discover_checkouts", return_value={"os-autoinst/openQA": tmp_path})
    mocker.patch.object(
        sut,
        "pr_state",
        side_effect=[make_state(sut, reviewed_on_head=True), make_state(sut)],
    )
    run_review = mocker.patch.object(sut, "run_review", side_effect=[(True, Path("/log/1")), (False, Path("/log/2"))])
    code = sut.main(["--owner", "os-autoinst", "--limit", "2", "--log-dir", str(tmp_path / "logs")])
    assert code == 1
    assert run_review.call_count == 2
    assert "done: 1 ok, 1 failed" in capsys.readouterr().err


def test_main_counts_a_posted_review_after_a_timeout_as_ok(sut, tmp_path, mocker, capsys):
    cands = [make_candidate(sut, number=1)]
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "search_candidates", return_value=cands)
    mocker.patch.object(sut, "filter_candidates", return_value=(cands, states_for(sut, cands)))
    mocker.patch.object(sut, "discover_checkouts", return_value={"os-autoinst/openQA": tmp_path})
    mocker.patch.object(sut, "run_review", return_value=(False, Path("/log/1")))
    mocker.patch.object(sut, "pr_state", return_value=make_state(sut, reviewed_on_head=True))
    code = sut.main(["--owner", "os-autoinst", "--limit", "1", "--log-dir", str(tmp_path / "logs")])
    assert code == 0
    assert "done: 1 ok, 0 failed" in capsys.readouterr().err


def test_main_marks_an_unposted_session_as_failed(sut, tmp_path, mocker, capsys):
    cands = [make_candidate(sut, number=1)]
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "search_candidates", return_value=cands)
    mocker.patch.object(sut, "filter_candidates", return_value=(cands, states_for(sut, cands)))
    mocker.patch.object(sut, "discover_checkouts", return_value={"os-autoinst/openQA": tmp_path})
    mocker.patch.object(sut, "run_review", return_value=(True, Path("/log/1")))
    mocker.patch.object(sut, "pr_state", return_value=make_state(sut))
    code = sut.main(["--owner", "os-autoinst", "--limit", "1", "--log-dir", str(tmp_path / "logs")])
    assert code == 1
    assert "done: 0 ok, 1 failed" in capsys.readouterr().err


def test_main_forces_comment_when_the_bot_already_requested_changes(sut, tmp_path, mocker):
    cands = [make_candidate(sut, number=1)]
    states = states_for(sut, cands, has_bot_block=True)
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "search_candidates", return_value=cands)
    mocker.patch.object(sut, "filter_candidates", return_value=(cands, states))
    mocker.patch.object(sut, "discover_checkouts", return_value={"os-autoinst/openQA": tmp_path})
    mocker.patch.object(sut, "pr_state", return_value=make_state(sut, reviewed_on_head=True))
    run_review = mocker.patch.object(sut, "run_review", return_value=(True, Path("/log/1")))
    sut.main(["--owner", "os-autoinst", "--limit", "1", "--log-dir", str(tmp_path / "logs")])
    assert run_review.call_args.kwargs["comment_only"] is True


def test_main_rejects_watch_with_list(sut, capsys):
    assert sut.main(["--owner", "os-autoinst", "--watch", "--list"]) == 2
    assert "--watch and --list" in capsys.readouterr().err


def test_main_watch_runs_cycles_until_interrupted(sut, mocker):
    run_cycle = mocker.patch.object(sut, "run_cycle", return_value=0)
    mocker.patch.object(sut, "pause", side_effect=KeyboardInterrupt)
    assert sut.main(["--owner", "os-autoinst", "--watch"]) == 130
    assert run_cycle.call_count == 1


def test_main_watch_uses_a_fresh_log_dir_per_cycle(sut, tmp_path, mocker):
    seen = []
    mocker.patch.object(sut, "run_cycle", side_effect=lambda args: seen.append(args.log_dir))
    mocker.patch.object(sut, "pause", side_effect=[None, KeyboardInterrupt])
    assert sut.main(["--owner", "os-autoinst", "--watch", "--log-dir", str(tmp_path)]) == 130
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(Path(path).parent == tmp_path for path in seen)


def test_main_watch_survives_a_failed_cycle(sut, mocker, capsys):
    run_cycle = mocker.patch.object(sut, "run_cycle", side_effect=[ValueError("bad payload"), 0])
    mocker.patch.object(sut, "pause", side_effect=[None, KeyboardInterrupt])
    assert sut.main(["--owner", "os-autoinst", "--watch"]) == 130
    assert run_cycle.call_count == 2
    assert "cycle failed: bad payload" in capsys.readouterr().err


def test_runner_env_grants_post_for_live_runs(sut, monkeypatch):
    monkeypatch.delenv("REVIEW_BOT_POST", raising=False)
    assert sut.runner_env(dry_run=False)["REVIEW_BOT_POST"] == "1"


def test_runner_env_keeps_the_write_gate_closed_for_dry_runs(sut, monkeypatch):
    monkeypatch.setenv("REVIEW_BOT_POST", "1")
    assert "REVIEW_BOT_POST" not in sut.runner_env(dry_run=True)


def test_run_review_passes_post_env_only_for_live_runs(sut, tmp_path, mocker):
    mocker.patch.object(sut, "fetch_pr_head")
    proc = mocker.patch.object(sut.subprocess, "run", return_value=MagicMock(returncode=0))
    sut.run_review(make_candidate(sut), tmp_path, dry_run=True, log_dir=tmp_path, timeout=5)
    assert "REVIEW_BOT_POST" not in proc.call_args.kwargs["env"]
    sut.run_review(make_candidate(sut), tmp_path, dry_run=False, log_dir=tmp_path, timeout=5)
    assert proc.call_args.kwargs["env"]["REVIEW_BOT_POST"] == "1"
