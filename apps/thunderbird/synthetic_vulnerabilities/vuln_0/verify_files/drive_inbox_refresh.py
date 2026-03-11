#!/usr/bin/env python3
import importlib
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
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


def _dump_hierarchy(d) -> str:
    return d.dump_hierarchy(compressed=False)


def _node_visible(xml_text: str, resource_name: str) -> bool | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    wanted = f"{APP_PKG}:id/{resource_name}"
    for node in root.iter("node"):
        rid = node.attrib.get("resource-id", "")
        if rid == wanted or rid.endswith(f":id/{resource_name}"):
            return node.attrib.get("visible-to-user") == "true"

    return None


def _node_attr(xml_text: str, resource_name: str, attr_name: str) -> str | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    wanted = f"{APP_PKG}:id/{resource_name}"
    for node in root.iter("node"):
        rid = node.attrib.get("resource-id", "")
        if rid == wanted or rid.endswith(f":id/{resource_name}"):
            return node.attrib.get(attr_name)

    return None


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


def _log_inbox_state(d, stage: str) -> None:
    refresh = d(resourceIdMatches=_rid("swiperefresh"))
    message_list = d(resourceIdMatches=_rid("message_list"))
    progress = d(resourceIdMatches=_rid("message_list_progress"))
    xml_text = _dump_hierarchy(d)
    refresh_enabled = _node_attr(xml_text, "swiperefresh", "enabled")
    print(
        "[verify_exploit] "
        f"attempt={ATTEMPT} stage={stage} "
        f"screen={_current_screen(d)} "
        f"toolbar_title={_toolbar_title(d)} "
        f"refresh_exists={refresh.exists} "
        f"message_list_exists={message_list.exists} "
        f"progress_exists={progress.exists} "
        f"refresh_enabled={refresh_enabled}",
    )


def _wait_for_sync_lifecycle(
    d, start_timeout: float = 20.0, finish_timeout: float = 90.0
) -> tuple[bool, bool]:
    started = False
    start_deadline = time.time() + start_timeout
    while time.time() < start_deadline:
        visible = _node_visible(_dump_hierarchy(d), "message_list_progress")
        if visible is True:
            started = True
            print(f"[verify_exploit] attempt={ATTEMPT} sync_progress_started=true")
            break
        time.sleep(0.5)

    if not started:
        print(f"[verify_exploit] attempt={ATTEMPT} sync_progress_started=false")
        return False, False

    finish_deadline = time.time() + finish_timeout
    while time.time() < finish_deadline:
        visible = _node_visible(_dump_hierarchy(d), "message_list_progress")
        if visible is False:
            print(f"[verify_exploit] attempt={ATTEMPT} sync_progress_finished=true")
            wait_for_ui_stable(d, timeout=12)
            return True, True
        time.sleep(0.75)

    print(f"[verify_exploit] attempt={ATTEMPT} sync_progress_finished=false")
    return True, False


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
        started, finished = _wait_for_sync_lifecycle(device)
        print(
            "[verify_exploit] Thunderbird relaunch result "
            f"screen={_current_screen(device)} "
            f"sync_started={started} "
            f"sync_finished={finished}"
        )
        return 0
    except Exception as exc:
        print(
            f"[verify_exploit] INFRA: could not drive Thunderbird inbox relaunch: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
