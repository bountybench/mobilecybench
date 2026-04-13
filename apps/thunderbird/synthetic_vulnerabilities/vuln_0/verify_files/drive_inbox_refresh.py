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
import re
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
)

# Keep the helper fast: the verifier already polls for local DB ingestion after
# this script returns, so we should not spend time waiting after the sync tap.
_POST_SYNC_WAIT_SECS = 0


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
    d.app_start(APP_PKG, wait=True, use_monkey=True)


def _wait_for_inbox_ready(d, timeout: float = 90.0) -> None:
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


def _sync_label(d):
    """Return a selector for the 'Sync all accounts' action.

    The dropdown drawer exposes this as a text node via NavigationDrawerItem,
    so textMatches works there.  The siderail drawer exposes it as an icon
    button whose label is only set as contentDescription (SettingItem uses
    Icon(contentDescription=label, …)), so we must also check description.
    """
    by_description = d(descriptionMatches=r"(?i)Sync all accounts")
    if by_description.exists:
        return by_description
    return d(textMatches=r"(?i)Sync all accounts")


def _drawer_is_open(d) -> bool:
    # First try the reliable resource ID
    drawer = _drawer_content(d)
    if drawer.exists:
        info = drawer.info or {}
        bounds = info.get("visibleBounds") or info.get("bounds") or {}
        left = int(bounds.get("left", -1))
        right = int(bounds.get("right", -1))
        if left >= 0 and right > left:
            return True

    # Fallback: check for elements that only appear in the drawer
    if d(textMatches="(?i)Sync all accounts").exists:
        return True
    if d(descriptionMatches="(?i)Sync all accounts").exists:
        return True
    if d(textMatches="(?i)Show accounts").exists:
        return True
    if d(descriptionMatches="(?i)Show accounts").exists:
        return True
    if d(textMatches="(?i)Hide accounts").exists:
        return True
    if d(descriptionMatches="(?i)Hide accounts").exists:
        return True

    # Check if the account email/name is visible AND MessageList is NOT the primary content
    # (The drawer overlays the MessageList)
    for label in (ACCOUNT_DISPLAY_NAME, ACCOUNT_EMAIL):
        if not label:
            continue
        if (
            d(textMatches=rf"(?i){re.escape(label)}").exists
            or d(descriptionMatches=rf"(?i){re.escape(label)}").exists
        ) and not d(resourceIdMatches=_rid("message_list")).exists:
            return True

    return False


def _open_navigation_drawer(d, timeout: float = 15.0) -> None:
    if _drawer_is_open(d):
        return

    # The actual drawer opener is framework-generated in this build, so the
    # stable signal we can rely on is the exposed accessibility label.
    for description in ("Navigate up", "Open navigation drawer"):
        try:
            nav = d(description=description)
            if nav.exists and click_then_expect(
                d,
                nav,
                lambda: _drawer_is_open(d),
                timeout=2,
                retries=1,
            ):
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
        by_description = d(descriptionMatches=r"(?i)Sync all accounts")
        if by_description.exists:
            return by_description
        return d(textMatches=r"(?i)Sync all accounts")

    def _show_accounts_label():
        by_description = d(descriptionMatches=r"(?i)Show accounts")
        if by_description.exists:
            return by_description
        return d(textMatches=r"(?i)Show accounts")

    def _find_clickable_ancestor(node):
        try:
            current = node
            for _ in range(8):
                if not current.exists:
                    break
                info = current.info or {}
                if info.get("clickable"):
                    return current
                current = current.parent()
        except Exception:
            return None
        return None

    def _tap_node(node) -> bool:
        if not node.exists:
            return False
        try:
            if node.click_exists(timeout=2):
                return True
        except Exception:
            pass
        try:
            info = node.info or {}
            bounds = info.get("visibleBounds") or info.get("bounds") or {}
            left = int(bounds.get("left", -1))
            right = int(bounds.get("right", -1))
            top = int(bounds.get("top", -1))
            bottom = int(bounds.get("bottom", -1))
            if left >= 0 and right > left and top >= 0 and bottom > top:
                d.click(left + (right - left) // 2, top + (bottom - top) // 2)
                return True
        except Exception:
            return False
        return False

    def _activate_account_selector() -> bool:
        for label in (ACCOUNT_DISPLAY_NAME, ACCOUNT_EMAIL):
            if not label:
                continue
            selector = d(textMatches=rf"(?i){re.escape(label)}")
            if not selector.exists:
                selector = d(descriptionMatches=rf"(?i){re.escape(label)}")
            if not selector.exists:
                continue

            print(f"[drive_inbox_refresh] found account selector candidate='{label}'")
            clickable = _find_clickable_ancestor(selector)
            if clickable is None:
                clickable = selector
            if _tap_node(clickable):
                return True
        return False

    def _make_sync_visible() -> bool:
        if _sync_label().exists:
            return True

        show_accounts = _show_accounts_label()
        if show_accounts.exists:
            print(
                "[drive_inbox_refresh] clicking 'Show accounts' to reveal sync action"
            )
            if _tap_node(show_accounts):
                time.sleep(0.5)
            if _sync_label().exists:
                return True

        if _activate_account_selector():
            time.sleep(0.5)
            if _sync_label().exists:
                return True

        if _sync_label().exists:
            return True

        print(
            "[drive_inbox_refresh] 'Sync all accounts' not visible, attempting scroll"
        )
        try:
            drawer = _drawer_content(d)
            target = _sync_label()
            if drawer.exists and drawer.info.get("scrollable"):
                drawer.scroll.to(target)
            else:
                d(scrollable=True).scroll.to(target)
        except Exception as e:
            print(f"[drive_inbox_refresh] scroll failed: {e}")
            width, height = d.window_size()
            x = int(width * 0.3)
            y_start = int(height * 0.7)
            y_end = int(height * 0.3)
            for _ in range(2):
                d.swipe(x, y_start, x, y_end, steps=30)
                if _sync_label().exists:
                    return True

        return _sync_label().exists

    if not _make_sync_visible():
        print(
            f"[drive_inbox_refresh] attempt={ATTEMPT} sync_label_missing=true fallback_to_drawer_swipe=true",
            flush=True,
        )
        drawer = _drawer_content(d)
        if drawer.exists:
            info = drawer.info
            bounds = info.get("visibleBounds") or info.get("bounds") or {}
            left = int(bounds.get("left", 0))
            right = int(bounds.get("right", 0))
            top = int(bounds.get("top", 0))
            bottom = int(bounds.get("bottom", 0))
            mid_x = left + (right - left) // 2
            start_y = top + int((bottom - top) * 0.2)
            end_y = top + int((bottom - top) * 0.8)
            d.swipe(mid_x, start_y, mid_x, end_y, steps=50)
        else:
            width, height = d.window_size()
            d.swipe(
                int(width * 0.5),
                int(height * 0.2),
                int(width * 0.5),
                int(height * 0.8),
                steps=50,
            )

    sync_label = _sync_label()
    print("[drive_inbox_refresh] clicking 'Sync all accounts'")
    if not _tap_node(sync_label):
        raise RuntimeError("sync action not tappable")
    print(
        f"[drive_inbox_refresh] attempt={ATTEMPT} sync_trigger_done=true",
        flush=True,
    )

    indicator = d(resourceIdMatches=_rid("PullToRefreshIndicator"))
    if indicator.exists:
        print("[drive_inbox_refresh] sync indicator appeared")
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
        import traceback

        print(
            f"[drive_inbox_refresh] INFRA: could not drive Thunderbird inbox sync: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
