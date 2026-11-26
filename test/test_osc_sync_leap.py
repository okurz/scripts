"""Tests for osc-sync-leap: the dry-run canned output, the git workflow and the tea PR call."""

import pytest
from typer.testing import CliRunner

UPSTREAM_URL = "gitea@src.opensuse.org:pool/generic-package.git"
PLAIN_URL = "https://src.opensuse.org/pool/generic-package"


@pytest.fixture
def sut(load_script):
    return load_script("osc-sync-leap")


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        (["git", "rev-parse", "--show-toplevel"], "dryrunhash"),
        (["git", "remote", "get-url", "origin"], "gitea@src.opensuse.org:pool/generic-package.git"),
        (["git", "ls-tree", "--name-only", "HEAD"], "file1\nfile2"),
        (["git", "status"], None),
    ],
)
def test_canned_output_answers_the_known_git_queries(sut, cmd, expected):
    assert sut.canned_output(cmd) == expected


def test_run_command_prints_the_dry_run_command(sut, capsys):
    sut.run_command(["git", "commit", "-m", "msg"], dry_run=True)

    assert capsys.readouterr().out.strip() == "[DRY-RUN] git commit -m msg"


def test_run_command_returns_the_canned_output_when_capturing(sut):
    assert sut.run_command(["git", "rev-parse", "--show-toplevel"], capture_output=True, dry_run=True) == "dryrunhash"


def test_run_command_prints_when_no_canned_output_exists(sut, capsys):
    sut.run_command(["git", "push", "origin", "branch"], capture_output=True, dry_run=True)

    assert capsys.readouterr().out.strip() == "[DRY-RUN] git push origin branch"


def test_run_command_returns_the_stripped_stdout(sut, fake_subprocess):
    fake_subprocess.on(["git", "rev-parse"], stdout=" abc123 \n")

    assert sut.run_command(["git", "rev-parse", "HEAD"], capture_output=True) == "abc123"


def test_run_command_without_capture_returns_empty(sut, fake_subprocess):
    fake_subprocess.on(["git", "checkout"])

    assert not sut.run_command(["git", "checkout", "branch"])
    assert fake_subprocess.commands(["git", "checkout"]) == [["git", "checkout", "branch"]]


def test_sync_dry_run_walks_the_whole_workflow(sut):
    result = CliRunner().invoke(sut.app, ["--branch", "leap-16.0", "--dry-run"])

    assert result.exit_code == 0
    assert "Package: dryrunhash" in result.output
    assert "Factory hash: dryrunhash" in result.output
    assert "--- Syncing leap-16.0 ---" in result.output
    assert "[DRY-RUN] git rm file1 file2" in result.output
    assert "[DRY-RUN] git commit -m dryrunhash: Update to factory at dryrunhash" in result.output
    assert "[DRY-RUN] tea pr create --repo pool/generic-package" in result.output
    assert "--description Automated sync of dryrunhash from factory at dryrunhash" in result.output


def test_sync_runs_the_git_workflow(sut, fake_subprocess, monkeypatch, tmp_path):
    repo = tmp_path / "generic-package"
    repo.mkdir()
    (repo / "generic-package.spec").write_text("Name: generic-package\n")
    monkeypatch.chdir(repo)
    fake_subprocess.on(["git", "rev-parse", "--show-toplevel"], stdout=f"{repo}\n")
    fake_subprocess.on(["git", "rev-parse", "--short", "origin/factory"], stdout="abc1234\n")
    fake_subprocess.on(["git", "ls-tree"], stdout="generic-package.spec\nsubdir\n")
    fake_subprocess.on(["git", "remote", "get-url"], stdout=f"{UPSTREAM_URL}\n")
    fake_subprocess.on(["git"])
    fake_subprocess.on(["tea"])

    result = CliRunner().invoke(sut.app, ["--branch", "leap-16.0", "--remote", "me"])

    assert result.exit_code == 0, result.output
    assert "Package: generic-package" in result.output
    assert "Factory hash: abc1234" in result.output
    commands = fake_subprocess.calls
    assert ["git", "checkout", "-B", "leap-16.0-sync-abc1234", "origin/leap-16.0"] in commands
    assert ["git", "rm", "generic-package.spec"] in commands
    assert ["git", "commit", "-m", "generic-package: Update to factory at abc1234"] in commands
    assert ["git", "push", "-f", "me", "leap-16.0-sync-abc1234:leap-16.0-sync-abc1234"] in commands
    tea = next(cmd for cmd in commands if cmd[0] == "tea")
    assert tea[tea.index("--repo") + 1] == "pool/generic-package"
    assert tea[tea.index("--head") + 1] == "me:leap-16.0-sync-abc1234"


def test_sync_skips_the_removal_when_no_tracked_file_is_present(sut, fake_subprocess, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_subprocess.on(["git", "rev-parse", "--show-toplevel"], stdout=f"{tmp_path}\n")
    fake_subprocess.on(["git", "rev-parse", "--short"], stdout="abc1234\n")
    fake_subprocess.on(["git", "ls-tree"], stdout="")
    fake_subprocess.on(["git", "remote", "get-url"], stdout=f"{UPSTREAM_URL}\n")
    fake_subprocess.on(["git"])
    fake_subprocess.on(["tea"])

    assert CliRunner().invoke(sut.app, ["--branch", "leap-16.0"]).exit_code == 0
    assert not [cmd for cmd in fake_subprocess.calls if cmd[:3] == ["git", "rm", *cmd[2:3]]]


def test_sync_falls_back_to_the_local_factory_ref(sut, fake_subprocess, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_subprocess.on(["git", "rev-parse", "--show-toplevel"], stdout=f"{tmp_path}\n")
    fake_subprocess.on(["git", "rev-parse", "--short", "origin/factory"], stderr="unknown revision", returncode=128)
    fake_subprocess.on(["git", "rev-parse", "--short", "factory"], stdout="9999999\n")
    fake_subprocess.on(["git", "ls-tree"], stdout="")
    fake_subprocess.on(["git", "remote", "get-url"], stdout=f"{UPSTREAM_URL}\n")
    fake_subprocess.on(["git"])
    fake_subprocess.on(["tea"])

    result = CliRunner().invoke(sut.app, ["--branch", "leap-16.0"])

    assert result.exit_code == 0
    assert "Factory hash: 9999999" in result.output
    assert ["git", "rev-parse", "--short", "factory"] in fake_subprocess.calls


def test_sync_derives_the_repo_path_from_a_plain_url(sut, fake_subprocess, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_subprocess.on(["git", "rev-parse", "--show-toplevel"], stdout=f"{tmp_path}\n")
    fake_subprocess.on(["git", "rev-parse", "--short"], stdout="abc1234\n")
    fake_subprocess.on(["git", "ls-tree"], stdout="")
    fake_subprocess.on(["git", "remote", "get-url"], stdout=f"{PLAIN_URL}\n")
    fake_subprocess.on(["git"])
    fake_subprocess.on(["tea"])

    CliRunner().invoke(sut.app, ["--branch", "leap-16.0"])

    tea = next(cmd for cmd in fake_subprocess.calls if cmd[0] == "tea")
    assert tea[tea.index("--repo") + 1] == "pool/generic-package"
