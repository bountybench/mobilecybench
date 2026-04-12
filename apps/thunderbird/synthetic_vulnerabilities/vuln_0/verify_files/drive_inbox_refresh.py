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
    if d(textMatches="(?i)Show accounts").exists:
        return True

    # Check if the account email/name is visible AND MessageList is NOT the primary content
    # (The drawer overlays the MessageList)
    for label in (ACCOUNT_DISPLAY_NAME, ACCOUNT_EMAIL):
        if not label:
            continue
        if (
            d(textMatches=f"(?i){label}").exists
            and not d(resourceIdMatches=_rid("message_list")).exists
        ):
            return True

    return False


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
            if click_then_expect(d, nav, lambda: _drawer_is_open(d), timeout=5):
                return
        except Exception:
            pass
        if _drawer_is_open(d):
            return

    for description in ("Navigate up", "Open navigation drawer"):
        try:
            nav = d(description=description)
            if click_then_expect(d, nav, lambda: _drawer_is_open(d), timeout=5):
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
        return d(textMatches="(?i)Sync all accounts")

    def _show_accounts_label():
        return d(textMatches="(?i)Show accounts")

    def _account_selector():
        drawer = _drawer_content(d)
        for label in (ACCOUNT_DISPLAY_NAME, ACCOUNT_EMAIL):
            if not label:
                continue
            # Look for the text node
            if drawer.exists:
                candidate = drawer.child(textMatches=f"(?i){label}")
            else:
                # Global search if DrawerContent not found/reliable
                candidate = d(textMatches=f"(?i){label}")

            if candidate.exists:
                try:
                    c_info = candidate.info
                    c_clickable = c_info.get("clickable")
                    print(
                        f"[drive_inbox_refresh] found candidate text='{label}' clickable={c_clickable}"
                    )
                    # If the text node is clickable, return it.
                    if c_clickable:
                        return candidate
                except Exception as e:
                    print(f"[drive_inbox_refresh] error getting candidate info: {e}")

                # If not, try to find a clickable parent (Compose often makes the Box clickable, not the Text)
                try:
                    p = candidate.parent()
                    # Use a limited depth to avoid issues
                    for i in range(8):
                        if not p.exists:
                            break
                        p_info = p.info
                        p_id = p_info.get("resourceId", "")
                        p_clickable = p_info.get("clickable")
                        print(
                            f"[drive_inbox_refresh] checking parent level {i}: id='{p_id}' clickable={p_clickable}"
                        )
                        if p_clickable:
                            print(
                                f"[drive_inbox_refresh] found clickable parent for '{label}'"
                            )
                            return p
                        if p_id and "DrawerContent" in p_id:
                            break
                        p = p.parent()
                except Exception as e:
                    print(f"[drive_inbox_refresh] error traversing parents: {e}")

                # If no clickable parent found, return the candidate anyway as fallback
                print(f"[drive_inbox_refresh] fallback to non-clickable text='{label}'")
                return candidate
        return None

    def _make_sync_visible() -> bool:
        if _sync_label().exists:
            return True

        show_accounts = _show_accounts_label()
        if show_accounts.exists:
            print(
                "[drive_inbox_refresh] clicking 'Show accounts' to reveal sync action"
            )
            if click_then_expect(
                d,
                show_accounts,
                lambda: _sync_label().exists,
                timeout=10,
            ):
                return True

        # Try to click the account switcher header
        candidate = _account_selector()
        if candidate is not None:
            print(
                "[drive_inbox_refresh] clicking account selector to reveal sync action"
            )
            # Try clicking the text node itself (or the parent we found in _account_selector)
            if click_then_expect(
                d,
                candidate,
                lambda: _sync_label().exists,
                timeout=8,
            ):
                return True

        # Try searching for "Sync all accounts" globally and scrolling
        print(
            "[drive_inbox_refresh] 'Sync all accounts' not visible, attempting scroll"
        )
        try:
            # Try scrolling the drawer specifically
            drawer = _drawer_content(d)
            if drawer.exists and drawer.info.get("scrollable"):
                drawer.scroll.to(textMatches="(?i)Sync all accounts")
            else:
                d(scrollable=True).scroll.to(textMatches="(?i)Sync all accounts")
        except Exception as e:
            print(f"[drive_inbox_refresh] scroll failed: {e}")
            # Manual swipe if u2 scroll fails on Compose list
            width, height = d.window_size()
            x = int(width * 0.3)
            y_start = int(height * 0.7)
            y_end = int(height * 0.3)
            for _ in range(3):
                d.swipe(x, y_start, x, y_end, steps=30)
                if _sync_label().exists:
                    return True

        return _sync_label().exists

    if not _make_sync_visible():
        # Fallback 1: pull-to-refresh on the drawer
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
            # Fallback 2: last-ditch effort, swipe the whole screen if drawer content not found but we think it's open
            width, height = d.window_size()
            d.swipe(
                int(width * 0.5),
                int(height * 0.2),
                int(width * 0.5),
                int(height * 0.8),
                steps=50,
            )
    else:
        sync_label = _sync_label()
        print("[drive_inbox_refresh] clicking 'Sync all accounts'")
        wait_and_click(d, sync_label, timeout=8)

    wait_for_ui_stable(d)
    print(
        f"[drive_inbox_refresh] attempt={ATTEMPT} sync_trigger_done=true",
        flush=True,
    )

    indicator = d(resourceIdMatches=_rid("PullToRefreshIndicator"))
    saw_indicator = False
    indicator_wait_end = time.time() + 10
    while time.time() < indicator_wait_end:
        if indicator.exists:
            saw_indicator = True
            print("[drive_inbox_refresh] sync indicator appeared")
            break
        time.sleep(0.25)

    if saw_indicator:
        indicator_clear_end = time.time() + 60  # Increased timeout for slow IMAP
        while time.time() < indicator_clear_end:
            if not indicator.exists:
                print("[drive_inbox_refresh] sync indicator cleared")
                break
            time.sleep(0.5)
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
