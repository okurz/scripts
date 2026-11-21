"""Tests for review-bot-batch: scope parsing, selection, checkout mapping and dispatch."""

import subprocess
from pathlib import Path
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


def test_pr_state_detects_bot_review_on_head(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123\n", stderr="")
    reviews = MagicMock(returncode=0, stdout="APPROVED\tabc123\nAPPROVED\told\n", stderr="")
    run = mocker.patch.object(sut, "run", side_effect=[view, reviews])
    assert sut.pr_state(make_candidate(sut), "os-autoinst-review") == ("abc123", True)
    assert "--paginate" in run.call_args_list[1].args[0]
    assert "?per_page=100" in run.call_args_list[1].args[0][3]


def test_pr_state_ignores_review_on_other_head(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123", stderr="")
    reviews = MagicMock(returncode=0, stdout="APPROVED\tabc123\nCHANGES_REQUESTED\told\n", stderr="")
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    assert sut.pr_state(make_candidate(sut), "os-autoinst-review") == ("abc123", True)
    reviews = MagicMock(returncode=0, stdout="APPROVED\told\n", stderr="")
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    assert sut.pr_state(make_candidate(sut), "os-autoinst-review") == ("abc123", False)


def test_filter_candidates_drops_drafts_bot_author_and_reviewed(sut):
    cands = [
        make_candidate(sut, number=1, author="okurz"),
        make_candidate(sut, number=2, author="os-autoinst-review"),
        make_candidate(sut, number=3, draft=True),
        make_candidate(sut, number=4, author="perlpunk"),
    ]
    kept = sut.filter_candidates(
        cands, "os-autoinst-review", skip_reviewed=True, state_lookup=lambda c, _l: ("h", c.number == 1)
    )
    assert [c.number for c in kept] == [4]


def test_filter_candidates_skips_dependency_bots_by_default(sut):
    cands = [make_candidate(sut, number=1, author="dependabot[bot]"), make_candidate(sut, number=2)]
    kept = sut.filter_candidates(
        cands, "os-autoinst-review", skip_reviewed=False, state_lookup=lambda _c, _l: ("h", False)
    )
    assert [c.number for c in kept] == [2]
    kept = sut.filter_candidates(
        cands, "os-autoinst-review", skip_reviewed=False, include_bots=True, state_lookup=lambda _c, _l: ("h", False)
    )
    assert [c.number for c in kept] == [1, 2]


def test_filter_candidates_skips_candidate_with_unreadable_state(sut, capsys):
    cands = [make_candidate(sut, number=1), make_candidate(sut, number=2)]

    def lookup(cand: object, _login: str) -> tuple[str, bool]:
        if cand.number == 1:
            msg = "api down"
            raise RuntimeError(msg)
        return "h", False

    kept = sut.filter_candidates(cands, "os-autoinst-review", skip_reviewed=True, state_lookup=lookup)
    assert [c.number for c in kept] == [2]
    assert "skip os-autoinst/openQA#1: api down" in capsys.readouterr().err


def test_filter_candidates_recheck_keeps_reviewed(sut):
    cand = make_candidate(sut, number=1)
    kept = sut.filter_candidates(
        [cand], "os-autoinst-review", skip_reviewed=False, state_lookup=lambda _c, _l: ("h", True)
    )
    assert kept == [cand]


def test_filter_candidates_stops_once_the_batch_is_full(sut):
    cands = [make_candidate(sut, number=n) for n in range(1, 6)]
    calls = []

    def lookup(cand: object, _login: str) -> tuple[str, bool]:
        calls.append(cand.number)
        return "h", cand.number == 1

    kept = sut.filter_candidates(cands, "os-autoinst-review", skip_reviewed=True, limit=2, state_lookup=lookup)
    assert [c.number for c in kept] == [2, 3]
    assert calls == [1, 2, 3]


def test_select_candidates_newest_first_and_limited(sut):
    cands = [
        make_candidate(sut, number=1, created="2026-02-01"),
        make_candidate(sut, number=2, created="2026-01-01"),
        make_candidate(sut, number=3, created="2026-03-01"),
    ]
    assert [c.number for c in sut.select_candidates(cands, 2)] == [3, 1]
    assert [c.number for c in sut.select_candidates(cands, 2, oldest=True)] == [2, 1]


def test_review_command_post_and_dry_run(sut):
    cand = make_candidate(sut, number=7)
    assert sut.review_command(cand, dry_run=False, pi_args=[]) == [
        "pi",
        "-p",
        "/review-as-bot https://github.com/os-autoinst/openQA/pull/7 --post",
    ]
    assert sut.review_command(cand, dry_run=True, pi_args=["--model", "m"]) == [
        "pi",
        "--model",
        "m",
        "-p",
        "/review-as-bot https://github.com/os-autoinst/openQA/pull/7 --dry-run",
    ]


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


def test_run_review_writes_log_and_detects_block(sut, tmp_path, mocker):
    mocker.patch.object(sut, "fetch_pr_head")
    mocker.patch.object(sut.subprocess, "run", return_value=MagicMock(returncode=0))
    log = tmp_path / "logs"
    ok, path = sut.run_review(make_candidate(sut), tmp_path, dry_run=False, pi_args=[], log_dir=log, timeout=5)
    assert ok is True
    assert path == log / "os-autoinst-openQA-1.log"
    assert path.exists()


def test_run_review_kills_and_records_a_timeout(sut, tmp_path, mocker):
    mocker.patch.object(sut, "fetch_pr_head")
    mocker.patch.object(sut.subprocess, "run", side_effect=subprocess.TimeoutExpired(["pi"], 5))
    ok, path = sut.run_review(make_candidate(sut), tmp_path, dry_run=False, pi_args=[], log_dir=tmp_path, timeout=5)
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


def test_main_list_prints_selection_without_reviewing(sut, mocker, capsys):
    cands = [make_candidate(sut, number=1)]
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "search_candidates", return_value=cands)
    mocker.patch.object(sut, "filter_candidates", return_value=cands)
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


def test_main_runs_each_selected_pr(sut, tmp_path, mocker, capsys):
    cands = [make_candidate(sut, number=1), make_candidate(sut, number=2)]
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "search_candidates", return_value=cands)
    mocker.patch.object(sut, "filter_candidates", return_value=cands)
    mocker.patch.object(sut, "discover_checkouts", return_value={"os-autoinst/openQA": tmp_path})
    mocker.patch.object(sut, "pr_state", return_value=("h", False))
    run_review = mocker.patch.object(sut, "run_review", side_effect=[(True, Path("/log/1")), (False, Path("/log/2"))])
    code = sut.main(["--owner", "os-autoinst", "--limit", "2", "--log-dir", str(tmp_path / "logs")])
    assert code == 1
    assert run_review.call_count == 2
    assert "done: 1 ok, 1 failed" in capsys.readouterr().err


def test_main_counts_a_posted_review_after_a_timeout_as_ok(sut, tmp_path, mocker, capsys):
    cands = [make_candidate(sut, number=1)]
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "search_candidates", return_value=cands)
    mocker.patch.object(sut, "filter_candidates", return_value=cands)
    mocker.patch.object(sut, "discover_checkouts", return_value={"os-autoinst/openQA": tmp_path})
    mocker.patch.object(sut, "run_review", return_value=(False, Path("/log/1")))
    mocker.patch.object(sut, "pr_state", return_value=("h", True))
    code = sut.main(["--owner", "os-autoinst", "--limit", "1", "--log-dir", str(tmp_path / "logs")])
    assert code == 0
    assert "done: 1 ok, 0 failed" in capsys.readouterr().err
