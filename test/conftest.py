"""Shared fixtures: load repository scripts that have no .py suffix as modules."""

import importlib.machinery
import importlib.util
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import responses

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

    def _answer(self, cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
        recorded = cmd.split() if isinstance(cmd, str) else list(cmd)
        self.calls.append(recorded)
        for prefix, stdout, stderr, returncode in self._responses:
            if recorded[: len(prefix)] == prefix:
                return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
        msg = f"unexpected command: {recorded}"
        raise AssertionError(msg)

    def _run(self, cmd, *_args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        completed = self._answer(cmd)
        if kwargs.get("check") and completed.returncode != 0:
            raise subprocess.CalledProcessError(completed.returncode, cmd, completed.stdout, completed.stderr)
        return completed

    def _call(self, cmd, *_args: Any, **_kwargs: Any) -> int:
        return self._answer(cmd).returncode


@pytest.fixture
def fake_subprocess(mocker) -> FakeSubprocess:
    """Return a FakeSubprocess with subprocess.run and subprocess.call patched."""
    return FakeSubprocess(mocker)


class FakeHttpx:
    """Answer httpx requests from a path table and record every request that was made."""

    def __init__(self, mocker) -> None:
        """Patch httpx.Client and httpx.AsyncClient to talk to this instance's table."""
        self.requests: list[httpx.Request] = []
        self._routes: dict[str, httpx.Response] = {}
        self._async_client_cls = httpx.AsyncClient
        self._client_cls = httpx.Client
        self._transport = httpx.MockTransport(self._handle)
        mocker.patch.object(httpx, "AsyncClient", self._async_client)
        mocker.patch.object(httpx, "Client", self._sync_client)

    def on(self, path: str, *, json_body: Any = None, text: str = "", status_code: int = 200) -> None:
        """Register the answer for a URL path, as JSON or as plain text."""
        response = (
            httpx.Response(status_code, json=json_body)
            if json_body is not None
            else httpx.Response(status_code, text=text)
        )
        self._routes[path] = response

    def paths(self) -> list[str]:
        """Return the paths of the recorded requests in call order."""
        return [request.url.path for request in self.requests]

    def raw_paths(self) -> list[str]:
        """Return the percent-encoded paths of the recorded requests in call order."""
        return [request.url.raw_path.decode() for request in self.requests]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path not in self._routes:
            msg = f"unexpected httpx request: {request.method} {request.url.path}"
            raise AssertionError(msg)
        return self._routes[request.url.path]

    def _async_client(self, **kwargs: Any) -> httpx.AsyncClient:
        return self._async_client_cls(transport=self._transport, **kwargs)

    def _sync_client(self, **kwargs: Any) -> httpx.Client:
        return self._client_cls(transport=self._transport, **kwargs)


@pytest.fixture
def fake_httpx(mocker) -> FakeHttpx:
    """Return a FakeHttpx with httpx.Client and httpx.AsyncClient patched."""
    return FakeHttpx(mocker)


@pytest.fixture
def fake_requests() -> Iterator[responses.RequestsMock]:
    """Return a responses mock that answers and records requests calls."""
    with responses.RequestsMock() as mock:
        yield mock
