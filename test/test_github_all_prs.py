import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "github-all-prs"
loader = importlib.machinery.SourceFileLoader("github_all_prs", str(SCRIPT_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
sut = importlib.util.module_from_spec(spec)
loader.exec_module(sut)


def test_parse_date():
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
                "comments": [
                    {"author": {"login": "okurz"}, "createdAt": "2026-10-11T12:00:00Z"}
                ],
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
def test_has_unanswered_changes_requested(desc, pr, me, expected):
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
                "comments": [
                    {"author": {"login": "okurz"}, "createdAt": "2026-10-11T12:00:00Z"}
                ],
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
def test_needs_review_filter(desc, pr, me, expected):
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
                "comments": [
                    {"author": {"login": "okurz"}, "createdAt": "2026-10-11T12:00:00Z"}
                ],
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
def test_needs_work_filter(desc, pr, me, expected):
    assert sut.needs_work_filter(pr, me) == expected, desc
