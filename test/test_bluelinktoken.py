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


def make_driver(mocker, urls: list[str]):
    """Return a driver mock whose current_url walks the given URLs and holds the last one."""
    driver = mocker.MagicMock()
    queue = list(urls)

    def next_url() -> str:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    type(driver).current_url = mocker.PropertyMock(side_effect=next_url)
    return driver


def brand(*, extra: str | None = None):
    return {
        "client_id": "cid",
        "client_secret": "secret",
        "redirect_url_final": "https://ctbapi.example.com/api/auth",
        "success_selector": "#success",
        "extra_selector": extra,
        "redirect_pattern": r"https://ctbapi\.example\.com/api/auth",
        "login_url": "https://idp.example.com/login",
    }


def test_configure_driver_sends_the_ccs_user_agent_and_maximises(sut, mocker):
    options = mocker.patch.object(sut.webdriver, "ChromeOptions")
    chrome = mocker.patch.object(sut.webdriver, "Chrome")

    driver = sut.configure_driver()

    arguments = options.return_value.add_argument.call_args_list
    assert any("_CCS_APP_AOS" in call.args[0] for call in arguments)
    assert any("--auto-open-devtools-for-tabs" in call.args[0] for call in arguments)
    assert driver is chrome.return_value
    driver.maximize_window.assert_called_once_with()


def test_wait_for_login_waits_for_the_single_success_selector(sut, mocker):
    wait = mocker.patch.object(sut, "WebDriverWait")
    ec = mocker.patch.object(sut, "EC")

    sut.wait_for_login(mocker.MagicMock(), brand())

    assert ec.presence_of_element_located.call_count == 1
    wait.return_value.until.assert_called_once_with(ec.presence_of_element_located.return_value)


def test_wait_for_login_waits_for_any_of_both_selectors(sut, mocker):
    wait = mocker.patch.object(sut, "WebDriverWait")
    ec = mocker.patch.object(sut, "EC")

    sut.wait_for_login(mocker.MagicMock(), brand(extra="#extra"))

    assert ec.presence_of_element_located.call_count == 2
    wait.return_value.until.assert_called_once_with(ec.any_of.return_value)


def test_wait_for_redirect_returns_after_the_endpoint_appears(sut, mocker, capsys):
    driver = make_driver(mocker, ["https://idp.example.com/login", "https://ctbapi.example.com/api/auth?code=1"])
    clock = mocker.Mock()
    mocker.patch.object(sut, "time", clock)

    url = sut.wait_for_redirect(driver, brand()["redirect_pattern"])

    assert url == "https://ctbapi.example.com/api/auth?code=1"
    assert "[1] Waiting for redirect URL with code" in capsys.readouterr().out
    clock.sleep.assert_called_once_with(1)


def test_wait_for_redirect_reports_the_last_url_when_the_endpoint_never_appears(sut, mocker, capsys):
    driver = make_driver(mocker, ["https://idp.example.com/login"])
    clock = mocker.Mock()
    mocker.patch.object(sut, "time", clock)

    url = sut.wait_for_redirect(driver, brand()["redirect_pattern"])

    assert url == "https://idp.example.com/login"
    assert "Failed to get redirected to correct URL" in capsys.readouterr().out
    assert clock.sleep.call_count == sut.REDIRECT_TRIES


def test_exchange_code_prints_the_tokens(sut, mocker, capsys):
    response = mocker.MagicMock(status_code=200)
    response.json.return_value = {"refresh_token": "r", "access_token": "a"}
    post = mocker.patch.object(sut.requests.Session, "post", return_value=response)

    sut.exchange_code(brand(), "the-code", "https://idp.example.com/api/")

    assert post.call_args.args[0] == "https://idp.example.com/api/token"
    assert post.call_args.kwargs["data"] == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "redirect_uri": "https://ctbapi.example.com/api/auth",
        "client_id": "cid",
        "client_secret": "secret",
    }
    assert "Refresh Token: r" in capsys.readouterr().out


def test_exchange_code_ignores_a_null_token_body(sut, mocker, capsys):
    response = mocker.MagicMock(status_code=200)
    response.json.return_value = None
    mocker.patch.object(sut.requests.Session, "post", return_value=response)

    sut.exchange_code(brand(), "the-code", "https://idp.example.com/api/")

    assert "Your tokens are" not in capsys.readouterr().out


def test_exchange_code_reports_a_failing_token_request(sut, mocker, capsys):
    response = mocker.MagicMock(status_code=400, text="invalid_grant")
    mocker.patch.object(sut.requests.Session, "post", return_value=response)

    sut.exchange_code(brand(), "the-code", "https://idp.example.com/api/")

    out = capsys.readouterr().out
    assert "Error getting tokens from the API!" in out
    assert "invalid_grant" in out


def test_print_login_instructions_and_banner(sut, capsys):
    sut.print_login_instructions("https://idp.example.com/login")
    sut.print_login_wait_banner()

    out = capsys.readouterr().out
    assert "Opening login page: https://idp.example.com/login" in out
    assert "Please log in manually in the browser window." in out


def test_complete_redirect_exchanges_the_code(sut, mocker):
    driver = make_driver(mocker, ["https://idp.example.com/login"])
    mocker.patch.object(sut, "wait_for_redirect", return_value=f"https://ctbapi.example.com/api/auth?code={CODE}")
    exchange = mocker.patch.object(sut, "exchange_code")

    sut.complete_redirect(driver, brand(), "https://idp.example.com/api/", "https://idp.example.com/authorize")

    exchange.assert_called_once_with(brand(), CODE, "https://idp.example.com/api/")


def test_complete_redirect_reports_a_missing_code(sut, mocker, capsys):
    driver = make_driver(mocker, ["https://idp.example.com/login"])
    mocker.patch.object(sut, "wait_for_redirect", return_value="https://ctbapi.example.com/api/auth?error=denied")
    exchange = mocker.patch.object(sut, "exchange_code")

    sut.complete_redirect(driver, brand(), "https://idp.example.com/api/", "https://idp.example.com/authorize")

    exchange.assert_not_called()
    assert "No OAuth code in https://ctbapi.example.com/api/auth?error=denied" in capsys.readouterr().out


def test_run_login_flow_reports_a_timeout(sut, mocker, capsys):
    mocker.patch.object(sut, "wait_for_login", side_effect=sut.TimeoutException("too slow"))

    sut.run_login_flow(mocker.MagicMock(), brand(), "https://idp.example.com/api/", "https://idp.example.com/auth")

    assert "Timed out after 5 minutes" in capsys.readouterr().out


def test_run_login_flow_reports_an_unexpected_error_and_backs_off(sut, mocker, capsys):
    driver = mocker.MagicMock()
    mocker.patch.object(sut, "wait_for_login", side_effect=RuntimeError("driver gone"))
    clock = mocker.Mock()
    mocker.patch.object(sut, "time", clock)

    sut.run_login_flow(driver, brand(), "https://idp.example.com/api/", "https://idp.example.com/auth")

    assert "An unexpected error occurred: driver gone" in capsys.readouterr().out
    clock.sleep.assert_called_once_with(3600)


def test_main_runs_the_flow_and_closes_the_browser(sut, mocker, monkeypatch):
    driver = make_driver(mocker, ["https://idp.example.com/login"])
    mocker.patch.object(sut, "configure_driver", return_value=driver)
    monkeypatch.setattr("sys.argv", ["bluelinktoken.py", "--brand", "kia"])
    flow = mocker.patch.object(sut, "run_login_flow")

    sut.main()

    flow.assert_called_once_with(
        driver, sut.BRANDS["kia"], "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/", mocker.ANY
    )
    driver.get.assert_called_once_with(sut.BRANDS["kia"]["login_url"])
    driver.quit.assert_called_once_with()


def test_run_login_flow_waits_then_completes_the_redirect(sut, mocker):
    driver = make_driver(mocker, ["https://idp.example.com/login"])
    wait = mocker.patch.object(sut, "wait_for_login")
    complete = mocker.patch.object(sut, "complete_redirect")

    sut.run_login_flow(driver, brand(), "https://idp.example.com/api/", "https://idp.example.com/auth")

    wait.assert_called_once_with(driver, brand())
    complete.assert_called_once_with(driver, brand(), "https://idp.example.com/api/", "https://idp.example.com/auth")
