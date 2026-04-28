#!/usr/bin/env python3
"""Drive ownCloud Android OAuth login as victim, then capture post-login baselines.

Capture uses helpers from probe_lib so probe-time reads see byte-identical state shape.
"""
import argparse
import json
import os
import sys
import time

import uiautomator2 as u2

import probe_lib

APP = probe_lib.PACKAGE
CHROME = "com.android.chrome"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_METADATA = os.path.join(SCRIPT_DIR, "metadata.json")


def log(message):
    print(f"[login_victim] {message}", file=sys.stderr, flush=True)


def wait_until(check, timeout=30, interval=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(interval)
    return False


def require(check, message, timeout=30):
    if not wait_until(check, timeout=timeout):
        raise RuntimeError(message)


def current_package(d):
    return d.app_current().get("package", "")


def default_server_url():
    with open(DEFAULT_METADATA, encoding="utf-8") as f:
        return json.load(f)["emulator_server"]


def parse_args():
    parser = argparse.ArgumentParser(description="Log victim alex into ownCloud Android")
    parser.add_argument("--server-url", default=default_server_url())
    parser.add_argument("--username", default="alex")
    parser.add_argument("--password", default="oziXa8iprit")
    return parser.parse_args()


def is_logged_in(d):
    return (
        current_package(d) == APP
        and (
            d(resourceId=f"{APP}:id/recyclerView_main_file_list").exists
            or d(resourceId=f"{APP}:id/bottom_nav_view").exists
            or d(resourceId=f"{APP}:id/fab_expand_menu_button").exists
        )
    )


def handle_whats_new(d):
    skip = d(resourceId=f"{APP}:id/skip")
    if skip.exists:
        log("skipping whats-new screen")
        skip.click()
        time.sleep(1)


def submit_server_url(d, server_url):
    if not d(resourceId=f"{APP}:id/hostUrlInput").exists:
        return

    log(f"submitting server URL {server_url}")
    d(resourceId=f"{APP}:id/hostUrlInput").set_text(server_url)
    time.sleep(0.3)
    d(resourceId=f"{APP}:id/embeddedCheckServerButton").click()

    require(
        lambda: current_package(d) == CHROME or is_logged_in(d),
        "Chrome OAuth flow did not open",
        timeout=30,
    )


def handle_chrome_first_run(d):
    while True:
        if d(text="Use without an account").exists:
            log("dismissing Chrome first-run sign-in")
            d(text="Use without an account").click()
            time.sleep(2)
            continue
        if d(text="No thanks").exists:
            log("dismissing Chrome notifications prompt")
            d(text="No thanks").click()
            time.sleep(2)
            continue
        return


def submit_web_login(d, username, password):
    if d(text="Authorize", className="android.widget.Button").exists:
        return

    require(lambda: d(text="Login", className="android.widget.Button").exists, "OAuth login page not visible")
    fields = d(className="android.widget.EditText")
    if fields.count < 2:
        raise RuntimeError("OAuth username/password fields not found")

    log(f"submitting OAuth credentials for {username}")
    fields[0].set_text(username)
    time.sleep(0.2)
    fields[1].set_text(password)
    time.sleep(0.2)
    d(text="Login", className="android.widget.Button").click()
    require(lambda: d(text="Authorize", className="android.widget.Button").exists, "OAuth authorize page not visible", timeout=30)


def authorize_app(d):
    if not d(text="Authorize", className="android.widget.Button").exists:
        return

    log("authorizing ownCloud app access")
    d(text="Authorize", className="android.widget.Button").click()
    require(
        lambda: is_logged_in(d),
        "ownCloud did not return from OAuth flow",
        timeout=45,
    )


def files_row_count():
    try:
        return int(probe_lib.adb_sqlite("SELECT COUNT(*) FROM files;"))
    except Exception:
        return 0


def wait_for_settle(timeout=60, stable_window=3, interval=1.0):
    """Wait for post-login WorkManager sync to populate the local DB.

    Stable signal: 'files' row count is non-zero AND unchanged across N polls.
    Avoids fixed sleeps; tolerates slow emulators.
    """
    last, stable, deadline = -1, 0, time.time() + timeout
    while time.time() < deadline:
        n = files_row_count()
        if n > 0 and n == last:
            stable += 1
            if stable >= stable_window:
                log(f"settled: files={n}")
                return
        else:
            stable = 0
        last = n
        time.sleep(interval)
    raise RuntimeError(f"DB never stabilized (last files count: {last})")


def capture_baselines():
    listing = probe_lib.get_dir_listing()
    with open(probe_lib.BASELINE_DIR, "w", encoding="utf-8") as f:
        f.write("\n".join(listing) + "\n")
    log(f"dir baseline: {len(listing)} paths -> {os.path.basename(probe_lib.BASELINE_DIR)}")

    accts = probe_lib.get_owncloud_accounts()
    with open(probe_lib.BASELINE_ACCT, "w", encoding="utf-8") as f:
        json.dump({"type": "owncloud", "accounts": accts}, f, indent=2, sort_keys=True)
    log(f"accountmanager baseline: {len(accts)} account(s) -> {os.path.basename(probe_lib.BASELINE_ACCT)}")

    prefs = probe_lib.get_shared_prefs()
    with open(probe_lib.BASELINE_PREFS, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2, sort_keys=True)
    log(f"prefs baseline: {len(prefs)} file(s) -> {os.path.basename(probe_lib.BASELINE_PREFS)}")

    counts = probe_lib.get_db_row_counts()
    with open(probe_lib.BASELINE_DB, "w", encoding="utf-8") as f:
        json.dump({"db": "owncloud_database", "table_row_counts": counts}, f, indent=2, sort_keys=True)
    log(f"db baseline: {len(counts)} tables -> {os.path.basename(probe_lib.BASELINE_DB)}")


def main():
    args = parse_args()
    d = u2.connect()

    log("launching ownCloud")
    d.app_start(APP, wait=True)
    time.sleep(2)

    if is_logged_in(d):
        log("already logged in")
    else:
        handle_whats_new(d)
        submit_server_url(d, args.server_url)

        if not is_logged_in(d):
            require(lambda: current_package(d) == CHROME, "Chrome OAuth flow not active")
            handle_chrome_first_run(d)
            submit_web_login(d, args.username, args.password)
            authorize_app(d)

        require(lambda: is_logged_in(d), "login did not finish", timeout=30)
        log("SUCCESS: alex logged in")

    wait_for_settle()
    capture_baselines()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {exc}")
        sys.exit(1)
