"""tests for git-upstream-base, git review and git review-branch."""

import os
import re
import shutil
import subprocess

import pytest

rootpath = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

COMMIT_CONFIG = [
    "-c",
    "user.email=test@example.com",
    "-c",
    "user.name=test",
    "-c",
    "commit.gpgsign=false",
]

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def env():
    result = dict(os.environ)
    result["PATH"] = rootpath + os.pathsep + result["PATH"]
    result["REVIEW_PAGER"] = "cat"
    return result


def run_tool(work, command):
    return subprocess.run(
        command,
        cwd=str(work),
        env=env(),
        capture_output=True,
        text=True,
        input="",
        check=False,
    )


def run_interactive(work, keys):
    return subprocess.run(
        ["script", "-qc", "git review", "/dev/null"],
        cwd=str(work),
        env=env(),
        input=keys,
        capture_output=True,
        text=True,
        check=False,
    )


def git(work: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *COMMIT_CONFIG, *list(args)],
        cwd=str(work),
        capture_output=True,
        text=True,
        check=True,
    )


def make_repo(tmp_path, default_branch, work_branch, commit_count):
    upstream = tmp_path / "up"
    git(str(tmp_path), "init", "-q", "--bare", "-b", default_branch, str(upstream))
    work = tmp_path / "wk"
    git(str(tmp_path), "clone", "-q", str(upstream), str(work))
    (work / "seed").write_text("seed\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "seed")
    git(work, "push", "-q", "origin", default_branch)
    git(work, "remote", "set-head", "origin", "--auto")
    git(work, "checkout", "-q", "-b", work_branch)
    for i in range(commit_count):
        (work / f"f{i}").write_text(f"content{i}\n")
        git(work, "add", "-A")
        git(work, "commit", "-qm", f"commit {i}")
    return work


def merge_repo(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 1)
    git(work, "checkout", "-q", "-b", "side")
    (work / "side").write_text("side content\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "side commit")
    git(work, "checkout", "-q", "feature")
    (work / "f1").write_text("content1\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "commit 1")
    git(work, "merge", "-q", "--no-edit", "side")
    return work


def numbered(result):
    return [line.split()[0] for line in result.stdout.splitlines() if line.strip()]


def test_origin_head_symref_is_preferred(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 0)
    result = run_tool(work, ["git-upstream-base"])
    assert result.returncode == 0
    assert result.stdout.strip() == "origin/master"


def test_falls_back_to_main_without_origin_head(tmp_path):
    work = make_repo(tmp_path, "main", "feature", 0)
    git(work, "symbolic-ref", "-d", "refs/remotes/origin/HEAD")
    result = run_tool(work, ["git-upstream-base"])
    assert result.returncode == 0
    assert result.stdout.strip() == "origin/main"


def test_falls_back_to_master_before_main(tmp_path):
    work = make_repo(tmp_path, "main", "feature", 0)
    git(work, "symbolic-ref", "-d", "refs/remotes/origin/HEAD")
    git(work, "remote", "set-url", "origin", "file:///nonexistent-upstream")
    git(work, "update-ref", "refs/remotes/origin/master", "refs/remotes/origin/main")
    result = run_tool(work, ["git-upstream-base"])
    assert result.stdout.strip() == "origin/master"


def test_reports_missing_origin_refs(tmp_path):
    work = tmp_path / "noremote"
    git(str(tmp_path), "init", "-q", "-b", "master", str(work))
    result = run_tool(work, ["git-upstream-base"])
    assert result.returncode == 1
    assert "origin/HEAD" in result.stderr


def test_review_lists_commits_oldest_first(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 3)
    result = run_tool(work, ["git", "review", "-l"])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert numbered(result) == ["1.", "2.", "3."]
    assert lines[0].endswith("commit 0")
    assert lines[2].endswith("commit 2")


def test_step_view_shows_patch_and_position(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 2)
    result = run_tool(work, ["git", "review"])
    assert "=== commit 1/2 ===" in result.stdout
    assert "content0" in result.stdout
    assert "content1" not in result.stdout


def test_review_shows_patch_for_requested_commit(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 3)
    result = run_tool(work, ["git", "review", "-n", "2"])
    assert "=== commit 2/3 ===" in result.stdout
    assert "content1" in result.stdout
    assert "content0" not in result.stdout
    assert "content2" not in result.stdout


def test_review_rejects_number_outside_range(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 2)
    result = run_tool(work, ["git", "review", "-n", "5"])
    assert result.returncode == 1
    assert "outside 1..2" in result.stdout


def test_review_reports_nothing_to_review_on_clean_branch(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 0)
    result = run_tool(work, ["git", "review"])
    assert "Nothing to review" in result.stdout


def test_rest_continues_from_current_commit(tmp_path):
    if shutil.which("script") is None:
        pytest.skip("script(1) needed for a pty")
    work = make_repo(tmp_path, "master", "feature", 3)
    result = run_interactive(work, "2\na\n")
    markers = ANSI.sub("", result.stdout)
    assert re.findall(r"=== commit (\d+)/(\d+) ===", markers) == [
        ("1", "3"),
        ("2", "3"),
        ("2", "3"),
        ("3", "3"),
    ]
    assert "content2" in markers


def test_review_stream_shows_patches_oldest_first(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 2)
    result = run_tool(work, ["git", "review", "-p"])
    assert result.stdout.find("content0") < result.stdout.find("content1")
    assert result.stdout.count("diff --git") == 2


def test_stream_stays_plain_text_without_pager(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 1)
    result = run_tool(work, ["git", "review", "-p"])
    assert "\x1b[" not in result.stdout


def test_numbering_skips_merge_commits(tmp_path):
    work = merge_repo(tmp_path)
    result = run_tool(work, ["git", "review", "-l"])
    assert numbered(result) == ["1.", "2.", "3."]
    assert "side commit" in result.stdout
    assert "Merge" not in result.stdout


def test_merges_flag_includes_merge_commits(tmp_path):
    work = merge_repo(tmp_path)
    result = run_tool(work, ["git", "review", "--merges", "-l"])
    assert numbered(result) == ["1.", "2.", "3.", "4."]
    assert "Merge" in result.stdout


def test_review_shows_diffstat_for_stat_mode(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 1)
    result = run_tool(work, ["git", "review", "-s"])
    assert "f0 | 1 +" in result.stdout
    assert "content0" not in result.stdout


def test_review_branch_treats_flag_as_flag_not_base(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 1)
    result = run_tool(work, ["git", "review-branch", "feature", "-l"])
    assert result.returncode == 0
    assert result.stdout.strip().endswith("commit 0")


def test_review_branch_accepts_explicit_base(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 3)
    result = run_tool(work, ["git", "review-branch", "feature", "HEAD~1", "-l"])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].endswith("commit 2")


def test_rebase_all_branches_skips_up_to_date_branches(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 1)
    result = run_tool(work, ["git-rebase-all-branches"])
    assert result.returncode == 0
    assert "Skipping feature" in result.stdout


def test_rebase_all_branches_reports_conflict(tmp_path):
    work = make_repo(tmp_path, "master", "feature", 1)
    git(work, "checkout", "-q", "master")
    (work / "f0").write_text("upstream wins\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "upstream change on f0")
    git(work, "push", "-q", "origin", "master")
    git(work, "checkout", "-q", "feature")
    git(work, "fetch", "-q", "origin")
    result = run_tool(work, ["git-rebase-all-branches"])
    assert result.returncode == 1
    assert "Conflict on feature" in result.stdout
