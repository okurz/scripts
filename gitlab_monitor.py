#!/usr/bin/env python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Monitor GitLab CI jobs for specific log patterns."""

import asyncio

import httpx
import typer

app = typer.Typer(help="Monitor GitLab CI jobs for specific log patterns.", add_completion=False)

HTTP_OK = 200
FINISHED_STATUSES = frozenset({"success", "failed", "canceled"})


def print_match(job: dict[str, str | int]) -> None:
    """Print the job id, URL and status of a trace match."""
    typer.secho(f"[*] Match found in job {job['id']}:", fg=typer.colors.GREEN)
    typer.echo(f"    URL:    {job['web_url']}")
    typer.echo(f"    Status: {job['status']}")


async def fetch_jobs(client: httpx.AsyncClient, project_id: str) -> list[dict[str, str | int]]:
    """Fetch the recent jobs of a project through the GitLab API."""
    response = await client.get(f"/api/v4/projects/{project_id}/jobs")
    response.raise_for_status()
    return response.json()


async def scan_jobs(
    client: httpx.AsyncClient,
    project_id: str,
    jobs: list[dict[str, str | int]],
    job_name: str,
    search_term: str,
) -> bool:
    """Search the trace of every finished job with the requested name, return whether any matched."""
    found = False
    for job in jobs:
        if job["name"] != job_name or job["status"] not in FINISHED_STATUSES:
            continue
        trace_response = await client.get(f"/api/v4/projects/{project_id}/jobs/{job['id']}/trace")
        if trace_response.status_code == HTTP_OK and search_term in trace_response.text:
            print_match(job)
            found = True
    return found


async def check_gitlab_jobs(
    url: str,
    project: str,
    job_name: str,
    search_term: str,
    token: str | None,
) -> None:
    """Check GitLab jobs for a specific search term in their traces."""
    headers = {"PRIVATE-TOKEN": token} if token else {}
    # Project path needs to be URL-encoded (e.g., namespace/project -> namespace%2Fproject)
    project_id = project.replace("/", "%2F")

    async with httpx.AsyncClient(base_url=url, headers=headers, follow_redirects=True) as client:
        try:
            jobs = await fetch_jobs(client, project_id)
            found = await scan_jobs(client, project_id, jobs, job_name, search_term)
            if not found:
                typer.echo("No matching terms found in recent jobs.")
        except httpx.HTTPStatusError as e:
            typer.secho(f"Error fetching data from GitLab: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from e
        except Exception as e:
            typer.secho(f"An unexpected error occurred: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from e


@app.command()
def main(
    project: str = typer.Argument(
        "qa-maintenance/bot-ng",
        help="The full path of the project (e.g. namespace/repo)",
    ),
    job_name: str = typer.Option("approve increments", "--job", "-j", help="Name of the CI job to inspect"),
    search_term: str = typer.Option(
        "End of reasons for not approving",
        "--search",
        "-s",
        help="The string to search for in the logs",
    ),
    gitlab_url: str = typer.Option("https://gitlab.suse.de", "--url", "-u", help="Base URL of the GitLab instance"),
    token: str | None = typer.Option(
        None,
        "--token",
        "-t",
        envvar="GITLAB_TOKEN",
        help="GitLab API token (or set GITLAB_TOKEN env var)",
    ),
) -> None:
    """Monitor GitLab CI jobs and search logs for specific terms.

    Example:
    python gitlab_monitor.py qa-maintenance/bot-ng --job "approve increments" --search "End of reasons"

    """
    asyncio.run(check_gitlab_jobs(gitlab_url, project, job_name, search_term, token))


if __name__ == "__main__":
    app()
