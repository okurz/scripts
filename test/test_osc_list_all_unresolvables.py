"""tests for osc-list-unresolvables."""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

rootpath = str(Path(__file__).resolve().parent.parent)

loader = importlib.machinery.SourceFileLoader("sut", str(Path(rootpath) / "osc-list-all-unresolvables"))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
sut = importlib.util.module_from_spec(spec)
loader.exec_module(sut)


@pytest.mark.xfail(reason="Stub not implemented yet, needs network; see plan 001_D")
def test_default_repo():
    assert sut.default_repo("home:okurz:try_openqa_leap16") == "16.0"


@pytest.mark.xfail(reason="Stub not implemented yet; see plan 001_D")
def test_basic():
    assert sut.list_unresolvables()
