"""tests for osc-list-all-unresolvables: project lookup, package enumeration and error lines."""

import pytest

PROJECT_META = """<project name="home:okurz:my_project">
  <repository name="15.6"><path project="openSUSE:Leap:15.6" repository="standard"/></repository>
  <repository name="16.0"><path project="openSUSE:Leap:16.0" repository="standard"/></repository>
</project>
"""

BUILDINFO_UNRESOLVABLE = """<buildinfo project="home:okurz:my_project" repository="16.0" package="mypkg" arch="x86_64">
  <error>nothing provides perl(Foo::Bar) needed by mypkg</error>
  <error>expansion error: have choice for something</error>
</buildinfo>
"""

BUILDINFO_CLEAN = """<buildinfo project="home:okurz:my_project" repository="16.0" package="cleanpkg" arch="x86_64"/>"""


@pytest.fixture
def sut(load_script):
    return load_script("osc-list-all-unresolvables")


def test_project_repositories_keeps_the_project_order(sut, fake_subprocess):
    fake_subprocess.on(["osc", "meta", "prj", "home:okurz:my_project"], stdout=PROJECT_META)

    assert sut.project_repositories("home:okurz:my_project") == ["15.6", "16.0"]


def test_project_repositories_without_a_repository_returns_an_empty_list(sut, fake_subprocess):
    fake_subprocess.on(["osc", "meta", "prj"], stdout='<project name="empty"/>')

    assert sut.project_repositories("empty") == []


def test_osc_failure_names_the_command_and_the_stderr(sut, fake_subprocess):
    fake_subprocess.on(["osc", "meta", "prj"], stderr="Server returned an error: 404", returncode=1)

    with pytest.raises(sut.OscError, match="osc meta failed: Server returned an error: 404"):
        sut.project_repositories("missing")


def test_unparsable_xml_is_reported_as_an_osc_error(sut, fake_subprocess):
    fake_subprocess.on(["osc", "meta", "prj"], stdout="not xml")

    with pytest.raises(sut.OscError, match="printed no XML"):
        sut.project_repositories("broken")


def test_project_packages_skips_blank_lines(sut, fake_subprocess):
    fake_subprocess.on(["osc", "ls"], stdout="pkg-a\npkg-b\n\n")

    assert sut.project_packages("home:okurz:my_project") == ["pkg-a", "pkg-b"]


def test_project_packages_failure_is_an_osc_error(sut, fake_subprocess):
    fake_subprocess.on(["osc", "ls"], stderr="unknown project", returncode=4)

    with pytest.raises(sut.OscError, match="osc ls failed: unknown project"):
        sut.project_packages("missing")


def test_unresolvables_returns_only_the_nothing_provides_lines(sut, fake_subprocess):
    fake_subprocess.on(["osc", "buildinfo"], stdout=BUILDINFO_UNRESOLVABLE)

    assert sut.unresolvables("home:okurz:my_project", "mypkg", "16.0", "x86_64") == [
        "perl(Foo::Bar) needed by mypkg",
    ]


def test_unresolvables_of_a_clean_package_is_empty(sut, fake_subprocess):
    fake_subprocess.on(["osc", "buildinfo"], stdout=BUILDINFO_CLEAN)

    assert sut.unresolvables("home:okurz:my_project", "cleanpkg", "16.0", "x86_64") == []


def test_report_keeps_packages_without_unresolvables(sut, fake_subprocess):
    fake_subprocess.on(["osc", "buildinfo", "home:okurz:my_project", "mypkg"], stdout=BUILDINFO_UNRESOLVABLE)
    fake_subprocess.on(["osc", "buildinfo", "home:okurz:my_project", "cleanpkg"], stdout=BUILDINFO_CLEAN)

    assert sut.report("home:okurz:my_project", ["mypkg", "cleanpkg"], "16.0", "x86_64") == {
        "mypkg": ["perl(Foo::Bar) needed by mypkg"],
        "cleanpkg": [],
    }


def test_main_prints_the_first_repository_and_every_package(sut, fake_subprocess, mocker, capsys):
    fake_subprocess.on(["osc", "meta", "prj"], stdout=PROJECT_META)
    fake_subprocess.on(["osc", "ls"], stdout="mypkg\n")
    fake_subprocess.on(["osc", "buildinfo"], stdout=BUILDINFO_UNRESOLVABLE)
    mocker.patch.object(sut.sys, "argv", ["osc-list-all-unresolvables", "home:okurz:my_project"])

    sut.main()

    out = capsys.readouterr().out
    assert out.splitlines() == [
        "# home:okurz:my_project 15.6 x86_64",
        "## pkg: mypkg",
        "perl(Foo::Bar) needed by mypkg",
    ]


def test_main_inspects_a_single_package_on_a_named_repository(sut, fake_subprocess, mocker, capsys):
    fake_subprocess.on(["osc", "buildinfo"], stdout=BUILDINFO_UNRESOLVABLE)
    mocker.patch.object(
        sut.sys,
        "argv",
        ["osc-list-all-unresolvables", "home:okurz:my_project", "--package", "mypkg", "--repo", "16.0"],
    )

    sut.main()

    assert fake_subprocess.commands(["osc", "ls"]) == []
    assert fake_subprocess.commands(["osc", "buildinfo"]) == [
        ["osc", "buildinfo", "home:okurz:my_project", "mypkg", "16.0", "x86_64"],
    ]
    assert "## pkg: mypkg" in capsys.readouterr().out


def test_main_without_a_repository_exits_one(sut, fake_subprocess, mocker, capsys):
    fake_subprocess.on(["osc", "meta", "prj"], stdout='<project name="empty"/>')
    mocker.patch.object(sut.sys, "argv", ["osc-list-all-unresolvables", "empty"])

    with pytest.raises(SystemExit) as excinfo:
        sut.main()

    assert excinfo.value.code == 1
    assert "Error: empty defines no repository" in capsys.readouterr().err


def test_main_reports_an_osc_failure_on_stderr(sut, fake_subprocess, mocker, capsys):
    fake_subprocess.on(["osc", "meta", "prj"], stderr="Server returned an error: 404", returncode=1)
    mocker.patch.object(sut.sys, "argv", ["osc-list-all-unresolvables", "missing"])

    with pytest.raises(SystemExit) as excinfo:
        sut.main()

    assert excinfo.value.code == 1
    assert "Error: osc meta failed: Server returned an error: 404" in capsys.readouterr().err


@pytest.mark.parametrize(("verbose_flags", "expected"), [([], 40), (["-v"], 30), (["-v", "-v", "-v"], 10)])
def test_verbose_sets_the_log_level(sut, mocker, verbose_flags, expected):
    mocker.patch.object(sut.sys, "argv", ["osc-list-all-unresolvables", "prj", *verbose_flags])
    mocker.patch.object(sut.log, "setLevel")

    sut.parse_args()

    sut.log.setLevel.assert_called_once_with(expected)
