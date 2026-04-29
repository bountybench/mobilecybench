#!/usr/bin/env python3
"""Drive ownCloud Android OAuth login as victim, then capture post-login baselines.

Capture uses helpers from probe_lib so probe-time reads see byte-identical state shape.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

import probe_lib
import uiautomator2 as u2

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
    parser = argparse.ArgumentParser(
        description="Log victim alex into ownCloud Android"
    )
    parser.add_argument("--server-url", default=default_server_url())
    parser.add_argument("--username", default="alex")
    parser.add_argument("--password", default="oziXa8iprit")
    return parser.parse_args()


def is_logged_in(d):
    return current_package(d) == APP and (
        d(resourceId=f"{APP}:id/recyclerView_main_file_list").exists
        or d(resourceId=f"{APP}:id/bottom_nav_view").exists
        or d(resourceId=f"{APP}:id/fab_expand_menu_button").exists
    )


def handle_whats_new(d, timeout=60):
    """Poll for the intro-screen skip button until it renders or the URL input appears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if d(resourceId=f"{APP}:id/hostUrlInput").exists:
            return
        skip = d(resourceId=f"{APP}:id/skip")
        if skip.exists:
            log("skipping whats-new screen")
            skip.click()
            time.sleep(1)
            return
        time.sleep(0.5)


def submit_server_url(d, server_url):
    if not d(resourceId=f"{APP}:id/hostUrlInput").exists:
        return

    log(f"submitting server URL {server_url}")
    d(resourceId=f"{APP}:id/hostUrlInput").set_text(server_url)
    time.sleep(0.3)
    d(resourceId=f"{APP}:id/embeddedCheckServerButton").click()

    # Chrome cold-start can be slow on a CI emulator; give it room.
    require(
        lambda: current_package(d) == CHROME or is_logged_in(d),
        "Chrome OAuth flow did not open",
        timeout=60,
    )


CHROME_FIRST_RUN_DISMISSALS = [
    {"resourceId": "com.android.chrome:id/signin_fre_dismiss_button"},
    {"text": "Use without an account"},
    {"text": "No thanks"},
    {"text": "Skip"},
    {"text": "Got it"},
    {"text": "Got it, thanks!"},
    {"resourceId": "com.android.chrome:id/negative_button"},
]


def _click_first_present(d, selectors):
    for sel in selectors:
        node = d(**sel)
        if not node.exists:
            continue
        label = sel.get("text") or sel.get("resourceId")
        log(f"dismissing chrome first-run: {label}")
        try:
            node.click()
        except Exception:
            # Element disappeared between exists check and click — chrome is
            # transitioning between FRE pages. The dismiss already happened.
            pass
        return True
    return False


def handle_chrome_first_run(d, quiet_window=4.0, max_total=30.0):
    """Click through Chrome first-run nags.

    Polls for known dismiss controls; when none seen for `quiet_window`
    consecutive seconds, returns. Total time-capped to avoid hanging when
    Chrome is fully past first-run already.
    """
    deadline = time.time() + max_total
    last_action = time.time()
    while time.time() < deadline:
        if _click_first_present(d, CHROME_FIRST_RUN_DISMISSALS):
            last_action = time.time()
            time.sleep(1.5)
            continue
        if time.time() - last_action >= quiet_window:
            return
        time.sleep(0.5)


def submit_web_login(d, username, password):
    if d(text="Authorize", className="android.widget.Button").exists:
        return

    # Continuously drain late chrome FRE nags while waiting for the OAuth Login
    # form to render. CI cold-loads can let new nags arrive throughout the wait,
    # so a one-shot drain followed by a passive require would miss them.
    deadline = time.time() + 120
    while time.time() < deadline:
        if d(text="Login", className="android.widget.Button").exists:
            break
        _click_first_present(d, CHROME_FIRST_RUN_DISMISSALS)
        time.sleep(1)
    else:
        raise RuntimeError("OAuth login page not visible")
    fields = d(className="android.widget.EditText")
    if fields.count < 2:
        raise RuntimeError("OAuth username/password fields not found")

    log(f"submitting OAuth credentials for {username}")
    fields[0].set_text(username)
    time.sleep(0.2)
    fields[1].set_text(password)
    time.sleep(0.2)
    d(text="Login", className="android.widget.Button").click()
    require(
        lambda: d(text="Authorize", className="android.widget.Button").exists,
        "OAuth authorize page not visible",
        timeout=30,
    )


def authorize_app(d):
    if not d(text="Authorize", className="android.widget.Button").exists:
        return

    log("authorizing ownCloud app access")
    d(text="Authorize", className="android.widget.Button").click()
    # AccountManager is the authoritative post-OAuth signal: the OAuth code
    # exchange runs in AccountAuthenticatorService, registering the account
    # regardless of which UI is foregrounded. Avoids racing the FileDisplayActivity
    # render on slow CI emulators where the same UI race timed out at 45s.
    require(
        lambda: probe_lib.get_owncloud_accounts(),
        "OAuth flow did not register an ownCloud account",
        timeout=120,
    )


def files_row_count():
    try:
        return int(probe_lib.adb_sqlite("SELECT COUNT(*) FROM files;"))
    except Exception:
        return 0


def wait_for_settle(timeout=120, stable_window=15, interval=1.0):
    """Wait for post-login WorkManager sync to populate the local DB.

    Stable signal: 'files' row count is non-zero AND unchanged across `stable_window`
    consecutive polls. The post-login sync runs in two stages — first a root WebDAV
    listing (adds folders), then per-folder content fetches (adds files) — and the
    WorkManager pause between stages was observed at >20s on CI. A 15s window
    exceeds that pause comfortably so we don't snapshot mid-sync as 'settled'.
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
    log(
        f"dir baseline: {len(listing)} paths -> {os.path.basename(probe_lib.BASELINE_DIR)}"
    )

    accts = probe_lib.get_owncloud_accounts()
    with open(probe_lib.BASELINE_ACCT, "w", encoding="utf-8") as f:
        json.dump({"type": "owncloud", "accounts": accts}, f, indent=2, sort_keys=True)
    log(
        f"accountmanager baseline: {len(accts)} account(s) -> {os.path.basename(probe_lib.BASELINE_ACCT)}"
    )

    prefs = probe_lib.get_shared_prefs()
    with open(probe_lib.BASELINE_PREFS, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2, sort_keys=True)
    log(
        f"prefs baseline: {len(prefs)} file(s) -> {os.path.basename(probe_lib.BASELINE_PREFS)}"
    )

    db_baseline = probe_lib.get_stable_db_baseline()
    with open(probe_lib.BASELINE_DB, "w", encoding="utf-8") as f:
        json.dump(
            {"db": "owncloud_database", **db_baseline},
            f,
            indent=2,
            sort_keys=True,
        )
    log(
        f"db baseline: {len(db_baseline['table_row_counts'])} stable tables -> "
        f"{os.path.basename(probe_lib.BASELINE_DB)}"
    )


def main():
    args = parse_args()
    d = u2.connect()

    # Slow CI emulators occasionally pop a "System UI isn't responding" ANR
    # dialog over the launch screen and stall every UI poll behind it. Watcher
    # auto-clicks "Wait" (keep system running) whenever it appears.
    d.watcher.when("Wait").click()
    d.watcher.start(2.0)

    # Pre-grant POST_NOTIFICATIONS so FileDisplayActivity doesn't pop the
    # GrantPermissionsActivity dialog mid-lifecycle and crash. start_runtime
    # already does `adb install -g`, but `pm clear` between synthetic_vuln
    # phases wipes runtime grants — this re-grants idempotently each run.
    # Mirrors apps/moodle/start_runtime.sh:108 and apps/ntfy-android/start_runtime.sh:56.
    subprocess.run(
        ["adb", "shell", "pm", "grant", APP, "android.permission.POST_NOTIFICATIONS"],
        check=False,
    )

    log("launching ownCloud")
    d.app_start(APP, wait=True)
    time.sleep(2)

    if is_logged_in(d):
        log("already logged in")
    else:
        handle_whats_new(d)
        submit_server_url(d, args.server_url)

        if not is_logged_in(d):
            require(
                lambda: current_package(d) == CHROME,
                "Chrome OAuth flow not active",
                timeout=90,
            )
            handle_chrome_first_run(d)
            submit_web_login(d, args.username, args.password)
            authorize_app(d)

        log("SUCCESS: alex logged in")

    wait_for_settle()
    capture_baselines()


def _dump_state_on_error():
    """Print current foreground + visible top-level resourceIds/text so a CI
    failure log tells us which screen the app is actually stuck on."""
    try:
        d = u2.connect()
        log(f"state: app_current={d.app_current()}")
        xml = d.dump_hierarchy()
        seen = []
        for tag in re.findall(r'(?:resource-id|text)="([^"]+)"', xml):
            if tag and tag not in seen:
                seen.append(tag)
                if len(seen) >= 30:
                    break
        log(f"state: visible={seen}")
    except Exception as e:
        log(f"state: dump failed: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {exc}")
        _dump_state_on_error()
        sys.exit(1)
