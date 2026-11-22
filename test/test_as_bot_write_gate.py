"""Tests for the gh-as-bot and glab-as-bot write gate."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

GH_READS = [
    ["api", "user", "--jq", ".login"],
    ["pr", "view", "1", "--json", "title"],
    ["pr", "list", "-R", "os-autoinst/openQA", "--json", "number"],
    ["pr", "comment", "list", "1"],
    ["pr", "review", "list", "1"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "--jq", ".[-1].state"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "-X", "GET", "-f", "per_page=100"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "-XGET"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "--method", "GET"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "--method=GET"],
    ["api", "graphql", "-f", "query=query { viewer { login } }"],
    ["api", "graphql", "--field", "query=query { viewer { login } }"],
    ["search", "prs", "--owner", "os-autoinst", "--json", "number"],
]

GH_WRITES = [
    ["pr", "review", "1", "--approve", "--body", "x"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "-X", "POST", "-f", "event=APPROVE"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "-f", "event=APPROVE"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "--raw-field", "body=x"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "-F", "body=x"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "-fbody=x"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "-XPOST"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "--method=POST"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "-X", "DELETE"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "--input", "body.json"],
    ["api", "repos/os-autoinst/openQA/pulls/1/reviews", "--form", "file=@x"],
    ["api", "graphql", "-f", "query=mutation { addComment(input:{}) { clientMutationId } }"],
    ["api", "graphql", "--input", "mutation.json"],
    ["api", "graphql", "-f", "query=@mutation.graphql"],
    ["api", "graphql", "-f", "query=-"],
    ["pr", "comment", "1", "-b", "x"],
    ["pr", "merge", "1"],
]

GLAB_READS = [
    ["api", "user"],
    ["mr", "view", "1"],
    ["mr", "diff", "1"],
    ["mr", "note", "list", "1"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "-X", "GET"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "-X", "GET", "-f", "per_page=100"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "-XGET"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "--method", "GET"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "--method=GET"],
    ["api", "graphql", "-f", "query=query { currentUser { username } }"],
]

GLAB_WRITES = [
    ["mr", "approve", "1"],
    ["mr", "note", "create", "1", "-m", "x"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests/1/approve", "-X", "POST"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "-f", "title=x"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "--raw-field", "title=x"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "--field", "title=x"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "-XPOST"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "--method=POST"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "--input", "body.json"],
    ["api", "projects/openqa%2Fsalt-states-openqa/merge_requests", "--form", "file=@x"],
    ["api", "graphql", "-f", "query=mutation { addNote(input:{}) { clientMutationId } }"],
    ["api", "graphql", "-f", "query=@mutation.graphql"],
]


@pytest.fixture
def fake_forge(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("gh", "glab"):
        script = bindir / name
        script.write_text('#!/bin/sh\necho "FAKE-EXECUTED $*"\n')
        script.chmod(0o755)
    conf = tmp_path / "config" / "review-assistant"
    conf.mkdir(parents=True)
    (conf / "write.env").write_text("REVIEW_ASSISTANT_GH_TOKEN=fake\n")
    (conf / "write-classic-public_repo.env").write_text("REVIEW_ASSISTANT_GH_TOKEN=fake\n")
    (conf / "gitlab-suse-de.env").write_text("REVIEW_ASSISTANT_GITLAB_TOKEN=fake\n")
    return tmp_path


def runner_env(tmp_path, post):
    env = dict(os.environ)
    env["PATH"] = str(tmp_path / "bin") + os.pathsep + env["PATH"]
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env.pop("REVIEW_BOT_POST", None)
    if post:
        env["REVIEW_BOT_POST"] = "1"
    return env


def run_wrapper(tool, args, tmp_path, post):
    return subprocess.run(
        [str(ROOT / tool), *args],
        cwd=str(tmp_path),
        env=runner_env(tmp_path, post),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("args", GH_READS)
def test_gh_read_passes_without_post(args, fake_forge):
    res = run_wrapper("gh-as-bot", args, fake_forge, post=False)
    assert res.returncode == 0
    assert "FAKE-EXECUTED" in res.stdout


@pytest.mark.parametrize("args", GH_WRITES)
def test_gh_write_refused_without_post(args, fake_forge):
    res = run_wrapper("gh-as-bot", args, fake_forge, post=False)
    assert res.returncode != 0
    assert "REVIEW_BOT_POST=1" in res.stderr
    assert "FAKE-EXECUTED" not in res.stdout


@pytest.mark.parametrize("args", GH_WRITES + GH_READS)
def test_gh_every_call_passes_with_post(args, fake_forge):
    res = run_wrapper("gh-as-bot", args, fake_forge, post=True)
    assert res.returncode == 0
    assert "FAKE-EXECUTED" in res.stdout


@pytest.mark.parametrize("args", GLAB_READS)
def test_glab_read_passes_without_post(args, fake_forge):
    res = run_wrapper("glab-as-bot", args, fake_forge, post=False)
    assert res.returncode == 0
    assert "FAKE-EXECUTED" in res.stdout


@pytest.mark.parametrize("args", GLAB_WRITES)
def test_glab_write_refused_without_post(args, fake_forge):
    res = run_wrapper("glab-as-bot", args, fake_forge, post=False)
    assert res.returncode != 0
    assert "REVIEW_BOT_POST=1" in res.stderr
    assert "FAKE-EXECUTED" not in res.stdout


@pytest.mark.parametrize("args", GLAB_WRITES + GLAB_READS)
def test_glab_every_call_passes_with_post(args, fake_forge):
    res = run_wrapper("glab-as-bot", args, fake_forge, post=True)
    assert res.returncode == 0
    assert "FAKE-EXECUTED" in res.stdout
