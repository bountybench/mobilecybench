#!/usr/bin/env python3
"""SimpleLogin Android — on-device shared_prefs hydration overlay.

Writes <string name="API_KEY">…</string> and <string name="API_URL">…</string>
into /data/data/io.simplelogin.android.fdroid/shared_prefs/io.simplelogin.android.xml,
preserving the two <boolean> defaults BaseAppCompatActivity writes on
first launch. Verifies by re-reading the XML and simulating the
SharedPreferencesImpl reader API (getString only succeeds against
<string> elements — wrong-tag values raise loud per the prompt's
documented Jitsi-style bug).

APK is non-debuggable (verified by apkanalyzer manifest debuggable →
false), so run-as is unavailable. All file ops go through
`adb shell su 0 sh` with the script body delivered via stdin (NOT via
`sh -c "<script>"`, which silently produces empty output on macOS
adb 1.0.41 the moment any shell metacharacter is present).

XML payload is base64-encoded at the host before the shell hand-off so
no XML metacharacter ever has to be quoted across the device shell
boundary.

Sensitive fields (auth_policy.md §3.1): the api_key is NEVER echoed
verbatim. Logs and the manifest use sha256_prefix(value)[:12] only.

Stage 3 draft; Stage 4d will move this verbatim under apps/simplelogin/.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

PACKAGE_DEFAULT = "io.simplelogin.android.fdroid"
PREFS_FILE_NAME = "io.simplelogin.android.xml"
LAUNCHER_ACTIVITY = "io.simplelogin.android.fdroid/io.simplelogin.android.module.startup.StartupActivity"
API_URL_DEFAULT = "https://10.0.2.2:7777"


def log(msg: str) -> None:
    print(f"[hydrate] {msg}", file=sys.stderr)


def sha256_prefix(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app-dir", default=str(Path(__file__).resolve().parent))
    p.add_argument(
        "--package", default=os.environ.get("MCB_PACKAGE_NAME", PACKAGE_DEFAULT)
    )
    p.add_argument(
        "--api-url",
        default=os.environ.get("MCB_API_URL_ON_DEVICE", API_URL_DEFAULT),
        help="API URL the on-device app will persist (default: https://10.0.2.2:7777)",
    )
    p.add_argument(
        "--api-key",
        default=None,
        help="API key value; default: read from <app-dir>/secrets.json::user_b_auth_token",
    )
    p.add_argument(
        "--manifest",
        default=None,
        help="Path to write redacted hydration manifest JSON",
    )
    p.add_argument("--timeout", type=int, default=30)
    return p.parse_args()


# ─── adb plumbing ─────────────────────────────────────────────────────


def adb(
    args: list[str], *, input_text: str | None = None, timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", *args],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def adb_root_shell(
    script: str, *, timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    """Run `script` under `su 0 sh` via stdin (heredoc-equivalent).

    NEVER use `adb shell su 0 sh -c "<script>"` — empty-output bug on
    macOS adb 1.0.41 with metacharacters.
    """
    return adb(["shell", "su", "0", "sh"], input_text=script, timeout=timeout)


def adb_get_state() -> str:
    res = adb(["get-state"], timeout=10)
    return (res.stdout or res.stderr or "").strip()


def ensure_single_device(deadline_s: int = 60) -> None:
    """Wait up to deadline_s for adb to show exactly one ready device.

    The host adb daemon (macOS 14, adb 1.0.41) can transiently report
    `offline` even when the emulator is booted — typically right after
    a docker-compose burst, an APK install, or a sibling adb invocation.
    We poll until the state stabilizes on `device`.
    """
    deadline = time.time() + deadline_s
    last = ""
    while time.time() < deadline:
        state = adb_get_state()
        if state.startswith("device"):
            return
        last = state
        time.sleep(2)
    res = adb(["devices"], timeout=10)
    raise RuntimeError(
        f"adb not ready after {deadline_s}s: state={last!r} devices=\n"
        f"{(res.stdout or res.stderr).strip()}"
    )


def pm_package_installed(package: str, deadline_s: int = 30) -> bool:
    """Poll `pm path` until it succeeds or the deadline elapses.

    The macOS adb daemon can transiently report `device offline` (or
    `pm` can refuse with `Can't find service: package`) right after the
    emulator boots / re-attaches. We retry until either the package
    surfaces or we hit the deadline.
    """
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        res = adb(["shell", "pm", "path", package], timeout=10)
        out = res.stdout or ""
        if res.returncode == 0 and "package:" in out:
            return True
        # Adb churn signals — keep polling.
        if "offline" in (res.stderr or "") or "no devices" in (res.stderr or ""):
            time.sleep(2)
            continue
        if "Can't find service" in out or "Can't find service" in (res.stderr or ""):
            time.sleep(2)
            continue
        # pm responded cleanly with no rows → package genuinely absent
        # but maybe transient between install and indexing; brief retry.
        time.sleep(1)
    return False


def file_exists(path: str) -> bool:
    # `test -f` returns 0/1, plain command no metacharacters → safe argv form.
    res = adb(["shell", "su", "0", "test", "-f", path], timeout=10)
    return res.returncode == 0


def cat_file(path: str) -> str:
    # `cat` is a single argv command, no metachars.
    res = adb(["shell", "su", "0", "cat", path], timeout=15)
    if res.returncode != 0:
        raise RuntimeError(
            f"failed to read {path}: rc={res.returncode} stderr={(res.stderr or '').strip()[:200]}"
        )
    # adb returns \r\n line endings; normalise.
    return (res.stdout or "").replace("\r\n", "\n")


def force_stop(package: str) -> None:
    adb(["shell", "am", "force-stop", package], timeout=10)


def launch_app(package: str) -> None:
    # `monkey` is what start_runtime.sh::smoke_test uses; matches that
    # path for parity.
    adb(
        [
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
        timeout=15,
    )


def pidof(package: str) -> str:
    res = adb(["shell", "pidof", package], timeout=10)
    return (res.stdout or "").strip().replace("\r", "")


# ─── XML merge (preserving the two <boolean> defaults) ─────────────────


def build_merged_xml(existing_xml: str, api_key: str, api_url: str) -> bytes:
    """Insert/update <string> children for API_KEY and API_URL.

    Preserves all other children (the two <boolean> elements
    BaseAppCompatActivity writes on first launch).
    """
    root = ET.fromstring(existing_xml)
    if root.tag != "map":
        raise RuntimeError(
            f"unexpected SharedPreferences root: {root.tag!r} (expected 'map')"
        )

    def upsert_string(name: str, value: str) -> None:
        for child in list(root):
            if child.get("name") == name:
                # If the existing element is the WRONG tag for a getString
                # consumer, we DELETE it and re-add as <string>. This is
                # the type-contract enforcement — leaving a <boolean>
                # named API_KEY in place would raise ClassCastException on
                # the next consumer read.
                if child.tag != "string":
                    log(
                        f"WARN: removing wrong-tag element <{child.tag} name={name}> "
                        f"(getString requires <string>)"
                    )
                root.remove(child)
        elem = ET.SubElement(root, "string")
        elem.set("name", name)
        elem.text = value

    upsert_string("API_KEY", api_key)
    upsert_string("API_URL", api_url)

    # Serialise with the same header Android writes.
    body = ET.tostring(root, encoding="unicode")
    # Android writes: <?xml version='1.0' encoding='utf-8' standalone='yes' ?>
    out = "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n" + body + "\n"
    return out.encode("utf-8")


def ensure_prefs_file(package: str, prefs_path: str, deadline_s: int = 20) -> None:
    """If the prefs file does not exist (post pm-clear or post-uninstall+install),
    launch the app once so BaseAppCompatActivity writes its defaults.

    We then force-stop before the caller proceeds to write.
    """
    if file_exists(prefs_path):
        return
    log(f"prefs file absent; launching app to materialize: {prefs_path}")
    launch_app(package)
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        if file_exists(prefs_path):
            log("prefs file appeared")
            time.sleep(0.5)  # let the implCommit fsync settle
            force_stop(package)
            return
        time.sleep(1)
    raise RuntimeError(
        f"prefs file did not appear within {deadline_s}s after launch: {prefs_path}"
    )


def write_preferences(package: str, api_key: str, api_url: str) -> None:
    appdir = f"/data/data/{package}"
    prefs_dir = f"{appdir}/shared_prefs"
    prefs_path = f"{prefs_dir}/{PREFS_FILE_NAME}"

    if not pm_package_installed(package):
        raise RuntimeError(f"package not installed: {package}")

    # 1) Make sure the file exists so we have the <boolean> defaults to preserve.
    ensure_prefs_file(package, prefs_path)

    # 2) Stop the app so SharedPreferencesImpl can't race us.
    force_stop(package)

    existing = cat_file(prefs_path)
    merged = build_merged_xml(existing, api_key=api_key, api_url=api_url)

    payload_b64 = base64.b64encode(merged).decode("ascii")
    # Single base64 token is shell-meta-free; safe to inline in heredoc.
    # The script writes a tmp file, mv's into place, chowns, restorecons.
    # Owner uid/gid derived from stat of /data/data/<pkg> so we don't
    # hardcode the per-install uid (it varies by emulator image).
    script = f"""set -e
TMP=/data/local/tmp/{PREFS_FILE_NAME}.staging
PREFS={prefs_path}
APPDIR={appdir}
PREFS_DIR={prefs_dir}
mkdir -p $PREFS_DIR
echo {payload_b64} | base64 -d > $TMP
mv $TMP $PREFS
APP_UID=$(stat -c %u $APPDIR)
APP_GID=$(stat -c %g $APPDIR)
chown $APP_UID:$APP_GID $PREFS
chmod 660 $PREFS
restorecon $PREFS 2>/dev/null || true
sync
"""
    res = adb_root_shell(script, timeout=20)
    if res.returncode != 0:
        raise RuntimeError(
            f"shared_prefs write failed: rc={res.returncode} "
            f"stderr={(res.stderr or '').strip()[:300]}"
        )
    log(
        "shared_prefs hydrated "
        f"(api_url={api_url}, api_key_sha256_prefix={sha256_prefix(api_key)})"
    )


# ─── Reader-API simulator (the bug class the prompt calls out) ─────────


def verify_preferences(
    package: str, expected_api_key: str, expected_api_url: str
) -> dict[str, Any]:
    """Re-read the XML and simulate getString.

    SharedPreferencesImpl: only <string name=key>…</string> satisfies
    getString(key, default). <boolean>/<int>/<long>/<set> for the same
    name raises ClassCastException at the cast.

    Same simulation logic for the two booleans we are NOT supposed to
    have touched — they MUST still be <boolean> on disk.
    """
    prefs_path = f"/data/data/{package}/shared_prefs/{PREFS_FILE_NAME}"
    xml_text = cat_file(prefs_path)
    root = ET.fromstring(xml_text)

    def find_for_getString(name: str) -> str | None:
        hits = [c for c in root if c.get("name") == name]
        if not hits:
            return None
        if len(hits) != 1:
            raise RuntimeError(
                f"shared_prefs has {len(hits)} elements named {name!r} — "
                "Android's last-wins implCommit should produce exactly 1"
            )
        elem = hits[0]
        if elem.tag != "string":
            # This is the bug class. Fail loud with the field name and
            # the wrong tag — but DON'T leak the value.
            raise RuntimeError(
                f"reader-API contract violated for {name!r}: getString requires "
                f"<string>, found <{elem.tag}>; ClassCastException would crash app"
            )
        return elem.text or ""

    def find_for_getBoolean(name: str) -> bool | None:
        hits = [c for c in root if c.get("name") == name]
        if not hits:
            return None
        if len(hits) != 1:
            raise RuntimeError(f"shared_prefs has {len(hits)} elements named {name!r}")
        elem = hits[0]
        if elem.tag != "boolean":
            raise RuntimeError(
                f"reader-API contract violated for {name!r}: getBoolean requires "
                f"<boolean>, found <{elem.tag}>"
            )
        return elem.get("value") == "true"

    got_api_key = find_for_getString("API_KEY")
    got_api_url = find_for_getString("API_URL")
    got_dark = find_for_getBoolean("FORCE_DARK_MODE")
    got_local_auth = find_for_getBoolean("SHOULD_LOCALLY_AUTHENTICATE")

    if got_api_key != expected_api_key:
        # Report only the sha256 prefix of what we found.
        observed_prefix = sha256_prefix(got_api_key or "")
        raise RuntimeError(
            f"API_KEY mismatch: expected sha256_prefix={sha256_prefix(expected_api_key)} "
            f"observed sha256_prefix={observed_prefix}"
        )
    if got_api_url != expected_api_url:
        raise RuntimeError(
            f"API_URL mismatch: expected={expected_api_url!r} observed={got_api_url!r}"
        )

    return {
        "api_key_present": True,
        "api_key_sha256_prefix": sha256_prefix(expected_api_key),
        "api_url": got_api_url,
        "force_dark_mode_preserved": got_dark is not None,
        "should_locally_authenticate_preserved": got_local_auth is not None,
    }


def relaunch_and_wait(package: str, deadline_s: int = 90) -> str:
    launch_app(package)
    deadline = time.time() + deadline_s
    pid = ""
    while time.time() < deadline:
        pid = pidof(package)
        if pid:
            # 5-second stability check: pid must persist (the StartupActivity →
            # LoginActivity bounce would still have a pid, but if there's an
            # actual crash on first read of API_KEY the process dies fast).
            time.sleep(5)
            pid_after = pidof(package)
            if pid_after == pid:
                log(f"app relaunched stably (pid={pid})")
                return pid
            log(f"pid flipped: {pid} → {pid_after}; retrying")
            pid = ""
        time.sleep(1)
    raise RuntimeError(f"app did not start stably within {deadline_s}s: {package}")


# ─── main ──────────────────────────────────────────────────────────────


def main() -> int:
    args = parse_args()
    try:
        app_dir = Path(args.app_dir).resolve()
        api_key = args.api_key
        if api_key is None:
            secrets_path = app_dir / "secrets.json"
            if not secrets_path.exists():
                raise RuntimeError(f"secrets file missing: {secrets_path}")
            data = json.loads(secrets_path.read_text(encoding="utf-8"))
            api_key = data.get("user_b_auth_token")
            if not isinstance(api_key, str) or not api_key.startswith("sl_"):
                raise RuntimeError(
                    "secrets.json missing or malformed user_b_auth_token; "
                    "run apps/simplelogin/start_runtime.sh first"
                )

        ensure_single_device()
        write_preferences(args.package, api_key=api_key, api_url=args.api_url)
        verify_summary = verify_preferences(
            args.package, expected_api_key=api_key, expected_api_url=args.api_url
        )
        pid = relaunch_and_wait(args.package, deadline_s=args.timeout)

        summary = {
            "package": args.package,
            "api_url": args.api_url,
            "api_key_sha256_prefix": sha256_prefix(api_key),
            "api_key_value_redacted": True,
            "verify": verify_summary,
            "app_pid_after_relaunch": pid,
            "caveats": [
                "allowBackup=true and no dataExtractionRules — the API key we "
                "wrote into shared_prefs is eligible for Auto Backup. "
                "Documented per Stage 2 auth_policy row #46; hydration does "
                "not defend against this per Stage 3 scope.",
            ],
        }
        if args.manifest:
            mpath = Path(args.manifest).resolve()
            mpath.parent.mkdir(parents=True, exist_ok=True)
            mpath.write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        print(json.dumps({"status": "hydrated", "summary": summary}))
        return 0
    except Exception as exc:  # noqa: BLE001
        # Defensive redaction: scrub any sl_... substring from the message.
        msg = str(exc)
        # If api_key happens to be in scope, replace it with its prefix.
        try:
            ak = api_key  # type: ignore[name-defined]
            if isinstance(ak, str) and ak in msg:
                msg = msg.replace(ak, f"<api_key:{sha256_prefix(ak)}>")
        except Exception:
            pass
        print(json.dumps({"status": "hydration_failed", "error": msg[:400]}))
        log(f"ERROR: {msg}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
