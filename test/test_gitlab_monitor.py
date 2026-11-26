"""Tests for gitlab_monitor: job listing, trace scanning and the CLI entry point."""

import asyncio

import httpx
import pytest
from typer.testing import CliRunner

PROJECT_ID = "qa-maintenance/bot-ng"
JOBS = [
    {"id": 1, "name": "approve increments", "status": "success", "web_url": "https://gitlab/jobs/1"},
    {"id": 2, "name": "approve increments", "status": "running", "web_url": "https://gitlab/jobs/2"},
    {"id": 3, "name": "other job", "status": "failed", "web_url": "https://gitlab/jobs/3"},
]


@pytest.fixture
def sut(load_script):
    return load_script("gitlab_monitor.py")


def test_fetch_jobs_returns_the_job_list(sut, fake_httpx):
    fake_httpx.on(f"/api/v4/projects/{PROJECT_ID}/jobs", json_body=JOBS)

    jobs = asyncio.run(sut.fetch_jobs(httpx.AsyncClient(base_url="https://gitlab.suse.de"), PROJECT_ID))

    assert jobs == JOBS


def test_scan_jobs_prints_the_matching_finished_job(sut, fake_httpx, capsys):
    fake_httpx.on(f"/api/v4/projects/{PROJECT_ID}/jobs/1/trace", text="line\nEnd of reasons for not approving\n")

    found = asyncio.run(
        sut.scan_jobs(
            httpx.AsyncClient(base_url="https://gitlab.suse.de"),
            PROJECT_ID,
            JOBS,
            "approve increments",
            "End of reasons for not approving",
        )
    )

    assert found is True
    out = capsys.readouterr().out
    assert "Match found in job 1" in out
    assert "https://gitlab/jobs/1" in out


def test_scan_jobs_skips_unfinished_and_unrelated_jobs(sut, fake_httpx):
    found = asyncio.run(
        sut.scan_jobs(httpx.AsyncClient(base_url="https://gitlab.suse.de"), PROJECT_ID, JOBS, "no such job", "needle")
    )

    assert found is False
    assert fake_httpx.paths() == []


def test_scan_jobs_does_not_request_the_trace_of_a_running_job(sut, fake_httpx):
    found = asyncio.run(
        sut.scan_jobs(
            httpx.AsyncClient(base_url="https://gitlab.suse.de"), PROJECT_ID, JOBS[1:2], "approve increments", "x"
        )
    )

    assert found is False
    assert fake_httpx.paths() == []


def test_scan_jobs_ignores_a_trace_that_is_not_ok(sut, fake_httpx, capsys):
    fake_httpx.on(f"/api/v4/projects/{PROJECT_ID}/jobs/1/trace", text="needle", status_code=404)

    assert (
        asyncio.run(
            sut.scan_jobs(
                httpx.AsyncClient(base_url="https://gitlab.suse.de"), PROJECT_ID, JOBS, "approve increments", "needle"
            )
        )
        is False
    )
    assert not capsys.readouterr().out


def test_check_gitlab_jobs_reports_when_nothing_matched(sut, fake_httpx, capsys):
    fake_httpx.on(f"/api/v4/projects/{PROJECT_ID}/jobs", json_body=[])

    asyncio.run(
        sut.check_gitlab_jobs("https://gitlab.suse.de", "qa-maintenance/bot-ng", "approve increments", "x", None)
    )

    assert fake_httpx.paths() == [f"/api/v4/projects/{PROJECT_ID}/jobs"]
    assert "No matching terms found in recent jobs." in capsys.readouterr().out


def test_check_gitlab_jobs_sends_the_token_and_follows_redirects(sut, fake_httpx):
    fake_httpx.on(f"/api/v4/projects/{PROJECT_ID}/jobs", json_body=[])

    asyncio.run(sut.check_gitlab_jobs("https://gitlab.suse.de", "qa-maintenance/bot-ng", "job", "x", "tok"))

    request = fake_httpx.requests[0]
    assert request.headers["PRIVATE-TOKEN"] == "tok"
    assert fake_httpx.raw_paths() == ["/api/v4/projects/qa-maintenance%2Fbot-ng/jobs"]


def test_check_gitlab_jobs_exits_one_on_an_http_error(sut, fake_httpx, capsys):
    fake_httpx.on(f"/api/v4/projects/{PROJECT_ID}/jobs", json_body={"message": "401"}, status_code=401)

    with pytest.raises(sut.typer.Exit) as excinfo:
        asyncio.run(sut.check_gitlab_jobs("https://gitlab.suse.de", "qa-maintenance/bot-ng", "job", "x", None))

    assert excinfo.value.exit_code == 1
    assert "Error fetching data from GitLab" in capsys.readouterr().err


def test_check_gitlab_jobs_exits_one_on_an_unexpected_error(sut, fake_httpx, capsys):
    fake_httpx.on(f"/api/v4/projects/{PROJECT_ID}/jobs", json_body="not a list")

    with pytest.raises(sut.typer.Exit) as excinfo:
        asyncio.run(sut.check_gitlab_jobs("https://gitlab.suse.de", "qa-maintenance/bot-ng", "job", "x", None))

    assert excinfo.value.exit_code == 1
    assert "An unexpected error occurred" in capsys.readouterr().err


def test_cli_runs_the_check_with_the_parsed_options(sut, mocker):
    checks: list[tuple[str, ...]] = []
    mocker.patch.object(sut, "check_gitlab_jobs", lambda *args: checks.append(args))
    ran = mocker.patch.object(sut.asyncio, "run")

    result = CliRunner().invoke(sut.app, ["qa-maintenance/bot-ng", "--job", "j", "--search", "s", "--token", "t"])

    assert result.exit_code == 0
    assert checks == [("https://gitlab.suse.de", "qa-maintenance/bot-ng", "j", "s", "t")]
    ran.assert_called_once_with(None)


def test_check_gitlab_jobs_prints_a_match(sut, fake_httpx, capsys):
    fake_httpx.on(f"/api/v4/projects/{PROJECT_ID}/jobs", json_body=JOBS[:1])
    fake_httpx.on(f"/api/v4/projects/{PROJECT_ID}/jobs/1/trace", text="End of reasons for not approving")

    asyncio.run(
        sut.check_gitlab_jobs(
            "https://gitlab.suse.de", "qa-maintenance/bot-ng", "approve increments", "End of reasons", None
        )
    )

    out = capsys.readouterr().out
    assert "Match found in job 1" in out
    assert "No matching terms found" not in out
