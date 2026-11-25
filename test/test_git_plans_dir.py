"""tests for git-plans-dir."""

import subprocess
from pathlib import Path

GIT_CONFIG = [
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
        ["git", *GIT_CONFIG, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def run_plans_dir(load_script, capsys, cwd: Path, monkeypatch) -> tuple[int, str, str]:
    """Run the command in-process from the given directory."""
    monkeypatch.chdir(cwd)
    code = load_script("git-plans-dir").main([])
    captured = capsys.readouterr()
    return code, captured.out.strip(), captured.err.strip()


def test_primary_checkout_reports_its_tasks_directory(load_script, capsys, monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "master")

    code, out, _ = run_plans_dir(load_script, capsys, repo, monkeypatch)

    assert code == 0
    assert out == str(repo / "tasks")


def test_worktree_reports_the_primary_checkout_tasks_directory(
    load_script, capsys, monkeypatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "master")
    (repo / "README.md").write_text("seed\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "seed")
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", str(worktree), "-b", "wt-branch")

    code, out, _ = run_plans_dir(load_script, capsys, worktree, monkeypatch)

    assert code == 0
    assert out == str(repo / "tasks")


def test_plans_dir_config_overrides_the_default(load_script, capsys, monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "master")
    override = tmp_path / "plans"
    git(repo, "config", "plans.dir", str(override))

    code, out, _ = run_plans_dir(load_script, capsys, repo, monkeypatch)

    assert code == 0
    assert out == str(override)


def test_outside_a_repository_fails(load_script, capsys, monkeypatch, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    code, out, err = run_plans_dir(load_script, capsys, plain, monkeypatch)

    assert code == 1
    assert not out
    assert err == "not inside a git repository"
