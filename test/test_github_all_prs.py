"""Tests for github-all-prs: date parsing and the review-request filters."""

import json

import pytest
from typer.testing import CliRunner


@pytest.fixture
def sut(load_script):
    return load_script("github-all-prs")


def test_parse_date(sut):
    assert sut.parse_date("").timestamp() == 0
    assert sut.parse_date("2026-09-28T08:00:00").tzinfo is not None


@pytest.mark.parametrize(
    ("desc", "pr", "me", "expected"),
    [
        (
            "non-changes-requested reviewDecision returns false",
            {"reviewDecision": "APPROVED", "latestReviews": []},
            "okurz",
            False,
        ),
        (
            "changes requested reviewDecision but no changes requested in latest reviews returns false",
            {
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [{"state": "APPROVED"}],
            },
            "okurz",
            False,
        ),
        (
            "changes requested review without submittedAt or updatedAt returns true",
            {
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [{"state": "CHANGES_REQUESTED"}],
            },
            "okurz",
            True,
        ),
        (
            "changes requested without answering comments or commits returns true",
            {
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [
                    {
                        "state": "CHANGES_REQUESTED",
                        "submittedAt": "2026-09-28T08:00:00Z",
                    }
                ],
                "comments": [],
                "commits": [{"committedDate": "2026-09-27T08:00:00Z"}],
                "reviews": [],
            },
            "okurz",
            True,
        ),
        (
            "changes requested answered by author comment after submittedAt returns false",
            {
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [
                    {
                        "state": "CHANGES_REQUESTED",
                        "submittedAt": "2026-09-28T08:00:00Z",
                    }
                ],
                "comments": [{"author": {"login": "okurz"}, "createdAt": "2026-10-11T12:00:00Z"}],
                "commits": [],
                "reviews": [],
            },
            "okurz",
            False,
        ),
        (
            "changes requested with non-author comment after submittedAt remains unanswered",
            {
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [
                    {
                        "state": "CHANGES_REQUESTED",
                        "submittedAt": "2026-09-28T08:00:00Z",
                    }
                ],
                "comments": [
                    {
                        "author": {"login": "codecov"},
                        "createdAt": "2026-10-11T12:00:00Z",
                    }
                ],
                "commits": [],
                "reviews": [],
            },
            "okurz",
            True,
        ),
        (
            "changes requested answered by author review after submittedAt returns false",
            {
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [
                    {
                        "state": "CHANGES_REQUESTED",
                        "submittedAt": "2026-09-28T08:00:00Z",
                    }
                ],
                "comments": [],
                "commits": [],
                "reviews": [
                    {
                        "author": {"login": "okurz"},
                        "submittedAt": "2026-10-11T12:00:00Z",
                    }
                ],
            },
            "okurz",
            False,
        ),
        (
            "changes requested answered by commit after submittedAt returns false",
            {
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [
                    {
                        "state": "CHANGES_REQUESTED",
                        "submittedAt": "2026-09-28T08:00:00Z",
                    }
                ],
                "comments": [],
                "commits": [{"committedDate": "2026-10-11T12:00:00Z"}],
                "reviews": [],
            },
            "okurz",
            False,
        ),
    ],
)
def test_has_unanswered_changes_requested(sut, desc, pr, me, expected):
    assert sut.has_unanswered_changes_requested(pr, me) is expected, desc


@pytest.mark.parametrize(
    ("desc", "pr", "me", "expected"),
    [
        (
            "ready for review when no changes requested and checks pass",
            {
                "url": "https://github.com/foo/bar/pull/1",
                "title": "feat: test",
                "reviewDecision": "REVIEW_REQUIRED",
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            },
            "okurz",
            "* https://github.com/foo/bar/pull/1 feat: test",
        ),
        (
            "ready for review when changes requested was answered and checks pass",
            {
                "url": "https://github.com/foo/bar/pull/1",
                "title": "feat: test",
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [
                    {
                        "state": "CHANGES_REQUESTED",
                        "submittedAt": "2026-09-28T08:00:00Z",
                    }
                ],
                "comments": [{"author": {"login": "okurz"}, "createdAt": "2026-10-11T12:00:00Z"}],
                "commits": [],
                "reviews": [],
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            },
            "okurz",
            "* https://github.com/foo/bar/pull/1 feat: test",
        ),
        (
            "not ready for review when changes requested is unanswered",
            {
                "url": "https://github.com/foo/bar/pull/1",
                "title": "feat: test",
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [
                    {
                        "state": "CHANGES_REQUESTED",
                        "submittedAt": "2026-09-28T08:00:00Z",
                    }
                ],
                "comments": [],
                "commits": [],
                "reviews": [],
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            },
            "okurz",
            None,
        ),
        (
            "not ready for review when status checks failed",
            {
                "url": "https://github.com/foo/bar/pull/1",
                "title": "feat: test",
                "reviewDecision": "REVIEW_REQUIRED",
                "statusCheckRollup": [{"conclusion": "FAILURE"}],
            },
            "okurz",
            None,
        ),
    ],
)
def test_needs_review_filter(sut, desc, pr, me, expected):
    assert sut.needs_review_filter(pr, me) == expected, desc


@pytest.mark.parametrize(
    ("desc", "pr", "me", "expected"),
    [
        (
            "no work needed when checks pass and changes requested was answered",
            {
                "url": "https://github.com/foo/bar/pull/1",
                "title": "feat: test",
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [
                    {
                        "state": "CHANGES_REQUESTED",
                        "submittedAt": "2026-09-28T08:00:00Z",
                    }
                ],
                "comments": [{"author": {"login": "okurz"}, "createdAt": "2026-10-11T12:00:00Z"}],
                "commits": [],
                "reviews": [],
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            },
            "okurz",
            None,
        ),
        (
            "work needed due to unanswered changes requested",
            {
                "url": "https://github.com/foo/bar/pull/1",
                "title": "feat: test",
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [
                    {
                        "state": "CHANGES_REQUESTED",
                        "submittedAt": "2026-09-28T08:00:00Z",
                    }
                ],
                "comments": [],
                "commits": [],
                "reviews": [],
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            },
            "okurz",
            "* https://github.com/foo/bar/pull/1 feat: test (Changes requested)",
        ),
        (
            "work needed due to failing CI",
            {
                "url": "https://github.com/foo/bar/pull/1",
                "title": "feat: test",
                "reviewDecision": "REVIEW_REQUIRED",
                "statusCheckRollup": [{"conclusion": "FAILURE"}],
            },
            "okurz",
            "* https://github.com/foo/bar/pull/1 feat: test (CI failing)",
        ),
        (
            "work needed due to both failing CI and unanswered changes requested",
            {
                "url": "https://github.com/foo/bar/pull/1",
                "title": "feat: test",
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [
                    {
                        "state": "CHANGES_REQUESTED",
                        "submittedAt": "2026-09-28T08:00:00Z",
                    }
                ],
                "comments": [],
                "commits": [],
                "reviews": [],
                "statusCheckRollup": [{"conclusion": "FAILURE"}],
            },
            "okurz",
            "* https://github.com/foo/bar/pull/1 feat: test (CI failing, Changes requested)",
        ),
    ],
)
def test_needs_work_filter(sut, desc, pr, me, expected):
    assert sut.needs_work_filter(pr, me) == expected, desc


@pytest.fixture
def fake_gh(fake_subprocess):
    fake_subprocess.on(["gh", "api"], stdout="alice\n")
    return fake_subprocess


PR_DETAILS = {
    "url": "https://github.com/org/repo/pull/1",
    "title": "Fix the thing",
    "statusCheckRollup": [],
    "reviewDecision": "APPROVED",
    "latestReviews": [],
}


def test_run_gh_returns_the_stripped_stdout(sut, fake_subprocess):
    fake_subprocess.on(["gh"], stdout="alice\n")

    assert sut.run_gh(["api", "user"]) == "alice"


def test_run_gh_returns_none_when_gh_fails(sut, fake_subprocess):
    fake_subprocess.on(["gh"], stderr="boom", returncode=1)

    assert sut.run_gh(["api", "user"]) is None


def test_get_me_returns_the_login(sut, fake_gh):
    assert sut.get_me() == "alice"
    assert fake_gh.commands(["gh", "api"]) == [["gh", "api", "user", "--jq", ".login"]]


def test_get_me_falls_back_to_me_when_gh_fails(sut, fake_subprocess):
    fake_subprocess.on(["gh"], returncode=1)

    assert sut.get_me() == "@me"


def test_get_pr_details_parses_the_json_output(sut, fake_subprocess):
    fake_subprocess.on(["gh", "pr", "view"], stdout=json.dumps(PR_DETAILS))

    assert sut.get_pr_details(PR_DETAILS["url"]) == PR_DETAILS


def test_get_pr_details_without_output_is_empty(sut, fake_subprocess):
    fake_subprocess.on(["gh", "pr", "view"], returncode=1)

    assert sut.get_pr_details(PR_DETAILS["url"]) == {}


def test_list_needs_review_echoes_the_ready_pr(sut, fake_gh, capsys):
    fake_gh.on(["gh", "search"], stdout=json.dumps([{"url": PR_DETAILS["url"], "title": "t", "isDraft": False}]))
    fake_gh.on(["gh", "pr", "view"], stdout=json.dumps(PR_DETAILS))

    sut.list_needs_review(10, 2)

    assert capsys.readouterr().out.strip() == f"* {PR_DETAILS['url']} {PR_DETAILS['title']}"


def test_list_needs_review_stops_when_the_search_returns_nothing(sut, fake_gh, capsys):
    fake_gh.on(["gh", "search"], returncode=1)

    sut.list_needs_review(10, 2)

    assert not capsys.readouterr().out
    assert fake_gh.commands(["gh", "pr", "view"]) == []


def test_list_needs_work_names_the_failing_checks(sut, fake_gh, capsys):
    failing = {**PR_DETAILS, "statusCheckRollup": [{"conclusion": "FAILURE"}]}
    fake_gh.on(["gh", "search"], stdout=json.dumps([{"url": PR_DETAILS["url"], "title": "t", "isDraft": False}]))
    fake_gh.on(["gh", "pr", "view"], stdout=json.dumps(failing))

    sut.list_needs_work(10, 2)

    assert capsys.readouterr().out.strip() == f"* {PR_DETAILS['url']} {PR_DETAILS['title']} (CI failing)"


def test_list_needs_work_stops_when_the_search_returns_nothing(sut, fake_gh, capsys):
    fake_gh.on(["gh", "search"], returncode=1)

    sut.list_needs_work(10, 2)

    assert not capsys.readouterr().out
    assert fake_gh.commands(["gh", "pr", "view"]) == []


def test_needs_review_command_passes_the_options(sut, mocker):
    listed = mocker.patch.object(sut, "list_needs_review")

    result = CliRunner().invoke(sut.app, ["needs-review", "--limit", "5", "--workers", "3"])

    assert result.exit_code == 0
    listed.assert_called_once_with(5, 3)


def test_needs_work_command_passes_the_options(sut, mocker):
    listed = mocker.patch.object(sut, "list_needs_work")

    result = CliRunner().invoke(sut.app, ["needs-work"])

    assert result.exit_code == 0
    listed.assert_called_once_with(100, 10)


def test_main_defaults_to_needs_review(sut, mocker):
    listed = mocker.patch.object(sut, "list_needs_review")

    result = CliRunner().invoke(sut.app, [])

    assert result.exit_code == 0
    listed.assert_called_once_with(100, 10)


def test_list_needs_review_echoes_nothing_without_a_matching_pr(sut, fake_gh, capsys):
    fake_gh.on(["gh", "search"], stdout=json.dumps([{"url": PR_DETAILS["url"], "title": "t", "isDraft": False}]))
    fake_gh.on(
        ["gh", "pr", "view"], stdout=json.dumps({**PR_DETAILS, "statusCheckRollup": [{"conclusion": "FAILURE"}]})
    )

    sut.list_needs_review(10, 2)

    assert not capsys.readouterr().out


def test_list_needs_work_echoes_nothing_without_a_matching_pr(sut, fake_gh, capsys):
    fake_gh.on(["gh", "search"], stdout=json.dumps([{"url": PR_DETAILS["url"], "title": "t", "isDraft": False}]))
    fake_gh.on(["gh", "pr", "view"], stdout=json.dumps(PR_DETAILS))

    sut.list_needs_work(10, 2)

    assert not capsys.readouterr().out
