#!/usr/bin/env python3
"""Drive Thunderbird inbox sync via pull-to-refresh in MessageListActivity.

MessageListFragment wires swipeRefreshLayout to checkMail(), which fetches
new IMAP messages and posts notifications.  Pull-to-refresh is the simplest
reliable path; navigation-drawer sync is redundant and brittle.
"""
import os
import subprocess
import sys
import time

import uiautomator2 as u2

APP_PKG = os.environ["PKG"]
ACCOUNT_UUID = os.environ["ACCOUNT_UUID"]
MESSAGE_LIST_ACTIVITY = "com.fsck.k9.activity.MessageList"
ATTEMPT = os.environ.get("TB_REFRESH_ATTEMPT", "?")


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
    _adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        f"{APP_PKG}/{MESSAGE_LIST_ACTIVITY}",
        "-a",
        "shortcut",
        "--es",
        "account_uuid",
        ACCOUNT_UUID,
        check=False,
    )


def _wait_for_inbox_ready(d, timeout: float = 30.0) -> None:
    refresh = d(resourceIdMatches=_rid("swiperefresh"))
    msg_list = d(resourceIdMatches=_rid("message_list"))
    end = time.time() + timeout
    while time.time() < end:
        app = d.app_current() or {}
        if app.get("package") == APP_PKG and refresh.exists and msg_list.exists:
            return
        time.sleep(1)
    raise RuntimeError(
        f"inbox UI not ready after {timeout:.0f}s; screen={_current_screen(d)}"
    )


def _pull_to_refresh(d) -> None:
    """Swipe down to trigger MessageListFragment.checkMail() via swipeRefreshLayout."""
    width, height = d.window_size()
    mid_x = width // 2
    _adb(
        "shell",
        "input",
        "swipe",
        str(mid_x),
        str(int(height * 0.25)),
        str(mid_x),
        str(int(height * 0.65)),
        "600",
    )
    # Allow time for IMAP fetch and notification posting.
    time.sleep(8)
    print(f"[drive_inbox_refresh] attempt={ATTEMPT} pull_to_refresh_done=true")


def main() -> int:
    try:
        _adb("shell", "am", "force-stop", APP_PKG, check=False)
        time.sleep(1)
        _launch_inbox()
        d = u2.connect()
        _wait_for_inbox_ready(d, timeout=30)
        print(
            f"[drive_inbox_refresh] attempt={ATTEMPT} inbox_ready=true screen={_current_screen(d)}"
        )
        _pull_to_refresh(d)
        print(
            f"[drive_inbox_refresh] attempt={ATTEMPT} sync_complete screen={_current_screen(d)}"
        )
        return 0
    except Exception as exc:
        print(
            f"[drive_inbox_refresh] INFRA: could not drive Thunderbird inbox sync: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
