import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "obs-pr-repair"
loader = importlib.machinery.SourceFileLoader("obs_pr_repair", str(SCRIPT_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
sut = importlib.util.module_from_spec(spec)
sys.modules["obs_pr_repair"] = sut
loader.exec_module(sut)

SAMPLE_OPENQA_WORKFLOW = """---
pr:
  steps:
    - branch_package:
        source_project: devel:openQA
        source_package: openQA
        target_project: devel:openQA:GitHub
        add_repositories: disabled
    - configure_repositories:
        project: devel:openQA:GitHub
        repositories:
          - name: openSUSE_Tumbleweed
            architectures: [ x86_64 ]
          - name: SLE_15_SP7_Backports
            architectures: [ x86_64 ]
          - name: '16.0'
            architectures: [ x86_64 ]
"""

SAMPLE_OS_AUTOINST_WORKFLOW = """---
pr:
  steps:
    - branch_package:
        source_project: devel:openQA
        source_package: os-autoinst
        target_project: devel:openQA:GitHub
        add_repositories: disabled
    - configure_repositories:
        project: devel:openQA:GitHub
        repositories:
          - name: openSUSE_Tumbleweed
            architectures: [ x86_64 ]
"""


def make_completed_process(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["mock"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


@pytest.mark.parametrize(
    (
        "desc",
        "workflow_yaml",
        "expected_target",
        "expected_src_prj",
        "expected_src_pkg",
        "expected_repos",
    ),
    [
        (
            "openQA workflow extracts correct targets and all three repositories",
            SAMPLE_OPENQA_WORKFLOW,
            "devel:openQA:GitHub",
            "devel:openQA",
            "openQA",
            ["openSUSE_Tumbleweed", "SLE_15_SP7_Backports", "16.0"],
        ),
        (
            "os-autoinst workflow extracts correct package and single repository",
            SAMPLE_OS_AUTOINST_WORKFLOW,
            "devel:openQA:GitHub",
            "devel:openQA",
            "os-autoinst",
            ["openSUSE_Tumbleweed"],
        ),
        (
            "empty or missing steps returns empty string fields and empty repo list",
            "---\npr: {}\n",
            "",
            "",
            "",
            [],
        ),
    ],
)
def test_parse_workflow_content(
    desc: str,
    workflow_yaml: str,
    expected_target: str,
    expected_src_prj: str,
    expected_src_pkg: str,
    expected_repos: list[str],
) -> None:
    config = sut.parse_workflow_content(workflow_yaml)
    assert config.target_project == expected_target, desc
    assert config.source_project == expected_src_prj, desc
    assert config.source_package == expected_src_pkg, desc
    assert config.target_repositories == expected_repos, desc


@pytest.mark.parametrize(
    ("desc", "url", "expected"),
    [
        (
            "SSH remote with git suffix extracts owner and repo",
            "git@github.com:os-autoinst/openQA.git",
            ("os-autoinst", "openQA"),
        ),
        (
            "SSH remote without git suffix extracts owner and repo",
            "git@github.com:os-autoinst/os-autoinst",
            ("os-autoinst", "os-autoinst"),
        ),
        (
            "HTTPS remote with git suffix extracts owner and repo",
            "https://github.com/os-autoinst/openQA.git",
            ("os-autoinst", "openQA"),
        ),
        (
            "HTTPS remote without git suffix extracts owner and repo",
            "https://github.com/someuser/test-repo",
            ("someuser", "test-repo"),
        ),
        (
            "non-github remote returns None",
            "https://gitlab.com/group/repo.git",
            None,
        ),
    ],
)
def test_parse_github_remote_url(
    desc: str, url: str, expected: tuple[str, str] | None
) -> None:
    assert sut.parse_github_remote_url(url) == expected, desc


@pytest.mark.parametrize(
    ("desc", "target_prj", "owner", "repo", "pr_number", "expected"),
    [
        (
            "openQA PR canonical project path",
            "devel:openQA:GitHub",
            "os-autoinst",
            "openQA",
            7968,
            "devel:openQA:GitHub:os-autoinst:openQA:PR-7968",
        ),
        (
            "os-autoinst PR canonical project path",
            "devel:openQA:GitHub",
            "os-autoinst",
            "os-autoinst",
            123,
            "devel:openQA:GitHub:os-autoinst:os-autoinst:PR-123",
        ),
    ],
)
def test_generate_obs_project_name(
    desc: str, target_prj: str, owner: str, repo: str, pr_number: int, expected: str
) -> None:
    assert (
        sut.generate_obs_project_name(target_prj, owner, repo, pr_number) == expected
    ), desc


def test_detect_github_repo_from_origin() -> None:
    runner = MagicMock(
        return_value=make_completed_process(
            stdout="git@github.com:os-autoinst/openQA.git\n"
        )
    )
    owner, repo = sut.detect_github_repo(runner=runner)
    assert (owner, repo) == ("os-autoinst", "openQA")


def test_detect_github_repo_fallback_gh() -> None:
    def fake_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1] == "remote":
            return make_completed_process(returncode=1)
        if cmd[0] == "gh":
            return make_completed_process(stdout="os-autoinst/openQA\n")
        return make_completed_process(returncode=1)

    owner, repo = sut.detect_github_repo(runner=fake_runner)
    assert (owner, repo) == ("os-autoinst", "openQA")


def test_detect_github_repo_failure() -> None:
    runner = MagicMock(return_value=make_completed_process(returncode=1))
    with pytest.raises(ValueError, match="Could not detect GitHub repository"):
        sut.detect_github_repo(runner=runner)


def test_detect_pr_number_success() -> None:
    runner = MagicMock(return_value=make_completed_process(stdout="7968\n"))
    assert sut.detect_pr_number(runner=runner) == 7968


def test_detect_pr_number_failure() -> None:
    runner = MagicMock(
        return_value=make_completed_process(returncode=1, stderr="no pr")
    )
    with pytest.raises(ValueError, match="Could not detect active PR number"):
        sut.detect_pr_number(runner=runner)


def test_resolve_context_cli_overrides(tmp_path: Path) -> None:
    workflow_file = tmp_path / "workflows.yml"
    workflow_file.write_text(SAMPLE_OPENQA_WORKFLOW, encoding="utf-8")

    parser = sut.create_parser()
    args = parser.parse_args(
        [
            "--repo",
            "custom-owner/custom-repo",
            "--pr",
            "PR-42",
            "--workflow",
            str(workflow_file),
        ]
    )

    context = sut.resolve_context(args)
    assert context.owner == "custom-owner"
    assert context.repo == "custom-repo"
    assert context.pr_number == 42
    assert context.obs_project == "devel:openQA:GitHub:custom-owner:custom-repo:PR-42"
    assert context.workflow.source_package == "openQA"


def test_resolve_context_explicit_project_override() -> None:
    parser = sut.create_parser()
    args = parser.parse_args(
        [
            "--repo",
            "owner/repo",
            "--pr",
            "1",
            "--project",
            "home:someone:my-override",
            "--target-project",
            "devel:openQA:GitHub",
        ]
    )
    context = sut.resolve_context(args)
    assert context.obs_project == "home:someone:my-override"


def test_verify_prerequisites_all_passing() -> None:
    runner = MagicMock(return_value=make_completed_process(returncode=0))
    with patch("shutil.which", return_value="/usr/bin/tool"):
        sut.verify_prerequisites(runner=runner)


@pytest.mark.parametrize(
    ("desc", "which_side_effect", "cmd_failure", "expected_error"),
    [
        (
            "missing osc executable raises RuntimeError",
            lambda cmd: None if cmd == "osc" else "/usr/bin/gh",
            None,
            "Required tool 'osc' is not installed",
        ),
        (
            "osc whois authentication failure raises RuntimeError",
            lambda cmd: "/usr/bin/" + cmd,
            "osc",
            "OBS authentication failed",
        ),
        (
            "gh auth status failure raises RuntimeError",
            lambda cmd: "/usr/bin/" + cmd,
            "gh",
            "GitHub authentication failed",
        ),
    ],
)
def test_verify_prerequisites_failures(
    desc: str, which_side_effect: object, cmd_failure: str | None, expected_error: str
) -> None:
    def fake_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if cmd_failure and cmd[0] == cmd_failure:
            return make_completed_process(returncode=1, stderr="Authentication error")
        return make_completed_process(returncode=0)

    with (
        patch("shutil.which", side_effect=which_side_effect),
        pytest.raises(RuntimeError, match=expected_error),
    ):
        sut.verify_prerequisites(runner=fake_runner)


def test_check_project_meta_found() -> None:
    xml_data = '<project name="test"><repository name="repo1"/><repository name="repo2"/></project>'
    runner = MagicMock(
        return_value=make_completed_process(stdout=xml_data, returncode=0)
    )
    exists, repos = sut.check_project_meta("test", runner=runner)
    assert exists is True
    assert repos == ["repo1", "repo2"]


def test_check_project_meta_not_found() -> None:
    runner = MagicMock(
        return_value=make_completed_process(
            stderr="Server returned an error: HTTP Error 404: Not Found",
            returncode=1,
        )
    )
    exists, repos = sut.check_project_meta("nonexistent", runner=runner)
    assert exists is False
    assert repos == []


@pytest.mark.parametrize(
    ("desc", "report", "expected_status", "expected_action_keyword"),
    [
        (
            "nonexistent project classified as NOT_FOUND",
            sut.DiagnosticReport(project_exists=False),
            sut.HealthStatus.NOT_FOUND,
            "--recreate",
        ),
        (
            "project with zero repositories classified as BROKEN_EMPTY_PROJECT",
            sut.DiagnosticReport(project_exists=True, repositories=[], packages=[]),
            sut.HealthStatus.BROKEN_EMPTY_PROJECT,
            "--recreate",
        ),
        (
            "project with repositories but no package files classified as BROKEN_UNBRANCHED_PACKAGE",
            sut.DiagnosticReport(
                project_exists=True,
                repositories=["openSUSE_Tumbleweed"],
                packages=["openQA"],
                package_files=[],
            ),
            sut.HealthStatus.BROKEN_UNBRANCHED_PACKAGE,
            "--repair-branch",
        ),
        (
            "project with repositories and only branch request classified as BROKEN_UNBRANCHED_PACKAGE",
            sut.DiagnosticReport(
                project_exists=True,
                repositories=["openSUSE_Tumbleweed"],
                packages=["openQA"],
                package_files=["_branch_request"],
            ),
            sut.HealthStatus.BROKEN_UNBRANCHED_PACKAGE,
            "--repair-branch",
        ),
        (
            "project with only branch request and all excluded results classified as BROKEN_EXCLUDED_OR_DISABLED",
            sut.DiagnosticReport(
                project_exists=True,
                repositories=["openSUSE_Tumbleweed"],
                packages=["openQA"],
                package_files=["_branch_request"],
                all_results_excluded_or_disabled=True,
            ),
            sut.HealthStatus.BROKEN_EXCLUDED_OR_DISABLED,
            "--repair-branch",
        ),
        (
            "project with source files and all excluded results classified as BROKEN_EXCLUDED_OR_DISABLED",
            sut.DiagnosticReport(
                project_exists=True,
                repositories=["openSUSE_Tumbleweed"],
                packages=["openQA"],
                package_files=["_service", "_branch_request"],
                all_results_excluded_or_disabled=True,
            ),
            sut.HealthStatus.BROKEN_EXCLUDED_OR_DISABLED,
            "--recreate",
        ),
        (
            "project with repositories and files classified as HEALTHY",
            sut.DiagnosticReport(
                project_exists=True,
                repositories=["openSUSE_Tumbleweed"],
                packages=["openQA"],
                package_files=["_service", "_branch_request"],
            ),
            sut.HealthStatus.HEALTHY,
            "--rebuild",
        ),
    ],
)
def test_classify_health(
    desc: str,
    report: sut.DiagnosticReport,
    expected_status: sut.HealthStatus,
    expected_action_keyword: str,
) -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=1,
        workflow=sut.WorkflowConfig(
            target_project="devel:openQA:GitHub",
            source_project="devel:openQA",
            source_package="openQA",
        ),
        obs_project="devel:openQA:GitHub:os-autoinst:openQA:PR-1",
    )
    sut.classify_health(report, ctx)
    assert report.status == expected_status, desc
    assert expected_action_keyword in report.suggested_action, desc


def test_diagnose_flow() -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=7968,
        workflow=sut.WorkflowConfig(
            target_project="devel:openQA:GitHub",
            source_project="devel:openQA",
            source_package="openQA",
        ),
        obs_project="devel:openQA:GitHub:os-autoinst:openQA:PR-7968",
    )

    xml_data = '<project name="test"><repository name="TW"/></project>'

    def fake_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1:3] == ["meta", "prj"]:
            return make_completed_process(stdout=xml_data)
        if cmd[1] == "ls" and len(cmd) == 3:
            return make_completed_process(stdout="openQA\nopenQA:test\n")
        if cmd[1] == "ls" and len(cmd) == 4:
            return make_completed_process(
                stdout="_service\n_branch_request\n# comment\n"
            )
        if cmd[1] == "results":
            return make_completed_process(stdout="openQA: succeeded\n")
        return make_completed_process()

    report = sut.diagnose(ctx, runner=fake_runner)
    assert report.project_exists is True
    assert report.repositories == ["TW"]
    assert report.packages == ["openQA", "openQA:test"]
    assert report.package_files == ["_service", "_branch_request"]
    assert report.status == sut.HealthStatus.HEALTHY
    formatted = sut.format_report(report, ctx)
    assert "HEALTHY" in formatted
    assert "devel:openQA:GitHub:os-autoinst:openQA:PR-7968" in formatted


@pytest.mark.parametrize(
    ("desc", "xml_content", "returncode", "expected"),
    [
        (
            "all packages excluded returns True",
            '<resultlist><result project="p" repository="r" arch="a"><status package="pkg" code="excluded"/></result></resultlist>',
            0,
            True,
        ),
        (
            "all packages disabled returns True",
            '<resultlist><result project="p" repository="r" arch="a"><status package="pkg" code="disabled"/></result></resultlist>',
            0,
            True,
        ),
        (
            "mixed excluded and disabled returns True",
            '<resultlist><result project="p" repository="r1" arch="a"><status package="pkg" code="excluded"/></result><result project="p" repository="r2" arch="a"><status package="pkg" code="disabled"/></result></resultlist>',
            0,
            True,
        ),
        (
            "repository-level code disabled without status elements returns True",
            '<resultlist><result project="p" repository="r" arch="a" code="disabled"/></resultlist>',
            0,
            True,
        ),
        (
            "repository-level state disabled without status elements returns True",
            '<resultlist><result project="p" repository="r" arch="a" state="disabled"/></resultlist>',
            0,
            True,
        ),
        (
            "at least one active package build returns False",
            '<resultlist><result project="p" repository="r" arch="a"><status package="pkg" code="succeeded"/><status package="pkg:test" code="excluded"/></result></resultlist>',
            0,
            False,
        ),
        (
            "failed build returns False",
            '<resultlist><result project="p" repository="r" arch="a"><status package="pkg" code="failed"/></result></resultlist>',
            0,
            False,
        ),
        (
            "building status returns False",
            '<resultlist><result project="p" repository="r" arch="a"><status package="pkg" code="building"/></result></resultlist>',
            0,
            False,
        ),
        (
            "empty resultlist returns False",
            "<resultlist></resultlist>",
            0,
            False,
        ),
        (
            "invalid XML returns False",
            "<not-xml",
            0,
            False,
        ),
        (
            "command failure returns False",
            "",
            1,
            False,
        ),
    ],
)
def test_check_all_results_excluded_or_disabled(
    desc: str, xml_content: str, returncode: int, expected: bool
) -> None:
    runner = MagicMock(
        return_value=make_completed_process(stdout=xml_content, returncode=returncode)
    )
    assert (
        sut.check_all_results_excluded_or_disabled("test-proj", runner=runner)
        is expected
    ), desc


def test_diagnose_flow_excluded_or_disabled() -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=7963,
        workflow=sut.WorkflowConfig(
            target_project="devel:openQA:GitHub",
            source_project="devel:openQA",
            source_package="openQA",
        ),
        obs_project="devel:openQA:GitHub:os-autoinst:openQA:PR-7963",
    )

    prj_meta_xml = '<project name="test"><repository name="TW"/><repository name="16.0"/></project>'
    results_xml = '<resultlist><result project="test" repository="TW" arch="x86_64"><status package="openQA" code="excluded"/></result></resultlist>'
    results_text = "openQA\n x  TW x86_64 (published)\n"

    def fake_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1:3] == ["meta", "prj"]:
            return make_completed_process(stdout=prj_meta_xml)
        if cmd[1] == "ls" and len(cmd) == 3:
            return make_completed_process(stdout="openQA\n")
        if cmd[1] == "ls" and len(cmd) == 4:
            return make_completed_process(stdout="_branch_request\n")
        if cmd[1] == "results" and "--xml" in cmd:
            return make_completed_process(stdout=results_xml)
        if cmd[1] == "results" and "--show-excluded" in cmd:
            return make_completed_process(stdout=results_text)
        return make_completed_process()

    report = sut.diagnose(ctx, runner=fake_runner)
    assert report.project_exists is True
    assert report.repositories == ["TW", "16.0"]
    assert report.packages == ["openQA"]
    assert report.package_files == ["_branch_request"]
    assert report.all_results_excluded_or_disabled is True
    assert report.status == sut.HealthStatus.BROKEN_EXCLUDED_OR_DISABLED
    assert "--repair-branch" in report.suggested_action
    formatted = sut.format_report(report, ctx)
    assert "BROKEN_EXCLUDED_OR_DISABLED" in formatted
    assert "no source files" in formatted
    assert "x  TW x86_64" in formatted


def test_recreate_project_abort_on_prompt() -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=1,
        workflow=sut.WorkflowConfig("", "", ""),
        obs_project="proj",
    )
    runner = MagicMock()
    with patch("builtins.input", return_value="n"):
        success = sut.recreate_project(ctx, auto_confirm=False, runner=runner)
    assert success is False
    runner.assert_not_called()


def test_recreate_project_auto_confirm() -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=123,
        workflow=sut.WorkflowConfig("", "", ""),
        obs_project="devel:openQA:GitHub:os-autoinst:openQA:PR-123",
    )
    calls: list[list[str]] = []

    def fake_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        return make_completed_process(returncode=0)

    success = sut.recreate_project(ctx, auto_confirm=True, runner=fake_runner)
    assert success is True
    assert calls[0][:3] == ["osc", "rdelete", "-r"]
    assert calls[0][-1] == ctx.obs_project
    assert calls[1] == ["gh", "pr", "close", "123", "--repo", "os-autoinst/openQA"]
    assert calls[2] == ["gh", "pr", "reopen", "123", "--repo", "os-autoinst/openQA"]


def test_repair_branch() -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=7968,
        workflow=sut.WorkflowConfig(
            target_project="devel:openQA:GitHub",
            source_project="devel:openQA",
            source_package="openQA",
        ),
        obs_project="devel:openQA:GitHub:os-autoinst:openQA:PR-7968",
    )
    calls: list[list[str]] = []

    def fake_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        if cmd[0] == "gh" and cmd[1:3] == ["pr", "view"]:
            payload = {
                "headRefOid": "abc12345def",
                "headRepository": {"nameWithOwner": "okurz/openQA"},
            }
            return make_completed_process(stdout=json.dumps(payload))
        return make_completed_process(returncode=0)

    success = sut.repair_branch(ctx, runner=fake_runner)
    assert success is True
    assert calls[0] == [
        "osc",
        "branch",
        "-f",
        "devel:openQA",
        "openQA",
        "devel:openQA:GitHub:os-autoinst:openQA:PR-7968",
        "openQA",
    ]
    assert calls[1][:3] == ["gh", "pr", "view"]
    assert calls[2][:4] == ["osc", "api", "-X", "PUT"]
    assert (
        calls[2][-1]
        == "/source/devel:openQA:GitHub:os-autoinst:openQA:PR-7968/openQA/_branch_request"
    )


def test_rebuild_project() -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=1,
        workflow=sut.WorkflowConfig("", "", ""),
        obs_project="target:project",
    )
    runner = MagicMock(return_value=make_completed_process(returncode=0))
    success = sut.rebuild_project(ctx, runner=runner)
    assert success is True
    runner.assert_called_once_with(["osc", "rebuild", "target:project"])


def test_main_multiple_actions_error() -> None:
    exit_code = sut.main(["--recreate", "--rebuild", "--skip-auth-check"])
    assert exit_code == 1


def test_find_and_parse_workflow_file(tmp_path: Path) -> None:
    obs_dir = tmp_path / ".obs"
    obs_dir.mkdir()
    wf = obs_dir / "workflows.yml"
    wf.write_text(SAMPLE_OPENQA_WORKFLOW, encoding="utf-8")

    sub_dir = tmp_path / "sub" / "dir"
    sub_dir.mkdir(parents=True)

    found = sut.find_workflow_file(sub_dir)
    assert found == wf

    parsed = sut.parse_workflow_file(wf)
    assert parsed.source_package == "openQA"

    not_found = sut.find_workflow_file(Path("/tmp"))
    assert not_found is None or not_found.name == "workflows.yml"


@pytest.mark.parametrize(
    ("desc", "args_list", "expected_err"),
    [
        (
            "invalid repository format raises ValueError",
            ["--repo", "invalid_repo", "--pr", "1"],
            "Invalid repo format",
        ),
        (
            "invalid PR number raises ValueError",
            ["--repo", "owner/repo", "--pr", "not_a_number"],
            "Invalid PR number",
        ),
        (
            "missing target project without workflow raises ValueError",
            ["--repo", "owner/repo", "--pr", "1", "--target-project", ""],
            "Target project could not be resolved",
        ),
    ],
)
def test_resolve_context_validation_errors(
    desc: str, args_list: list[str], expected_err: str
) -> None:
    parser = sut.create_parser()
    args = parser.parse_args(args_list)
    with pytest.raises(ValueError, match=expected_err):
        sut.resolve_context(args)


def test_check_project_meta_parse_error() -> None:
    runner = MagicMock(
        return_value=make_completed_process(stdout="not xml", returncode=0)
    )
    exists, repos = sut.check_project_meta("test", runner=runner)
    assert exists is True
    assert repos == []


def test_list_packages_and_files_failure() -> None:
    runner = MagicMock(return_value=make_completed_process(returncode=1))
    assert sut.list_packages("test", runner=runner) == []
    assert sut.list_package_files("test", "pkg", runner=runner) == []


@pytest.mark.parametrize(
    ("desc", "close_code", "reopen_code", "expected_success"),
    [
        ("close failure returns False", 1, 0, False),
        ("reopen failure returns False", 0, 1, False),
    ],
)
def test_recreate_project_gh_failures(
    desc: str, close_code: int, reopen_code: int, expected_success: bool
) -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=1,
        workflow=sut.WorkflowConfig("", "", ""),
        obs_project="proj",
    )

    def fake_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if len(cmd) > 2 and cmd[2] == "close":
            return make_completed_process(returncode=close_code, stderr="err")
        if len(cmd) > 2 and cmd[2] == "reopen":
            return make_completed_process(returncode=reopen_code, stderr="err")
        return make_completed_process(returncode=0)

    success = sut.recreate_project(ctx, auto_confirm=True, runner=fake_runner)
    assert success is expected_success, desc


def test_fetch_pr_head_commit_failure() -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=1,
        workflow=sut.WorkflowConfig("", "", ""),
        obs_project="proj",
    )
    runner = MagicMock(
        return_value=make_completed_process(returncode=1, stderr="gh error")
    )
    with pytest.raises(RuntimeError, match="Failed to inspect PR"):
        sut.fetch_pr_head_commit(ctx, runner=runner)


@pytest.mark.parametrize(
    ("desc", "branch_code", "api_code", "expected_success"),
    [
        ("osc branch failure returns False", 1, 0, False),
        ("osc api failure returns False", 0, 1, False),
    ],
)
def test_repair_branch_failures(
    desc: str, branch_code: int, api_code: int, expected_success: bool
) -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=1,
        workflow=sut.WorkflowConfig("tgt", "src", "pkg"),
        obs_project="tgt:proj",
    )

    def fake_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1] == "branch":
            return make_completed_process(returncode=branch_code, stderr="branch fail")
        if cmd[0] == "gh":
            payload = {
                "headRefOid": "abc",
                "headRepository": {"nameWithOwner": "owner/repo"},
            }
            return make_completed_process(stdout=json.dumps(payload))
        if cmd[1] == "api":
            return make_completed_process(returncode=api_code, stderr="api fail")
        return make_completed_process(returncode=0)

    success = sut.repair_branch(ctx, runner=fake_runner)
    assert success is expected_success, desc


def test_rebuild_project_failure() -> None:
    ctx = sut.ProjectContext(
        owner="os-autoinst",
        repo="openQA",
        pr_number=1,
        workflow=sut.WorkflowConfig("", "", ""),
        obs_project="proj",
    )
    runner = MagicMock(
        return_value=make_completed_process(returncode=1, stderr="rebuild fail")
    )
    assert sut.rebuild_project(ctx, runner=runner) is False


def test_main_dispatch_flows(tmp_path: Path) -> None:
    base_args = [
        "--repo",
        "os-autoinst/openQA",
        "--pr",
        "7968",
        "--target-project",
        "devel:openQA:GitHub",
        "--skip-auth-check",
    ]

    with patch.object(sut, "recreate_project", return_value=True) as mock_rec:
        assert sut.main([*base_args, "--recreate", "-y"]) == 0
        assert mock_rec.called

    with patch.object(sut, "repair_branch", return_value=True) as mock_rep:
        assert sut.main([*base_args, "--repair-branch"]) == 0
        assert mock_rep.called

    with patch.object(sut, "rebuild_project", return_value=True) as mock_reb:
        assert sut.main([*base_args, "--rebuild"]) == 0
        assert mock_reb.called

    healthy_report = sut.DiagnosticReport(
        project_exists=True,
        repositories=["TW"],
        packages=["openQA"],
        package_files=["_service"],
        status=sut.HealthStatus.HEALTHY,
    )
    with patch.object(sut, "diagnose", return_value=healthy_report):
        assert sut.main(base_args) == 0

    unhealthy_report = sut.DiagnosticReport(
        project_exists=False,
        status=sut.HealthStatus.NOT_FOUND,
    )
    with patch.object(sut, "diagnose", return_value=unhealthy_report):
        assert sut.main(base_args) == 2
