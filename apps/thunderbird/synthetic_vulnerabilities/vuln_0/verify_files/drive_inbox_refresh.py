#!/usr/bin/env python3
"""Drive Thunderbird mailbox sync via the navigation drawer refresh path.

This is intentionally aligned to the vendored Thunderbird code in this repo:

- `apps/thunderbird/codebase/legacy/ui/legacy/src/main/java/com/fsck/k9/activity/MessageList.kt`
  enables the action bar home affordance and handles `android.R.id.home` by
  opening the navigation drawer.
- Both drawer implementations wrap their content in `PullToRefreshBox` with
  `onRefresh = OnSyncAccount`, and expose the drawer root via
  `testTagAsResourceId("DrawerContent")`.
- The drawer action label is defined in the drawer feature resources as
  `Sync all accounts` and wired in
  `apps/thunderbird/codebase/feature/navigation/drawer/dropdown/src/main/kotlin/net/thunderbird/feature/navigation/drawer/dropdown/ui/setting/AccountSettingList.kt`
  and
  `apps/thunderbird/codebase/feature/navigation/drawer/siderail/src/main/kotlin/net/thunderbird/feature/navigation/drawer/siderail/ui/account/AccountList.kt`.
- `DrawerViewModel.onSyncAccount()` calls
  `messagingController.checkMail(account, ignoreLastCheckedTime=true, ...)`,
  which is the real UI-backed sync path for the selected account.

So the correct automation target is the drawer sync action, backed by the app's
own UI helper layer and real selectors, not the inbox list refresh gesture.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
APP_DIR = Path(__file__).resolve().parents[3]
META_JSON = APP_DIR / "metadata.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

APP_PKG = os.environ["PKG"]
ATTEMPT = os.environ.get("TB_REFRESH_ATTEMPT", "?")
os.environ.setdefault("UI_TARGET_PACKAGE", APP_PKG)

try:
    _META = json.loads(META_JSON.read_text())
except Exception:
    _META = {}
ACCOUNT_DISPLAY_NAME = os.environ.get(
    "TB_ACCOUNT_DISPLAY_NAME",
    _META.get("additional_info", {})
    .get("account_config", {})
    .get("display_name", "User A"),
)
ACCOUNT_EMAIL = os.environ.get(
    "TB_ACCOUNT_EMAIL",
    _META.get("username", "usera@test.com"),
)

from utils.ui_utils import (  # noqa: E402
    click_then_expect,
    initialize_ui_automation,
    wait_and_click,
    wait_for_ui_stable,
)

# Post-sync wait: allow time for IMAP fetch, DB write, and notification posting.
_POST_SYNC_WAIT_SECS = 20


def _rid(name: str) -> str:
    return rf"(.*:id/)?{name}"


def _adb(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def _current_screen(d) -> str:
    try:
        app = d.app_current() or {}
    except Exception as exc:
        return f"<unknown> ({exc})"
    return f"{app.get('package', '<none>')}/{app.get('activity', '<none>')}"


def _launch_inbox() -> None:
    _adb("shell", "input", "keyevent", "KEYCODE_WAKEUP", check=False)
    _adb("shell", "wm", "dismiss-keyguard", check=False)
    # Launch through the exported LAUNCHER entrypoint. MainActivity then routes
    # to MessageHomeActivity once account setup is complete.
    _adb(
        "shell", "monkey", "-p", APP_PKG, "-c", "android.intent.category.LAUNCHER", "1"
    )


def _ensure_app_foreground(d) -> None:
    # `monkey` can leave the fake launcher visible on some emulator boots even
    # when Thunderbird is already installed, so force the app task into the
    # foreground before waiting for the message list.
    d.app_start(APP_PKG, stop=True, wait=True, use_monkey=True)
    wait_for_ui_stable(d)


def _wait_for_inbox_ready(d, timeout: float = 45.0) -> None:
    """Wait until the inbox screen is ready for drawer-based sync automation."""
    msg_list = d(resourceIdMatches=_rid("message_list"))
    end = time.time() + timeout
    while time.time() < end:
        app = d.app_current() or {}
        if app.get("package") == APP_PKG and msg_list.exists:
            return
        time.sleep(0.5)
    raise RuntimeError(
        f"message list not ready after {timeout:.0f}s; screen={_current_screen(d)}"
    )


def _drawer_content(d):
    return d(resourceIdMatches=_rid("DrawerContent"))


def _drawer_is_open(d) -> bool:
    drawer = _drawer_content(d)
    if not drawer.exists:
        return False

    info = drawer.info or {}
    bounds = info.get("visibleBounds") or info.get("bounds") or {}
    left = int(bounds.get("left", -1))
    right = int(bounds.get("right", -1))
    return left >= 0 and right > left


def _open_navigation_drawer(d, timeout: float = 15.0) -> None:
    if _drawer_is_open(d):
        return

    # The actual drawer opener is the app bar home/up affordance from
    # MessageList.kt, but its accessibility node is framework-generated rather
    # than app-defined. Try the most stable selectors first, then the exposed
    # content description labels, then the edge-swipe fallback.
    for name in ("home", "up"):
        try:
            nav = d(resourceIdMatches=rf"(^|.*:)id/{name}$")
            if click_then_expect(d, nav, _drawer_is_open, timeout=5):
                return
        except Exception:
            pass
        if _drawer_is_open(d):
            return

    for description in ("Navigate up", "Open navigation drawer"):
        try:
            nav = d(description=description)
            if click_then_expect(d, nav, _drawer_is_open, timeout=5):
                return
        except Exception:
            pass
        if _drawer_is_open(d):
            return

    width, height = d.window_size()
    top_y = max(int(height * 0.15), 1)

    # MessageList uses DrawerLayout and toggles the drawer from the toolbar home
    # affordance. An edge swipe remains a last-resort fallback when the app bar
    # navigation button is not exposed by uiautomator2 on this build.
    d.swipe(1, top_y, int(width * 0.55), top_y, steps=40)

    end = time.time() + timeout
    while time.time() < end:
        if _drawer_is_open(d):
            return
        time.sleep(0.25)

    raise RuntimeError(f"navigation drawer did not open; screen={_current_screen(d)}")


def _trigger_drawer_sync(d) -> None:
    """Trigger the drawer's real sync action using the code-defined label.

    Both drawer variants wrap their content in PullToRefreshBox and dispatch
    OnSyncAccount on refresh. DrawerViewModel then calls
    messagingController.checkMail(... ignoreLastCheckedTime=true ...).
    """

    def _sync_label():
        return d(text="Sync all accounts")

    def _show_accounts_label():
        return d(text="Show accounts")

    def _account_selector():
        for label in (ACCOUNT_DISPLAY_NAME, ACCOUNT_EMAIL):
            if not label:
                continue
            candidate = d(text=label)
            if candidate.exists:
                return candidate
        return None

    def _make_sync_visible() -> bool:
        sync_label = _sync_label()
        if sync_label.exists:
            return True

        show_accounts = _show_accounts_label()
        if show_accounts.exists:
            if click_then_expect(
                d, show_accounts, lambda: _sync_label().exists, timeout=10
            ):
                return True

        account_selector = _account_selector()
        if account_selector is not None:
            if click_then_expect(
                d, account_selector, lambda: _sync_label().exists, timeout=10
            ):
                return True

        try:
            d(scrollable=True).scroll.to(text="Sync all accounts")
        except Exception:
            pass

        return _sync_label().exists

    if not _make_sync_visible():
        raise RuntimeError("drawer sync label 'Sync all accounts' not visible")

    sync_label = _sync_label()
    wait_and_click(d, sync_label, timeout=8)
    wait_for_ui_stable(d)

    print(
        f"[drive_inbox_refresh] attempt={ATTEMPT} drawer_sync_label_clicked=true",
        flush=True,
    )

    indicator = d(resourceIdMatches=_rid("PullToRefreshIndicator"))
    saw_indicator = False
    indicator_wait_end = time.time() + 10
    while time.time() < indicator_wait_end:
        if indicator.exists:
            saw_indicator = True
            break
        time.sleep(0.25)

    if saw_indicator:
        indicator_clear_end = time.time() + 35
        while time.time() < indicator_clear_end:
            if not indicator.exists:
                break
            time.sleep(0.25)
    else:
        print(
            f"[drive_inbox_refresh] attempt={ATTEMPT} sync_indicator_absent=true",
            flush=True,
        )

    time.sleep(_POST_SYNC_WAIT_SECS)


def main() -> int:
    try:
        _adb("shell", "am", "force-stop", APP_PKG, check=False)
        time.sleep(1)
        _launch_inbox()
        d = initialize_ui_automation(max_retries=4, retry_delay=2)
        _ensure_app_foreground(d)
        _wait_for_inbox_ready(d)
        print(
            f"[drive_inbox_refresh] attempt={ATTEMPT} inbox_ready=true screen={_current_screen(d)}",
            flush=True,
        )
        _open_navigation_drawer(d)
        print(
            f"[drive_inbox_refresh] attempt={ATTEMPT} drawer_open=true",
            flush=True,
        )
        _trigger_drawer_sync(d)
        print(
            f"[drive_inbox_refresh] attempt={ATTEMPT} sync_complete screen={_current_screen(d)}",
            flush=True,
        )
        return 0
    except Exception as exc:
        print(
            f"[drive_inbox_refresh] INFRA: could not drive Thunderbird inbox sync: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
