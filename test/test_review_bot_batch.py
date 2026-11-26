"""Tests for review-bot-batch: scope parsing, selection, checkout mapping and dispatch."""

import argparse
import json
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


def test_census_scopes_cover_owners_and_repos(sut):
    assert sut.census_scopes(["os-autoinst"], ["openSUSE/qem-bot"]) == [
        "user:os-autoinst is:pr is:open archived:false",
        "repo:openSUSE/qem-bot is:pr is:open archived:false",
    ]


def census_node(*, reviews: str = "", head: str = "h1") -> dict[str, Any]:
    return {
        "number": 7779,
        "title": "A change",
        "isDraft": False,
        "createdAt": "2026-08-19T13:54:26Z",
        "updatedAt": "2026-11-25T23:07:12Z",
        "headRefOid": head,
        "repository": {"nameWithOwner": "os-autoinst/openQA"},
        "author": {"login": "okurz"},
        "commits": {"nodes": [{"commit": {"committedDate": "2026-11-25T22:41:16Z"}}]},
        "reviews": {"nodes": json.loads(reviews or "[]")},
    }


def bot_review(state: str, commit: str, submitted: str, login: str = "os-autoinst-review") -> dict[str, Any]:
    return {"author": {"login": login}, "state": state, "submittedAt": submitted, "commit": {"oid": commit}}


def test_facts_from_node_reads_head_reviews_and_author(sut):
    node = census_node(
        reviews=json.dumps([
            bot_review("CHANGES_REQUESTED", "old", "2026-11-24T05:34:43Z"),
            bot_review("APPROVED", "h1", "2026-11-25T16:24:23Z", login="Martchus"),
            bot_review("APPROVED", "h1", "2026-11-25T16:24:23Z", login="dependabot[bot]"),
            bot_review("COMMENTED", "h1", "2026-11-25T07:53:21Z", login="okurz"),
        ])
    )
    facts = sut.facts_from_node(node, "os-autoinst-review")
    assert (facts.repo, facts.number, facts.author) == ("os-autoinst/openQA", 7779, "okurz")
    assert (facts.head, facts.head_at) == ("h1", "2026-11-25T22:41:16Z")
    assert facts.bot_reviews == (sut.BotReview("CHANGES_REQUESTED", "old", "2026-11-24T05:34:43Z"),)
    assert facts.human_reviewers == 1
    assert facts.candidate.slug == "os-autoinst-openQA-7779"
    assert facts.state.has_bot_block is True
    assert facts.state.blocked_on_head is False


def test_census_pages_until_the_scope_is_exhausted(sut, mocker):
    first = {"pageInfo": {"hasNextPage": True, "endCursor": "c1"}, "nodes": [census_node()]}
    second = {"pageInfo": {"hasNextPage": False, "endCursor": "c2"}, "nodes": []}
    run = mocker.patch.object(sut, "run")
    run.side_effect = [
        MagicMock(returncode=0, stderr="", stdout=json.dumps({"data": {"search": first}})),
        MagicMock(returncode=0, stderr="", stdout=json.dumps({"data": {"search": second}})),
    ]
    got = sut.fetch_census(["os-autoinst"], [], "os-autoinst-review")
    assert [facts.number for facts in got] == [7779]
    assert run.call_count == 2
    assert run.call_args_list[0].args[0][:3] == ["gh-as-bot", "api", "graphql"]
    assert any(arg.startswith("cursor=") for arg in run.call_args_list[1].args[0])


def test_census_reports_a_gh_failure(sut, mocker):
    mocker.patch.object(sut, "run", return_value=MagicMock(returncode=1, stderr="boom", stdout=""))
    with pytest.raises(RuntimeError, match=r"census failed for user:os-autoinst .*: boom"):
        sut.fetch_census(["os-autoinst"], [], "os-autoinst-review")


def make_facts(
    sut,
    *,
    number=1,
    repo="os-autoinst/openQA",
    author="okurz",
    draft=False,
    created="2026-11-15T00:00:00Z",
    updated="2026-11-15T00:00:00Z",
    head="h1",
    head_at="2026-11-15T00:00:00Z",
    reviews=(),
):
    return sut.PrFacts(
        repo=repo,
        number=number,
        title="A change",
        author=author,
        created_at=created,
        updated_at=updated,
        head=head,
        head_at=head_at,
        is_draft=draft,
        bot_reviews=tuple(sut.BotReview(state, commit, submitted) for state, commit, submitted in reviews),
        human_reviewers=0,
    )


CUTOFF = "2026-11-01T00:00:00Z"


def test_obligation_c1_when_the_head_moved_past_the_verdict(sut):
    facts = make_facts(sut, reviews=[("CHANGES_REQUESTED", "old", "2026-11-01T00:00:00Z")])
    assert sut.obligation(facts, cutoff=CUTOFF) == ("C1", "2026-11-15T00:00:00Z")


def test_obligation_c1_when_the_bot_only_commented_on_an_older_head(sut):
    facts = make_facts(sut, reviews=[("COMMENTED", "old", "2026-11-01T00:00:00Z")])
    assert sut.obligation(facts, cutoff=CUTOFF) == ("C1", "2026-11-15T00:00:00Z")


def test_obligation_c2_when_activity_follows_the_verdict_on_the_head(sut):
    facts = make_facts(
        sut, head="h1", updated="2026-11-20T00:00:00Z", reviews=[("APPROVED", "h1", "2026-11-15T00:00:00Z")]
    )
    assert sut.obligation(facts, cutoff=CUTOFF) == ("C2", "2026-11-15T00:00:00Z")


def test_obligation_is_none_when_the_verdict_covers_the_head(sut):
    facts = make_facts(
        sut, head="h1", updated="2026-11-15T00:00:00Z", reviews=[("APPROVED", "h1", "2026-11-15T00:00:00Z")]
    )
    assert sut.obligation(facts, cutoff=CUTOFF) is None


@pytest.mark.parametrize(("created", "expected"), [("2026-11-15T00:00:00Z", "C3"), ("2026-08-19T00:00:00Z", "C4")])
def test_obligation_orders_an_unreviewed_pr_by_age(sut, created, expected):
    facts = make_facts(sut, created=created)
    assert sut.obligation(facts, cutoff=CUTOFF) == (expected, created)


def test_parse_stamp_reads_both_stamp_forms(sut):
    assert sut.parse_stamp("2026-11-25T22:41:16Z") == sut.parse_stamp("2026-11-25T23:41:16+01:00")


@pytest.mark.parametrize(("seconds", "expected"), [(30, "30s"), (120, "2m"), (7200, "2h"), (864000, "10d")])
def test_format_wait_picks_the_largest_whole_unit(sut, seconds, expected):
    assert sut.format_wait(seconds) == expected


def test_wait_seconds_measures_the_owed_time(sut):
    assert sut.wait_seconds("2026-11-20T00:00:00Z", now="2026-11-25T00:00:00Z") == 5 * 86400


def test_record_wait_appends_the_class_the_cycle_and_the_wait(sut, tmp_path):
    path = tmp_path / "waits.csv"
    sut.record_wait(
        path,
        make_candidate(sut, number=7779),
        ("C1", "2026-11-20T00:00:00Z"),
        cycle="20261126-111041-000",
        now="2026-11-25T00:00:00Z",
    )
    sut.record_wait(
        path,
        make_candidate(sut, number=7775),
        ("C4", "2026-08-19T00:00:00Z"),
        cycle="20261126-111041-000",
        now="2026-11-25T00:00:00Z",
    )
    assert path.read_text().splitlines() == [
        "# v2 stamp,repo,number,cycle,class,owed_since,wait_seconds",
        "2026-11-25T00:00:00Z,os-autoinst/openQA,7779,20261126-111041-000,C1,2026-11-20T00:00:00Z,432000",
        "2026-11-25T00:00:00Z,os-autoinst/openQA,7775,20261126-111041-000,C4,2026-08-19T00:00:00Z,8467200",
    ]


def test_record_wait_keeps_the_header_and_the_newest_rows_when_trimming(sut, tmp_path, mocker):
    mocker.patch.object(sut, "MAX_WAIT_ROWS", 4)
    path = tmp_path / "waits.csv"
    for number in range(1, 6):
        sut.record_wait(path, make_candidate(sut, number=number), ("C1", "2026-11-20T00:00:00Z"), cycle="c")
    lines = path.read_text().splitlines()
    assert lines[0].startswith("# v2")
    assert [line.split(",")[2] for line in lines[1:]] == ["4", "5"]


def test_load_waits_reads_both_row_versions_and_skips_junk(sut, tmp_path):
    path = tmp_path / "waits.csv"
    path.write_text(
        "# v2 stamp,repo,number,cycle,class,owed_since,wait_seconds\n"
        "2026-11-25T00:00:00Z,os-autoinst/openQA,7779,cycle-1,C1,2026-11-20T00:00:00Z,432000\n"
        "2026-11-25T00:00:00Z,os-autoinst/openQA,7775,C4,2026-08-19T00:00:00Z,60\n"
        "junk\n"
        "\n"
    )
    assert sut.load_waits(path) == [
        sut.Wait("2026-11-25T00:00:00Z", "cycle-1", "C1", 432000.0),
        sut.Wait("2026-11-25T00:00:00Z", "", "C4", 60.0),
    ]


def test_load_waits_drops_rows_outside_the_window(sut, tmp_path, mocker):
    mocker.patch.object(sut, "stamp_days_ago", return_value="2026-11-20T00:00:00Z")
    path = tmp_path / "waits.csv"
    path.write_text(
        "2026-11-19T00:00:00Z,os-autoinst/openQA,1,cycle-1,C1,2026-11-19T00:00:00Z,60\n"
        "2026-11-25T00:00:00Z,os-autoinst/openQA,2,cycle-1,C1,2026-11-25T00:00:00Z,60\n"
    )
    assert [wait.stamp for wait in sut.load_waits(path)] == ["2026-11-25T00:00:00Z"]


def test_load_waits_treats_a_missing_ledger_as_empty(sut, tmp_path):
    assert sut.load_waits(tmp_path / "absent.csv") == []


def test_latency_reports_count_worst_and_percentile(sut):
    waits = [sut.Wait("2026-11-25T00:00:00Z", "c", "C1", seconds) for seconds in (60.0, 120.0, 7200.0, 3.0)]
    summary = sut.latency(waits, "C1")
    assert summary == sut.Latency(count=4, max_seconds=7200.0, p95_seconds=7200.0)
    assert sut.latency(waits, "C2") is None


def test_throughput_counts_rows_per_cycle(sut):
    waits = [
        sut.Wait("2026-11-25T00:00:00Z", "cycle-1", "C4", 1.0),
        sut.Wait("2026-11-25T00:00:00Z", "cycle-1", "C4", 1.0),
        sut.Wait("2026-11-25T00:00:00Z", "cycle-2", "C4", 1.0),
        sut.Wait("2026-11-25T00:00:00Z", "cycle-2", "C1", 1.0),
    ]
    assert sut.throughput(waits, "C4") == pytest.approx(1.5)
    assert sut.throughput(waits, "C3") == pytest.approx(0.0)


def test_latency_report_names_every_class(sut):
    waits = [
        sut.Wait("2026-11-25T00:00:00Z", "cycle-1", "C1", 3600.0),
        sut.Wait("2026-11-25T00:00:00Z", "cycle-1", "C4", 60.0),
    ]
    assert sut.latency_report(waits) == "C1 max 1h p95 1h n=1 · C2 none · C3 none · C4 1.0/cycle n=1"


def make_state(sut, *, head="h", **fields: Any):
    return sut.PrState(head=head, **fields)


def make_outcome(sut, *, ok: bool, skipped: bool = False, log: str = "/log/1"):
    return sut.ReviewOutcome(ok=ok, skipped=skipped, log=Path(log))


def write_log(handle: Any, text: str) -> MagicMock:
    handle.write(text)
    return MagicMock(returncode=0)


def test_pr_state_marks_head_review(sut, mocker):
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
    assert state.has_bot_block is False
    assert "--paginate" in run.call_args_list[1].args[0]
    assert "?per_page=100" in run.call_args_list[1].args[0][3]


def test_pr_state_detects_stale_block(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123", stderr="")
    reviews = MagicMock(returncode=0, stdout="os-autoinst-review\tCHANGES_REQUESTED\told\n", stderr="")
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    state = sut.pr_state(make_candidate(sut), "os-autoinst-review")
    assert state.reviewed_on_head is False
    assert state.has_bot_block is True
    assert state.blocked_on_head is False


def test_pr_state_detects_block_on_head(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123", stderr="")
    reviews = MagicMock(returncode=0, stdout="os-autoinst-review\tCHANGES_REQUESTED\tabc123\n", stderr="")
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    state = sut.pr_state(make_candidate(sut), "os-autoinst-review")
    assert state.reviewed_on_head is True
    assert state.has_bot_block is True
    assert state.blocked_on_head is True


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
    assert state.blocked_on_head is True


def test_pr_state_raises_when_reviews_cannot_be_read(sut, mocker):
    view = MagicMock(returncode=0, stdout="abc123", stderr="")
    reviews = MagicMock(returncode=1, stdout="", stderr="rate limited")
    mocker.patch.object(sut, "run", side_effect=[view, reviews])
    with pytest.raises(RuntimeError, match="cannot read reviews of os-autoinst/openQA#1: rate limited"):
        sut.pr_state(make_candidate(sut), "os-autoinst-review")


def owed_from(sut, facts, *, skips=None, cutoff=CUTOFF, **kwargs: Any):
    candidates, owed = sut.owed_work(facts, "os-autoinst-review", skips=skips or {}, cutoff=cutoff, **kwargs)
    return [cand.number for cand in candidates], owed


def test_owed_work_drops_drafts_bot_authors_and_dependency_bots(sut):
    facts = [
        make_facts(sut, number=1),
        make_facts(sut, number=2, author="os-autoinst-review"),
        make_facts(sut, number=3, draft=True),
        make_facts(sut, number=4, author="dependabot[bot]"),
    ]
    assert owed_from(sut, facts)[0] == [1]
    assert owed_from(sut, facts, include_bots=True)[0] == [1, 4]


def test_owed_work_only_blocked_keeps_the_bot_block(sut):
    block = [("CHANGES_REQUESTED", "old", "2026-11-01T00:00:00Z")]
    facts = [make_facts(sut, number=1), make_facts(sut, number=2, reviews=block), make_facts(sut, number=3)]
    assert owed_from(sut, facts, only_blocked=True)[0] == [2]


def test_owed_work_drops_a_head_the_bot_deliberately_skipped(sut):
    facts = [make_facts(sut, number=1, head="h1")]
    assert owed_from(sut, facts, skips={"os-autoinst/openQA#1": "h1"})[0] == []
    assert owed_from(sut, facts, skips={"os-autoinst/openQA#1": "old"})[0] == [1]
    assert owed_from(sut, facts, skips={"os-autoinst/openQA#1": "h1"}, recheck=True)[0] == [1]


def test_owed_work_reports_the_class_and_the_owed_since(sut):
    moved = [("CHANGES_REQUESTED", "old", "2026-11-01T00:00:00Z")]
    facts = [make_facts(sut, number=1, reviews=moved), make_facts(sut, number=4, created="2026-08-19T00:00:00Z")]
    _, owed = owed_from(sut, facts)
    assert owed == {
        ("os-autoinst/openQA", 1): ("C1", "2026-11-15T00:00:00Z"),
        ("os-autoinst/openQA", 4): ("C4", "2026-08-19T00:00:00Z"),
    }


def test_owed_work_recheck_adds_the_c5_class(sut):
    covered = [("APPROVED", "h1", "2026-11-15T00:00:00Z")]
    facts = [make_facts(sut, number=1, reviews=covered)]
    assert owed_from(sut, facts)[0] == []
    assert owed_from(sut, facts, recheck=True)[1] == {("os-autoinst/openQA", 1): ("C5", "2026-11-15T00:00:00Z")}


@pytest.mark.parametrize(("shard", "expected"), [((1, 3), [1, 4]), ((2, 3), [2]), ((3, 3), [3])])
def test_owed_work_shards_partition_the_universe(sut, shard, expected):
    facts = [make_facts(sut, number=n) for n in range(1, 5)]
    assert owed_from(sut, facts, shard=shard)[0] == expected


def test_select_owed_reserves_slots_for_the_backlog(sut):
    moved = [("CHANGES_REQUESTED", "old", "2026-11-01T00:00:00Z")]
    facts = [make_facts(sut, number=n, reviews=moved) for n in range(1, 6)]
    facts.extend((
        make_facts(sut, number=10, created="2026-11-10T00:00:00Z"),
        make_facts(sut, number=20, created="2026-08-19T00:00:00Z"),
    ))
    candidates, owed = sut.owed_work(facts, "os-autoinst-review", skips={}, cutoff=CUTOFF)
    assert [cand.number for cand in sut.select_owed(candidates, owed, 4)] == [1, 2, 10, 20]


def test_select_owed_orders_by_class_then_owed_age(sut):
    moved = [("CHANGES_REQUESTED", "old", "2026-11-01T00:00:00Z")]
    facts = [
        make_facts(sut, number=1, reviews=moved),
        make_facts(sut, number=2, created="2026-08-19T00:00:00Z"),
        make_facts(sut, number=3, created="2026-11-10T00:00:00Z"),
    ]
    candidates, owed = sut.owed_work(facts, "os-autoinst-review", skips={}, cutoff=CUTOFF)
    assert [cand.number for cand in sut.select_owed(candidates, owed, 3)] == [1, 3, 2]
    assert [cand.number for cand in sut.select_owed(candidates, owed, 1)] == [1]


@pytest.mark.parametrize(
    ("value", "expected"), [("1/3", (1, 3)), ("3/3", (3, 3)), ("0/3", None), ("4/3", None), ("x", None)]
)
def test_parse_shard_accepts_one_based_ranges_only(sut, value, expected):
    if expected is None:
        with pytest.raises(argparse.ArgumentTypeError):
            sut.parse_shard(value)
    else:
        assert sut.parse_shard(value) == expected


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


def test_review_skipped_detects_the_marker(sut):
    assert sut.review_skipped("--- REVIEW SKIPPED (github o/r#1, nothing new) ---") is True
    assert sut.review_skipped("Verdict: APPROVE") is False


def test_skip_cache_round_trip_and_malformed_cache(sut, tmp_path):
    cache = tmp_path / "nested" / "skipped.json"
    assert sut.load_skips(cache) == {}
    sut.save_skips(cache, {"o/r#1": "abc"})
    assert sut.load_skips(cache) == {"o/r#1": "abc"}
    cache.write_text("[1, 2]")
    assert sut.load_skips(cache) == {}
    cache.write_text("{not json")
    assert sut.load_skips(cache) == {}


def test_record_skip_keys_the_head_by_repo_and_number(sut, tmp_path):
    cache = tmp_path / "skipped.json"
    skips: dict[str, str] = {}
    sut.record_skip(cache, make_candidate(sut, number=7, repo="o/r"), make_state(sut, head="abc"), skips)
    assert sut.load_skips(cache) == {"o/r#7": "abc"}


def test_confirm_posted_accepts_a_skip_without_a_review(sut, mocker):
    mocker.patch.object(sut, "pr_state", side_effect=AssertionError("a skip needs no API lookup"))
    assert sut.confirm_posted(make_candidate(sut), "bot", make_outcome(sut, ok=True, skipped=True), dry_run=False)


def test_confirm_posted_rejects_a_skip_that_failed(sut, mocker):
    mocker.patch.object(sut, "pr_state", side_effect=AssertionError("a skip needs no API lookup"))
    assert not sut.confirm_posted(make_candidate(sut), "bot", make_outcome(sut, ok=False, skipped=True), dry_run=False)


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
    outcome = sut.run_review(make_candidate(sut), tmp_path, dry_run=False, log_dir=log, timeout=5)
    assert outcome == sut.ReviewOutcome(ok=True, skipped=False, log=log / "os-autoinst-openQA-1.log")
    assert outcome.log.exists()


def test_run_review_reports_a_skipped_session(sut, tmp_path, mocker):
    mocker.patch.object(sut, "fetch_pr_head")
    mocker.patch.object(
        sut.subprocess,
        "run",
        side_effect=lambda _cmd, **kw: write_log(kw["stdout"], "--- REVIEW SKIPPED (github o/r#1, nothing new) ---\n"),
    )
    outcome = sut.run_review(make_candidate(sut), tmp_path, dry_run=False, log_dir=tmp_path, timeout=5)
    assert outcome.ok is True
    assert outcome.skipped is True


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
    outcome = sut.run_review(make_candidate(sut), tmp_path, dry_run=False, log_dir=tmp_path, timeout=5)
    assert outcome.ok is False
    assert outcome.skipped is False
    assert "REVIEW FAILED (timeout after 5s)" in outcome.log.read_text()


def test_parse_args_defaults(sut):
    args = sut.parse_args([])
    assert args.limit == sut.DEFAULT_LIMIT
    assert args.dry_run is False
    assert args.list is False
    assert args.shard is None
    assert not args.cache
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
    patch_cycle(sut, mocker, [make_facts(sut, number=1)])
    run_review = mocker.patch.object(sut, "run_review")
    assert sut.main(["--owner", "os-autoinst", "--list"]) == 0
    out = capsys.readouterr().out
    assert out.split("\t")[:3] == ["os-autoinst/openQA#1", "C3", "2026-11-15"]
    run_review.assert_not_called()


def test_main_reports_nothing_owed_when_the_census_is_empty(sut, mocker, capsys):
    patch_cycle(sut, mocker, [])
    assert sut.main(["--owner", "os-autoinst", "--limit", "2"]) == 0
    assert "nothing owed for os-autoinst" in capsys.readouterr().err


def test_main_reports_a_census_of_prs_that_owe_nothing(sut, mocker, capsys):
    covered = make_facts(sut, reviews=[("APPROVED", "h1", "2026-11-15T00:00:00Z")])
    patch_cycle(sut, mocker, [covered])
    assert sut.main(["--owner", "os-autoinst", "--limit", "2"]) == 0
    err = capsys.readouterr().err
    assert "census: 1 open PRs, 0 owed, 0 eligible" in err
    assert "nothing owed" in err


def patch_cycle(sut, mocker, facts, *, checkouts=None, skip_cache=None):
    """Wire one cycle to a fixed census and cutoff so a test decides what the bot owes."""
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "fetch_census", return_value=facts)
    mocker.patch.object(sut, "stamp_days_ago", return_value=CUTOFF)
    if checkouts is not None:
        mocker.patch.object(sut, "discover_checkouts", return_value=checkouts)
    if skip_cache is not None:
        mocker.patch.object(sut, "cache_dir", return_value=skip_cache)


def test_main_requires_a_scope(sut, mocker, capsys):
    mocker.patch.object(sut, "infer_owner", return_value="")
    assert sut.main([]) == 2
    assert "give --owner" in capsys.readouterr().err


def test_main_reports_a_census_failure_without_a_traceback(sut, mocker, capsys):
    mocker.patch.object(sut, "bot_login", return_value="bot")
    mocker.patch.object(sut, "fetch_census", side_effect=RuntimeError("gh down"))
    assert sut.main(["--owner", "os-autoinst"]) == 1
    assert "census failed: gh down" in capsys.readouterr().err


def test_main_runs_each_selected_pr(sut, tmp_path, mocker, capsys):
    patch_cycle(
        sut,
        mocker,
        [make_facts(sut, number=1), make_facts(sut, number=2)],
        checkouts={"os-autoinst/openQA": tmp_path},
    )
    mocker.patch.object(
        sut,
        "pr_state",
        side_effect=[make_state(sut, reviewed_on_head=True), make_state(sut)],
    )
    run_review = mocker.patch.object(
        sut,
        "run_review",
        side_effect=[make_outcome(sut, ok=True, log="/log/1"), make_outcome(sut, ok=False, log="/log/2")],
    )
    code = sut.main(["--owner", "os-autoinst", "--limit", "2", "--log-dir", str(tmp_path / "logs")])
    assert code == 1
    assert run_review.call_count == 2
    assert "done: 1 ok, 1 failed" in capsys.readouterr().err


def test_main_counts_a_posted_review_after_a_timeout_as_ok(sut, tmp_path, mocker, capsys):
    patch_cycle(sut, mocker, [make_facts(sut)], checkouts={"os-autoinst/openQA": tmp_path})
    mocker.patch.object(sut, "run_review", return_value=make_outcome(sut, ok=False, log="/log/1"))
    mocker.patch.object(sut, "pr_state", return_value=make_state(sut, reviewed_on_head=True))
    code = sut.main(["--owner", "os-autoinst", "--limit", "1", "--log-dir", str(tmp_path / "logs")])
    assert code == 0
    assert "done: 1 ok, 0 failed" in capsys.readouterr().err


def test_main_counts_a_skipped_session_as_ok_and_records_the_head(sut, tmp_path, mocker, capsys):
    patch_cycle(
        sut, mocker, [make_facts(sut, head="abc123")], checkouts={"os-autoinst/openQA": tmp_path}, skip_cache=tmp_path
    )
    mocker.patch.object(sut, "run_review", return_value=make_outcome(sut, ok=True, skipped=True, log="/log/1"))
    mocker.patch.object(sut, "pr_state", side_effect=AssertionError("a skip needs no API lookup"))
    code = sut.main(["--owner", "os-autoinst", "--limit", "1", "--log-dir", str(tmp_path / "logs")])
    assert code == 0
    assert "skip  os-autoinst/openQA#1" in capsys.readouterr().err
    assert sut.load_skips(tmp_path / "skipped.json") == {"os-autoinst/openQA#1": "abc123"}


def test_main_marks_an_unposted_session_as_failed(sut, tmp_path, mocker, capsys):
    patch_cycle(sut, mocker, [make_facts(sut)], checkouts={"os-autoinst/openQA": tmp_path})
    mocker.patch.object(sut, "run_review", return_value=make_outcome(sut, ok=True, log="/log/1"))
    mocker.patch.object(sut, "pr_state", return_value=make_state(sut))
    code = sut.main(["--owner", "os-autoinst", "--limit", "1", "--log-dir", str(tmp_path / "logs")])
    assert code == 1
    assert "done: 0 ok, 1 failed" in capsys.readouterr().err


def test_main_forces_comment_when_the_bot_already_requested_changes(sut, tmp_path, mocker):
    blocked = make_facts(
        sut,
        updated="2026-11-20T00:00:00Z",
        reviews=[("CHANGES_REQUESTED", "h1", "2026-11-15T00:00:00Z")],
    )
    patch_cycle(sut, mocker, [blocked], checkouts={"os-autoinst/openQA": tmp_path})
    mocker.patch.object(sut, "pr_state", return_value=make_state(sut, reviewed_on_head=True))
    run_review = mocker.patch.object(sut, "run_review", return_value=make_outcome(sut, ok=True, log="/log/1"))
    sut.main(["--owner", "os-autoinst", "--limit", "1", "--log-dir", str(tmp_path / "logs")])
    assert run_review.call_args.kwargs["comment_only"] is True


def test_main_reviews_a_new_head_for_a_new_verdict(sut, tmp_path, mocker):
    moved = make_facts(sut, reviews=[("CHANGES_REQUESTED", "old", "2026-11-01T00:00:00Z")])
    patch_cycle(sut, mocker, [moved], checkouts={"os-autoinst/openQA": tmp_path})
    mocker.patch.object(sut, "pr_state", return_value=make_state(sut, has_bot_block=True))
    run_review = mocker.patch.object(sut, "run_review", return_value=make_outcome(sut, ok=True, log="/log/1"))
    sut.main(["--owner", "os-autoinst", "--limit", "1", "--log-dir", str(tmp_path / "logs")])
    assert run_review.call_args.kwargs["comment_only"] is False


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


def test_select_owed_holds_the_reserves_back_from_a_flood_of_urgent_work(sut):
    moved = [("CHANGES_REQUESTED", "old", "2026-11-01T00:00:00Z")]
    quiet = [("APPROVED", "h1", "2026-11-01T00:00:00Z")]
    facts = [make_facts(sut, number=n, reviews=moved) for n in range(1, 7)]
    facts.extend(make_facts(sut, number=n, updated="2026-11-20T00:00:00Z", reviews=quiet) for n in range(10, 18))
    facts.extend((
        make_facts(sut, number=30, created="2026-11-10T00:00:00Z"),
        make_facts(sut, number=40, created="2026-08-19T00:00:00Z"),
    ))
    candidates, owed = sut.owed_work(facts, "os-autoinst-review", skips={}, cutoff=CUTOFF)
    selected = [cand.number for cand in sut.select_owed(candidates, owed, 12)]
    assert len(selected) == 12
    assert selected[-2:] == [30, 40]
