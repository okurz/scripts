"""tests for git-delete-no-content-branches and its worktree pruning."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOTPATH = str(Path(__file__).resolve().parent.parent)

COMMIT_CONFIG = [
    "-c",
    "user.email=test@example.com",
    "-c",
    "user.name=test",
    "-c",
    "commit.gpgsign=false",
]


def git(cwd: Path, *args: str) -> str:
    """Run git in a directory and return stripped stdout."""
    result = subprocess.run(
        ["git", *COMMIT_CONFIG, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def run_tool(work: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the script from PATH inside a repository."""
    env = dict(os.environ)
    env["PATH"] = ROOTPATH + os.pathsep + env["PATH"]
    return subprocess.run(
        ["git", "delete-no-content-branches", *args],
        cwd=str(work),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Return a checkout whose branch ``merged`` is fully contained in origin/master."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "--bare", "-b", "master")
    work = tmp_path / "repo"
    git(tmp_path, "clone", str(origin), str(work))
    (work / "README.md").write_text("seed\n")
    git(work, "add", "README.md")
    git(work, "commit", "-m", "seed")
    git(work, "push", "origin", "master")
    git(work, "checkout", "-b", "merged")
    (work / "feature.txt").write_text("content\n")
    git(work, "add", "feature.txt")
    git(work, "commit", "-m", "merged content")
    git(work, "checkout", "master")
    git(work, "merge", "--no-ff", "-m", "merge merged", "merged")
    git(work, "push", "origin", "master")
    return work


def test_branch_without_worktree_is_deleted(repo: Path) -> None:
    result = run_tool(repo)

    assert result.returncode == 0, result.stderr
    assert "merged" not in git(repo, "branch", "--format=%(refname:short)").splitlines()


def test_clean_worktree_is_removed_with_its_branch(repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", str(worktree), "merged")

    result = run_tool(repo)

    assert result.returncode == 0, result.stderr
    assert f"Removing worktree {worktree}" in result.stdout
    assert not worktree.exists()
    assert "merged" not in git(repo, "branch", "--format=%(refname:short)").splitlines()
    assert str(worktree) not in git(repo, "worktree", "list", "--porcelain")


def test_dirty_worktree_keeps_branch_and_worktree(repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", str(worktree), "merged")
    (worktree / "uncommitted.txt").write_text("work in progress\n")

    result = run_tool(repo)

    assert result.returncode == 0, result.stderr
    assert "has uncommitted or stashed changes" in result.stdout
    assert worktree.exists()
    assert "merged" in git(repo, "branch", "--format=%(refname:short)").splitlines()


def test_stashed_worktree_keeps_branch_and_worktree(repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", str(worktree), "merged")
    (worktree / "README.md").write_text("stashed\n")
    git(worktree, "stash")

    result = run_tool(repo)

    assert result.returncode == 0, result.stderr
    assert "has uncommitted or stashed changes" in result.stdout
    assert worktree.exists()
    assert "merged" in git(repo, "branch", "--format=%(refname:short)").splitlines()


def test_keep_worktree_option_and_config(repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", str(worktree), "merged")
    git(repo, "config", "prune.worktrees", "false")

    result = run_tool(repo)

    assert result.returncode == 0, result.stderr
    assert f"Keeping branch merged: checked out in worktree {worktree}" in result.stdout
    assert worktree.exists()
    assert "merged" in git(repo, "branch", "--format=%(refname:short)").splitlines()

    result = run_tool(repo, "--keep-worktree")

    assert result.returncode == 0, result.stderr
    assert worktree.exists()


def test_dry_run_changes_nothing(repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", str(worktree), "merged")

    result = run_tool(repo, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert f"git worktree remove {worktree}" in result.stdout
    assert "git branch -D merged" in result.stdout
    assert worktree.exists()
    assert "merged" in git(repo, "branch", "--format=%(refname:short)").splitlines()


def test_branch_with_unique_content_is_kept(repo: Path) -> None:
    git(repo, "checkout", "-b", "unmerged")
    (repo / "unique.txt").write_text("unique\n")
    git(repo, "add", "unique.txt")
    git(repo, "commit", "-m", "unique work")
    git(repo, "checkout", "master")

    result = run_tool(repo)

    assert result.returncode == 0, result.stderr
    assert "unmerged" in git(repo, "branch", "--format=%(refname:short)").splitlines()
    assert "merged" not in git(repo, "branch", "--format=%(refname:short)").splitlines()


def test_current_branch_and_main_branches_are_kept(repo: Path) -> None:
    git(repo, "checkout", "merged")

    result = run_tool(repo)

    assert result.returncode == 0, result.stderr
    assert "merged" in git(repo, "branch", "--format=%(refname:short)").splitlines()
    assert "master" in git(repo, "branch", "--format=%(refname:short)").splitlines()


def test_unknown_argument_is_a_usage_error(repo: Path) -> None:
    result = run_tool(repo, "--nope")

    assert result.returncode == 2
    assert "Usage: git delete-no-content-branches" in result.stderr


def test_missing_worktree_directory_is_pruned(repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", str(worktree), "merged")
    shutil.rmtree(worktree)

    result = run_tool(repo)

    assert result.returncode == 0, result.stderr
    assert str(worktree) not in git(repo, "worktree", "list", "--porcelain")
    assert "merged" not in git(repo, "branch", "--format=%(refname:short)").splitlines()


def test_nested_branch_is_listed_once(repo: Path) -> None:
    tip = git(repo, "rev-parse", "origin/master")
    git(repo, "update-ref", "refs/heads/clones/oqa2/master", tip)
    git(repo, "update-ref", "refs/remotes/clones/oqa2/master", tip)

    result = run_tool(repo, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("git branch -D clones/oqa2/master") == 1
    assert "heads/clones" not in result.stdout


def test_nested_branch_is_deleted_without_breaking_the_run(repo: Path) -> None:
    tip = git(repo, "rev-parse", "origin/master")
    git(repo, "update-ref", "refs/heads/clones/oqa2/master", tip)
    git(repo, "update-ref", "refs/remotes/clones/oqa2/master", tip)

    result = run_tool(repo)

    assert result.returncode == 0, result.stderr
    heads = git(repo, "for-each-ref", "--format=%(refname)", "refs/heads").splitlines()
    assert "refs/heads/clones/oqa2/master" not in heads
    remotes = git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes").splitlines()
    assert "refs/remotes/clones/oqa2/master" in remotes
    assert "merged" not in heads
