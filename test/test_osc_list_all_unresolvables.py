"""tests for osc-list-unresolvables."""

import pytest


@pytest.fixture
def sut(load_script):
    return load_script("osc-list-all-unresolvables")


@pytest.mark.xfail(reason="Stub not implemented yet, needs network; see plan 001_D")
def test_default_repo(sut):
    assert sut.default_repo("home:okurz:try_openqa_leap16") == "16.0"


@pytest.mark.xfail(reason="Stub not implemented yet; see plan 001_D")
def test_basic(sut):
    assert sut.list_unresolvables()
