#!/usr/bin/env python3
import importlib
import os
import re
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

_STRING_RESOURCE_CACHE: dict[str, set[str]] = {}
_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def _rid(name: str) -> str:
    return rf"(.*:id/)?{name}"


def _adb(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def _resource_string_values(resource_name: str) -> set[str]:
    cached = _STRING_RESOURCE_CACHE.get(resource_name)
    if cached is not None:
        return cached

    values: set[str] = set()
    for strings_xml in REPO_ROOT.glob(
        "apps/thunderbird/codebase/feature/navigation/drawer/**/src/main/res/values*/strings.xml"
    ):
        try:
            root = ET.parse(strings_xml).getroot()
        except ET.ParseError:
            continue

        for node in root.findall("string"):
            if node.attrib.get("name") == resource_name and node.text:
                values.add(node.text.strip())

    _STRING_RESOURCE_CACHE[resource_name] = values
    return values


def _dump_xml_root(d):
    try:
        return ET.fromstring(d.dump_hierarchy(compressed=False))
    except ET.ParseError:
        return None


def _parse_bounds(raw: str):
    match = _BOUNDS_RE.fullmatch(raw or "")
    if not match:
        return None
    left, top, right, bottom = map(int, match.groups())
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


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


def _drawer_bounds(d):
    drawer = _drawer_content(d)
    if not drawer.exists:
        return None

    left, top, right, bottom = drawer.bounds()
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None

    return left, top, right, bottom, width, height


def _find_text_any(d, candidates: set[str]):
    for text in candidates:
        obj = d(text=text)
        if obj.exists:
            return obj
    return None


def _clickable_candidates_in_region(d, x_min: int, x_max: int, y_min: int, y_max: int):
    root = _dump_xml_root(d)
    if root is None:
        return []

    matches = []
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        bounds = _parse_bounds(node.attrib.get("bounds", ""))
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        center_x = (left + right) // 2
        center_y = (top + bottom) // 2
        if x_min <= center_x <= x_max and y_min <= center_y <= y_max:
            matches.append((center_y, center_x, bounds, node.attrib))

    matches.sort(reverse=True)
    return matches


def _sync_all_accounts_button(d):
    return _find_text_any(
        d,
        _resource_string_values("navigation_drawer_dropdown_action_sync_all_accounts")
        | _resource_string_values(
            "navigation_drawer_siderail_action_sync_all_accounts"
        ),
    )


def _show_accounts_button(d):
    return _find_text_any(
        d,
        _resource_string_values("navigation_drawer_dropdown_action_show_accounts")
        | _resource_string_values("navigation_drawer_dropdown_action_hide_accounts"),
    )


def _account_list_header(d):
    return _find_text_any(
        d,
        _resource_string_values(
            "navigation_drawer_dropdown_avount_view_selection_title"
        ),
    )


def _click_account_selector_header(d) -> bool:
    bounds = _drawer_bounds(d)
    if bounds is None:
        return False
    left, top, _, _, width, height = bounds

    click_y = top + max(48, min(height // 8, 180))
    # Try both structurally valid header lanes:
    # - dropdown: centered header row
    # - side-rail: right-pane header row
    for click_x in (left + width // 2, left + int(width * 0.72)):
        pre_click = d.dump_hierarchy(compressed=True)
        d.click(click_x, click_y)
        changed = wait_for_screen_change(d, pre_click, timeout=2.0)
        wait_for_ui_stable(d, timeout=8)
        if changed:
            return True

        account_list_header = _account_list_header(d)
        sync_button = _sync_all_accounts_button(d)
        if (account_list_header and account_list_header.exists) or (
            sync_button and sync_button.exists
        ):
            return True

    return False


def _account_actions_visible(d) -> bool:
    account_list_header = _account_list_header(d)
    sync_button = _sync_all_accounts_button(d)
    return bool(
        (account_list_header and account_list_header.exists)
        or (sync_button and sync_button.exists)
    )


def _scroll_drawer_for_sync_action(d, max_swipes: int = 3) -> bool:
    bounds = _drawer_bounds(d)
    if bounds is None:
        return False
    left, top, _, _, width, height = bounds

    start_y = top + int(height * 0.82)
    end_y = top + int(height * 0.35)
    swipe_xs = (left + width // 2, left + int(width * 0.22))

    for _ in range(max_swipes):
        for x in swipe_xs:
            sync_button = _sync_all_accounts_button(d)
            if sync_button and sync_button.exists:
                return True
            _adb(
                "shell",
                "input",
                "swipe",
                str(x),
                str(start_y),
                str(x),
                str(end_y),
                "250",
            )
            wait_for_ui_stable(d, timeout=8)

    sync_button = _sync_all_accounts_button(d)
    return bool(sync_button and sync_button.exists)


def _tap_first_account_action_row(d) -> bool:
    bounds = _drawer_bounds(d)
    if bounds is None:
        return False
    left, top, _, _, width, height = bounds

    region_specs = (
        # dropdown account-action region
        (
            left + int(width * 0.12),
            left + int(width * 0.88),
            top + int(height * 0.72),
            top + int(height * 0.96),
        ),
        # side-rail left action region
        (
            left,
            left + int(width * 0.42),
            top + int(height * 0.68),
            top + int(height * 0.96),
        ),
    )

    for region_x_min, region_x_max, region_y_min, region_y_max in region_specs:
        candidates = _clickable_candidates_in_region(
            d,
            region_x_min,
            region_x_max,
            region_y_min,
            region_y_max,
        )
        if not candidates:
            continue

        _, click_x, (_, cand_top, _, cand_bottom), _ = candidates[0]
        click_y = (cand_top + cand_bottom) // 2
        pre_click = d.dump_hierarchy(compressed=True)
        d.click(click_x, click_y)
        changed = wait_for_screen_change(d, pre_click, timeout=2.5)
        wait_for_ui_stable(d, timeout=8)
        if changed:
            return True

    fallback_points = (
        (left + width // 2, top + int(height * 0.86)),
        (left + int(width * 0.22), top + int(height * 0.88)),
    )
    for click_x, click_y in fallback_points:
        pre_click = d.dump_hierarchy(compressed=True)
        d.click(click_x, click_y)
        changed = wait_for_screen_change(d, pre_click, timeout=2.0)
        wait_for_ui_stable(d, timeout=8)
        if changed:
            return True

    return False


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
        f"sync_button_exists={bool(sync_button and sync_button.exists)}",
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
    if _account_actions_visible(d):
        return

    if _click_account_selector_header(d):
        if _account_actions_visible(d):
            wait_for_ui_stable(d, timeout=8)
            if _account_actions_visible(d) or _scroll_drawer_for_sync_action(d):
                return

    toggle = _show_accounts_button(d)
    if toggle and toggle.exists:
        _tap_center(toggle)
        wait_for_ui_stable(d, timeout=8)
        if _account_actions_visible(d) or _scroll_drawer_for_sync_action(d):
            return

    for candidate in (
        _account_list_header(d),
        d(textContains="@"),
    ):
        if candidate and candidate.exists:
            _tap_center(candidate)
            wait_for_ui_stable(d, timeout=8)
            sync_button = _sync_all_accounts_button(d)
            if (sync_button and sync_button.exists) or _scroll_drawer_for_sync_action(
                d
            ):
                return

    raise RuntimeError("Sync all accounts action not visible in navigation drawer")


def _trigger_supported_sync(d) -> None:
    _open_navigation_drawer(d)
    _wait_for_drawer_ready(d)
    _ensure_account_actions_visible(d)
    _scroll_drawer_for_sync_action(d)

    clicked = _tap_first_account_action_row(d)
    if not clicked:
        sync_button = _sync_all_accounts_button(d)
        if sync_button is None or not sync_button.exists:
            raise RuntimeError(
                "Sync all accounts button unresolved after account-action setup"
            )
        pre_click = d.dump_hierarchy(compressed=True)
        _tap_center(sync_button)
        clicked = wait_for_screen_change(d, pre_click, timeout=2.5)
        wait_for_ui_stable(d, timeout=8)

    if not clicked:
        raise RuntimeError("Sync action tap did not produce a UI state change")

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
