"""Tests for pr-sweep: own-PR selection, worktree preparation, session wiring and ledgers."""

import argparse
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def sut(load_script):
    return load_script("pr-sweep")


@pytest.fixture
def cache(sut, mocker, tmp_path):
    """Point every ledger of a test at a temporary cache, never at ~/.cache/pr-sweep."""
    target = tmp_path / "cache"
    mocker.patch.object(sut, "cache_dir", return_value=target)
    return target


def make_pr(sut, *, number=8141, repo="os-autoinst/openQA", draft=False, decision="", failed=()):
    return sut.Pr(
        repo=repo,
        number=number,
        title="A change",
        branch="feature/change",
        head="a" * 40,
        url=f"https://github.com/{repo}/pull/{number}",
        draft=draft,
        review_decision=decision,
        failed_checks=tuple(failed),
    )


def worktree(sut, tmp_path, state="ready"):
    return sut.Worktree(tmp_path / "wt", state)


def args(**overrides: object) -> argparse.Namespace:
    """Return parsed defaults with the given overrides."""
    parser_defaults = {
        "repo": "",
        "author": "@me",
        "limit": 50,
        "prs": [],
        "exclude": [],
        "all": False,
        "prepare": False,
        "run": False,
        "jobs": 1,
        "runner": "pi",
        "model": "",
        "apply": False,
        "timeout": 3600.0,
        "worktree_root": "/tmp/wt-root",
        "cache": "",
        "log_dir": "",
    }
    return argparse.Namespace(**{**parser_defaults, **overrides})


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:os-autoinst/openQA.git", "os-autoinst/openQA"),
        ("https://github.com/os-autoinst/openQA", "os-autoinst/openQA"),
        ("https://gitlab.com/os-autoinst/openQA", None),
        ("", None),
    ],
)
def test_parse_github_repo(sut, url, expected):
    assert sut.parse_github_repo(url) == expected


def test_slug_names_the_repository_and_number(sut):
    assert make_pr(sut, repo="os-autoinst/openQA", number=8141).slug == "os-autoinst-openQA-8141"


def test_infer_repo_reads_the_origin_remote(sut, fake_subprocess):
    fake_subprocess.on(["git", "remote", "get-url", "origin"], stdout="git@github.com:os-autoinst/openQA.git\n")
    assert sut.infer_repo() == "os-autoinst/openQA"


def test_infer_repo_is_empty_without_a_github_remote(sut, fake_subprocess):
    fake_subprocess.on(["git", "remote", "get-url", "origin"], stdout="https://gitlab.com/x/y\n")
    assert not sut.infer_repo()


def test_infer_repo_is_empty_when_git_fails(sut, fake_subprocess):
    fake_subprocess.on(["git", "remote", "get-url", "origin"], returncode=2)
    assert not sut.infer_repo()


def test_failed_checks_names_every_failing_check(sut):
    rollup = [
        {"name": "checks", "conclusion": "FAILURE"},
        {"context": "jenkins", "state": "timed_out"},
        {"name": "unit", "conclusion": "SUCCESS"},
        {"conclusion": "ERROR"},
        {},
    ]
    assert sut.failed_checks(rollup) == ("checks", "jenkins", "unknown")


def test_make_pr_defaults_a_missing_entry(sut):
    pr = sut.make_pr("os-autoinst/openQA", {"number": "7", "headRefName": "topic"})
    assert pr.url == "https://github.com/os-autoinst/openQA/pull/7"
    assert (pr.draft, pr.head, pr.review_decision, pr.failed_checks) == (False, "", "", ())


def test_make_pr_reads_a_full_entry(sut):
    entry = {
        "number": 7,
        "title": "Fix it",
        "headRefName": "topic",
        "headRefOid": "abc",
        "isDraft": True,
        "reviewDecision": "CHANGES_REQUESTED",
        "statusCheckRollup": [{"name": "checks", "conclusion": "FAILURE"}],
        "url": "https://github.com/o/r/pull/7",
    }
    pr = sut.make_pr("o/r", entry)
    assert (pr.title, pr.head, pr.draft, pr.failed_checks) == ("Fix it", "abc", True, ("checks",))


def test_fetch_prs_queries_my_open_prs(sut, fake_subprocess):
    payload = [{"number": 3, "headRefName": "topic"}]
    fake_subprocess.on(["gh", "pr", "list"], stdout=json.dumps(payload))
    assert [pr.number for pr in sut.fetch_prs("o/r", limit=5, author="@me")] == [3]
    (cmd,) = fake_subprocess.commands(["gh", "pr", "list"])
    assert cmd[cmd.index("--author") + 1] == "@me"
    assert cmd[cmd.index("--limit") + 1] == "5"


def test_fetch_prs_reports_a_gh_failure(sut, fake_subprocess):
    fake_subprocess.on(["gh", "pr", "list"], stderr="boom", returncode=1)
    with pytest.raises(RuntimeError, match="boom"):
        sut.fetch_prs("o/r", limit=5, author="@me")


def test_viewer_login_reads_the_authenticated_user(sut, fake_subprocess):
    fake_subprocess.on(["gh", "api", "user"], stdout="okurz\n")
    assert sut.viewer_login() == "okurz"


def test_viewer_login_is_empty_when_gh_fails(sut, fake_subprocess):
    fake_subprocess.on(["gh", "api", "user"], returncode=1)
    assert not sut.viewer_login()


def test_fetch_selected_reads_the_named_prs_of_the_viewer(sut, fake_subprocess):
    fake_subprocess.on(["gh", "api", "user"], stdout="okurz\n")
    fake_subprocess.on(
        ["gh", "pr", "view", "8088"],
        stdout=json.dumps({"number": 8088, "headRefName": "b", "author": {"login": "okurz"}}),
    )
    fake_subprocess.on(
        ["gh", "pr", "view", "8089"],
        stdout=json.dumps({"number": 8089, "headRefName": "c", "author": {"login": "someone"}}),
    )
    assert [pr.number for pr in sut.fetch_selected("o/r", [8089, 8088], author="@me")] == [8088]


def test_fetch_selected_keeps_every_named_pr_without_an_author_filter(sut, fake_subprocess):
    fake_subprocess.on(["gh", "pr", "view", "7"], stdout=json.dumps({"number": 7, "headRefName": "b"}))
    assert [pr.number for pr in sut.fetch_selected("o/r", [7], author="")] == [7]


def test_fetch_selected_reports_a_gh_failure(sut, fake_subprocess):
    fake_subprocess.on(["gh", "api", "user"], stdout="okurz\n")
    fake_subprocess.on(["gh", "pr", "view", "7"], stderr="HTTP 504", returncode=1)
    with pytest.raises(RuntimeError, match="HTTP 504"):
        sut.fetch_selected("o/r", [7], author="@me")


def test_fetch_selected_reports_an_unparsable_answer(sut, fake_subprocess):
    fake_subprocess.on(["gh", "api", "user"], stdout="okurz\n")
    fake_subprocess.on(["gh", "pr", "view", "7"], stdout="")
    with pytest.raises(RuntimeError, match="gh pr view 7 returned no JSON"):
        sut.fetch_selected("o/r", [7], author="@me")


def test_fetch_prs_reports_an_unparsable_answer(sut, fake_subprocess):
    fake_subprocess.on(["gh", "pr", "list"], stdout="not json")
    with pytest.raises(RuntimeError, match="no JSON"):
        sut.fetch_prs("o/r", limit=5, author="@me")


@pytest.mark.parametrize(
    ("draft", "decision", "failed", "everything", "expected"),
    [
        (False, "CHANGES_REQUESTED", (), False, True),
        (False, "", ("checks",), False, True),
        (False, "APPROVED", (), False, False),
        (True, "CHANGES_REQUESTED", (), False, False),
        (False, "APPROVED", (), True, True),
    ],
)
def test_owes_an_answer(sut, draft, decision, failed, everything, expected):
    pr = make_pr(sut, draft=draft, decision=decision, failed=failed)
    assert sut.owes_an_answer(pr, everything=everything) is expected


def test_select_prs_keeps_only_the_requested_numbers(sut):
    prs = [make_pr(sut, number=1, decision="APPROVED"), make_pr(sut, number=2, decision="APPROVED")]
    assert [pr.number for pr in sut.select_prs(prs, args(prs=[2]))] == [2]


def test_select_prs_skips_the_excluded_numbers(sut):
    prs = [make_pr(sut, number=3, decision="CHANGES_REQUESTED"), make_pr(sut, number=4, decision="CHANGES_REQUESTED")]
    assert [pr.number for pr in sut.select_prs(prs, args(exclude=[3]))] == [4]


def test_select_prs_excludes_even_from_an_explicit_list(sut):
    prs = [make_pr(sut, number=3, decision="APPROVED"), make_pr(sut, number=4, decision="APPROVED")]
    assert [pr.number for pr in sut.select_prs(prs, args(prs=[3, 4], exclude=[4]))] == [3]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("3,4,5", [3, 4, 5]), ("3, 4", [3, 4]), ("7", [7])],
)
def test_pr_numbers_reads_a_list(sut, text, expected):
    assert sut.pr_numbers(text) == expected


def test_pr_numbers_rejects_a_non_number(sut):
    with pytest.raises(argparse.ArgumentTypeError, match="not a comma-separated list"):
        sut.pr_numbers("3,x")


def test_flatten_joins_the_repeated_lists(sut):
    assert sut.flatten([[1, 2], [3]]) == [1, 2, 3]


def test_select_prs_keeps_what_owes_an_answer(sut):
    prs = [make_pr(sut, number=1, decision="APPROVED"), make_pr(sut, number=2, failed=("checks",))]
    assert [pr.number for pr in sut.select_prs(prs, args())] == [2]


def test_primary_checkout_is_the_first_worktree(sut, fake_subprocess):
    fake_subprocess.on(
        ["git", "worktree", "list", "--porcelain"],
        stdout="worktree /home/u/openQA\nHEAD abc\nbranch refs/heads/master\n\nworktree /home/u/wt\nHEAD def\n",
    )
    assert sut.primary_checkout() == Path("/home/u/openQA")


@pytest.mark.parametrize(("stdout", "returncode"), [("", 0), ("", 1)])
def test_primary_checkout_reports_a_missing_repository(sut, fake_subprocess, stdout, returncode):
    fake_subprocess.on(["git", "worktree", "list", "--porcelain"], stdout=stdout, stderr="nope", returncode=returncode)
    with pytest.raises(RuntimeError, match=r"nope|not inside"):
        sut.primary_checkout()


def test_worktree_entries_maps_branches_to_paths(sut, fake_subprocess):
    fake_subprocess.on(
        ["git", "-C", "/p", "worktree", "list", "--porcelain"],
        stdout=(
            "worktree /p\nHEAD a\nbranch refs/heads/master\n\n"
            "worktree /p/topic\nHEAD b\nbranch refs/heads/topic\n\n"
            "worktree /p/detached\nHEAD c\ndetached\n"
        ),
    )
    assert sut.worktree_entries(Path("/p")) == {"master": Path("/p"), "topic": Path("/p/topic")}


def test_worktree_entries_reports_a_git_failure(sut, fake_subprocess):
    fake_subprocess.on(["git", "-C", "/p", "worktree", "list", "--porcelain"], stderr="boom", returncode=1)
    with pytest.raises(RuntimeError, match="boom"):
        sut.worktree_entries(Path("/p"))


def test_is_dirty_sees_uncommitted_changes(sut, fake_subprocess):
    fake_subprocess.on(["git", "-C", "/p", "status", "--porcelain"], stdout=" M file\n")
    assert sut.is_dirty(Path("/p")) is True


def test_is_dirty_on_a_clean_checkout(sut, fake_subprocess):
    fake_subprocess.on(["git", "-C", "/p", "status", "--porcelain"], stdout="")
    assert sut.is_dirty(Path("/p")) is False


def test_lacks_head_is_false_without_a_head(sut):
    assert sut.lacks_head(Path("/p"), "") is False


def test_lacks_head_is_false_when_the_head_is_unknown_locally(sut, fake_subprocess):
    fake_subprocess.on(["git", "-C", "/p", "cat-file"], returncode=1)
    assert sut.lacks_head(Path("/p"), "abc") is False


def test_lacks_head_is_false_when_the_checkout_has_it(sut, fake_subprocess):
    fake_subprocess.on(["git", "-C", "/p", "cat-file"], returncode=0)
    fake_subprocess.on(["git", "-C", "/p", "merge-base"], returncode=0)
    assert sut.lacks_head(Path("/p"), "abc") is False


def test_lacks_head_is_true_when_the_pr_moved_on(sut, fake_subprocess):
    fake_subprocess.on(["git", "-C", "/p", "cat-file"], returncode=0)
    fake_subprocess.on(["git", "-C", "/p", "merge-base"], returncode=1)
    assert sut.lacks_head(Path("/p"), "abc") is True


def test_prepare_worktree_reuses_the_checkout_that_has_the_branch(sut, fake_subprocess, tmp_path):
    fake_subprocess.on(
        ["git", "-C", "/p", "worktree", "list", "--porcelain"],
        stdout="worktree /p/topic\nbranch refs/heads/feature/change\n",
    )
    fake_subprocess.on(["git", "-C", "/p/topic", "status"], stdout="")
    fake_subprocess.on(["git", "-C", "/p/topic", "cat-file"], returncode=1)
    result = sut.prepare_worktree(make_pr(sut), Path("/p"), tmp_path)
    assert result == sut.Worktree(Path("/p/topic"), "ready")
    assert fake_subprocess.commands(["git", "-C", "/p", "worktree", "add"]) == []


def test_prepare_worktree_creates_the_worktree_from_the_local_branch(sut, fake_subprocess):
    fake_subprocess.on(["git", "-C", "/p", "worktree", "list"], stdout="worktree /p\n")
    fake_subprocess.on(["git", "-C", "/p", "rev-parse", "--verify"], returncode=0)
    fake_subprocess.on(["git", "-C", "/p", "worktree", "add"], returncode=0)
    fake_subprocess.on(["git", "-C", "/tmp/wt-root/os-autoinst-openQA-8141", "status"], stdout="")
    fake_subprocess.on(["git", "-C", "/tmp/wt-root/os-autoinst-openQA-8141", "cat-file"], returncode=1)
    result = sut.prepare_worktree(make_pr(sut), Path("/p"), Path("/tmp/wt-root"))
    assert result == sut.Worktree(Path("/tmp/wt-root/os-autoinst-openQA-8141"), "ready")


def test_prepare_worktree_reports_a_missing_local_branch(sut, fake_subprocess, tmp_path):
    fake_subprocess.on(["git", "-C", "/p", "worktree", "list"], stdout="worktree /p\n")
    fake_subprocess.on(["git", "-C", "/p", "rev-parse", "--verify"], returncode=1)
    result = sut.prepare_worktree(make_pr(sut), Path("/p"), tmp_path)
    assert (result.state, result.path) == ("branch-missing", tmp_path / "os-autoinst-openQA-8141")


def test_prepare_worktree_reports_a_failed_worktree_add(sut, fake_subprocess, tmp_path):
    fake_subprocess.on(["git", "-C", "/p", "worktree", "list"], stdout="worktree /p\n")
    fake_subprocess.on(["git", "-C", "/p", "rev-parse", "--verify"], returncode=0)
    fake_subprocess.on(["git", "-C", "/p", "worktree", "add"], stderr="locked", returncode=1)
    with pytest.raises(RuntimeError, match="locked"):
        sut.prepare_worktree(make_pr(sut), Path("/p"), tmp_path)


def test_prepare_worktree_reports_a_dirty_checkout(sut, fake_subprocess, tmp_path):
    fake_subprocess.on(
        ["git", "-C", "/p", "worktree", "list", "--porcelain"],
        stdout="worktree /p/topic\nbranch refs/heads/feature/change\n",
    )
    fake_subprocess.on(["git", "-C", "/p/topic", "status"], stdout="?? notes\n")
    result = sut.prepare_worktree(make_pr(sut), Path("/p"), tmp_path)
    assert result.state == "dirty"


def test_prepare_worktree_reports_a_checkout_behind_the_pr_head(sut, fake_subprocess, tmp_path):
    fake_subprocess.on(
        ["git", "-C", "/p", "worktree", "list", "--porcelain"],
        stdout="worktree /p/topic\nbranch refs/heads/feature/change\n",
    )
    fake_subprocess.on(["git", "-C", "/p/topic", "status"], stdout="")
    fake_subprocess.on(["git", "-C", "/p/topic", "cat-file"], returncode=0)
    fake_subprocess.on(["git", "-C", "/p/topic", "merge-base"], returncode=1)
    result = sut.prepare_worktree(make_pr(sut), Path("/p"), tmp_path)
    assert result.state == "behind"


def test_model_flags_pair_a_model_with_its_runner_flag(sut):
    assert (sut.model_flags("", "-m"), sut.model_flags("m", "-m")) == ([], ["-m", "m"])


def test_session_command_runs_pi_in_the_worktree(sut, tmp_path):
    cmd = sut.session_command(make_pr(sut), worktree(sut, tmp_path), runner="pi", model="", apply=False)
    assert cmd == ["pi", "-p", "/pr-watch https://github.com/os-autoinst/openQA/pull/8141 --cycles 1"]


def test_session_command_passes_the_model_and_apply_to_pi(sut, tmp_path):
    cmd = sut.session_command(make_pr(sut), worktree(sut, tmp_path), runner="pi", model="m", apply=True)
    assert cmd == [
        "pi",
        "--model",
        "m",
        "-p",
        "/pr-watch https://github.com/os-autoinst/openQA/pull/8141 --cycles 1 --auto",
    ]


@pytest.mark.parametrize(
    ("model", "apply", "flags"),
    [("", False, []), ("m", False, ["-m", "m"]), ("", True, ["--auto"])],
)
def test_session_command_runs_opencode_in_the_worktree(sut, tmp_path, model, apply, flags):
    cmd = sut.session_command(make_pr(sut), worktree(sut, tmp_path), runner="opencode", model=model, apply=apply)
    assert cmd == [
        "opencode",
        "run",
        "--dir",
        str(tmp_path / "wt"),
        *flags,
        "--command",
        "pr-watch",
        f"https://github.com/os-autoinst/openQA/pull/8141 --cycles 1{' --auto' if apply else ''}",
    ]


@pytest.mark.parametrize(("apply", "present"), [(True, True), (False, False)])
def test_session_env_marks_the_run_unattended(sut, mocker, apply, present):
    mocker.patch.dict("os.environ", {"PR_SWEEP_APPLY": "1"}, clear=True)
    env = sut.session_env(make_pr(sut), apply=apply, jobs=1)
    assert env["PR_SWEEP"] == "1"
    assert ("PR_SWEEP_APPLY" in env) is present


def test_session_env_drops_the_parent_session_identity(sut, mocker):
    mocker.patch.dict("os.environ", {"PI_SESSION_FILE": "/tmp/parent.jsonl", "PI_MODEL": "m"}, clear=True)
    env = sut.session_env(make_pr(sut), apply=False, jobs=1)
    assert set(env).isdisjoint(sut.PARENT_SESSION_VARS)


def test_session_env_gives_parallel_sessions_their_own_cluster(sut, mocker):
    mocker.patch.dict("os.environ", {}, clear=True)
    env = sut.session_env(make_pr(sut, number=8141), apply=False, jobs=2)
    assert env["TEST_PG_PATH"] == "/dev/shm/tpg-sweep-8141"


def test_session_env_keeps_a_chosen_cluster(sut, mocker):
    mocker.patch.dict("os.environ", {"TEST_PG_PATH": "/dev/shm/mine"}, clear=True)
    assert sut.session_env(make_pr(sut), apply=False, jobs=4)["TEST_PG_PATH"] == "/dev/shm/mine"


def test_write_ledger_records_head_status_and_log(sut, cache, tmp_path):
    sut.write_ledger(cache, make_pr(sut), status="ok", log=tmp_path / "run.log")
    recorded = json.loads((cache / "os-autoinst-openQA-8141.json").read_text(encoding="utf-8"))
    assert (recorded["head"], recorded["status"], recorded["log"]) == ("a" * 40, "ok", str(tmp_path / "run.log"))


def test_run_logged_tee_output_and_returns_the_exit_code(sut, tmp_path):
    log = tmp_path / "logs" / "run.log"
    code = sut.run_logged(["sh", "-c", "echo hi"], cwd=tmp_path, env={}, log=log, timeout=30)
    assert (code, log.read_text(encoding="utf-8")) == (0, "hi\n")


def test_run_logged_reports_a_timeout(sut, tmp_path, mocker):
    mocker.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pi", 5))
    log = tmp_path / "run.log"
    assert sut.run_logged(["pi"], cwd=tmp_path, env={}, log=log, timeout=5) == sut.TIMEOUT_EXIT
    assert "PR SWEEP TIMEOUT after 5s" in log.read_text(encoding="utf-8")


def test_sweep_one_runs_the_session_and_records_it(sut, cache, tmp_path, mocker):
    logged = mocker.patch.object(sut, "run_logged", return_value=0)
    outcome = sut.sweep_one(make_pr(sut), worktree(sut, tmp_path), args(), tmp_path)
    assert (outcome.status, outcome.reason) == ("ok", "")
    assert json.loads((cache / "os-autoinst-openQA-8141.json").read_text(encoding="utf-8"))["status"] == "ok"
    assert logged.call_args.kwargs["cwd"] == tmp_path / "wt"


def test_sweep_one_names_a_failing_session(sut, tmp_path, mocker):
    mocker.patch.object(sut, "run_logged", return_value=3)
    outcome = sut.sweep_one(make_pr(sut), worktree(sut, tmp_path), args(), tmp_path)
    assert (outcome.status, outcome.reason) == ("failed", "exit 3")


@pytest.mark.parametrize("state", ["dirty", "behind", "branch-missing"])
def test_sweep_one_skips_an_unusable_worktree(sut, tmp_path, mocker, state):
    logged = mocker.patch.object(sut, "run_logged")
    outcome = sut.sweep_one(make_pr(sut), worktree(sut, tmp_path, state), args(), tmp_path)
    assert (outcome.status, outcome.reason) == (state, sut.UNUSABLE[state])
    logged.assert_not_called()


def test_print_prs_names_failing_checks(sut, capsys):
    sut.print_prs([make_pr(sut, number=1, failed=("checks",)), make_pr(sut, number=2)])
    out = capsys.readouterr().out
    assert "checks" in out
    assert f"{2:>6}  {'-':18}" in out


def test_print_outcome_shows_the_reason_without_a_log(sut, capsys, tmp_path):
    sut.print_outcome(sut.Outcome(make_pr(sut), worktree(sut, tmp_path, "dirty"), "dirty", Path(), "why"))
    assert "why" in capsys.readouterr().err


def test_print_outcome_shows_the_log(sut, capsys, tmp_path):
    sut.print_outcome(sut.Outcome(make_pr(sut), worktree(sut, tmp_path), "ok", tmp_path / "run.log"))
    assert str(tmp_path / "run.log") in capsys.readouterr().err


def test_sweep_prepares_without_running(sut, tmp_path, capsys, mocker):
    mocker.patch.object(sut, "primary_checkout", return_value=Path("/p"))
    mocker.patch.object(sut, "prepare_worktree", return_value=sut.Worktree(tmp_path / "wt", "ready"))
    code = sut.sweep([make_pr(sut)], args(worktree_root=str(tmp_path)))
    assert code == 0
    assert "ready" in capsys.readouterr().out


def test_sweep_runs_the_sessions_serially(sut, tmp_path, mocker):
    mocker.patch.object(sut, "primary_checkout", return_value=Path("/p"))
    mocker.patch.object(sut, "prepare_worktree", return_value=sut.Worktree(tmp_path / "wt", "ready"))
    one = mocker.patch.object(sut, "sweep_one", side_effect=lambda pr, wt, *_: sut.Outcome(pr, wt, "ok", Path()))
    assert sut.sweep([make_pr(sut), make_pr(sut, number=2)], args(run=True)) == 0
    assert one.call_count == 2


def test_sweep_runs_the_sessions_in_parallel_and_reports_a_failure(sut, tmp_path, mocker):
    mocker.patch.object(sut, "primary_checkout", return_value=Path("/p"))
    mocker.patch.object(sut, "prepare_worktree", return_value=sut.Worktree(tmp_path / "wt", "ready"))
    mocker.patch.object(sut, "sweep_one", side_effect=lambda pr, wt, *_: sut.Outcome(pr, wt, "failed", Path()))
    assert sut.sweep([make_pr(sut), make_pr(sut, number=2)], args(run=True, jobs=2)) == 1


def test_parse_args_defaults_to_the_audit(sut):
    parsed = sut.parse_args([])
    assert (parsed.author, parsed.jobs, parsed.run, parsed.apply) == ("@me", 1, False, False)


def test_parse_args_takes_the_model_from_the_environment(sut, mocker):
    mocker.patch.dict("os.environ", {"PR_SWEEP_MODEL": "helmcode/deepseek-v4-flash"}, clear=True)
    assert sut.parse_args([]).model == "helmcode/deepseek-v4-flash"


def test_parse_args_defaults_the_model_to_the_runner(sut, mocker):
    mocker.patch.dict("os.environ", {}, clear=True)
    assert not sut.parse_args([]).model


def test_parse_args_reads_repeated_and_comma_separated_numbers(sut):
    parsed = sut.parse_args(["--pr", "3,4", "--pr", "5", "--exclude", "1,2"])
    assert (parsed.prs, parsed.exclude) == ([3, 4, 5], [1, 2])


def test_main_rejects_prepare_together_with_run(sut, capsys):
    assert sut.main(["--prepare", "--run"]) == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_main_needs_a_repository(sut, mocker, capsys):
    mocker.patch.object(sut, "infer_repo", return_value="")
    assert sut.main([]) == 2
    assert "run inside a checkout" in capsys.readouterr().err


def test_main_audits_the_prs_that_owe_an_answer(sut, mocker, capsys):
    mocker.patch.object(sut, "infer_repo", return_value="o/r")
    mocker.patch.object(sut, "fetch_prs", return_value=[make_pr(sut, decision="CHANGES_REQUESTED")])
    assert sut.main([]) == 0
    assert "CHANGES_REQUESTED" in capsys.readouterr().out


def test_main_lets_apply_imply_a_run(sut, mocker):
    mocker.patch.object(sut, "infer_repo", return_value="o/r")
    mocker.patch.object(sut, "fetch_prs", return_value=[make_pr(sut, decision="CHANGES_REQUESTED")])
    sweep = mocker.patch.object(sut, "sweep", return_value=0)
    assert sut.main(["--apply"]) == 0
    assert sweep.call_args.args[1].run is True


def test_main_rejects_apply_together_with_prepare(sut, capsys):
    assert sut.main(["--prepare", "--apply"]) == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_main_reads_named_prs_one_by_one(sut, mocker):
    mocker.patch.object(sut, "infer_repo", return_value="o/r")
    mocker.patch.object(sut, "fetch_prs", side_effect=AssertionError("census used"))
    mocker.patch.object(sut, "fetch_selected", return_value=[make_pr(sut, number=8088)])
    mocker.patch.object(sut, "sweep", return_value=0)
    assert sut.main(["--pr", "8088", "--prepare"]) == 0


def test_main_prepares_the_worktrees(sut, mocker):
    mocker.patch.object(sut, "infer_repo", return_value="o/r")
    mocker.patch.object(sut, "fetch_prs", return_value=[make_pr(sut, decision="CHANGES_REQUESTED")])
    sweep = mocker.patch.object(sut, "sweep", return_value=0)
    assert sut.main(["--prepare"]) == 0
    assert sweep.call_args.args[1].run is False


def test_main_reports_a_gh_failure(sut, mocker, capsys):
    mocker.patch.object(sut, "infer_repo", return_value="o/r")
    mocker.patch.object(sut, "fetch_prs", side_effect=RuntimeError("boom"))
    assert sut.main([]) == 2
    assert "boom" in capsys.readouterr().err
