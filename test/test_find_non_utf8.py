import io
import os
import subprocess
import sys
from pathlib import Path

BAD_FILE = os.fsencode(b"bad\xffname").decode("utf-8", "surrogateescape")
BAD_DIR = os.fsencode(b"sub\xffdir").decode("utf-8", "surrogateescape")


def test_is_utf8_accepts_ascii_names(load_script):
    sut = load_script("find_non_utf8.py")
    assert sut.is_utf8("normal name.txt")


def test_is_utf8_accepts_non_ascii_utf8_names(load_script):
    sut = load_script("find_non_utf8.py")
    assert sut.is_utf8("Grüße-φύση-名前.txt")


def test_is_utf8_rejects_names_with_invalid_utf8_bytes(load_script):
    sut = load_script("find_non_utf8.py")
    assert not sut.is_utf8(BAD_FILE)


def test_non_utf8_paths_finds_only_the_bad_file(load_script, tmp_path):
    sut = load_script("find_non_utf8.py")
    (tmp_path / "good.txt").write_text("x")
    (tmp_path / BAD_FILE).write_text("x")
    assert sut.non_utf8_paths(str(tmp_path)) == [str(tmp_path / BAD_FILE)]


def test_non_utf8_paths_finds_directories_with_bad_names(load_script, tmp_path):
    sut = load_script("find_non_utf8.py")
    Path(tmp_path / BAD_DIR).mkdir()
    (tmp_path / BAD_DIR / "inner.txt").write_text("x")
    assert sut.non_utf8_paths(str(tmp_path)) == [str(tmp_path / BAD_DIR)]


def test_non_utf8_paths_is_empty_for_a_clean_tree(load_script, tmp_path):
    sut = load_script("find_non_utf8.py")
    Path(tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("x")
    assert sut.non_utf8_paths(str(tmp_path)) == []


def test_non_utf8_paths_does_not_follow_directory_symlinks(load_script, tmp_path):
    sut = load_script("find_non_utf8.py")
    Path(tmp_path / "target").mkdir()
    Path(tmp_path / "link").symlink_to("target")
    assert sut.non_utf8_paths(str(tmp_path)) == []


def test_main_writes_found_paths_and_exits_zero(load_script, tmp_path):
    sut = load_script("find_non_utf8.py")
    out = io.BytesIO()
    (tmp_path / BAD_FILE).write_text("x")
    assert sut.main(str(tmp_path), out) == 0
    assert out.getvalue() == os.fsencode(str(tmp_path / BAD_FILE)) + b"\n"


def test_main_exits_one_when_nothing_is_found(load_script, tmp_path):
    sut = load_script("find_non_utf8.py")
    (tmp_path / "clean.txt").write_text("x")
    assert sut.main(str(tmp_path)) == 1


def test_main_defaults_to_the_current_directory(load_script, tmp_path, monkeypatch):
    sut = load_script("find_non_utf8.py")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "clean.txt").write_text("x")
    assert sut.main() == 1


def test_cli_exits_two_for_a_missing_directory(tmp_path):
    script = Path(__file__).resolve().parent.parent / "find_non_utf8.py"
    res = subprocess.run(
        [sys.executable, str(script), "does-not-exist"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 2
    assert "does-not-exist" in res.stderr


def test_cli_writes_found_paths_below_the_given_directory(tmp_path):
    script = Path(__file__).resolve().parent.parent / "find_non_utf8.py"
    (tmp_path / BAD_FILE).write_text("x")
    res = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        capture_output=True,
        check=False,
    )
    assert res.returncode == 0
    assert res.stdout == os.fsencode(str(tmp_path / BAD_FILE)) + b"\n"
