#!/usr/bin/env python3
"""Drive Thunderbird mailbox sync via the navigation drawer refresh path.

This is intentionally aligned to the vendored Thunderbird code in this repo:

- `MessageListFragment.initializeSwipeRefreshLayout()` does *not* make the
  message-list pull-to-refresh path call `checkMail()` for a normal
  single-account local inbox. In that state `isCheckMailSupported` is false,
  so swiping the inbox can be a no-op for sync.
- `MessageList.onOptionsItemSelected(android.R.id.home)` opens the
  `NavigationDrawer` while the message list is displayed.
- Both drawer implementations wrap their content in `PullToRefreshBox` with
  `onRefresh = OnSyncAccount`.
- `DrawerViewModel.onSyncAccount()` calls
  `messagingController.checkMail(account, ignoreLastCheckedTime=true, ...)`,
  which is the real UI-backed sync path for the selected account.

So the correct automation target is the drawer refresh gesture, not the inbox
list refresh gesture.
"""
import os
import subprocess
import sys
import time

import uiautomator2 as u2

APP_PKG = os.environ["PKG"]
ATTEMPT = os.environ.get("TB_REFRESH_ATTEMPT", "?")

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


def _drawer_is_open(d) -> bool:
    drawer = d(resourceIdMatches=_rid("navigation_drawer_content"))
    if not drawer.exists:
        return False

    bounds = drawer.info.get("bounds") or {}
    left = int(bounds.get("left", -1))
    right = int(bounds.get("right", -1))
    return left >= 0 and right > left


def _open_navigation_drawer(d, timeout: float = 15.0) -> None:
    if _drawer_is_open(d):
        return

    for description in ("Navigate up", "Open navigation drawer"):
        try:
            d(descriptionContains=description).click_exists(timeout=2.0)
        except Exception:
            pass
        if _drawer_is_open(d):
            return

    width, height = d.window_size()
    top_y = max(int(height * 0.15), 1)

    # MessageList uses DrawerLayout and toggles the drawer from the toolbar home
    # affordance. An edge swipe is the least locale-dependent way to expose it.
    d.swipe(1, top_y, int(width * 0.55), top_y, steps=40)

    end = time.time() + timeout
    while time.time() < end:
        if _drawer_is_open(d):
            return
        time.sleep(0.25)

    raise RuntimeError(f"navigation drawer did not open; screen={_current_screen(d)}")


def _pull_to_refresh_drawer(d) -> None:
    """Swipe the drawer's PullToRefreshBox to trigger OnSyncAccount.

    Both drawer variants wrap their content in PullToRefreshBox and dispatch
    OnSyncAccount on refresh. DrawerViewModel then calls
    messagingController.checkMail(... ignoreLastCheckedTime=true ...).
    """
    refresh_box = d(resourceIdMatches=_rid("PullToRefreshBox"))
    if not refresh_box.exists:
        raise RuntimeError("drawer PullToRefreshBox not visible before refresh")

    bounds = refresh_box.info.get("bounds") or {}
    left = int(bounds.get("left", 0))
    right = int(bounds.get("right", 0))
    top = int(bounds.get("top", 0))
    bottom = int(bounds.get("bottom", 0))

    if not (right > left and bottom > top):
        raise RuntimeError(f"invalid drawer refresh bounds: {bounds}")

    mid_x = left + (right - left) // 2
    start_y = top + max(32, int((bottom - top) * 0.12))
    end_y = min(bottom - 24, top + int((bottom - top) * 0.72))
    if end_y <= start_y:
        raise RuntimeError(f"drawer refresh swipe would be degenerate: {bounds}")
    d.swipe(mid_x, start_y, mid_x, end_y, steps=50)

    time.sleep(_POST_SYNC_WAIT_SECS)
    print(
        f"[drive_inbox_refresh] attempt={ATTEMPT} drawer_pull_to_refresh_done=true",
        flush=True,
    )


def main() -> int:
    try:
        _adb("shell", "am", "force-stop", APP_PKG, check=False)
        time.sleep(1)
        _launch_inbox()
        d = u2.connect()
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
        _pull_to_refresh_drawer(d)
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
