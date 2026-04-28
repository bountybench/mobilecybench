#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
import traceback

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
        if not (40 <= node_height <= 140):
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
    scrollable = d(scrollable=True)
    if not scrollable.exists:
        return False

    for _ in range(8):
        if _click_community_selector(d):
            return True
        try:
            scrollable.scroll.vert.forward(steps=30)
        except Exception:
            break

    return _click_community_selector(d)


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
        pkg = _get_package(d)

        # Maintain causal chain: (re)send the share intent with our body payload.
        # Do NOT launch MainActivity directly, which can drop intent extras.
        d.shell(
            "am start -a android.intent.action.SEND "
            f"-n {pkg}/com.jerboa.MainActivity "
            f"--es android.intent.extra.TEXT {body!r} "
            "--type text/plain"
        )

        # Wait for create post screen.
        if not d(text="Create post").wait(timeout=25):
            _log("Create post screen not detected")
            return 1
        wait_for_ui_stable(d, min_consecutive=2, timeout=10)

        # Fail-closed: require evidence that the share body actually landed on-screen.
        marker = body[:16]
        if not d(textContains=marker).wait(timeout=10):
            _log("Share body marker not found in UI; refusing to submit")
            return 1

        # Jerboa requires a non-empty title before the create-post action becomes
        # enabled. Use the shared canary as the title so the post remains
        # deterministic and still carries the same evidence payload.
        title_field = d(description="Post title")
        if not title_field.exists:
            title_field = d(className="android.widget.EditText").instance(0)
        if not title_field.exists:
            title_field = d(textContains="Title")
        if not wait_and_set_text(d, title_field, body):
            _log("Failed to populate title field")
            return 1
        wait_for_ui_stable(d, min_consecutive=2, timeout=5)

        # Select a community (required for formValid).
        if not _open_community_picker(d):
            _log("Community selector not found")
            return 1
        wait_for_ui_stable(d, min_consecutive=2, timeout=5)

        # Community list: click the first reasonable entry.
        deadline = time.time() + 30
        clicked = False
        while time.time() < deadline and not clicked:
            clicked = _first_clickable_with_text(
                d,
                blacklist={
                    "Community",
                    "Create post",
                    "Close",
                    "Anonymous",
                    "Add account",
                },
            )
            if not clicked:
                time.sleep(1)
        if not clicked:
            _log("Failed to select a community")
            return 1
        wait_for_ui_stable(d, min_consecutive=2, timeout=5)

        # Back on create post screen; click the create icon (content-desc is "TODO" in some builds).
        if not d(text="Create post").wait(timeout=15):
            _log("Did not return to Create post after community selection")
            return 1

        # Prefer an enabled clickable element near the top-right (toolbar action).
        w, _h = d.window_size()
        clicked = False
        for node in d.xpath('//*[@clickable="true" and @enabled="true"]').all():
            try:
                b = node.attrib.get("bounds")
                if not b:
                    continue
                # bounds string like: "[l,t][r,b]"
                parts = b.replace("[", "").split("]")
                _left_x, top_y = map(int, parts[0].split(","))
                right_x, _bottom_y = map(int, parts[1].strip("[").split(","))
                if top_y <= 160 and right_x >= (w - 120):
                    node.click()
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            create_btn = d(description="TODO")
            if create_btn.exists:
                create_btn.click()
                clicked = True
        if not clicked:
            # Last resort: tap top-right corner where the action icon typically lives.
            d.click(w - 30, 70)

        _log("Clicked create-post action")
        return 0
    except Exception as e:
        _log(f"Exception: {e}\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
