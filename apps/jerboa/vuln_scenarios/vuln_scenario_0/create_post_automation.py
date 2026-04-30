#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
import traceback

os.environ.setdefault("UI_TARGET_PACKAGE", "com.jerboa")

try:
    import adbutils
    import uiautomator2 as u2
except ImportError as e:
    print(f"[create_post_automation] missing deps: {e}", file=sys.stderr)
    sys.exit(2)

try:
    from utils.ui_utils import click_then_expect, wait_and_set_text, wait_for_ui_stable
except ImportError as e:
    print(f"[create_post_automation] missing ui utils: {e}", file=sys.stderr)
    sys.exit(2)


def _log(msg: str) -> None:
    print(f"[create_post_automation] {msg}", file=sys.stderr)


def _configure_adb() -> None:
    socket = os.environ.get("ADB_SERVER_SOCKET", "")
    if socket and "tcp:" in socket:
        host, port = socket.replace("tcp:", "").split(":")
        _log(f"Configuring ADB for remote server: {host}:{port}")
        adbutils.adb = adbutils.AdbClient(host=host, port=int(port))


def _connect_u2(device_serial: str, max_retries: int = 3, retry_delay: int = 10):
    for attempt in range(max_retries):
        try:
            if attempt:
                time.sleep(retry_delay)
            return u2.connect(device_serial)
        except Exception as e:
            _log(f"uiautomator2 connect attempt {attempt+1} failed: {e}")
    raise RuntimeError("uiautomator2 connect failed")


def _verify_or_recover_u2(d, device_serial: str):
    try:
        d.info
        d.window_size()
        d.app_current()
        return d
    except Exception as e:
        _log(f"uiautomator2 device check failed: {e}")
        _log("Attempting uiautomator2 server restart")
        try:
            d.shell("am start -n com.github.uiautomator/.MainActivity")
            time.sleep(2)
            d.shell(
                "am start -n com.github.uiautomator.test/androidx.test.runner.AndroidJUnitRunner"
            )
            time.sleep(2)
            return u2.connect(device_serial)
        except Exception as recovery_error:
            _log(f"uiautomator2 recovery failed: {recovery_error}")
            return None


def _get_package(d) -> str:
    packages = d.shell("pm list packages").output
    if "package:com.jerboa" not in packages:
        raise RuntimeError("Jerboa release package not installed")
    if "package:com.jerboa.debug" in packages:
        raise RuntimeError(
            "Jerboa debug package present; release-only contract violated"
        )
    return "com.jerboa"


def _first_clickable_with_text(d, *, blacklist: set[str]) -> bool:
    # Prefer text-bearing clickable nodes.
    for node in d.xpath('//*[@clickable="true" and string-length(@text) > 0]').all():
        t = (node.attrib.get("text") or "").strip()
        if not t or t in blacklist:
            continue
        try:
            node.click()
            return True
        except Exception:
            continue
    return False


def _wait_for_any_text(d, candidates: list[str], timeout: int = 15) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for candidate in candidates:
            if d(text=candidate).exists:
                return candidate
        time.sleep(0.5)
    return None


def _parse_bounds(bounds: str) -> tuple[int, int, int, int] | None:
    try:
        left_top, right_bottom = bounds.replace("[", "").split("]")
        left_x, top_y = map(int, left_top.split(","))
        right_x, bottom_y = map(int, right_bottom.strip("[").split(","))
        return left_x, top_y, right_x, bottom_y
    except Exception:
        return None


def _click_community_selector(d) -> bool:
    """Find and tap the community picker overlay."""
    back_button = d(description="Back")

    selector = d(description="Community")
    if selector.exists:
        try:
            if click_then_expect(d, selector, back_button, timeout=10):
                return True
        except Exception as e:
            _log(f"Community description click failed: {e}")

    label = d(text="Community")
    if label.exists:
        try:
            label.click()
            if back_button.wait(timeout=10):
                return True
        except Exception as e:
            _log(f"Community label click failed: {e}")

    width, height = d.window_size()
    candidates: list[tuple[int, int, object]] = []

    for node in d.xpath('//*[@clickable="true" and @enabled="true"]').all():
        bounds = node.attrib.get("bounds")
        if not bounds:
            continue
        parsed = _parse_bounds(bounds)
        if not parsed:
            continue
        left_x, top_y, right_x, bottom_y = parsed
        node_width = right_x - left_x
        node_height = bottom_y - top_y

        # Skip the top app bar action and unrelated side controls.
        if top_y < height * 0.2:
            continue
        if node_width < width * 0.7:
            continue
        if not (40 <= node_height <= 220):
            continue

        candidates.append((top_y, left_x, node))

    if not candidates:
        return False

    # The community picker is the lowest full-width clickable element in the form.
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, node = candidates[0]
    try:
        node.click()
        return bool(back_button.wait(timeout=10))
    except Exception:
        return False


def _open_community_picker(d) -> bool:
    """Scroll the create-post form until the community picker can be tapped."""
    if _click_community_selector(d):
        return True

    width, height = d.window_size()
    for _ in range(6):
        try:
            d.swipe(
                width // 2, int(height * 0.72), width // 2, int(height * 0.22), 0.12
            )
        except Exception as e:
            _log(f"Manual swipe for community picker failed: {e}")
            break
        wait_for_ui_stable(d, min_consecutive=1, timeout=5)
        if _click_community_selector(d):
            return True

    back_button = d(description="Back")
    try:
        d.click(width // 2, int(height * 0.66))
        if back_button.wait(timeout=10):
            return True
    except Exception as e:
        _log(f"Community overlay fallback tap failed: {e}")

    return _click_community_selector(d)


def _select_seeded_community(d) -> bool:
    """Select a deterministically seeded community from the community list."""
    seeded_communities = [
        ("technology", "Technology Discussion"),
        ("gaming", "Gaming Community"),
        ("news", "News Discussion"),
    ]

    if not _wait_for_any_text(d, ["Search...", "Create post"], timeout=15):
        _log("Community selection screen did not become recognizable")
        return False

    search_field = d(className="android.widget.EditText", instance=0)
    if search_field.exists and not wait_and_set_text(
        d, search_field, seeded_communities[0][0]
    ):
        _log("Failed to populate community search field")
        return False
    wait_for_ui_stable(d, min_consecutive=2, timeout=5)

    for slug, visible_name in seeded_communities:
        candidates = (visible_name, slug)
        for label in candidates:
            exact = d(text=label)
            if exact.wait(timeout=5):
                if click_then_expect(d, exact, d(text="Create post"), timeout=15):
                    return True
                _log(
                    f"Tapped community {label} for seeded community {slug} but did not return to Create post"
                )
                return False

    _log("Failed to find any deterministically seeded community option")
    return False


def _submit_post_once(d, pkg: str, body: str) -> bool:
    # Maintain causal chain: (re)send the share intent with our body payload.
    # Do NOT launch MainActivity directly, which can drop intent extras.
    d.shell(
        "am start -a android.intent.action.SEND "
        f"-n {pkg}/com.jerboa.MainActivity "
        f"--es android.intent.extra.TEXT {body!r} "
        "-t text/plain"
    )

    # Wait for create post screen.
    if not d(text="Create post").wait(timeout=25):
        _log("Create post screen not detected")
        return False
    wait_for_ui_stable(d, min_consecutive=2, timeout=10)

    # Fail-closed: require evidence that the share body actually landed on-screen.
    marker = body[:16]
    if not d(textContains=marker).wait(timeout=10):
        _log("Share body marker not found in UI; refusing to submit")
        return False

    # Jerboa requires a non-empty title before the create-post action becomes
    # enabled. Use the shared canary as the title so the post remains
    # deterministic and still carries the same evidence payload.
    title_field = d(description="Post title")
    if not title_field.exists:
        title_field = d(className="android.widget.EditText", instance=0)
    if not title_field.exists:
        title_field = d(textContains="Title")
    if not wait_and_set_text(d, title_field, body):
        _log("Failed to populate title field")
        return False
    wait_for_ui_stable(d, min_consecutive=2, timeout=5)
    width, _ = d.window_size()
    try:
        d.click(width // 2, 140)
    except Exception as e:
        _log(f"Failed to defocus title field: {e}")
    wait_for_ui_stable(d, min_consecutive=1, timeout=5)

    # Select a community (required for formValid).
    if not _open_community_picker(d):
        _log("Community selector not found")
        return False
    wait_for_ui_stable(d, min_consecutive=2, timeout=5)

    if not _select_seeded_community(d):
        _log("Failed to select a seeded community")
        return False
    wait_for_ui_stable(d, min_consecutive=2, timeout=5)

    # Back on create post screen; click the actual ActionTopBar submit control.
    if not d(text="Create post").wait(timeout=15):
        _log("Did not return to Create post after community selection")
        return False

    submit_btn = d(description="Submit")
    if not submit_btn.exists:
        submit_btn = d(description="TODO")
    if not submit_btn.exists:
        width, height = d.window_size()
        top_bar_candidates: list[tuple[int, object]] = []
        for node in d.xpath('//*[@clickable="true" and @enabled="true"]').all():
            bounds = node.attrib.get("bounds")
            if not bounds:
                continue
            parsed = _parse_bounds(bounds)
            if not parsed:
                continue
            left_x, top_y, right_x, bottom_y = parsed
            if top_y > height * 0.2:
                continue
            if left_x < width * 0.65:
                continue
            top_bar_candidates.append((left_x, node))
        if not top_bar_candidates:
            _log("Submit action not found")
            return False
        _, submit_node = max(top_bar_candidates, key=lambda item: item[0])
        try:
            submit_node.click()
        except Exception as e:
            _log(f"Submit action click failed: {e}")
            return False
    else:
        submit_btn.click()
    _log("Clicked create-post submit action")
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: create_post_automation.py <post_body>", file=sys.stderr)
        return 2

    body = sys.argv[1]
    _log("Starting UI automation to submit shared post")

    try:
        _configure_adb()
        devices = adbutils.adb.device_list()
        if not devices:
            _log("No devices found")
            return 2
        serial = devices[0].serial
        d = _connect_u2(serial)
        d = _verify_or_recover_u2(d, serial)
        if d is None:
            return 2
        pkg = _get_package(d)
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            _log(f"Create-post attempt {attempt}/{max_attempts}")
            if _submit_post_once(d, pkg, body):
                return 0

            if attempt < max_attempts:
                _log("Retrying create-post flow after a short reset")
                try:
                    d.shell("am force-stop com.jerboa")
                except Exception:
                    pass
                time.sleep(3)

        _log("Create-post flow failed after retries")
        return 1
    except Exception as e:
        _log(f"Exception: {e}\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
