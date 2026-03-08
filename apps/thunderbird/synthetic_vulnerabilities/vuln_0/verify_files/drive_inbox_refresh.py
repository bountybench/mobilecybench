#!/usr/bin/env python3
import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ui_utils = importlib.import_module("utils.ui_utils")

APP_PKG = os.environ["PKG"]
ACCOUNT_UUID = os.environ["ACCOUNT_UUID"]
MESSAGE_LIST_ACTIVITY = "com.fsck.k9.activity.MessageList"
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
    _adb("shell", "am", "force-stop", APP_PKG, check=False)
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


def _swipe_bounds(bounds: dict[str, int]) -> tuple[int, int, int, int]:
    left = bounds["left"]
    top = bounds["top"]
    right = bounds["right"]
    bottom = bounds["bottom"]
    width = right - left
    height = bottom - top
    x = left + width // 2
    start_y = top + max(80, height // 5)
    end_y = min(bottom - 40, top + max(240, (height * 3) // 4))
    return x, start_y, x, end_y


def _pull_to_refresh(d) -> None:
    message_list = d(resourceIdMatches=_rid("message_list"))
    if not message_list.exists:
        raise RuntimeError("message list view not present")

    try:
        pre_refresh = d.dump_hierarchy(compressed=True)
    except Exception:
        pre_refresh = None

    bounds = (message_list.info or {}).get("bounds")
    if not bounds:
        raise RuntimeError("could not resolve message_list bounds")

    x1, y1, x2, y2 = _swipe_bounds(bounds)
    d.swipe(x1, y1, x2, y2, 0.2)

    if pre_refresh is not None:
        wait_for_screen_change(d, pre_refresh, timeout=3.0)

    time.sleep(1.5)
    wait_for_ui_stable(d, timeout=12)


def main() -> int:
    try:
        device = initialize_ui_automation(max_retries=3, retry_delay=1)
        _launch_account_inbox()
        _wait_for_inbox_ready(device)
        _pull_to_refresh(device)
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
