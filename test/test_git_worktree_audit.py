"""tests for git-worktree-audit."""

import json
import subprocess
from pathlib import Path
from typing import Any

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


def audit(load_script, capsys, *args: str) -> tuple[int, str]:
    """Run the audit in-process and return the exit code with the text report."""
    module = load_script("git-worktree-audit")
    code = module.main(list(args))
    return code, capsys.readouterr().out


def audit_json(load_script, capsys, *args: str) -> tuple[int, dict[str, Any]]:
    """Run the audit with --json and return the exit code with the parsed report."""
    code, out = audit(load_script, capsys, "--json", *args)
    return code, json.loads(out)


def test_peer_branch_at_risk_blocks_the_gate(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    git(peer, "checkout", "-b", "feature/unique")
    commit(peer, "unique.txt", "unique\n")

    code, report = audit_json(load_script, capsys, "--primary", str(primary), str(peer))

    directory = report["directories"][0]
    assert code == 1
    assert directory["heads_at_risk"] == ["feature/unique"]
    assert directory["remote_refs_at_risk"] == []


def test_fetching_into_the_clones_namespace_clears_the_gate(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    git(peer, "checkout", "-b", "feature/unique")
    commit(peer, "unique.txt", "unique\n")
    git(primary, "fetch", "--no-tags", str(peer), "+refs/heads/*:refs/remotes/clones/peer/*")

    code, report = audit_json(load_script, capsys, "--primary", str(primary), str(peer))

    directory = report["directories"][0]
    assert code == 0
    assert directory["heads_at_risk"] == []
    assert directory["remote_refs_at_risk"] == []


def test_remote_tracking_refs_at_risk(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    git(peer, "checkout", "-b", "feature/unique")
    commit(peer, "unique.txt", "unique\n")
    git(peer, "update-ref", "refs/remotes/okurz/feature/unique", "HEAD")

    code, report = audit_json(load_script, capsys, "--primary", str(primary), str(peer))

    directory = report["directories"][0]
    assert code == 1
    assert directory["remote_refs_at_risk"] == ["okurz/feature/unique"]


def test_worktree_and_missing_path_are_reported(checkouts, load_script, capsys, tmp_path) -> None:
    primary, _ = checkouts
    worktree = tmp_path / "wt"
    git(primary, "worktree", "add", str(worktree), "-b", "wt-branch", "origin/master")
    missing = tmp_path / "gone"

    code, report = audit_json(
        load_script,
        capsys,
        "--primary",
        str(primary),
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

    code, report = audit_json(load_script, capsys, "--primary", str(primary), str(primary), str(plain))

    assert code == 0
    assert [d["kind"] for d in report["directories"]] == ["primary", "other"]
    assert report["base"] == "origin/master"


def test_dirty_checkout_counts(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    (peer / "README.md").write_text("modified\n")
    (peer / "untracked.txt").write_text("untracked\n")

    code, report = audit_json(load_script, capsys, "--primary", str(primary), str(peer))

    assert code == 0
    assert report["directories"][0]["dirty"] == {"staged": 0, "modified": 1, "untracked": 1, "stashes": 0}


def test_detached_head_is_reported_without_upstream(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    git(peer, "checkout", "--detach", "HEAD")

    code, report = audit_json(load_script, capsys, "--primary", str(primary), str(peer))

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

    code, report = audit_json(load_script, capsys, str(peer))

    assert code == 0
    assert report["primary"] == str(primary.resolve())


def test_outside_a_repository_without_primary_is_a_usage_error(load_script, capsys, monkeypatch, tmp_path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)

    code = load_script("git-worktree-audit").main([str(plain)])

    assert code == 2
    assert "not a git repository" in capsys.readouterr().err


def test_staged_change_counts_as_staged_only(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    (peer / "staged.txt").write_text("staged\n")
    git(peer, "add", "staged.txt")

    code, report = audit_json(load_script, capsys, "--primary", str(primary), str(peer))

    assert code == 0
    assert report["directories"][0]["dirty"] == {"staged": 1, "modified": 0, "untracked": 0, "stashes": 0}


def test_text_report_skips_a_missing_directory(checkouts, load_script, capsys, tmp_path) -> None:
    primary, _ = checkouts
    missing = tmp_path / "gone"

    code, text = audit(load_script, capsys, "--primary", str(primary), str(missing))

    assert code == 0
    assert f"{missing} (missing)" in text
    assert "head:" not in text


@pytest.mark.parametrize(
    ("output", "expected"),
    [("3\t4", {"behind": 3, "ahead": 4}), ("", {}), (None, {}), ("7", {})],
)
def test_parse_counts_reads_the_rev_list_pair(load_script, output, expected) -> None:
    assert load_script("git-worktree-audit").parse_counts(output) == expected


def test_base_defaults_to_the_remote_head_of_the_primary(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts

    code, report = audit_json(load_script, capsys, "--primary", str(primary), str(peer))

    assert code == 0
    assert report["base"] == "origin/master"


def test_base_defaults_to_origin_main_for_a_main_repository(tmp_path, load_script, capsys) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-b", "main")
    commit(seed, "README.md", "seed\n")
    primary = tmp_path / "primary"
    git(tmp_path, "clone", str(seed), str(primary))

    code, report = audit_json(load_script, capsys, "--primary", str(primary), str(primary))

    assert code == 0
    assert report["base"] == "origin/main"


def test_default_base_names_both_candidates_when_neither_resolves(tmp_path, load_script, capsys) -> None:
    repo = tmp_path / "lonely"
    repo.mkdir()
    git(repo, "init", "-b", "trunk")
    commit(repo, "README.md", "seed\n")

    code = load_script("git-worktree-audit").main(["--primary", str(repo), str(repo)])

    assert code == 2
    assert "Base ref 'origin/main or origin/master' cannot be resolved" in capsys.readouterr().err


def test_explicit_base_wins_over_the_remote_head(checkouts, load_script, capsys) -> None:
    primary, peer = checkouts
    git(primary, "branch", "release", "origin/master")

    code, report = audit_json(load_script, capsys, "--primary", str(primary), "--base", "release", str(peer))

    assert code == 0
    assert report["base"] == "release"
