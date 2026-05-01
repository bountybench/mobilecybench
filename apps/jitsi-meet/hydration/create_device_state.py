#!/usr/bin/env python3
"""Hydrate every AsyncStorage row + both SharedPreferences XML files.

The orchestrator pulls RKStorage and force-stops the app before this
runs, then pushes back after. This script writes only to a host-side
copy via Python's stdlib `sqlite3` (no shell escaping, no run-as, no
device-side sqlite3 needed) and stages SharedPreferences XML for the
orchestrator to push.

Every key, field name, and value type below is tied to the app code path that
reads or writes it so the hydration state stays reviewable without relying on
external notes.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import _async_storage as a

# -----------------------------------------------------------------------------
# Identity seeded for the victim profile.
# -----------------------------------------------------------------------------

DEFAULT_DISPLAY_NAME = 'Robert "Bob" Marsh'
DEFAULT_EMAIL = "robert.marsh@northbridge-research.example"
DEFAULT_AVATAR = "https://gravatar.com/avatar/8c0b7e7b7c1e1a4e2b3a4e5f6a7b8c9d"
DEFAULT_SERVER = "https://10.0.2.2:8443"

# Lowercased (per react/features/base/connection/utils.ts:41-49 — the recent-list
# reducer stores `getURLWithoutParamsNormalized(...)` which lowercases href).
ROOM_PRIMARY = "project-aurora-sync"  # also matches the Prosody MUC + polls meeting key
DAY_MS = 86_400_000
HOUR_MS = 3_600_000

# Participant-id-shaped strings (uuid-ish). Real Jitsi participant ids are
# 8-hex; voters are written by polls/reducer.ts:106-110 as {id: senderId, name: voterName}.
LOCAL_PARTICIPANT_ID = "d2b5fe0c"
REMOTE_MARIANA_PID = "7c41e9ad"
REMOTE_AARON_PID = "1f93b6e2"


# -----------------------------------------------------------------------------
# Builders for each key (every value is consumer-shape correct).
# -----------------------------------------------------------------------------


def build_settings(args: argparse.Namespace) -> dict:
    """features/base/settings (filtered subtree per reducer.ts:107-124).

    The reducer's persistence filter excludes the *current* device ids
    (audioOutputDeviceId, cameraDeviceId, micDeviceId) but keeps the
    user-selected ones. We supply human-plausible Pixel device labels
    so the settings tree looks like a configured user.
    """
    return {
        "displayName": args.display_name,
        "email": args.email,
        "avatarURL": args.avatar_url,
        "serverURL": args.server_url,
        "disableCrashReporting": True,  # mirrored into SharedPrefs (Object 2)
        "disableSelfView": False,
        "localFlipX": True,
        "maxStageParticipants": 1,
        "startWithAudioMuted": True,
        "startWithVideoMuted": True,
        "startAudioOnly": False,
        "startCarMode": False,
        "showSubtitlesOnStage": False,
        "hideShareAudioHelper": False,
        "soundsIncomingMessage": True,
        "soundsParticipantJoined": True,
        "soundsParticipantKnocking": True,
        "soundsParticipantLeft": True,
        "soundsTalkWhileMuted": True,
        "soundsReactions": True,
        "userSelectedNotifications": {"notify.chatMessages": True},
        "userSelectedAudioOutputDeviceLabel": "Pixel speaker",
        "userSelectedCameraDeviceLabel": "Pixel front camera",
        "userSelectedMicDeviceLabel": "Pixel microphone",
    }


def build_recent_list(args: argparse.Namespace) -> list[dict]:
    """features/recent-list — all conference URLs lowercase per
    getURLWithoutParamsNormalized (utils.ts:41-49). Reverse-sorted: oldest
    first, newest last (per recent-list/reducer.ts:92).
    """
    now_ms = int(time.time() * 1000)
    server = args.server_url.rstrip("/")
    return [
        {
            "conference": "https://meet.jit.si/northbridgebudgetreview2026",
            "date": now_ms - 11 * DAY_MS,
            "duration": 8 * 60 * 1000,
        },
        {
            "conference": f"{server}/{ROOM_PRIMARY}",
            "date": now_ms - 4 * DAY_MS,
            "duration": 65 * 60 * 1000,
        },
        {
            "conference": f"{server}/1on1-mariana",
            "date": now_ms - 2 * DAY_MS,
            "duration": 47 * 60 * 1000,
        },
        {
            "conference": f"{server}/standup-northbridge",
            "date": now_ms - 1 * DAY_MS,
            "duration": 23 * 60 * 1000,
        },
    ]


def build_known_domains(args: argparse.Namespace) -> list[str]:
    """features/base/known-domains. The reducer's DEFAULT_STATE
    (known-domains/reducer.ts:16-21) is the four Jitsi defaults; we
    append the local host because the victim has joined `10.0.2.2`
    rooms. _addKnownDomains lowercases each domain (line 55).
    """
    from urllib.parse import urlparse

    host = (urlparse(args.server_url).hostname or "10.0.2.2").lower()
    return ["alpha.jitsi.net", "beta.meet.jit.si", "meet.jit.si", "8x8.vc", host]


def build_dropbox(args: argparse.Namespace) -> dict:
    """features/dropbox (full subtree persisted per dropbox/reducer.ts:11-20).

    The `_FAKE_VICTIM_..._DO_NOT_USE_` infix is intentional: probes
    pattern-matching on the synthetic markers find them deterministically;
    the marker also makes it impossible to confuse with real Dropbox
    tokens in a server log. `sl.B-` is the real Dropbox short-lived
    user-token prefix.
    """
    now_ms = int(time.time() * 1000)
    return {
        "token": "sl.B-FAKE_VICTIM_DROPBOX_ACCESS_TOKEN_DO_NOT_USE_3a7f9c2e",
        "rToken": "8FAKE_VICTIM_DROPBOX_REFRESH_TOKEN_DO_NOT_USE_5e2c1b3a",
        "expireDate": now_ms + 4 * HOUR_MS,
    }


def build_calendar_sync(args: argparse.Namespace) -> dict:
    """features/calendar-sync. Filter (reducer.tsx:62-65) is exactly
    {integrationType, msAuthState}. We seed Microsoft integration with a
    realistic-shaped (but synthetic) auth state.
    """
    now_s = int(time.time())
    expires = now_s + 30 * 24 * 3600
    return {
        "integrationType": "microsoft",
        "msAuthState": {
            "accessToken": (
                "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0."
                "FAKE_VICTIM_MS_GRAPH_ACCESS_TOKEN_DO_NOT_USE."
                "synthetic_signature_marker"
            ),
            "refreshToken": "0.AAA_FAKE_VICTIM_MS_REFRESH_TOKEN_DO_NOT_USE_2026",
            "expiresAt": expires,
            "homeAccountId": "northbridge-bob.northbridge-tenant",
            "tenantId": "northbridge-tenant",
            "scope": "Calendars.Read User.Read offline_access",
            "userSigninName": args.email,
        },
    }


def build_polls_history(args: argparse.Namespace) -> dict:
    """features/polls-history. Meeting key is the lowercased plain room
    name (polls-history/middleware.ts:10 reads
    `state['features/base/conference'].room`, which goes through
    parseURIString's `room?.toLowerCase()` at uri.ts:165).

    IPollData shape (polls/types.ts:34-88):
      pollId, senderId, question, answers: IAnswerData[]
      changingVote: bool, editing: bool, lastVote: bool[]|null,
      saved: bool, showResults: bool

    IAnswerData: { name, voters?: IVoterData[] }
    IVoterData:  { id, name }

    The reducer at polls/reducer.ts:112 sets `voters = voters?.length ? voters : undefined`
    — empty answer voters become `undefined` (omitted from JSON).
    `senderName` is on the wire (polls/middleware.ts:123) and is preserved
    on the persisted record.
    """
    return {
        "polls": {
            ROOM_PRIMARY: {
                "poll-1a2b3c": {
                    "pollId": "poll-1a2b3c",
                    "senderId": REMOTE_MARIANA_PID,
                    "senderName": "Mariana Velez",
                    "question": "Should we move the Aurora launch to Q3?",
                    "answers": [
                        {
                            "name": "Yes",
                            "voters": [
                                {
                                    "id": LOCAL_PARTICIPANT_ID,
                                    "name": DEFAULT_DISPLAY_NAME,
                                },
                            ],
                        },
                        {"name": "No"},  # voters omitted (reducer behavior)
                        {"name": "Defer 2 weeks"},
                    ],
                    "changingVote": False,
                    "editing": False,
                    "lastVote": [True, False, False],
                    "saved": True,
                    "showResults": True,
                },
                "poll-9z8y7x": {
                    "pollId": "poll-9z8y7x",
                    "senderId": REMOTE_AARON_PID,
                    "senderName": "Aaron Park",
                    "question": "Lunch on Friday — onsite or hybrid?",
                    "answers": [
                        {
                            "name": "Onsite",
                            "voters": [
                                {
                                    "id": LOCAL_PARTICIPANT_ID,
                                    "name": DEFAULT_DISPLAY_NAME,
                                },
                                {"id": REMOTE_MARIANA_PID, "name": "Mariana Velez"},
                            ],
                        },
                        {"name": "Hybrid"},
                    ],
                    "changingVote": False,
                    "editing": False,
                    "lastVote": [True, False],
                    "saved": True,
                    "showResults": True,
                },
            }
        }
    }


def build_config_cache(args: argparse.Namespace) -> dict:
    """config.js/<baseURL>. baseURL = ${protocol}//${host}${contextRoot || '/'}
    (app/actions.native.ts:109) — for an empty contextRoot it always ends
    in '/'. Disabling third-party requests matches what
    start_runtime.sh:enable_giphy_in_config writes server-side, so the
    cache is consistent with what the next live fetch would return.
    """
    server = args.server_url.rstrip("/")
    websocket = server.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return {
        "hosts": {
            "domain": "meet.jitsi",
            "muc": "muc.meet.jitsi",
            "focus": "focus.meet.jitsi",
            "anonymousdomain": "guest.meet.jitsi",
            "authdomain": "auth.meet.jitsi",
        },
        "bosh": f"{server}/http-bind",
        "websocket": f"{websocket}/xmpp-websocket",
        "disableThirdPartyRequests": False,
        "enableLobbyChat": True,
        "p2p": {"enabled": True},
        "prejoinConfig": {"enabled": True},
        "deploymentInfo": {"environment": "northbridge-lab", "region": "emulator"},
    }


def build_jwt(args: argparse.Namespace) -> dict:
    """features/base/jwt. Filter (jwt/reducer.ts:26-28) only allows
    knownAvatarUrl. JWT/idToken/refreshToken are explicitly excluded.
    """
    return {"knownAvatarUrl": args.avatar_url}


def build_misc_subtrees() -> dict[str, Any]:
    """All the small persisted subtrees. Source citations:

    - features/prejoin filter is { skipPrejoinOnReload: true } (prejoin/reducer.ts)
    - features/noise-suppression persists full subtree {enabled} (noise-suppression/reducer.ts:8-18)
    - features/virtual-background persists full subtree (virtual-background/reducer.ts:8-14)
    - features/video-quality-persistent-storage stores { persistedPrefferedVideoQuality }
      with the typo 'Preffered' as in source (video-quality/reducer.ts:48,64)
    - features/keyboard-shortcuts filter is { enabled: true } (keyboard-shortcuts/reducer.ts:17-25)
    - features/screnshot-capture — persistence key has the typo (screnshot-capture/reducer.ts:6);
      reducer key has correct spelling (line 18) so the row is orphaned at rehydrate, but it
      IS what the persistence inventory reports. We write the source-honest value.
    """
    return {
        "features/prejoin": {"skipPrejoinOnReload": False},
        "features/noise-suppression": {"enabled": True},
        "features/virtual-background": {
            "backgroundEffectEnabled": True,
            "backgroundType": "blur",
            "blurValue": 8,
            "selectedThumbnail": "blur",
            "virtualSource": "blur",
        },
        "features/video-quality-persistent-storage": {
            "persistedPrefferedVideoQuality": 720
        },
        "features/keyboard-shortcuts": {"enabled": True},
        "features/screnshot-capture": {"capturesEnabled": False},
    }


def build_virtual_backgrounds_direct() -> list[dict]:
    """Direct localStorage key 'virtualBackgrounds' (NOT JSON-prefixed by
    PersistenceRegistry — written by virtual-background/components/VirtualBackgrounds.tsx:216
    via jitsiLocalStorage.setItem). Image type from constants.ts: {id, src, tooltip?}.

    On native this code path is web-typically (file upload UI), so the row
    is unlikely to be read on Android — but the auth_policy lists it as a
    sensitive direct key, and writing it makes the persistence inventory
    complete. Harmless on native.
    """
    return [
        {
            "id": "northbridge-corner",
            "src": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
            "tooltip": "Northbridge corner office",
        }
    ]


# -----------------------------------------------------------------------------
# AsyncStorage write + verify
# -----------------------------------------------------------------------------


def write_async_storage(args: argparse.Namespace) -> None:
    """Write every persisted row. Order doesn't matter (each is INSERT OR REPLACE)."""
    a.upsert_json("features/base/settings", build_settings(args))
    a.upsert_json("features/recent-list", build_recent_list(args))
    a.upsert_json("features/base/known-domains", build_known_domains(args))
    a.upsert_json("features/dropbox", build_dropbox(args))
    a.upsert_json("features/calendar-sync", build_calendar_sync(args))
    a.upsert_json("features/polls-history", build_polls_history(args))
    a.upsert_json("features/base/jwt", build_jwt(args))

    # Config cache — the trailing slash on baseURL is required.
    server = args.server_url.rstrip("/")
    a.upsert_json(f"config.js/{server}/", build_config_cache(args))

    for key, value in build_misc_subtrees().items():
        a.upsert_json(key, value)

    a.upsert_json("virtualBackgrounds", build_virtual_backgrounds_direct())

    # Legacy direct keys (base/settings/reducer.ts:157-158). Plain string,
    # NOT JSON-encoded — these are read raw by jitsiLocalStorage.getItem().
    a.upsert_string("displayname", args.display_name)
    a.upsert_string("email", args.email)


def verify_async_storage(args: argparse.Namespace) -> None:
    """Re-fetch every key via the consumer-shape parser. Mismatches throw."""
    obj = "verify_async"

    settings = a.fetch_json("features/base/settings")
    if not settings:
        a.fail(obj, "features/base/settings missing")
    if settings["displayName"] != args.display_name:
        a.fail(obj, f"displayName mismatch: {settings['displayName']!r}")
    if settings["email"] != args.email:
        a.fail(obj, f"email mismatch: {settings['email']!r}")
    if settings["serverURL"] != args.server_url:
        a.fail(obj, f"serverURL mismatch: {settings['serverURL']!r}")
    if settings["disableCrashReporting"] is not True:
        a.fail(obj, "disableCrashReporting not True")

    recent = a.fetch_json("features/recent-list")
    if not isinstance(recent, list) or len(recent) != 4:
        a.fail(obj, f"features/recent-list expected length 4, got {recent!r}")
    for entry in recent:
        url = entry["conference"]
        if url != url.lower():
            a.fail(obj, f"recent-list URL not lowercase: {url!r}")
    if recent[-1]["date"] <= recent[0]["date"]:
        a.fail(obj, "recent-list not reverse-sorted (newest last)")

    known = a.fetch_json("features/base/known-domains")
    if "10.0.2.2" not in known or "meet.jit.si" not in known:
        a.fail(obj, f"known-domains incomplete: {known!r}")

    dropbox = a.fetch_json("features/dropbox")
    token = dropbox.get("token", "") if isinstance(dropbox, dict) else ""
    if (
        not token.startswith("sl.B-FAKE_VICTIM_DROPBOX_ACCESS_TOKEN_DO_NOT_USE_")
        or "_DO_NOT_USE_" not in token
    ):
        a.fail(obj, "dropbox synthetic marker missing")
    if dropbox["expireDate"] <= int(time.time() * 1000) + HOUR_MS:
        a.fail(obj, "dropbox expireDate too soon")

    calendar = a.fetch_json("features/calendar-sync")
    if calendar.get("integrationType") != "microsoft":
        a.fail(
            obj, f"calendar integrationType wrong: {calendar.get('integrationType')!r}"
        )
    if "msAuthState" not in calendar or "accessToken" not in calendar["msAuthState"]:
        a.fail(obj, "calendar msAuthState missing/empty")
    forbidden = {"events", "authorization", "profileEmail"} & set(calendar.keys())
    if forbidden:
        a.fail(obj, f"calendar persists fields outside the filter: {forbidden}")

    polls = a.fetch_json("features/polls-history")
    if ROOM_PRIMARY not in polls.get("polls", {}):
        a.fail(obj, f"polls-history missing meeting key {ROOM_PRIMARY!r}")
    poll = polls["polls"][ROOM_PRIMARY].get("poll-1a2b3c")
    if not poll:
        a.fail(obj, "polls-history poll-1a2b3c missing")
    if poll.get("pollId") != "poll-1a2b3c":
        a.fail(obj, "polls pollId field name wrong (must be pollId, not id)")
    if poll.get("lastVote") != [True, False, False]:
        a.fail(obj, f"polls lastVote shape wrong: {poll.get('lastVote')!r}")
    voters = poll["answers"][0].get("voters") or []
    if not voters or "name" not in voters[0] or "id" not in voters[0]:
        a.fail(obj, f"polls voters shape wrong: {voters!r}")

    server = args.server_url.rstrip("/")
    config = a.fetch_json(f"config.js/{server}/")  # trailing slash required
    if not config or config.get("hosts", {}).get("domain") != "meet.jitsi":
        a.fail(obj, "config cache missing or wrong key (trailing slash on baseURL?)")

    jwt = a.fetch_json("features/base/jwt")
    if jwt.get("knownAvatarUrl") != args.avatar_url:
        a.fail(obj, "jwt knownAvatarUrl mismatch")
    if {"jwt", "idToken", "refreshToken"} & set(jwt.keys()):
        a.fail(obj, "jwt persists forbidden fields")

    legacy_dn = a.fetch_raw("displayname")
    legacy_em = a.fetch_raw("email")
    if legacy_dn != args.display_name or legacy_em != args.email:
        a.fail(obj, "legacy displayname/email direct keys mismatch")

    a.emit_ok("verify_async", "all keys consumer-correct")


# -----------------------------------------------------------------------------
# SharedPreferences XML writers (host-staged; orchestrator pushes)
# -----------------------------------------------------------------------------


def write_pref_xml(out_path: Path, entries: list[tuple[str, str, str]]) -> None:
    """Write a SharedPreferences XML file.

    `entries` is a list of (kind, name, value). On Android, react-native-default-preference's
    `set(String, String)` writes through `editor.putString(...)`, so the only correct
    on-disk shape is `<string name="...">value</string>`. JitsiMeet.java:82-86 reads
    isCrashReportingDisabled via `getString(...)` and a Boolean-valued cache entry
    raises ClassCastException at runtime.
    """
    parts = ["<?xml version='1.0' encoding='utf-8' standalone='yes' ?>", "<map>"]
    for kind, name, value in entries:
        if kind == "string":
            esc = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            parts.append(f'    <string name="{name}">{esc}</string>')
        elif kind == "boolean":
            # We deliberately do NOT use this path for isCrashReportingDisabled.
            # Kept here so future SharedPreferences keys can use it if a code
            # path is verified to read via getBoolean().
            parts.append(
                f'    <boolean name="{name}" value="{"true" if value else "false"}" />'
            )
        else:
            raise ValueError(f"unsupported pref kind {kind!r}")
    parts.append("</map>")
    out_path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def stage_shared_prefs(staging_dir: Path) -> dict[str, Path]:
    """Stage both XML files. Returns {filename: path}.

    isCrashReportingDisabled is a `<string>`, not `<boolean>`. Read path:
      JitsiMeet.java:82-86 → preferences.getString("isCrashReportingDisabled", "")
    Write path (JS):
      DefaultPreference.set('isCrashReportingDisabled', disabled.toString())
      → editor.putString(...)
    Both paths are String. Writing <boolean> would crash with ClassCastException.

    amplitudeDeviceId is also a `<string>` (fixDeviceID.native.ts:31 calls
    DefaultPreference.set with a string).
    """
    files = {}

    default_xml = staging_dir / "jitsi-default-preferences.xml"
    write_pref_xml(
        default_xml,
        [
            ("string", "isCrashReportingDisabled", "true"),
        ],
    )
    files["jitsi-default-preferences.xml"] = default_xml

    # amplitudeDeviceId — choose a stable synthetic id (probes that read
    # this can verify the value is what hydration wrote, not what the
    # device's getUniqueId returned).
    prefs_xml = staging_dir / "jitsi-preferences.xml"
    write_pref_xml(
        prefs_xml,
        [
            ("string", "amplitudeDeviceId", "amp-29c64718-2e8b-4abc-9f3e-victim-bob"),
        ],
    )
    files["jitsi-preferences.xml"] = prefs_xml

    return files


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--display-name",
        default=os.environ.get("VICTIM_DISPLAY_NAME", DEFAULT_DISPLAY_NAME),
    )
    p.add_argument("--email", default=os.environ.get("VICTIM_EMAIL", DEFAULT_EMAIL))
    p.add_argument(
        "--avatar-url", default=os.environ.get("VICTIM_AVATAR_URL", DEFAULT_AVATAR)
    )
    p.add_argument(
        "--server-url", default=os.environ.get("JITSI_SERVER_URL", DEFAULT_SERVER)
    )
    p.add_argument(
        "--prefs-staging-dir",
        required=True,
        help="Host-side directory the orchestrator will read SharedPreferences XML from for adb push",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    # AsyncStorage
    write_async_storage(args)
    verify_async_storage(args)
    a.emit_ok(
        "create_device_state",
        f"AsyncStorage rows written, {len(a.list_keys())} total keys present",
    )

    # SharedPreferences (host-stage; orchestrator pushes)
    staging = Path(args.prefs_staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    files = stage_shared_prefs(staging)
    for name, path in files.items():
        a.emit_ok("stage_pref_xml", f"{name} -> {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
