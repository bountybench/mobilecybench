#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
import traceback

os.environ.setdefault("UI_TARGET_PACKAGE", "com.jerboa")

try:
    from apps.jerboa.helpers.ui_session import (
        configure_adb,
        connect_u2,
        get_release_package,
        register_anr_watchers,
        verify_or_recover_u2,
    )
    from utils.ui_utils import click_then_expect, wait_and_set_text, wait_for_ui_stable
except ImportError as e:
    print(f"[create_post_automation] missing ui utils: {e}", file=sys.stderr)
    sys.exit(2)


def _log(msg: str) -> None:
    print(f"[create_post_automation] {msg}", file=sys.stderr)


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


def _tap_community_field_from_label(d) -> bool:
    """Tap the overlaid community field using the known Compose layout.

    In Jerboa's CreatePostBody, the visible "Community" text field is covered by
    a full-width clickable Box that navigates to `communityList?select=true`.
    Tapping inside the field area is more stable than fishing for generic
    clickable nodes in the hierarchy.
    """
    back_button = d(description="Back")
    label = d(text="Community")
    if not label.exists:
        return False

    try:
        label_node = label.get()
        bounds = _parse_bounds(label_node.attrib.get("bounds", ""))
        if not bounds:
            return False
        left_x, _top_y, right_x, bottom_y = bounds
        tap_x = (left_x + right_x) // 2
        # The clickable Box overlays the full OutlinedTextField below the label.
        tap_y = bottom_y + 28
        d.click(tap_x, tap_y)
        return bool(back_button.wait(timeout=10))
    except Exception as e:
        _log(f"Community field tap from label failed: {e}")
        return False

def _open_community_picker(d) -> bool:
    """Open the select-mode community list from CreatePostBody.

    The Jerboa code first renders the create-post form and then overlays the
    Community field with a dedicated clickable Box. Use that invariant rather
    than generic clickable-node discovery.
    """
    if _tap_community_field_from_label(d):
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
        if _tap_community_field_from_label(d):
            return True

    back_button = d(description="Back")
    try:
        # Final fallback: tap the expected full-width field area near the bottom
        # of the form after swiping. This mirrors the Compose layout more
        # closely than scanning arbitrary clickable nodes.
        d.click(width // 2, int(height * 0.72))
        if back_button.wait(timeout=10):
            return True
    except Exception as e:
        _log(f"Community overlay fallback tap failed: {e}")

    return _tap_community_field_from_label(d)


def _select_seeded_community(d) -> bool:
    """Select a deterministically seeded community from the select-mode list.

    The `communityList?select=true` route is preloaded from followed
    communities in MainActivity before CommunityListActivity renders, so the
    stable path is to tap the seeded visible title directly and avoid search.
    """
    seeded_titles = [
        "Technology Discussion",
        "Gaming Community",
        "News Discussion",
    ]

    if not _wait_for_any_text(d, ["Search...", "Create post"], timeout=15):
        _log("Community selection screen did not become recognizable")
        return False

    for title in seeded_titles:
        exact = d(text=title)
        if exact.wait(timeout=3):
            if click_then_expect(d, exact, d(text="Create post"), timeout=15):
                return True
            _log(f"Tapped seeded community {title} but did not return to Create post")
            return False

    # Search only as a fallback if the followed-community preload did not
    # render as expected.
    search_field = d(className="android.widget.EditText", instance=0)
    if search_field.exists:
        for title, query in (
            ("Technology Discussion", "technology"),
            ("Gaming Community", "gaming"),
            ("News Discussion", "news"),
        ):
            if not wait_and_set_text(d, search_field, query):
                continue
            wait_for_ui_stable(d, min_consecutive=2, timeout=5)
            exact = d(text=title)
            if exact.wait(timeout=5):
                if click_then_expect(d, exact, d(text="Create post"), timeout=15):
                    return True
                _log(
                    f"Tapped searched seeded community {title} but did not return to Create post"
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


def _reset_app_between_attempts(d, pkg: str) -> None:
    """Clear partial UI state before the retry re-dispatches ACTION_SEND."""
    try:
        d.shell(f"am force-stop {pkg}")
    except Exception as e:
        _log(f"Failed to force-stop {pkg} between retries: {e}")
    time.sleep(1)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: create_post_automation.py <post_body>", file=sys.stderr)
        return 2

    body = sys.argv[1]
    _log("Starting UI automation to submit shared post")

    try:
        configure_adb(_log)
        d, serial = connect_u2(_log, retry_delay=10)
        d = verify_or_recover_u2(d, serial, _log)
        if d is None:
            return 2
        register_anr_watchers(d, _log)
        pkg = get_release_package(d)
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            _log(f"Create-post attempt {attempt}/{max_attempts}")
            if _submit_post_once(d, pkg, body):
                return 0

            if attempt < max_attempts:
                _log("Retrying create-post flow after resetting Jerboa state")
                _reset_app_between_attempts(d, pkg)

        _log("Create-post flow failed after retries")
        return 1
    except Exception as e:
        _log(f"Exception: {e}\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
