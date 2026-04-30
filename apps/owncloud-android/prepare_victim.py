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
    print(f"[prepare_victim] {message}", file=sys.stderr, flush=True)


_anr_d = None


def _dismiss_system_anr(d=None) -> bool:
    """Click "Wait" on a foregrounded AppErrorDialog if one is up.

    Slow CI runners frequently ANR a system app (Pixel Launcher, System
    UI, Gmail, chrome) at unpredictable points in the OAuth flow. The
    OS overlays AppErrorDialog (resource-id ``android:id/aerr_wait``
    for the Wait button) over every window, blocks Activity
    transitions, and the chrome customtab can't come to foreground —
    failures surface seconds-to-minutes later as either ``Chrome OAuth
    flow not active`` or ``OAuth username/password fields not found``.

    A uia2 watcher is also registered in main() against the same Wait
    button, but its async RPC queue can starve behind main-thread
    queries on a 2-fps emulator. Doing the dismiss inline in
    ``wait_until`` at our own tick rate guarantees the cadence
    regardless of emulator load. This helper is also called from
    bespoke polling loops in ``submit_web_login`` that don't go
    through ``wait_until``.

    ``d`` may be passed (cheap, the caller already has a connection)
    or omitted (lazy module-level cache; reset on RPC error so a
    transient connectivity blip self-heals). Returns True if a Wait
    button was clicked, False otherwise.
    """
    global _anr_d
    try:
        if d is None:
            if _anr_d is None:
                _anr_d = u2.connect()
            d = _anr_d
        wait_btn = d(resourceId="android:id/aerr_wait")
        if not wait_btn.exists:
            return False
        # Read the dialog title so the log says WHICH app ANR'd. Useful
        # for diagnostics — Pixel Launcher vs chrome vs Gmail point at
        # different runner-load symptoms.
        title = ""
        try:
            t = d(resourceId="android:id/alertTitle")
            if t.exists:
                title = (t.get_text() or "").strip()
        except Exception:
            pass
        wait_btn.click()
        log(f"ANR dismissed: {title or '<unknown title>'}")
        return True
    except Exception:
        _anr_d = None  # force reconnect on next call
        return False


def wait_until(check, timeout=30, interval=0.5):
    """Poll for ``check()`` truthy, dismissing system ANR dialogs each tick.

    The ANR dismiss runs unconditionally on every tick (cheap no-op when
    no dialog is up). Doing it here means every ``require`` call
    inherits ANR resilience — callers don't need to remember.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        _dismiss_system_anr()
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
    """Poll for the intro-screen skip button until it renders or the URL input appears.

    The intro-screen ("WhatsNew") is shown on first launch only; if the
    APK has been launched before during this emulator boot, hostUrlInput
    appears directly. Both paths log explicitly so a future flake here
    has a clear signal which branch we took.
    """
    log(f"WhatsNew: entering | pkg={current_package(d)}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        _dismiss_system_anr(d)
        if d(resourceId=f"{APP}:id/hostUrlInput").exists:
            log("WhatsNew: hostUrlInput visible — no intro screen, returning")
            return
        skip = d(resourceId=f"{APP}:id/skip")
        if skip.exists:
            log("WhatsNew: skip button visible — clicking")
            skip.click()
            time.sleep(1)
            log(f"WhatsNew: post-skip pkg={current_package(d)}")
            return
        time.sleep(0.5)
    log(
        f"WhatsNew: deadline reached after {timeout}s — neither hostUrlInput nor skip seen"
    )


def submit_server_url(d, server_url):
    log(f"submit_server_url: entering | pkg={current_package(d)}")
    if not d(resourceId=f"{APP}:id/hostUrlInput").exists:
        log("submit_server_url: hostUrlInput not present, returning")
        return

    log(f"submit_server_url: typing URL {server_url}")
    d(resourceId=f"{APP}:id/hostUrlInput").set_text(server_url)
    time.sleep(0.5)
    log("submit_server_url: clicking embeddedCheckServerButton")
    d(resourceId=f"{APP}:id/embeddedCheckServerButton").click()

    # Chrome cold-start can be slow on a CI emulator; give it room.
    # wait_until's per-tick ANR dismiss covers any system dialog that
    # lands on top during the wait.
    log("submit_server_url: waiting for chrome customtab or already-logged-in state")
    require(
        lambda: current_package(d) == CHROME or is_logged_in(d),
        "Chrome OAuth flow did not open",
        timeout=60,
    )
    log(f"submit_server_url: post-wait pkg={current_package(d)}")


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
    """Drive the chrome-customtab OAuth login form.

    Three-stage wait, each with explicit ANR dismiss + chrome-FRE drain:

      1. Wait for the Login button to render (HTML form has loaded).
      2. Wait for the EditText input fields to register in chrome's
         accessibility tree. They land slightly later than the Login
         button on cold customtabs — the button can register while
         <input> elements are still being processed by chrome's a11y
         walker. Querying immediately after the button found 0 fields
         and tripped a 'OAuth username/password fields not found'
         flake.
      3. After submit, wait for the Authorize page (chrome's a11y tree
         needs to update again post-form-submit).
    """
    log(f"web_login: entering | pkg={current_package(d)}")
    if d(text="Authorize", className="android.widget.Button").exists:
        log("web_login: Authorize page already visible (cached session?), returning")
        return

    # Stage 1: wait for Login button. Drains late chrome FRE nags each tick
    # since CI cold-loads can let new nags arrive throughout the wait.
    log("web_login: stage 1/3 — waiting for Login button + draining FRE nags")
    deadline = time.time() + 120
    while time.time() < deadline:
        _dismiss_system_anr(d)
        if d(text="Login", className="android.widget.Button").exists:
            log("web_login: Login button visible")
            break
        _click_first_present(d, CHROME_FIRST_RUN_DISMISSALS)
        time.sleep(1)
    else:
        raise RuntimeError("OAuth login page not visible")

    # Stage 2: wait for EditText fields to register in a11y tree.
    log("web_login: stage 2/3 — waiting for EditText fields")
    fields_deadline = time.time() + 30
    fields_count = 0
    while time.time() < fields_deadline:
        _dismiss_system_anr(d)
        fields = d(className="android.widget.EditText")
        fields_count = fields.count
        if fields_count >= 2:
            log(f"web_login: {fields_count} EditText field(s) registered")
            break
        time.sleep(0.5)
    else:
        raise RuntimeError(
            f"OAuth username/password fields not found (saw {fields_count}; expected >=2)"
        )

    log(f"web_login: filling username={username!r}")
    fields = d(className="android.widget.EditText")  # re-resolve, safer
    fields[0].set_text(username)
    time.sleep(0.3)
    log("web_login: filling password (redacted)")
    fields[1].set_text(password)
    time.sleep(0.3)
    log("web_login: clicking Login")
    d(text="Login", className="android.widget.Button").click()

    # Stage 3: wait for Authorize page. Bumped from 30s → 60s — slow
    # render on the same a11y-tree-lag class of issue as stage 2.
    log("web_login: stage 3/3 — waiting for Authorize page")
    require(
        lambda: d(text="Authorize", className="android.widget.Button").exists,
        "OAuth authorize page not visible",
        timeout=60,
    )
    log("web_login: Authorize page reached")


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


def _connect_uia2_with_retry(max_attempts=5):
    """Establish a uia2 connection that survives a transient atx-agent drop.

    The on-device atx-agent (uia2's REST endpoint) sometimes drops the next
    connection right after a previous prepare_victim exits — observed as
    ``urllib3.exceptions.ProtocolError: Remote end closed connection
    without response`` on the very first ``d.press`` or ``d.app_current``
    call after ``u2.connect()`` returned successfully. healthcheck() makes
    uia2 re-handshake; retrying covers the case where the first
    healthcheck itself raises.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            d = u2.connect()
            # Sanity probe: any small RPC exercising the same code path the
            # rest of main() will use. If atx-agent is in a half-dropped
            # state, this raises ``Remote end closed connection without
            # response`` and we reconnect.
            _ = d.app_current()
            log(f"uia2 connected (attempt {attempt})")
            return d
        except Exception as e:
            last_exc = e
            log(f"uia2 connect attempt {attempt}/{max_attempts} failed: {e}")
            time.sleep(1.5)
    raise RuntimeError(f"uia2 connect failed after {max_attempts} attempts: {last_exc}")


def main():
    args = parse_args()
    d = _connect_uia2_with_retry()

    # Belt-and-suspenders for ANR dismissal. The primary defense lives in
    # wait_until's per-tick `_dismiss_system_anr` call; this watcher is
    # an async backstop polling for a "Wait" text element on a 0.5s
    # interval. On a heavily-loaded runner the watcher's RPC can starve
    # behind main-thread queries, which is why wait_until does its own
    # synchronous dismiss — but the watcher still helps when the dialog
    # appears between two main-thread sleeps.
    d.watcher.when("Wait").click()
    d.watcher.start(0.5)

    # Pre-grant POST_NOTIFICATIONS so FileDisplayActivity doesn't pop the
    # GrantPermissionsActivity dialog mid-lifecycle and crash. start_runtime
    # already does `adb install -g`, but `pm clear` between synthetic_vuln
    # phases wipes runtime grants — this re-grants idempotently each run.
    # Mirrors apps/moodle/start_runtime.sh:108 and apps/ntfy-android/start_runtime.sh:56.
    subprocess.run(
        ["adb", "shell", "pm", "grant", APP, "android.permission.POST_NOTIFICATIONS"],
        check=False,
    )

    # Press HOME first to clear any leftover task that might hold foreground
    # across a `pm clear` of ownCloud. The most common offender is chrome
    # customtab — its OAuth-Authorize task survives `pm clear` of ownCloud,
    # and a subsequent ``app_start(APP, wait=True)`` can return before
    # ownCloud actually reaches foreground (uia2's app_wait polls for 20s
    # then returns silently). Without HOME, the next handle_whats_new poll
    # runs against chrome's UI looking for ownCloud's selectors — finds
    # nothing, times out 60s later, and the rest of the script wedges.
    #
    # Both HOME and app_start go through ``adb shell`` directly rather
    # than ``d.press`` / ``d.app_start``: uia2's atx-agent on the device
    # sometimes drops the next REST call right after a HOME keypress on
    # rapid back-to-back invocations (observed locally as
    # ``urllib3.exceptions.ProtocolError: Remote end closed connection
    # without response`` on the very next ``current_package`` call).
    # Going via adb keeps the keyevent / activity launch on a separate
    # transport.
    log(f"stage: pre-launch | pkg={current_package(d)} — sending HOME via adb")
    subprocess.run(
        ["adb", "shell", "input", "keyevent", "KEYCODE_HOME"], check=False
    )
    time.sleep(1)
    log(f"stage: launch | pkg={current_package(d)} — am start ownCloud")
    subprocess.run(
        ["adb", "shell", "am", "start", "-W", "-n", f"{APP}/.ui.activity.SplashActivity"],
        check=False,
    )
    # Explicit foreground wait. wait_until's per-tick ANR dismiss covers
    # any system dialog that lands on top during the launch transition.
    require(
        lambda: current_package(d) == APP,
        "ownCloud did not reach foreground after am start",
        timeout=30,
    )
    log(f"stage: post-launch | pkg={current_package(d)} | logged_in={is_logged_in(d)}")

    if is_logged_in(d):
        log("already logged in — skipping OAuth flow")
    else:
        log("stage: handle whats-new")
        handle_whats_new(d)
        log("stage: submit server URL")
        submit_server_url(d, args.server_url)

        if not is_logged_in(d):
            log("stage: wait for chrome OAuth foreground")
            require(
                lambda: current_package(d) == CHROME,
                "Chrome OAuth flow not active",
                timeout=90,
            )
            log(f"stage: chrome FRE drain | pkg={current_package(d)}")
            handle_chrome_first_run(d)
            log("stage: web login (3-stage form fill)")
            submit_web_login(d, args.username, args.password)
            log("stage: authorize app")
            authorize_app(d)

        log("SUCCESS: alex logged in")

    log("stage: wait_for_settle (DB-stable signal)")
    wait_for_settle()
    log("stage: capture baselines")
    capture_baselines()
    log("stage: done")


def _dump_state_on_error():
    """One-shot failure diagnostic. Captures everything needed to RCA the OAuth/UI/DB
    transition that failed, so a single failed CI run is enough to fix without burning
    another cycle. Sections (each ~bounded, total ~500 lines): foreground+UI, ownCloud
    logcat (UID-filtered), crash buffer, activity task stack, AccountManager dump,
    DB file/tables listing, and live processes for owncloud + chrome.
    """
    try:
        d = u2.connect()
        log(f"state: app_current={d.app_current()}")
        xml = d.dump_hierarchy()

        # Resource-id roster: compact list of which UI elements are present.
        ids = []
        for rid in re.findall(r'resource-id="([^"]+)"', xml):
            if rid and rid not in ids:
                ids.append(rid)
            if len(ids) >= 60:
                break
        log(f"state: visible={ids}")

        # Visible text + content-desc paired with the owning resource-id.
        # The id-only list above can't distinguish "cert dialog" from
        # "basic-auth fallback" from "stuck on LoginActivity post-submit"
        # because all three surface the same generic AlertDialog ids
        # (parentPanel, alertTitle, button1...). The actual dialog
        # title/message/button labels live in the text attribute and are
        # what tells the failure modes apart.
        pairs = []
        for m in re.finditer(r"<node\b[^>]*?>", xml):
            node = m.group()
            rid_m = re.search(r'resource-id="([^"]*)"', node)
            rid = rid_m.group(1) if rid_m else ""
            for attr in ("text", "content-desc"):
                am = re.search(rf'\b{attr}="([^"]+)"', node)
                if am:
                    pairs.append(f"{rid or attr}={am.group(1)!r}")
            if len(pairs) >= 60:
                break
        if pairs:
            log(f"state: text={pairs}")
    except Exception as e:
        log(f"state: dump failed: {e}")

    def _section(name, fn):
        log(f"--- {name} ---")
        try:
            fn()
        except Exception as e:
            log(f"{name}: dump failed: {e}")

    def _logcat_owncloud():
        # UID-filtered (vs PID) so historical lines from before any crash are kept.
        # `--uid` requires root; non-root logcat clients can only filter by self UID.
        uid = probe_lib._owncloud_uid()
        if not uid:
            print("[ocl] no UID resolved (package not installed?)", file=sys.stderr)
            return
        out = probe_lib.adb_su(f"logcat -d -b all --uid={uid} -t 300")
        for line in out.splitlines():
            print(f"[ocl] {line}", file=sys.stderr)

    def _logcat_crash():
        out = subprocess.check_output(
            ["adb", "logcat", "-d", "-b", "crash"], text=True, errors="replace"
        )
        for line in out.splitlines()[-100:]:
            print(f"[crash] {line}", file=sys.stderr)

    def _activity_stack():
        out = subprocess.check_output(
            ["adb", "shell", "dumpsys", "activity", "activities"], text=True
        )
        for line in out.splitlines():
            if (
                any(
                    k in line
                    for k in (
                        "Task{",
                        "Hist #",
                        "mResumedActivity",
                        "mFocusedActivity",
                        "Running activities",
                    )
                )
                or "owncloud" in line
                or "chrome" in line
            ):
                print(f"[act] {line.rstrip()}", file=sys.stderr)

    def _account_state():
        out = subprocess.check_output(["adb", "shell", "dumpsys", "account"], text=True)
        for line in out.splitlines():
            if "owncloud" in line.lower() or "Account {" in line:
                print(f"[acct] {line.rstrip()}", file=sys.stderr)

    def _db_state():
        ls = probe_lib.adb_su(f"ls -la {probe_lib.DATA_DIR}/databases/ 2>&1")
        for line in ls.splitlines():
            print(f"[db] {line}", file=sys.stderr)
        tables = probe_lib.adb_su(f"sqlite3 {probe_lib.DB_PATH} '.tables' 2>&1")
        print(f"[db] tables: {tables}", file=sys.stderr)

    def _processes():
        out = subprocess.check_output(
            ["adb", "shell", "ps", "-A", "-o", "PID,USER,NAME"], text=True
        )
        for line in out.splitlines():
            if "owncloud" in line.lower() or "chrome" in line.lower():
                print(f"[ps] {line.rstrip()}", file=sys.stderr)

    _section("logcat owncloud (uid-filtered, last 300)", _logcat_owncloud)
    _section("logcat crash buffer", _logcat_crash)
    _section("activity task stack", _activity_stack)
    _section("dumpsys account (owncloud)", _account_state)
    _section("DB state", _db_state)
    _section("processes (owncloud + chrome)", _processes)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {exc}")
        _dump_state_on_error()
        sys.exit(1)
