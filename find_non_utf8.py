#!/usr/bin/env python3
"""Find paths whose name is not valid UTF-8.

Reference: http://stackoverflow.com/questions/623764/find-non-utf8-filenames-on-linux-file-system
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO


def is_utf8(name: str) -> bool:
    """Return whether the raw name bytes decode as UTF-8."""
    try:
        os.fsencode(name).decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def non_utf8_paths(root: str = ".") -> list[str]:
    """Return paths below root whose name bytes are not valid UTF-8."""
    paths = []
    for entry in os.scandir(root):
        if not is_utf8(entry.name):
            paths.append(entry.path)
        if entry.is_dir(follow_symlinks=False):
            paths.extend(non_utf8_paths(entry.path))
    return paths


def main(root: str = ".", out: BinaryIO = sys.stdout.buffer) -> int:
    """Write every non-UTF-8 path below root to out, grep-style exit codes."""
    paths = non_utf8_paths(root)
    out.writelines(os.fsencode(path) + b"\n" for path in sorted(paths))
    out.flush()
    return 0 if paths else 1


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    try:
        sys.exit(main(target))
    except OSError as exc:
        print(f"{target}: {exc}", file=sys.stderr)
        sys.exit(2)
