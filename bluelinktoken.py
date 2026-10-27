#!/usr/bin/env uv run
"""Retrieve the OAuth refresh and access token for a Hyundai or Kia account.

Opens the brand login page in Chrome, waits for the manual login, follows
the OAuth redirect and exchanges the code for tokens.

Original authors: Kia: fuatakgun
(https://gist.githubusercontent.com/fuatakgun/fa4ef1e1d48b8dca2d22133d4d028dc9#gistfile1.txt),
Hyundai: Maaxion (https://gist.github.com/Maaxion/22a38ba8fb06937da18482ddf35171ac).
"""

import argparse
import re
import time
from typing import TypedDict

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

HTTP_OK = 200
LOGIN_TIMEOUT_S = 300
REDIRECT_TRIES = 10
CODE_PATTERN = re.compile(r"code=([0-9a-fA-F-]{36}\.[0-9a-fA-F-]{36}\.[0-9a-fA-F-]{36})")
BASE_URL = "https://idpconnect-eu.{brand}.com/auth/api/v2/user/oauth2/"


class BrandConfig(TypedDict):
    """OAuth client settings and login URLs for one car brand."""

    client_id: str
    client_secret: str
    redirect_url_final: str
    success_selector: str
    extra_selector: str | None
    redirect_pattern: str
    login_url: str


BRANDS: dict[str, BrandConfig] = {
    "kia": {
        "client_id": "fdc85c00-0a2f-4c64-bcb4-2cfb1500730a",
        "client_secret": "secret",
        "redirect_url_final": "https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/redirect",
        "success_selector": "a[class='logout user']",
        "extra_selector": None,
        "redirect_pattern": r"^https://.*:8080/api/v1/user/oauth2/redirect",
        "login_url": "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/authorize?ui_locales=de&scope=openid%20profile%20email%20phone&response_type=code&client_id=peukiaidm-online-sales&redirect_uri=https://www.kia.com/api/bin/oneid/login&state=aHR0cHM6Ly93d3cua2lhLmNvbTo0NDMvZGUvP21zb2NraWQ9MjM1NDU0ODBmNmUyNjg5NDIwMmU0MDBjZjc2OTY5NWQmX3RtPTE3NTYzMTg3MjY1OTImX3RtPTE3NTYzMjQyMTcxMjY=_default",
    },
    "hyundai": {
        "client_id": "6d477c38-3ca4-4cf3-9557-2a1929a94654",
        "client_secret": "KUy49XxPzLpLuoK0xhBC77W6VXhmtQR9iQhmIFjjoY4IpxsV",
        "redirect_url_final": "https://prd.eu-ccapi.hyundai.com:8080/api/v1/user/oauth2/token",
        "success_selector": "button.mail_check",
        "extra_selector": "button.ctb_button",
        "redirect_pattern": r"^https://.*:8080/api/v1/user/oauth2/token",
        "login_url": "https://idpconnect-eu.hyundai.com/auth/api/v2/user/oauth2/authorize?client_id=peuhyundaiidm-ctb&redirect_uri=https%3A%2F%2Fctbapi.hyundai-europe.com%2Fapi%2Fauth&nonce=&state=NL_&scope=openid+profile+email+phone&response_type=code&connector_client_id=peuhyundaiidm-ctb&connector_scope=&connector_session_key=&country=&captcha=1&ui_locales=en-US",
    },
}


def parse_args() -> argparse.Namespace:
    """Parse the brand to get the refresh token for."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--brand",
        help="Brand of vehicle (Hyundai/Kia)",
        type=str.lower,
        required=True,
        choices=sorted(BRANDS),
    )
    return parser.parse_args()


def extract_code(url: str) -> str | None:
    """Return the OAuth code from a redirect URL, None when the URL has none."""
    match = CODE_PATTERN.search(url)
    return match.group(1) if match else None


def is_redirect_url(url: str, pattern: str) -> bool:
    """Return whether the browser landed on the brand redirect endpoint."""
    return re.match(pattern, url) is not None


def configure_driver() -> webdriver.Chrome:
    """Start Chrome with the CCS app user agent and a maximised window."""
    options = webdriver.ChromeOptions()
    options.add_argument(
        "user-agent=Mozilla/5.0 (Linux; Android 4.1.1; Galaxy Nexus Build/JRO03C) AppleWebKit/535.19 (KHTML, like Gecko) Chrome/18.0.1025.166 Mobile Safari/535.19_CCS_APP_AOS"
    )
    options.add_argument("--auto-open-devtools-for-tabs")
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def wait_for_login(driver: webdriver.Chrome, cfg: BrandConfig) -> None:
    """Block until the login page shows the brand success element."""
    selectors = [cfg["success_selector"]]
    if cfg["extra_selector"]:
        selectors.append(cfg["extra_selector"])
    located = [EC.presence_of_element_located((By.CSS_SELECTOR, selector)) for selector in selectors]
    WebDriverWait(driver, LOGIN_TIMEOUT_S).until(EC.any_of(*located) if len(located) > 1 else located[0])


def wait_for_redirect(driver: webdriver.Chrome, pattern: str) -> str:
    """Poll the browser URL until the brand redirect endpoint appears."""
    current_url = driver.current_url
    for attempt in range(1, REDIRECT_TRIES + 1):
        print(f" - [{attempt}] Waiting for redirect URL with code")
        current_url = driver.current_url
        if is_redirect_url(current_url, pattern):
            break
        time.sleep(1)
    else:
        print(f"\n❌ Failed to get redirected to correct URL, got {current_url} instead")
    return current_url


def exchange_code(cfg: BrandConfig, code: str, base_url: str) -> None:
    """Post the OAuth code to the token endpoint and print the tokens."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["redirect_url_final"],
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }
    response = requests.Session().post(f"{base_url}token", data=data)
    if response.status_code == HTTP_OK:
        tokens = response.json()
        if tokens is not None:
            print(
                f"\n✅ Your tokens are:\n\n- Refresh Token: {tokens['refresh_token']}\n- Access Token: {tokens['access_token']}"
            )
    else:
        print(f"\n❌ Error getting tokens from the API!\n{response.text}")


def main() -> None:
    """Run the Selenium login, follow the redirect and print the tokens."""
    args = parse_args()
    cfg = BRANDS[args.brand]
    base_url = BASE_URL.format(brand=args.brand)
    redirect_url = f"{base_url}authorize?response_type=code&client_id={cfg['client_id']}&redirect_uri={cfg['redirect_url_final']}&lang=de&state=ccsp"

    driver = configure_driver()
    try:
        print(f"Opening login page: {cfg['login_url']}")
        driver.get(cfg["login_url"])
        print("\n" + "=" * 50)
        print("Please log in manually in the browser window.")
        print("The script will wait for you to complete the login...")
        print("=" * 50 + "\n")
        run_login_flow(driver, cfg, base_url, redirect_url)
    finally:
        print("Cleaning up and closing the browser.")
        driver.quit()


def run_login_flow(driver: webdriver.Chrome, cfg: BrandConfig, base_url: str, redirect_url: str) -> None:
    """Wait for the manual login, follow the redirect and exchange the code."""
    try:
        wait_for_login(driver, cfg)
        print("✅ Login successful! Element found.")
        print(f"Redirecting to: {redirect_url}")
        driver.get(redirect_url)
        current_url = wait_for_redirect(driver, cfg["redirect_pattern"])
        code = extract_code(current_url)
        if code is None:
            print(f"\n❌ No OAuth code in {current_url}")
            return
        exchange_code(cfg, code, base_url)
    except TimeoutException:
        print("❌ Timed out after 5 minutes. Login was not completed or the success element was not found.")
    except Exception as e:  # noqa: BLE001
        print(f"An unexpected error occurred: {e}")
        time.sleep(3600)


if __name__ == "__main__":
    main()
