"""tests for git-worktree-audit."""

import json
import subprocess
from pathlib import Path

import pytest

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


def commit(repo: Path, name: str, content: str) -> str:
    """Commit a new file in a repository and return the new commit hash."""
    (repo / name).write_text(content)
    git(repo, "add", name)
    git(repo, "commit", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def checkouts(tmp_path: Path) -> tuple[Path, Path]:
    """Return a primary checkout and a peer checkout cloned from the same seed."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-b", "master")
    commit(seed, "README.md", "seed\n")
    primary = tmp_path / "primary"
    peer = tmp_path / "peer"
    git(tmp_path, "clone", str(seed), str(primary))
    git(tmp_path, "clone", str(seed), str(peer))
    return primary, peer


def audit(load_script, capsys, *args: str) -> tuple[int, dict | str]:
    """Run the audit in-process and return exit code with parsed output."""
    module = load_script("git-worktree-audit")
    code = module.main(list(args))
    out = capsys.readouterr().out
    return code, json.loads(out) if "--json" in args else out


def test_peer_branch_at_risk_blocks_the_gate(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    git(peer, "checkout", "-b", "feature/unique")
    commit(peer, "unique.txt", "unique\n")

    code, report = audit(load_script, capsys, "--primary", str(primary), "--json", str(peer))

    directory = report["directories"][0]
    assert code == 1
    assert directory["heads_at_risk"] == ["feature/unique"]
    assert directory["remote_refs_at_risk"] == []


def test_fetching_into_the_clones_namespace_clears_the_gate(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    git(peer, "checkout", "-b", "feature/unique")
    commit(peer, "unique.txt", "unique\n")
    git(primary, "fetch", "--no-tags", str(peer), "+refs/heads/*:refs/remotes/clones/peer/*")

    code, report = audit(load_script, capsys, "--primary", str(primary), "--json", str(peer))

    directory = report["directories"][0]
    assert code == 0
    assert directory["heads_at_risk"] == []
    assert directory["remote_refs_at_risk"] == []


def test_remote_tracking_refs_at_risk(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    git(peer, "checkout", "-b", "feature/unique")
    commit(peer, "unique.txt", "unique\n")
    git(peer, "update-ref", "refs/remotes/okurz/feature/unique", "HEAD")

    code, report = audit(load_script, capsys, "--primary", str(primary), "--json", str(peer))

    directory = report["directories"][0]
    assert code == 1
    assert directory["remote_refs_at_risk"] == ["okurz/feature/unique"]


def test_worktree_and_missing_path_are_reported(checkouts, load_script, capsys, tmp_path) -> None:
    primary, _ = checkouts
    worktree = tmp_path / "wt"
    git(primary, "worktree", "add", str(worktree), "-b", "wt-branch", "origin/master")
    missing = tmp_path / "gone"

    code, report = audit(
        load_script,
        capsys,
        "--primary",
        str(primary),
        "--json",
        str(worktree),
        str(missing),
    )

    worktree_report, missing_report = report["directories"]
    assert code == 0
    assert worktree_report["kind"] == "worktree"
    assert worktree_report["head"] == "wt-branch"
    assert worktree_report["upstream"] == "origin/master"
    assert worktree_report["ahead"] == 0
    assert worktree_report["behind"] == 0
    assert worktree_report["dirty"] == {"staged": 0, "modified": 0, "untracked": 0, "stashes": 0}
    assert missing_report == {"path": str(missing), "kind": "missing"}


def test_primary_and_other_directory_kinds(checkouts, load_script, capsys, tmp_path) -> None:
    primary, _ = checkouts
    plain = tmp_path / "plain"
    plain.mkdir()

    code, report = audit(load_script, capsys, "--primary", str(primary), "--json", str(primary), str(plain))

    assert code == 0
    assert [d["kind"] for d in report["directories"]] == ["primary", "other"]
    assert report["base"] == "origin/master"


def test_dirty_checkout_counts(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    (peer / "README.md").write_text("modified\n")
    (peer / "untracked.txt").write_text("untracked\n")

    code, report = audit(load_script, capsys, "--primary", str(primary), "--json", str(peer))

    assert code == 0
    assert report["directories"][0]["dirty"] == {"staged": 0, "modified": 1, "untracked": 1, "stashes": 0}


def test_detached_head_is_reported_without_upstream(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    git(peer, "checkout", "--detach", "HEAD")

    code, report = audit(load_script, capsys, "--primary", str(primary), "--json", str(peer))

    directory = report["directories"][0]
    assert code == 0
    assert directory["head"] == "detached"
    assert directory["upstream"] is None
    assert directory["ahead"] is None


def test_text_report_lists_risk_counts(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    git(peer, "checkout", "-b", "feature/unique")
    commit(peer, "unique.txt", "unique\n")

    code, text = audit(load_script, capsys, "--primary", str(primary), str(peer))

    assert code == 1
    assert f"primary: {primary}" in text
    assert "base: origin/master" in text
    assert "heads_at_risk: 1" in text
    assert "remote_refs_at_risk: 0" in text


def test_unresolvable_base_ref_is_a_usage_error(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts

    code = load_script("git-worktree-audit").main(["--primary", str(primary), "--base", "nope", str(peer)])

    assert code == 2
    assert "cannot be resolved" in capsys.readouterr().err


def test_primary_defaults_to_the_current_repository(checkouts, load_script, capsys, monkeypatch) -> None:
    primary, peer = checkouts
    monkeypatch.chdir(primary)

    code, report = audit(load_script, capsys, "--json", str(peer))

    assert code == 0
    assert report["primary"] == str(primary.resolve())


def test_outside_a_repository_without_primary_is_a_usage_error(load_script, capsys, monkeypatch, tmp_path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)

    code = load_script("git-worktree-audit").main([str(plain)])

    assert code == 2
    assert "not a git repository" in capsys.readouterr().err
