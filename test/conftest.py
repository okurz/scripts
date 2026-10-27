import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def load_script():
    """Return a loader for scripts without a .py suffix in the repository root."""

    def load(filename: str) -> object:
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
