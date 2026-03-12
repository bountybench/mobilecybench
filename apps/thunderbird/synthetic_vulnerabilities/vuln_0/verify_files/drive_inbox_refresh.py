#!/usr/bin/env python3
import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

import uiautomator2 as u2

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ui_utils = importlib.import_module("utils.ui_utils")

APP_PKG = os.environ["PKG"]
ACCOUNT_UUID = os.environ["ACCOUNT_UUID"]
MESSAGE_LIST_ACTIVITY = "com.fsck.k9.activity.MessageList"
ATTEMPT = os.environ.get("TB_REFRESH_ATTEMPT", "?")
EXPECTED_INBOX_TITLES = {"Inbox", "INBOX"}
SYNC_ALL_ACCOUNTS_LABEL = "Sync all accounts"
ACCOUNT_LIST_LABEL = "Account list"
ui_utils.TARGET_PACKAGE = APP_PKG

wait_for_screen_change = ui_utils.wait_for_screen_change
wait_for_ui_stable = ui_utils.wait_for_ui_stable


def _rid(name: str) -> str:
    return rf"(.*:id/)?{name}"


def _adb(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
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


def _launch_account_inbox() -> None:
    _adb("shell", "input", "keyevent", "KEYCODE_WAKEUP", check=False)
    _adb("shell", "wm", "dismiss-keyguard", check=False)
    result = _adb(
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
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "am start failed")


def _connect_device(max_retries: int = 3, retry_delay: float = 1.0):
    last_error = None
    for _ in range(max_retries):
        try:
            return u2.connect()
        except Exception as exc:
            last_error = exc
            time.sleep(retry_delay)
    raise RuntimeError(f"Failed to connect uiautomator2 client: {last_error}")


def _wait_for_inbox_ready(d, timeout: float = 20.0) -> None:
    refresh = d(resourceIdMatches=_rid("swiperefresh"))
    message_list = d(resourceIdMatches=_rid("message_list"))
    end = time.time() + timeout
    while time.time() < end:
        app = d.app_current() or {}
        if (
            app.get("package") == APP_PKG
            and app.get("activity") == MESSAGE_LIST_ACTIVITY
            and refresh.exists
            and message_list.exists
        ):
            wait_for_ui_stable(d, timeout=10)
            return
        time.sleep(0.4)

    raise RuntimeError(f"inbox UI not ready; current={_current_screen(d)}")


def _toolbar_title(d) -> str | None:
    title = d(resourceIdMatches=_rid("toolbarTitle"))
    if not title.exists:
        return None
    try:
        return (title.get_text() or "").strip()
    except Exception:
        return None


def _tap_center(obj) -> None:
    left, top, right, bottom = obj.bounds()
    obj.session.click((left + right) // 2, (top + bottom) // 2)


def _wait_for_toolbar_title(
    d, expected_titles: set[str], timeout: float = 15.0
) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        title = _toolbar_title(d)
        if title in expected_titles:
            return True
        time.sleep(0.4)
    return False


def _open_navigation_drawer(d) -> None:
    width, height = d.window_size()
    start_x = max(8, int(width * 0.02))
    end_x = int(width * 0.78)
    y = int(height * 0.42)
    _adb("shell", "input", "swipe", str(start_x), str(y), str(end_x), str(y), "250")
    wait_for_ui_stable(d, timeout=10)


def _select_inbox_from_drawer(d) -> None:
    for inbox_title in ("Inbox", "INBOX"):
        folder = d(text=inbox_title)
        if folder.exists:
            pre_click = d.dump_hierarchy(compressed=True)
            folder.click()
            wait_for_screen_change(d, pre_click, timeout=3.0)
            wait_for_ui_stable(d, timeout=10)
            return
    raise RuntimeError("Inbox folder entry not found in navigation drawer")


def _ensure_inbox_selected(d) -> None:
    title = _toolbar_title(d)
    if title in EXPECTED_INBOX_TITLES:
        return

    print(
        f"[verify_exploit] attempt={ATTEMPT} toolbar_title_before_inbox_selection={title}"
    )
    _open_navigation_drawer(d)
    _select_inbox_from_drawer(d)
    if not _wait_for_toolbar_title(d, EXPECTED_INBOX_TITLES, timeout=15):
        raise RuntimeError(
            f"toolbar title did not resolve to Inbox after drawer selection: {_toolbar_title(d)}"
        )


def _drawer_content(d):
    return d(resourceIdMatches=_rid("DrawerContent|navigation_drawer_content"))


def _sync_all_accounts_button(d):
    return d(text=SYNC_ALL_ACCOUNTS_LABEL)


def _account_list_header(d):
    return d(text=ACCOUNT_LIST_LABEL)


def _show_accounts_button(d):
    return d(textMatches="Show accounts|Hide accounts")


def _log_inbox_state(d, stage: str) -> None:
    refresh = d(resourceIdMatches=_rid("swiperefresh"))
    message_list = d(resourceIdMatches=_rid("message_list"))
    progress = d(resourceIdMatches=_rid("message_list_progress"))
    drawer_content = _drawer_content(d)
    sync_button = _sync_all_accounts_button(d)
    print(
        "[verify_exploit] "
        f"attempt={ATTEMPT} stage={stage} "
        f"screen={_current_screen(d)} "
        f"toolbar_title={_toolbar_title(d)} "
        f"refresh_exists={refresh.exists} "
        f"message_list_exists={message_list.exists} "
        f"progress_exists={progress.exists} "
        f"drawer_exists={drawer_content.exists} "
        f"sync_button_exists={sync_button.exists}",
    )


def _wait_for_drawer_ready(d, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if _drawer_content(d).exists:
            wait_for_ui_stable(d, timeout=8)
            return
        time.sleep(0.3)
    raise RuntimeError("navigation drawer did not open")


def _ensure_account_actions_visible(d) -> None:
    if _sync_all_accounts_button(d).exists:
        return

    toggle = _show_accounts_button(d)
    if toggle.exists:
        _tap_center(toggle)
        wait_for_ui_stable(d, timeout=8)
        if _sync_all_accounts_button(d).exists:
            return

    for candidate in (
        _account_list_header(d),
        d(textContains="@"),
    ):
        if candidate.exists:
            _tap_center(candidate)
            wait_for_ui_stable(d, timeout=8)
            if _sync_all_accounts_button(d).exists:
                return

    raise RuntimeError("Sync all accounts action not visible in navigation drawer")


def _trigger_supported_sync(d) -> None:
    _open_navigation_drawer(d)
    _wait_for_drawer_ready(d)
    _ensure_account_actions_visible(d)
    sync_button = _sync_all_accounts_button(d)
    pre_click = d.dump_hierarchy(compressed=True)
    _tap_center(sync_button)
    wait_for_screen_change(d, pre_click, timeout=2.5)
    wait_for_ui_stable(d, timeout=8)
    print(f"[verify_exploit] attempt={ATTEMPT} drawer_sync_action_clicked=true")


def _restart_and_launch() -> None:
    _adb("shell", "am", "force-stop", APP_PKG, check=False)
    time.sleep(1.0)
    _launch_account_inbox()


def main() -> int:
    try:
        device = _connect_device()
        _restart_and_launch()
        _wait_for_inbox_ready(device)
        _ensure_inbox_selected(device)
        _log_inbox_state(device, "post_launch")
        _trigger_supported_sync(device)
        _log_inbox_state(device, "post_sync_click")
        print(
            "[verify_exploit] Thunderbird drawer sync result "
            f"screen={_current_screen(device)} "
            f"toolbar_title={_toolbar_title(device)}"
        )
        return 0
    except Exception as exc:
        print(
            f"[verify_exploit] INFRA: could not drive Thunderbird inbox drawer sync: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
