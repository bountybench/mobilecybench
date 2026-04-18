#!/usr/bin/env python3
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# Allow importing project utilities from repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.ui_utils import (  # noqa: E402
    click_then_expect,
    initialize_ui_automation,
    wait_and_click,
    wait_and_set_text,
)

APP_PKG = os.getenv("TB_PKG", "net.thunderbird.android")
ACCOUNT_EMAIL = os.getenv("TB_ACCOUNT_EMAIL", "usera@test.com")
ACCOUNT_PASSWORD = os.getenv("TB_ACCOUNT_PASSWORD", "userAPW123")
IMAP_HOST = os.getenv("TB_IMAP_HOST", "10.0.2.2")
SMTP_HOST = os.getenv("TB_SMTP_HOST", "10.0.2.2")
ACCOUNT_DISPLAY_NAME = os.getenv("TB_ACCOUNT_DISPLAY_NAME", "User A")
ADB_BIN = os.getenv("ADB_BIN", "adb")


def _rid(name: str) -> str:
    return rf"(.*:id/)?{name}"


def _id(d, name: str):
    return d(resourceIdMatches=_rid(name))


def _wait_until(predicate, timeout: float, error: str):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return
        time.sleep(0.3)
    raise RuntimeError(error)


def _current_activity_name(d) -> str:
    try:
        return (d.app_current() or {}).get("activity", "")
    except Exception:
        return ""


def _is_device_offline_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "device offline" in msg or "unable to connect to uiautomator2 server" in msg


def _recover_offline_device():
    # Best-effort recovery for transient adb/uiautomator disconnects.
    subprocess.run(
        [ADB_BIN, "wait-for-device"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [ADB_BIN, "start-server"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)


def _wait_id(d, name: str, timeout: float = 20):
    obj = _id(d, name)
    if not obj.wait(timeout=timeout):
        raise RuntimeError(f"Did not find '{name}'")
    return obj


def _tap_id(d, name: str, timeout: float = 12):
    obj = _wait_id(d, name, timeout=timeout)
    wait_and_click(d, obj, timeout=max(4, int(timeout)))


def _tap_next(d):
    next_by_id = _id(d, "account_setup_next_button")
    if next_by_id.exists:
        wait_and_click(d, next_by_id, timeout=8)
        return

    for txt in ("Next", "Done", "Finish"):
        obj = d(text=txt)
        if obj.exists:
            wait_and_click(d, obj, timeout=8)
            return

    raise RuntimeError("Could not find setup next button")


def _is_certificate_warning_screen(d) -> bool:
    indicators = [
        d(textMatches=r"(?i).*certificate.*"),
        d(textMatches=r"(?i).*security threat.*"),
        d(textMatches=r"(?i).*accept risk.*"),
        d(textMatches=r"(?i).*warning.*"),
    ]
    actions = [
        d(textMatches=r"(?i)^advanced$"),
        d(textMatches=r"(?i).*accept risk.*continue.*"),
        d(textMatches=r"(?i).*continue.*"),
    ]
    return any(obj.exists for obj in indicators) and any(obj.exists for obj in actions)


def _click_first_existing_text(d, patterns: list[str]) -> bool:
    for pattern in patterns:
        obj = d(textMatches=pattern)
        if obj.exists:
            wait_and_click(d, obj, timeout=6)
            time.sleep(0.25)
            return True
    return False


def _handle_certificate_warning_if_present(d, max_steps: int = 4) -> bool:
    if not _is_certificate_warning_screen(d):
        return False

    print(
        "[tb-setup] certificate warning detected; accepting risk to continue",
        flush=True,
    )
    for _ in range(max_steps):
        if _click_first_existing_text(
            d, [r"(?i).*accept risk.*continue.*", r"(?i).*continue anyway.*"]
        ):
            return True

        if _click_first_existing_text(d, [r"(?i)^advanced$", r"(?i).*more details.*"]):
            continue

        if (
            _id(d, "IncomingServerSettingsContent").exists
            or _id(d, "OutgoingServerSettingsContent").exists
        ):
            return True

        time.sleep(0.3)

    return False


def _wait_for_any_screen(
    d, screen_ids: list[str], timeout: float = 60.0, context: str = "setup flow"
) -> str:
    end = time.time() + timeout
    saw_validation = False

    while time.time() < end:
        for screen_id in screen_ids:
            if _id(d, screen_id).exists:
                return screen_id

        if _id(d, "AccountValidationContent").exists:
            saw_validation = True

        if _handle_certificate_warning_if_present(d):
            saw_validation = True

        time.sleep(0.35)

    expected = ", ".join(screen_ids)
    extra = " (passed through AccountValidationContent)" if saw_validation else ""
    raise RuntimeError(f"Did not reach one of [{expected}] in {context}{extra}")


def _read_field_text(field) -> str:
    try:
        txt = field.get_text()
        if txt is not None:
            return str(txt)
    except Exception:
        pass
    try:
        info = field.info or {}
        txt = info.get("text")
        if txt is not None:
            return str(txt)
    except Exception:
        pass
    return ""


def _set_field_text(d, field, value: str, label: str, password: bool = False):
    if not field.exists:
        raise RuntimeError(f"Field '{label}' does not exist")
    # Prefer shared text helper first.
    try:
        wait_and_set_text(d, field, value)
    except Exception:
        # Fallback for wrapper/stale Compose nodes.
        try:
            if not field.click_exists(timeout=1.5):
                field.click()
        except Exception as exc:
            raise RuntimeError(f"Could not focus '{label}': {exc}") from exc

        try:
            field.clear_text()
        except Exception:
            pass

        try:
            field.set_text(value)
        except Exception:
            try:
                d.send_keys(value, clear=True)
            except Exception:
                info = {}
                try:
                    info = field.info or {}
                except Exception:
                    info = {}
                bounds = _parse_bounds(info.get("bounds", "")) if info else None
                if bounds is not None:
                    _adb_tap_and_input(bounds, value)
                else:
                    raise

    time.sleep(0.4)
    current = _read_field_text(field).strip()
    if password:
        if current == "":
            raise RuntimeError(f"Password stayed empty for '{label}'")
        return
    if current != value and value not in current:
        # Compose wrappers can report stale/empty text even when input succeeded.
        # Keep password strict, but avoid hard-failing non-password fields here.
        print(
            f"[tb-setup] warning: could not strictly verify '{label}' text", flush=True
        )


def _set_text_id(
    d,
    name: str,
    value: str,
    label: str,
    password: bool = False,
    fallback_edit_index: int | None = None,
):
    tagged = _wait_id(d, name, timeout=15)
    field = tagged
    try:
        class_name = (tagged.info or {}).get("className")
    except Exception:
        class_name = None

    # Compose often tags a wrapper view instead of the actual EditText.
    if class_name != "android.widget.EditText" and fallback_edit_index is not None:
        by_index = d(className="android.widget.EditText", instance=fallback_edit_index)
        if by_index.exists:
            field = by_index

    _set_field_text(d, field, value, label, password=password)


def _dismiss_keyboard_if_open(d=None, expected_screen_id: str | None = None):
    if not _keyboard_visible():
        return

    # 1) Prefer explicit IME controls (done/check/hide keyboard).
    if d is not None:
        candidates = [
            d(
                descriptionMatches=r"(?i).*(hide keyboard|close keyboard|collapse keyboard).*"
            ),
            d(descriptionMatches=r"(?i).*(done|enter|ok|confirm|check).*"),
            d(textMatches=r"(?i)^(done|ok|close|hide)$"),
        ]
        for obj in candidates:
            try:
                if obj.exists:
                    if expected_screen_id:
                        click_then_expect(
                            d,
                            obj,
                            lambda: _id(d, expected_screen_id).exists,
                            timeout=4,
                            retries=1,
                        )
                    else:
                        wait_and_click(d, obj, timeout=4)
                    time.sleep(0.2)
                    if not _keyboard_visible():
                        return
            except Exception:
                pass

    # 2) IME action key (checkmark/done on many keyboards).
    subprocess.run(
        [ADB_BIN, "shell", "input", "keyevent", "66"], check=False
    )  # KEYCODE_ENTER
    time.sleep(0.2)
    if not _keyboard_visible():
        return

    # 3) Escape as hide-keyboard fallback on some keyboards.
    subprocess.run(
        [ADB_BIN, "shell", "input", "keyevent", "111"], check=False
    )  # KEYCODE_ESCAPE
    time.sleep(0.2)
    if not _keyboard_visible():
        return

    # 4) Last resort: neutral tap outside controls (never BACK).
    subprocess.run([ADB_BIN, "shell", "input", "tap", "540", "120"], check=False)
    time.sleep(0.2)


def _keyboard_visible() -> bool:
    try:
        out = subprocess.check_output(
            [ADB_BIN, "shell", "dumpsys", "input_method"],
            stderr=subprocess.DEVNULL,
            timeout=4,
            text=True,
        )
    except Exception:
        return False
    return "mInputShown=true" in out


def _dismiss_ephemeral_overlays(d):
    # Stylus/IME/tutorial popups can intercept taps/swipes.
    for label in (
        "Not now",
        "No thanks",
        "Maybe later",
        "Later",
        "Skip",
        "Cancel",
        "Close",
        "Got it",
    ):
        obj = d(text=label) if d(text=label).exists else d(textContains=label)
        if obj.exists:
            wait_and_click(d, obj, timeout=4)
            time.sleep(0.2)
            return
    for rid in ("android:id/button2", "android:id/button1"):
        btn = d(resourceId=rid)
        if btn.exists and (
            d(textContains="stylus").exists or d(textContains="handwriting").exists
        ):
            wait_and_click(d, btn, timeout=4)
            time.sleep(0.2)
            return


def _dismiss_keyboard_safely(d, expected_screen_id: str):
    _dismiss_ephemeral_overlays(d)
    if not _keyboard_visible():
        return
    _dismiss_keyboard_if_open(d, expected_screen_id)
    if _keyboard_visible():
        _dismiss_keyboard_if_open(d, expected_screen_id)


def _parse_bounds(bounds: str):
    try:
        left_top, right_bottom = bounds.strip().split("][")
        left, top = left_top.replace("[", "").split(",")
        right, bottom = right_bottom.replace("]", "").split(",")
        return int(left), int(top), int(right), int(bottom)
    except Exception:
        return None


def _dump_root(d):
    return ET.fromstring(d.dump_hierarchy())


def _iter_edit_nodes(root):
    for node in root.iter("node"):
        if node.attrib.get("class") != "android.widget.EditText":
            continue
        bounds = _parse_bounds(node.attrib.get("bounds") or "")
        if bounds is None:
            continue
        yield node, bounds


def _find_labeled_edit(root, label: str):
    target = label.strip().lower()
    edit_nodes = list(_iter_edit_nodes(root))

    for node in root.iter("node"):
        if node.attrib.get("class") != "android.widget.TextView":
            continue
        text = (node.attrib.get("text") or "").strip().lower().replace("*", "").strip()
        if text != target:
            continue
        lb = _parse_bounds(node.attrib.get("bounds") or "")
        if lb is None:
            continue
        l_left, l_top, l_right, l_bottom = lb

        best = None
        best_score = None
        for edit_node, eb in edit_nodes:
            e_left, e_top, e_right, e_bottom = eb
            if e_bottom < l_top - 40 or e_top > l_bottom + 140:
                continue
            if e_right < l_left or e_left > l_right + 900:
                continue
            score = abs(e_top - l_top)
            if best_score is None or score < best_score:
                best_score = score
                best = (edit_node, eb)
        if best is not None:
            return best

    return None


def _adb_tap_and_input(bounds, value: str):
    left, top, right, bottom = bounds
    x, y = (left + right) // 2, (top + bottom) // 2
    subprocess.run([ADB_BIN, "shell", "input", "tap", str(x), str(y)], check=False)
    time.sleep(0.2)
    subprocess.run(
        [ADB_BIN, "shell", "input", "keyevent", "KEYCODE_MOVE_END"], check=False
    )
    for _ in range(24):
        subprocess.run(
            [ADB_BIN, "shell", "input", "keyevent", "KEYCODE_DEL"], check=False
        )
    safe_text = value.replace(" ", "%s")
    subprocess.run([ADB_BIN, "shell", "input", "text", safe_text], check=False)
    time.sleep(0.4)


def _set_labeled_field(d, label: str, value: str, allow_contains: bool = False):
    _dismiss_keyboard_if_open(d)
    root = _dump_root(d)
    match = _find_labeled_edit(root, label)
    if match is None:
        raise RuntimeError(f"Could not locate labeled field '{label}'")

    edit_node, bounds = match
    current = (edit_node.attrib.get("text") or "").strip()
    if current == value or (allow_contains and value in current):
        return

    _adb_tap_and_input(bounds, value)


def _set_password_after_username(d, value: str):
    root = _dump_root(d)
    username_match = _find_labeled_edit(root, "Username")
    if username_match is None:
        raise RuntimeError("Could not locate Username field for password fallback")

    _, username_bounds = username_match
    username_top = username_bounds[1]

    candidates = []
    for node, bounds in _iter_edit_nodes(root):
        top = bounds[1]
        if top <= username_top:
            continue
        candidates.append((node, bounds))

    if not candidates:
        raise RuntimeError("No field found after Username for password fallback")

    # Prefer password=true field below username, otherwise nearest next field.
    pw = [c for c in candidates if c[0].attrib.get("password") == "true"]
    chosen = pw[0] if pw else sorted(candidates, key=lambda c: c[1][1])[0]
    _adb_tap_and_input(chosen[1], value)


def _set_first_password_field(d, value: str):
    root = _dump_root(d)
    for node, bounds in _iter_edit_nodes(root):
        if node.attrib.get("password") == "true":
            _adb_tap_and_input(bounds, value)
            return
    raise RuntimeError("Could not locate password=true input field")


def _is_setup_entry_visible(d) -> bool:
    activity = _current_activity_name(d).lower()
    return (
        _id(d, "account_setup_email_address_input").exists
        or _id(d, "AccountAutoDiscoveryContent").exists
        or _id(d, "IncomingServerSettingsContent").exists
        or _id(d, "OutgoingServerSettingsContent").exists
        or "accountsetupcomposition" in activity
    )


def _open_account_setup_directly(d):
    for component in ("com.fsck.k9.activity.setup.AccountSetupComposition",):
        try:
            d.app_start(APP_PKG, component, wait=True, stop=False, use_monkey=False)
            time.sleep(1.0)
            if _is_setup_entry_visible(d):
                return
        except Exception:
            pass

        subprocess.run(
            [ADB_BIN, "shell", "am", "start", "-W", "-n", f"{APP_PKG}/{component}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.0)
        if _is_setup_entry_visible(d):
            return


def _wait_onboarding_email_entry(d):
    # Some launches open directly on setup content.
    if _is_setup_entry_visible(d):
        return

    if _id(d, "onboarding_welcome_start_button").exists:
        _tap_id(d, "onboarding_welcome_start_button", timeout=8)

    try:
        _wait_until(
            lambda: _id(d, "onboarding_migration_new_account_button").exists
            or _is_setup_entry_visible(d),
            14,
            "Did not reach migration gate or setup entry after welcome",
        )
    except RuntimeError:
        _open_account_setup_directly(d)

    if _id(d, "onboarding_migration_new_account_button").exists:
        _tap_id(d, "onboarding_migration_new_account_button", timeout=8)

    if not _is_setup_entry_visible(d):
        _open_account_setup_directly(d)

    _wait_until(
        lambda: _is_setup_entry_visible(d),
        20,
        f"Did not reach setup entry screen; current activity='{_current_activity_name(d)}'",
    )

    _wait_id(d, "account_setup_email_address_input", timeout=20)


def _advance_email_to_manual(d):
    # First Next after entering email.
    click_then_expect(
        d,
        (
            _id(d, "account_setup_next_button")
            if _id(d, "account_setup_next_button").exists
            else d(text="Next")
        ),
        lambda: d(textContains="Configuration not found").exists
        or _id(d, "IncomingServerSettingsContent").exists,
        timeout=20,
        retries=2,
    ) or _tap_next(d)

    _wait_until(
        lambda: d(textContains="Configuration not found").exists
        or _id(d, "IncomingServerSettingsContent").exists,
        25,
        "Did not reach configuration-not-found or incoming-settings state",
    )

    # Validated path: click Next on "Configuration not found".
    if d(textContains="Configuration not found").exists:
        _wait_until(
            lambda: _id(d, "account_setup_next_button").exists
            or _id(d, "IncomingServerSettingsContent").exists,
            10,
            "Timed out waiting for next button on configuration-not-found screen",
        )
        if _id(d, "account_setup_next_button").exists:
            click_then_expect(
                d,
                _id(d, "account_setup_next_button"),
                lambda: _id(d, "IncomingServerSettingsContent").exists,
                timeout=20,
                retries=2,
            ) or _tap_next(d)

    _wait_id(d, "IncomingServerSettingsContent", timeout=25)


def _set_incoming_settings(d):
    _wait_id(d, "IncomingServerSettingsContent", timeout=25)
    _dismiss_ephemeral_overlays(d)
    _set_labeled_field(d, "Server", IMAP_HOST, allow_contains=True)
    try:
        _set_labeled_field(d, "Username", ACCOUNT_EMAIL, allow_contains=True)
    except RuntimeError:
        # Username is usually pre-filled from email entry.
        pass
    try:
        _set_labeled_field(d, "Password", ACCOUNT_PASSWORD)
    except RuntimeError:
        try:
            _set_password_after_username(d, ACCOUNT_PASSWORD)
        except RuntimeError:
            _set_first_password_field(d, ACCOUNT_PASSWORD)
    _dismiss_keyboard_safely(d, "IncomingServerSettingsContent")
    _tap_next(d)
    _handle_certificate_warning_if_present(d)


def _set_outgoing_settings(d):
    _wait_id(d, "OutgoingServerSettingsContent", timeout=25)
    _set_labeled_field(d, "Server", SMTP_HOST, allow_contains=True)
    _dismiss_keyboard_if_open(d, "OutgoingServerSettingsContent")
    _tap_next(d)
    _handle_certificate_warning_if_present(d)


def _set_display_options(d):
    _wait_id(d, "DisplayOptionsContent", timeout=20)
    # Prefer label-based fill for Compose input wrappers.
    try:
        _set_labeled_field(d, "Your name", ACCOUNT_DISPLAY_NAME, allow_contains=True)
    except RuntimeError:
        _set_text_id(
            d,
            "account_setup_display_options_display_name_input",
            ACCOUNT_DISPLAY_NAME,
            "Your name",
        )
    _dismiss_keyboard_safely(d, "DisplayOptionsContent")
    _tap_next(d)


def _ensure_notification_permission_granted():
    subprocess.run(
        [
            ADB_BIN,
            "shell",
            "pm",
            "grant",
            APP_PKG,
            "android.permission.POST_NOTIFICATIONS",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _dismiss_in_app_permissions_if_present(d):
    if _id(d, "onboarding_permissions_skip_button").exists:
        _tap_id(d, "onboarding_permissions_skip_button", timeout=5)


def _has_setup_ui(d) -> bool:
    return (
        _id(d, "AccountAutoDiscoveryContent").exists
        or _id(d, "IncomingServerSettingsContent").exists
        or _id(d, "OutgoingServerSettingsContent").exists
        or _id(d, "SpecialFoldersContent").exists
        or _id(d, "DisplayOptionsContent").exists
        or _id(d, "SyncOptionsContent").exists
        or _id(d, "CreateAccountContent").exists
        or _id(d, "onboarding_welcome_start_button").exists
        or _id(d, "onboarding_migration_new_account_button").exists
    )


def ensure_account_configured():
    attempts = 0
    last_exc = None
    while attempts < 2:
        attempts += 1
        try:
            # Grant permission before app start to prevent UI blocking on API 33+
            _ensure_notification_permission_granted()

            d = initialize_ui_automation(max_retries=4, retry_delay=2)
            d.app_start(APP_PKG, stop=True, wait=True, use_monkey=True)
            time.sleep(3.0)

            print(
                f"[tb-setup] onboarding/manual minimal flow start (attempt {attempts})",
                flush=True,
            )
            _wait_onboarding_email_entry(d)
            _set_text_id(
                d,
                "account_setup_email_address_input",
                ACCOUNT_EMAIL,
                "email",
                fallback_edit_index=0,
            )
            _dismiss_keyboard_if_open(d, "AccountAutoDiscoveryContent")
            _advance_email_to_manual(d)

            _set_incoming_settings(d)
            _wait_for_any_screen(
                d,
                ["OutgoingServerSettingsContent"],
                timeout=70,
                context="incoming -> outgoing transition",
            )

            _set_outgoing_settings(d)
            _wait_for_any_screen(
                d,
                ["SpecialFoldersContent", "DisplayOptionsContent"],
                timeout=70,
                context="outgoing -> post-validation transition",
            )

            if _id(d, "SpecialFoldersContent").exists:
                _tap_next(d)

            _set_display_options(d)

            _wait_for_any_screen(
                d,
                ["SyncOptionsContent", "CreateAccountContent"],
                timeout=30,
                context="display -> sync/create transition",
            )
            if _id(d, "SyncOptionsContent").exists:
                _tap_next(d)

            _ensure_notification_permission_granted()
            _dismiss_in_app_permissions_if_present(d)

            time.sleep(1.0)
            if _has_setup_ui(d):
                raise RuntimeError(
                    "Account setup appears incomplete; onboarding/setup UI still visible"
                )

            print("[tb-setup] account setup completed", flush=True)
            return
        except Exception as exc:
            last_exc = exc
            if _is_device_offline_error(exc) and attempts < 2:
                print(
                    "[tb-setup] device went offline; attempting one recovery retry",
                    flush=True,
                )
                _recover_offline_device()
                continue
            raise

    if last_exc is not None:
        raise last_exc


if __name__ == "__main__":
    mode = "--ensure-account"
    if len(sys.argv) > 1:
        mode = sys.argv[1]

    if mode == "--ensure-account":
        ensure_account_configured()
    else:
        raise SystemExit(f"Unknown mode: {mode}")
