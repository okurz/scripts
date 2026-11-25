"""tests for the post-checkout hook that links shared paths into a worktree."""

import subprocess
from pathlib import Path

ROOTPATH = Path(__file__).resolve().parent.parent

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


def worktree_add(cwd: Path, path: Path, branch: str) -> subprocess.CompletedProcess[str]:
    """Add a worktree and return the completed process including hook output."""
    return subprocess.run(
        ["git", *COMMIT_CONFIG, "worktree", "add", str(path), "-b", branch],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def repo_with_hook(tmp_path: Path) -> Path:
    """Return a repository that uses the repository's hooks directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "master")
    (repo / "README.md").write_text("seed\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "seed")
    git(repo, "config", "core.hooksPath", str(ROOTPATH / "git-hooks"))
    return repo


def test_worktree_gets_the_configured_symlink(tmp_path: Path) -> None:
    repo = repo_with_hook(tmp_path)
    shared = tmp_path / "shared-plans"
    shared.mkdir()
    git(repo, "config", "--add", "worktree.symlink", f"tasks={shared}")
    worktree = tmp_path / "wt"

    result = worktree_add(repo, worktree, "wt-branch")

    link = worktree / "tasks"
    assert link.is_symlink()
    assert link.readlink() == shared
    assert f"linked tasks -> {shared}" in result.stderr


def test_primary_checkout_keeps_its_real_directory(tmp_path: Path) -> None:
    repo = repo_with_hook(tmp_path)
    shared = tmp_path / "shared-plans"
    shared.mkdir()
    git(repo, "config", "--add", "worktree.symlink", f"tasks={shared}")
    (repo / "tasks").mkdir()
    (repo / "tasks" / "plan.md").write_text("plan\n")

    git(repo, "checkout", "-b", "topic")

    assert not (repo / "tasks").is_symlink()
    assert (repo / "tasks" / "plan.md").read_text() == "plan\n"


def test_existing_link_is_not_replaced(tmp_path: Path) -> None:
    repo = repo_with_hook(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    git(repo, "config", "--add", "worktree.symlink", f"tasks={first}")
    worktree = tmp_path / "wt"
    worktree_add(repo, worktree, "wt-branch")

    git(repo, "config", "--replace-all", "worktree.symlink", f"tasks={second}")
    git(worktree, "checkout", "-b", "another")

    assert (worktree / "tasks").readlink() == first


def test_multiple_entries_are_linked(tmp_path: Path) -> None:
    repo = repo_with_hook(tmp_path)
    plans = tmp_path / "plans"
    cache = tmp_path / "cache"
    plans.mkdir()
    cache.mkdir()
    git(repo, "config", "--add", "worktree.symlink", f"tasks={plans}")
    git(repo, "config", "--add", "worktree.symlink", f"local/cache={cache}")
    worktree = tmp_path / "wt"

    worktree_add(repo, worktree, "wt-branch")

    assert (worktree / "tasks").readlink() == plans
    assert (worktree / "local/cache").readlink() == cache


def test_setup_command_is_printed_but_not_run(tmp_path: Path) -> None:
    repo = repo_with_hook(tmp_path)
    shared = tmp_path / "shared-plans"
    shared.mkdir()
    marker = tmp_path / "ran"
    git(repo, "config", "--add", "worktree.symlink", f"tasks={shared}")
    git(repo, "config", "worktree.setup", f"touch {marker}")
    worktree = tmp_path / "wt"

    result = worktree_add(repo, worktree, "wt-branch")

    assert f"next: touch {marker} (in {worktree})" in result.stderr
    assert not marker.exists()


def test_unconfigured_repository_is_untouched(tmp_path: Path) -> None:
    repo = repo_with_hook(tmp_path)
    worktree = tmp_path / "wt"

    result = worktree_add(repo, worktree, "wt-branch")

    assert not (worktree / "tasks").exists()
    assert "linked" not in result.stderr


def test_hook_ignores_file_checkouts(tmp_path: Path) -> None:
    repo = repo_with_hook(tmp_path)
    shared = tmp_path / "shared-plans"
    shared.mkdir()
    git(repo, "config", "--add", "worktree.symlink", f"tasks={shared}")
    (repo / "tasks").mkdir()

    result = subprocess.run(
        ["git", *COMMIT_CONFIG, "checkout", "--", "README.md"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )

    assert "linked" not in result.stderr
    assert not (repo / "tasks").is_symlink()
