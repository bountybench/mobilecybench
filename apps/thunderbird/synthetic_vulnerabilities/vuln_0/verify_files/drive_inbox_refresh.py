#!/usr/bin/env python3
"""Drive Thunderbird inbox sync via pull-to-refresh in the account inbox.

MessageListFragment wires swipeRefreshLayout to checkMail(), which fetches
new IMAP messages and posts notifications.  Pull-to-refresh is the simplest
reliable path; navigation-drawer sync is redundant and brittle.

Key details from the codebase:
- MessageHomeActivity.shortcutIntentForAccount() launches the default folder
  by starting MessageHomeActivity with action="shortcut" and extra
  account_uuid. Launching the old MessageList activity directly bypasses that
  contract and can leave us outside the single-account/default-folder state
  that checkMail() expects.
- initializeSwipeRefreshLayout() sets isEnabled=false at inflation; isEnabled
  is only set to true inside setMessageList() after the local DB query finishes.
- checkMail() in isSingleAccountMode && isSingleFolderMode calls
  synchronizeMailbox(account, folderId, notify=false, listener), which runs
  backend.sync() on the background thread, writing messages to the local DB.
- SwipeRefreshLayout.onRefresh() fires only when the list is at the top AND
  the gesture crosses the trigger threshold.  Using d.swipe() with explicit
  steps produces a smooth, gradual gesture that SwipeRefreshLayout can
  distinguish from a fling.  adb input swipe can be too fast/coarse.
"""
import os
import subprocess
import sys
import time

import uiautomator2 as u2

APP_PKG = os.environ["PKG"]
ACCOUNT_UUID = os.environ["ACCOUNT_UUID"]
MESSAGE_HOME_ACTIVITY = "com.fsck.k9.activity.MessageHomeActivity"
ATTEMPT = os.environ.get("TB_REFRESH_ATTEMPT", "?")

# Post-swipe wait: allow time for IMAP fetch, DB write, and notification posting.
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
    _adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        f"{APP_PKG}/{MESSAGE_HOME_ACTIVITY}",
        "-a",
        "shortcut",
        "--es",
        "account_uuid",
        ACCOUNT_UUID,
        check=False,
    )


def _wait_for_inbox_ready(d, timeout: float = 45.0) -> None:
    """Wait until swipeRefreshLayout is present AND enabled.

    MessageListFragment.initializeSwipeRefreshLayout() sets isEnabled=false
    immediately after inflating the layout.  isEnabled is only set to true
    inside setMessageList(), which runs after the local DB query completes.
    Swiping before that returns no-op because SwipeRefreshLayout ignores
    gestures while disabled.
    """
    msg_list = d(resourceIdMatches=_rid("message_list"))
    end = time.time() + timeout
    while time.time() < end:
        app = d.app_current() or {}
        if app.get("package") == APP_PKG and msg_list.exists:
            # SwipeRefreshLayout must be enabled (setMessageList() has run).
            enabled_refresh = d(resourceIdMatches=_rid("swiperefresh"), enabled=True)
            if enabled_refresh.exists:
                return
        time.sleep(0.5)
    raise RuntimeError(
        "swipeRefreshLayout not enabled after "
        f"{timeout:.0f}s; screen={_current_screen(d)}"
    )


def _pull_to_refresh(d) -> None:
    """Swipe down to trigger MessageListFragment.checkMail() via swipeRefreshLayout.

    Uses d.swipe() (UiDevice.swipe via UiAutomation) with explicit steps=50
    to produce a smooth 500 ms gesture.  SwipeRefreshLayout needs a gradual
    drag past its trigger offset; a coarse or fast swipe may be interpreted
    as a fling and leave onRefresh() uncalled.

    SwipeRefreshLayout only engages when the list is at scroll position 0.
    We scroll to the beginning first so that residual scroll state (e.g. from
    a previous test phase that did not fully reset the activity) cannot silently
    turn our pull-to-refresh into an ordinary scroll and leave onRefresh uncalled.
    """
    msg_list = d(resourceIdMatches=_rid("message_list"))
    try:
        msg_list.scroll.toBeginning(max_swipes=5)
    except Exception:
        pass  # non-fatal; list may already be at top

    width, height = d.window_size()
    mid_x = width // 2
    # Start below the toolbar (~20 % height) and drag well past the trigger
    # threshold (~70 % height).  steps=50 yields ~500 ms at 10 ms/step.
    d.swipe(mid_x, int(height * 0.20), mid_x, int(height * 0.70), steps=50)
    time.sleep(_POST_SYNC_WAIT_SECS)
    print(
        f"[drive_inbox_refresh] attempt={ATTEMPT} pull_to_refresh_done=true",
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
        _pull_to_refresh(d)
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
