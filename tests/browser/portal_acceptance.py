"""Exercise the standalone portal with real Chromium, Laravel and a loopback identity provider.

Install both checkouts' development dependencies, Python Playwright and Chromium.
Set DB_HOST, DB_DATABASE, DB_USERNAME and DB_PASSWORD for a dedicated local MySQL
test database. Run: python3 tests/browser/portal_acceptance.py ../bulsca-site
"""

import argparse
import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright

from fake_authentik import FakeAuthentik

PORTAL = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("portal_fixture.php")


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def server(command, cwd, env, health, expected, accept):
    # A test HTTP server can log OAuth query parameters. Keep its output private.
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f"{command[0]} exited before becoming ready ({process.returncode})")
            try:
                with urlopen(Request(health, headers={"Accept": accept}), timeout=1) as response:
                    status = response.status
            except HTTPError as error:
                status = error.code
            except (OSError, URLError):
                status = None
            if status == expected:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f"Timed out starting {command[0]} (last HTTP status: {status})")
        yield
    finally:
        process.terminate()
        try:
            process.wait(5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def exercise(page, origin, provider, fixture):
    headers = {"Accept": "application/json", "Origin": origin, "Referer": origin + "/"}
    me = origin + "/api/v1/me"
    assert page.request.get(me, headers=headers).status == 401, "Guest identity must be denied"
    page.goto(origin + "/dashboard")
    with page.expect_response(lambda r: r.url == me and r.status == 200) as signed_in:
        page.locator('a[href^="/auth/sso"]').click()
    expect(page.get_by_role("heading", name="Welcome, Browser Manager")).to_be_visible()
    identity = signed_in.value.json()["data"]
    assert identity["user"]["email"] == provider.email
    assert not identity["organisations"] and not identity["is_superadmin"], "First login granted privileges"

    clubs = json.loads(fixture("membership", provider.email))
    page.reload()
    expect(page.get_by_role("link", name="Administration", exact=True)).to_have_count(0)
    page.get_by_role("link").filter(has_text="Browser Club").click()
    expect(page.get_by_role("heading", name="Browser Club")).to_be_visible()
    page.get_by_label("Registered email").fill(clubs["member"])
    with page.expect_response(lambda r: r.url.endswith(f"/organisations/{clubs['own']}/members")
                              and r.request.method == "POST") as saved:
        page.get_by_role("button", name="Add member", exact=True).click()
    assert saved.value.status == 201, "Club membership write failed"
    expect(page.get_by_role("cell", name="Example Member", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_role("cell", name="Example Member", exact=True)).to_be_visible()

    private_path = f"/api/v1/portal/organisations/{clubs['other']}"
    with page.expect_response(lambda r: urlsplit(r.url).path == private_path) as denied:
        page.goto(origin + f"/organisations/{clubs['other']}")
    assert denied.value.status == 404, "A manager may not read another club"
    expect(page.get_by_role("alert").first).to_be_visible()
    expect(page.get_by_text("Separate Club", exact=True)).to_have_count(0)

    logout = origin + "/api/v1/portal/logout"
    assert page.request.post(logout, headers=headers).status == 419, "Logout without CSRF was accepted"
    with page.expect_response(lambda r: r.url == logout and r.request.method == "POST") as ended:
        page.get_by_role("button", name="Sign out", exact=True).click()
    assert ended.value.ok, "Portal logout failed"
    expect(page.locator('a[href^="/auth/sso"]')).to_be_visible()
    assert page.request.get(me, headers=headers).status == 401, "Session remained authenticated"
    assert provider.revoked, "The provider did not receive revocation"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", type=Path)
    args = parser.parse_args()
    backend = args.backend.resolve()
    if not os.environ.get("DB_DATABASE") or not os.environ.get("DB_HOST"):
        parser.error("Set DB_DATABASE and DB_HOST to a dedicated local MySQL test database")
    browser = os.environ.get("CHROME_BIN") or shutil.which("google-chrome") or shutil.which("chromium")
    if not browser:
        parser.error("Set CHROME_BIN to a Chromium or Google Chrome executable")
    php = os.environ.get("PHP_BIN", "php")
    with ExitStack() as stack:
        temp = stack.enter_context(TemporaryDirectory(prefix="bulsca-portal-test-"))
        provider = FakeAuthentik(f"manager-{secrets.token_hex(8)}@example.test")
        stack.callback(provider.server_close)
        port = available_port()
        origin = f"http://127.0.0.1:{port}"
        provider.callback = origin + "/auth/sso/callback"
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        stack.callback(provider.shutdown)
        backend_port = available_port()
        while backend_port == port:
            backend_port = available_port()
        backend_origin = f"http://127.0.0.1:{backend_port}"
        env = {
            **os.environ, "APP_ENV": "testing", "APP_URL": origin, "APP_DEBUG": "false",
            "APP_KEY": "base64:" + base64.b64encode(secrets.token_bytes(32)).decode(),
            "APP_CONFIG_CACHE": temp + "/config.php", "DB_CONNECTION": "mysql",
            "SESSION_DRIVER": "file", "SESSION_SECURE_COOKIE": "false", "SESSION_DOMAIN": "null",
            "SESSION_COOKIE": "portal_browser_session", "SANCTUM_STATEFUL_DOMAINS": f"127.0.0.1:{port}",
            "AUTHENTIK_ENABLED": "true", "AUTHENTIK_BASE_URL": provider.origin,
            "AUTHENTIK_ISSUER": provider.issuer, "AUTHENTIK_CLIENT_ID": provider.client_id,
            "AUTHENTIK_CLIENT_SECRET": provider.secret, "AUTHENTIK_REDIRECT_URI": provider.callback,
            "CACHE_DRIVER": "array", "CACHE_STORE": "array", "MAIL_MAILER": "array", "QUEUE_CONNECTION": "sync",
            "META_ACCESS_TOKEN": "null", "META_USER_ID": "null", "PUBLIC_INTEGRATION_DIRECTORY": temp,
            "VITE_BACKEND_ORIGIN": backend_origin, "VITE_PORTAL_API_URL": "/api/v1/portal",
        }

        def fixture(*arguments):
            return subprocess.check_output([php, FIXTURE, *arguments], cwd=backend, env=env, text=True)

        fixture("migrate")
        stack.enter_context(server([php, "-S", f"127.0.0.1:{backend_port}", "-t", "public", "public/index.php"],
                                   backend, env, backend_origin + "/api/v1/me", 401, "application/json"))
        stack.enter_context(server(["node", "node_modules/vite/bin/vite.js", "--port", str(port)],
                                   PORTAL, env, origin, 200, "text/html"))
        runner = stack.enter_context(sync_playwright())
        chromium = runner.chromium.launch(executable_path=browser)
        stack.callback(chromium.close)
        context = chromium.new_context()
        context.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).hostname == "127.0.0.1"
                      else route.abort())
        exercise(context.new_page(), origin, provider, fixture)
    print("Passed portal browser acceptance: sign-in, identity, club membership, cross-club denial, CSRF and logout.")


if __name__ == "__main__":
    main()
