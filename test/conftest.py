"""Shared fixtures: load repository scripts that have no .py suffix as modules."""

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def load_script():
    """Return a loader for scripts without a .py suffix in the repository root."""

    def load(filename: str) -> Any:
        path = ROOT / filename
        module_name = path.stem.replace("-", "_")
        loader = importlib.machinery.SourceFileLoader(module_name, str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[loader.name] = module
        loader.exec_module(module)
        return module

    return load


class FakeSubprocess:
    """Answer subprocess.run/call from a prefix table and record every command."""

    def __init__(self, mocker) -> None:
        """Patch subprocess.run and subprocess.call with this instance's answers."""
        self.calls: list[list[str]] = []
        self._responses: list[tuple[list[str], str, str, int]] = []
        mocker.patch("subprocess.run", side_effect=self._run)
        mocker.patch("subprocess.call", side_effect=self._call)

    def on(self, prefix: list[str], *, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        """Register the answer for every command that starts with prefix (first match wins)."""
        self._responses.append((list(prefix), stdout, stderr, returncode))

    def commands(self, prefix: list[str]) -> list[list[str]]:
        """Return the recorded commands that start with prefix."""
        return [cmd for cmd in self.calls if cmd[: len(prefix)] == list(prefix)]

    def _answer(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        for prefix, stdout, stderr, returncode in self._responses:
            if list(cmd)[: len(prefix)] == prefix:
                return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
        msg = f"unexpected command: {cmd}"
        raise AssertionError(msg)

    def _run(self, cmd, *_args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        completed = self._answer(list(cmd))
        if kwargs.get("check") and completed.returncode != 0:
            raise subprocess.CalledProcessError(completed.returncode, cmd, completed.stdout, completed.stderr)
        return completed

    def _call(self, cmd, *_args: Any, **_kwargs: Any) -> int:
        return self._answer(list(cmd)).returncode


@pytest.fixture
def fake_subprocess(mocker) -> FakeSubprocess:
    """Return a FakeSubprocess with subprocess.run and subprocess.call patched."""
    return FakeSubprocess(mocker)
