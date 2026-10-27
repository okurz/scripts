"""Tests for the pure helpers of bluelinktoken: code extraction, redirect matching and CLI brand parsing."""

import pytest

CODE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.fixture
def sut(load_script):
    return load_script("bluelinktoken.py")


def test_extract_code_returns_the_oauth_code(sut):
    assert sut.extract_code(f"https://host/cb?code={CODE}&state=1") == CODE


def test_extract_code_returns_none_without_code(sut):
    assert sut.extract_code("https://host/cb?error=denied") is None


def test_is_redirect_url_matches_brand_endpoint(sut):
    pattern = sut.BRANDS["hyundai"]["redirect_pattern"]
    assert sut.is_redirect_url("https://a.example:8080/api/v1/user/oauth2/token?x", pattern)


def test_is_redirect_url_rejects_other_pages(sut):
    pattern = sut.BRANDS["hyundai"]["redirect_pattern"]
    assert not sut.is_redirect_url("https://a.example/login", pattern)


def test_parse_args_accepts_brand_case_insensitively(sut, monkeypatch):
    monkeypatch.setattr("sys.argv", ["bluelinktoken.py", "--brand", "KIA"])
    assert sut.parse_args().brand == "kia"


def test_parse_args_rejects_unknown_brand(sut, monkeypatch):
    monkeypatch.setattr("sys.argv", ["bluelinktoken.py", "--brand", "tesla"])
    with pytest.raises(SystemExit):
        sut.parse_args()


def test_base_url_is_brand_specific(sut):
    assert sut.BASE_URL.format(brand="kia") == "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/"
