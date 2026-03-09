#!/usr/bin/env python3
import importlib
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ui_utils = importlib.import_module("utils.ui_utils")

APP_PKG = os.environ["PKG"]
ACCOUNT_UUID = os.environ["ACCOUNT_UUID"]
MESSAGE_LIST_ACTIVITY = "com.fsck.k9.activity.MessageList"
ATTEMPT = os.environ.get("TB_REFRESH_ATTEMPT", "?")
ui_utils.TARGET_PACKAGE = APP_PKG

initialize_ui_automation = ui_utils.initialize_ui_automation
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


def _log_inbox_state(d, stage: str) -> None:
    refresh = d(resourceIdMatches=_rid("swiperefresh"))
    message_list = d(resourceIdMatches=_rid("message_list"))
    progress = d(resourceIdMatches=_rid("message_list_progress"))
    print(
        "[verify_exploit] "
        f"attempt={ATTEMPT} stage={stage} "
        f"screen={_current_screen(d)} "
        f"refresh_exists={refresh.exists} "
        f"message_list_exists={message_list.exists} "
        f"progress_exists={progress.exists}",
    )


def _pull_to_refresh(d) -> None:
    refresh = d(resourceIdMatches=_rid("swiperefresh"))
    message_list = d(resourceIdMatches=_rid("message_list"))
    if not refresh.exists or not message_list.exists:
        raise RuntimeError("message list refresh UI not present")

    try:
        scrolled_to_top = message_list.scroll.vert.toBeginning(max_swipes=6, steps=50)
        print(f"[verify_exploit] attempt={ATTEMPT} message_list_to_beginning={scrolled_to_top}")
    except Exception as exc:
        print(f"[verify_exploit] attempt={ATTEMPT} message_list_to_beginning_error={exc}")

    wait_for_ui_stable(d, timeout=8)

    try:
        pre_refresh = d.dump_hierarchy(compressed=True)
    except Exception:
        pre_refresh = None

    refresh.swipe("down", steps=60)
    if pre_refresh is not None:
        changed = wait_for_screen_change(d, pre_refresh, timeout=3.0)
        print(f"[verify_exploit] attempt={ATTEMPT} refresh_screen_changed={changed}")
        if not changed:
            try:
                fallback_pre_refresh = d.dump_hierarchy(compressed=True)
            except Exception:
                fallback_pre_refresh = None

            message_list.swipe("down", steps=60)
            if fallback_pre_refresh is not None:
                fallback_changed = wait_for_screen_change(
                    d,
                    fallback_pre_refresh,
                    timeout=3.0,
                )
                print(
                    f"[verify_exploit] attempt={ATTEMPT} "
                    f"refresh_fallback_screen_changed={fallback_changed}"
                )

    time.sleep(1.5)
    wait_for_ui_stable(d, timeout=12)


def _wait_for_sync_lifecycle(
    d, start_timeout: float = 20.0, finish_timeout: float = 90.0
) -> None:
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
        return

    finish_deadline = time.time() + finish_timeout
    while time.time() < finish_deadline:
        visible = _node_visible(_dump_hierarchy(d), "message_list_progress")
        if visible is False:
            print(f"[verify_exploit] attempt={ATTEMPT} sync_progress_finished=true")
            wait_for_ui_stable(d, timeout=12)
            return
        time.sleep(0.75)

    print(f"[verify_exploit] attempt={ATTEMPT} sync_progress_finished=false")


def main() -> int:
    try:
        device = initialize_ui_automation(max_retries=3, retry_delay=1)
        _launch_account_inbox()
        _wait_for_inbox_ready(device)
        _log_inbox_state(device, "before_refresh")
        _pull_to_refresh(device)
        _log_inbox_state(device, "after_refresh")
        _wait_for_sync_lifecycle(device)
        print(
            f"[verify_exploit] Thunderbird inbox refresh triggered on {_current_screen(device)}"
        )
        return 0
    except Exception as exc:
        print(
            f"[verify_exploit] INFRA: could not drive Thunderbird inbox refresh: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
