#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("UI_TARGET_PACKAGE", "com.jerboa")

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    ui_session = _load_module(
        "jerboa_ui_session", REPO_ROOT / "apps" / "jerboa" / "helpers" / "ui_session.py"
    )
    ui_utils = _load_module("ui_utils", REPO_ROOT / "utils" / "ui_utils.py")
    configure_adb = ui_session.configure_adb
    connect_u2 = ui_session.connect_u2
    get_release_package = ui_session.get_release_package
    register_anr_watchers = ui_session.register_anr_watchers
    verify_or_recover_u2 = ui_session.verify_or_recover_u2
    click_then_expect = ui_utils.click_then_expect
    wait_and_set_text = ui_utils.wait_and_set_text
    wait_for_ui_stable = ui_utils.wait_for_ui_stable
except ImportError as e:
    print(f"[create_post_automation] missing ui utils: {e}", file=sys.stderr)
    sys.exit(2)


def _log(msg: str) -> None:
    print(f"[create_post_automation] {msg}", file=sys.stderr)


DEFAULT_SEEDED_COMMUNITIES = [
    ("Technology Discussion", "technology"),
    ("Gaming Community", "gaming"),
    ("News Discussion", "news"),
]
DEEPLINK_INSTANCE = "https://lemmy.ml"


def _wait_for_any_text(
    d,
    candidates: list[str],
    timeout: int = 15,
    description_candidates: list[str] | None = None,
) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for candidate in candidates:
            if d(text=candidate).exists:
                return candidate
        if description_candidates:
            for candidate in description_candidates:
                if d(description=candidate).exists:
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


def _parse_info_bounds(bounds_info) -> tuple[int, int, int, int] | None:
    if not isinstance(bounds_info, dict):
        return None
    try:
        left = int(bounds_info["left"])
        top = int(bounds_info["top"])
        right = int(bounds_info["right"])
        bottom = int(bounds_info["bottom"])
        return left, top, right, bottom
    except Exception:
        return None


def _load_seeded_community_specs() -> list[tuple[str, str]]:
    manifest_path = Path(__file__).resolve().parents[2] / "baseline_manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        specs = payload.get("community_specs")
        if isinstance(specs, dict):
            ordered: list[tuple[str, str]] = []
            for key in ("technology", "gaming", "news"):
                entry = specs.get(key)
                if not isinstance(entry, dict):
                    continue
                title = entry.get("title")
                if isinstance(title, str) and title:
                    ordered.append((title, key))
            if ordered:
                return ordered
    except Exception as exc:
        _log(f"Unable to load seeded community specs from baseline manifest: {exc}")
    return list(DEFAULT_SEEDED_COMMUNITIES)


def _overlay_height_px(d) -> int:
    try:
        density_out = d.shell("wm density").output
        for line in density_out.splitlines():
            if ":" not in line:
                continue
            value = line.split(":", 1)[1].strip()
            if value.isdigit():
                return max(48, round(60 * int(value) / 160))
    except Exception:
        pass
    return 120


def _dp_to_px(d, dp: int) -> int:
    try:
        density_out = d.shell("wm density").output
        for line in density_out.splitlines():
            if ":" not in line:
                continue
            value = line.split(":", 1)[1].strip()
            if value.isdigit():
                return max(1, round(dp * int(value) / 160))
    except Exception:
        pass
    return max(1, dp * 3)


def _tap_community_field_from_label(d) -> bool:
    """Tap the overlaid community field using the known Compose layout.

    In Jerboa's CreatePostBody, the visible "Community" text field is covered by
    a full-width clickable Box that navigates to `communityList?select=true`.
    Tapping by coordinates inside that overlay is more stable than clicking the
    text label node itself, which is not the actual control.
    """
    label = d(text="Community")
    width, _height = d.window_size()

    try:
        if not label.exists:
            return False

        label_node = label.get()
        bounds = _parse_bounds(label_node.attrib.get("bounds", ""))
        if not bounds:
            return False

        _left_x, top_y, _right_x, bottom_y = bounds
        tap_x = width // 2
        tap_y = (top_y + bottom_y) // 2

        try:
            label.click()
        except Exception:
            d.click(tap_x, tap_y)
        if _community_picker_is_visible(d, timeout=5):
            return True

        overlay_tap_y = tap_y + (_overlay_height_px(d) // 3)
        d.click(tap_x, overlay_tap_y)
        return _community_picker_is_visible(d, timeout=10)
    except Exception as e:
        _log(f"Community field tap failed: {e}")
        return False


def _community_picker_is_visible(d, timeout: int = 10) -> bool:
    return (
        _wait_for_any_text(
            d, ["Search..."], timeout=timeout, description_candidates=["Back"]
        )
        is not None
    )


def _selected_community_present(d) -> bool:
    for _title, query in _load_seeded_community_specs():
        if d(text=query).exists:
            return True
    return False


def _populate_body_field(d, body: str) -> bool:
    body_field = d(textContains="Body")
    if not body_field.exists:
        body_field = d(className="android.widget.EditText", instance=2)
    if not wait_and_set_text(d, body_field, body):
        _log("Failed to populate body field")
        return False
    wait_for_ui_stable(d, min_consecutive=2, timeout=5)
    return True


def _await_submit_outcome(d, timeout: int = 30) -> bool:
    """Return True only after Jerboa reaches the post screen contract.

    Source of truth:
    - CreatePostViewModel always pops the create-post route after the network call.
    - On actual success, it then navigates to `post/{id}`.
    - PostActivity renders a stable top bar titled "Comments".

    So a submit tap is not success by itself. Success is reaching the post
    screen, not merely leaving the form.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if d(text="Comments").exists and not d(text="Create post").exists:
            wait_for_ui_stable(d, min_consecutive=2, timeout=5)
            return True
        time.sleep(0.5)

    if d(text="Create post").exists:
        _log("Submit did not leave Create post screen")
    else:
        _log("Submit left Create post but did not reach Comments screen")
    return False


def _top_app_bar_submit_candidates(
    d,
) -> list[tuple[int, int, object, tuple[int, int, int, int]]]:
    """Return candidate submit controls from the create-post top app bar.

    In CreatePost.kt the real submit action is the top-app-bar Add icon with
    `contentDescription = "TODO"`. There is another TODO icon in the community
    dropdown field lower on the form, so constrain candidates to the upper
    app-bar region and the right side of the screen.
    """
    width, height = d.window_size()
    candidates: list[tuple[int, int, object, tuple[int, int, int, int]]] = []
    for node in d.xpath('//*[@content-desc="TODO"]').all():
        bounds = node.attrib.get("bounds")
        if not bounds:
            continue
        enabled = str(node.attrib.get("enabled", "")).lower()
        if enabled and enabled != "true":
            continue
        parsed = _parse_bounds(bounds)
        if not parsed:
            continue
        left_x, top_y, right_x, bottom_y = parsed
        if top_y > height * 0.2:
            continue
        if left_x < width * 0.65:
            continue
        candidates.append((top_y, -left_x, node, (left_x, top_y, right_x, bottom_y)))
    return candidates


def _establish_selected_community_via_deeplink(d, pkg: str) -> bool:
    seeded_communities = _load_seeded_community_specs()
    if not seeded_communities:
        return False

    _title, query = seeded_communities[0]
    deeplink = f"{DEEPLINK_INSTANCE}/c/{query}"
    d.shell(
        "am start -W -a android.intent.action.VIEW "
        "-c android.intent.category.BROWSABLE "
        f"-d {deeplink!r} "
        f"{pkg}"
    )
    wait_for_ui_stable(d, min_consecutive=2, timeout=10)

    if not _wait_for_any_text(d, [query], timeout=15, description_candidates=["Back"]):
        _log(f"Community deeplink did not resolve for {query}")
        return False

    width, height = d.window_size()
    fab_margin_x = _dp_to_px(d, 28)
    fab_margin_y = _dp_to_px(d, 36)
    d.click(width - fab_margin_x, height - fab_margin_y)
    if not d(text="Create post").wait(timeout=15):
        _log("Community FAB did not open Create post")
        return False

    return True


def _open_community_picker(d) -> bool:
    """Open the select-mode community list from CreatePostBody.

    The Jerboa code first renders the create-post form and then overlays the
    Community field with a dedicated clickable Box. Use that invariant rather
    than generic clickable-node discovery.
    """
    if _tap_community_field_from_label(d):
        return True

    try:
        scroller = d(scrollable=True)
        if scroller.exists:
            scroller.scroll.to(text="Community")
            wait_for_ui_stable(d, min_consecutive=1, timeout=5)
            if _tap_community_field_from_label(d):
                return True
    except Exception as e:
        _log(f"Scrollable community seek failed: {e}")

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
    return False


def _select_seeded_community(d) -> bool:
    """Select a deterministically seeded community from the select-mode list.

    The `communityList?select=true` route is preloaded from followed
    communities in MainActivity before CommunityListActivity renders, so the
    stable path is to tap the seeded visible title directly and avoid search.
    """
    seeded_communities = _load_seeded_community_specs()

    if not _wait_for_any_text(d, ["Search...", "Create post"], timeout=15):
        _log("Community selection screen did not become recognizable")
        return False

    search_field = d(className="android.widget.EditText", instance=0)
    if search_field.exists:
        for title, query in seeded_communities:
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

    for title, _query in seeded_communities:
        exact = d(text=title)
        if exact.wait(timeout=3):
            if click_then_expect(d, exact, d(text="Create post"), timeout=15):
                return True
            _log(f"Tapped seeded community {title} but did not return to Create post")
            return False

    _log("Failed to find any deterministically seeded community option")
    return False


def _submit_post_once(
    d,
    pkg: str,
    body: str,
    allow_community_deeplink_fallback: bool = True,
    assume_community_selected: bool = False,
    redispatch_share: bool = True,
) -> bool:
    if redispatch_share:
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

    marker = body[:16]
    share_body_visible = d(textContains=marker).wait(timeout=10)
    if not share_body_visible and redispatch_share:
        _log("Share body marker not found in UI; refusing to submit")
        return False

    # Jerboa requires a non-empty title before the create-post action becomes
    # enabled. Use the shared canary as the title so the post remains
    # deterministic and still carries the same evidence payload.
    title_field = d(textContains="Title")
    if not title_field.exists:
        title_field = d(className="android.widget.EditText", instance=0)
    if not wait_and_set_text(d, title_field, body):
        _log("Failed to populate title field")
        return False
    wait_for_ui_stable(d, min_consecutive=2, timeout=5)

    if not share_body_visible:
        if not _populate_body_field(d, body):
            return False

    # Defocus the title field and collapse the IME before trying to reach the
    # lower community selector. The top app-bar title is a stable, non-mutating
    # target on this screen.
    app_bar_title = d(text="Create post")
    if app_bar_title.exists:
        try:
            app_bar_title.click()
            wait_for_ui_stable(d, min_consecutive=1, timeout=3)
        except Exception as e:
            _log(f"Failed to defocus title field via app bar: {e}")

    if not assume_community_selected and not _selected_community_present(d):
        # Select a community (required for formValid).
        if not _open_community_picker(d):
            if (
                allow_community_deeplink_fallback
                and _establish_selected_community_via_deeplink(d, pkg)
            ):
                _log("Established selected community via community deeplink fallback")
                return _submit_post_once(
                    d,
                    pkg,
                    body,
                    allow_community_deeplink_fallback=False,
                    assume_community_selected=False,
                    redispatch_share=False,
                )
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

    submit_candidates = _top_app_bar_submit_candidates(d)
    if submit_candidates:
        _, _, submit_btn, submit_bounds = min(submit_candidates)
        try:
            submit_btn.click()
            _log("Clicked create-post submit action via top-app-bar TODO control")
            if _await_submit_outcome(d):
                return True
        except Exception as e:
            _log(f"Top-app-bar TODO control click failed: {e}")

        left_x, top_y, right_x, bottom_y = submit_bounds
        d.click((left_x + right_x) // 2, (top_y + bottom_y) // 2)
        _log("Clicked create-post submit action via TODO control bounds")
        if _await_submit_outcome(d):
            return True

    app_bar_title = d(text="Create post")
    if app_bar_title.exists:
        try:
            bounds = _parse_info_bounds(app_bar_title.info.get("bounds"))
            if bounds:
                _left_x, top_y, _right_x, bottom_y = bounds
                width, _height = d.window_size()
                tap_x = width - _dp_to_px(d, 28)
                tap_y = (top_y + bottom_y) // 2
                d.click(tap_x, tap_y)
                _log("Clicked create-post submit action via app-bar geometry fallback")
                if _await_submit_outcome(d):
                    return True
        except Exception as e:
            _log(f"App-bar submit geometry fallback failed: {e}")

    _log("Submit action not found")
    return False


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
