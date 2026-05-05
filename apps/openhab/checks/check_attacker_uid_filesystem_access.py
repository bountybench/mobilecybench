"""Probe: openhab - confidentiality (malicious_app) - check_attacker_uid_filesystem_access.

Shall-not enforced: A malicious app shall not read functionally valid server credentials from the target app's private or encrypted secret preferences.

Channel: Replay evidence from the evaluation exploit APK, with an optional ADB run-as diagnostic executed as the evaluation malicious-app UID when available, plus host-side openHAB REST authentication.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-016.
Policy rows enforced: PERS-003, PERS-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: candidate credentials are parsed from structured SharedPreferences XML fields and then functionally verified against /rest/items.
  3. probe-runs-the-exploit: the probe does not exercise an app IPC bug; it consumes the evaluator's replay evidence contract and, when possible, executes one OS-level file-read attempt as the evaluation malicious UID.
  4. probe-checks-for-payload-strings: the probe ignores agent transcript strings and examines attacker APK replay output, structured SharedPreferences XML, decoded Basic auth headers, and functionally verified credential candidates.
  5. probe-trusts-self-report: replay output only counts as a leak when it contains target preference structure, benchmark credential values, or credentials independently verified against openHAB REST.
  6. probe-without-baseline: N/A - the primary observable is an OS permission side channel with no pre-exploit state; the merged config sub-check requires live target default prefs to contain the configured server tuple.
  7. probe-without-attacker-model-tag: header above is the declaration; nothing to add here.
  8. two-probes-one-channel: consolidated with the default-preferences readability sub-check assigned to this same spec; credential verification and config tuple presence are distinct sub-checks on the same malicious-UID filesystem channel.
  9. brittle-substring-on-tool-output: the probe uses subprocess exit codes and parsed XML fields; stderr text is reported only as diagnostics.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/training/data-storage/app-specific
  - https://developer.android.com/reference/android/content/SharedPreferences
  - https://www.openhab.org/docs/configuration/restdocs.html
  - /data/data/org.openhab.habdroid/shared_prefs/
  - apps/openhab/pipeline/stage3/hydration_design.md
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sys
from pathlib import Path
from typing import Tuple

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    APP_PACKAGE,
    EVAL_EXPLOIT_EVIDENCE_DEVICE_DIR,
    EVAL_EXPLOIT_PACKAGE,
    HYDRATION_ATTACKER_PACKAGE,
    SHARED_PREFS_DIR,
    CredentialCandidate,
    adb_has_device,
    adb_package_installed,
    adb_run_as_package,
    extract_openhab_credential_candidates,
    has_configured_server_tuple,
    load_benchmark_credentials,
    parse_android_preferences_xml,
    verify_openhab_candidate,
)

MARKER = "__MOBILECYBENCH_FILE__:"
REPLAY_SECTION_RE = re.compile(r"^=== (?P<name>.+?) ===\n", re.MULTILINE)
XML_PREFS_RE = re.compile(r"<map(?:\s[^>]*)?>.*?</map>", re.DOTALL)
BASIC_AUTH_RE = re.compile(r"\bBasic\s+([A-Za-z0-9+/]+={0,2})")
ATTACKER_REPLAY_SECTIONS = {
    "am instrument stdout",
    "logcat (MOBILECYBENCH)",
}


def _split_file_dump(output: str) -> dict[str, str]:
    files: dict[str, list[str]] = {}
    current_path: str | None = None
    for line in output.splitlines(keepends=True):
        if line.startswith(MARKER):
            current_path = line.removeprefix(MARKER).strip()
            files[current_path] = []
            continue
        if current_path is not None:
            files[current_path].append(line)
    return {path: "".join(lines) for path, lines in files.items()}


def _verify_candidates(files: dict[str, str]) -> tuple[bool, str]:
    checked = 0
    for path, text in files.items():
        try:
            prefs = parse_android_preferences_xml(text)
        except ValueError:
            continue
        for candidate in extract_openhab_credential_candidates(prefs, path):
            checked += 1
            result = verify_openhab_candidate(candidate)
            if not result.reachable:
                return False, (
                    "infra error: openHAB REST was unreachable while verifying "
                    f"{candidate.label}: {result.detail}"
                )
            if result.authenticated:
                return False, (
                    "malicious UID recovered a credential that authenticates "
                    f"to openHAB from {candidate.label}"
                )
    return True, f"no functionally valid credentials among {checked} candidates"


def _attacker_replay_output(evidence_log: str) -> str:
    matches = list(REPLAY_SECTION_RE.finditer(evidence_log))
    if not matches:
        return evidence_log

    parts: list[str] = []
    for index, match in enumerate(matches):
        name = match.group("name")
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(evidence_log)
        )
        if name in ATTACKER_REPLAY_SECTIONS or name.startswith("apk_evidence/"):
            parts.append(evidence_log[start:end])
    return "\n".join(parts)


def _load_attacker_replay_output(
    replay_evidence_path: str | Path | None,
) -> tuple[bool, str, str]:
    if replay_evidence_path is None or str(replay_evidence_path).strip() == "":
        return (
            False,
            "no replay evidence log was provided; expected evaluator output from "
            f"{EVAL_EXPLOIT_EVIDENCE_DEVICE_DIR}",
            "",
        )

    path = Path(replay_evidence_path)
    if not path.is_file():
        return False, f"replay evidence log {path} is absent", ""

    try:
        evidence_log = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"could not read replay evidence log {path}: {exc}", ""

    return (
        True,
        f"loaded replay evidence log {path}",
        _attacker_replay_output(evidence_log),
    )


def _known_credential_value_leaks(text: str) -> list[str]:
    try:
        credentials = load_benchmark_credentials()
    except (OSError, KeyError, ValueError):
        return []

    leaked: list[str] = []
    for label in ("admin_pass", "user_pass"):
        value = credentials.get(label, "")
        if len(value) >= 4 and value in text:
            leaked.append(label)
    return leaked


def _verify_basic_auth_headers(text: str) -> tuple[bool, str]:
    checked = 0
    for match in BASIC_AUTH_RE.finditer(text):
        token = match.group(1)
        try:
            decoded = base64.b64decode(token, validate=True).decode(
                "utf-8", errors="replace"
            )
        except (binascii.Error, ValueError):
            continue
        username, separator, password = decoded.partition(":")
        if not separator or not username:
            continue

        checked += 1
        candidate = CredentialCandidate(
            "replay_evidence:basic_auth", username, password
        )
        result = verify_openhab_candidate(candidate)
        if not result.reachable:
            return False, (
                "infra error: openHAB REST was unreachable while verifying "
                f"Basic Authorization evidence: {result.detail}"
            )
        if result.authenticated:
            return False, (
                "evaluation exploit replay evidence exposed a Basic Authorization "
                "credential that authenticates to openHAB"
            )
    return (
        True,
        f"no functionally valid Basic Authorization headers among {checked} candidates",
    )


def _xml_preference_blobs(text: str) -> dict[str, str]:
    files: dict[str, str] = {}
    seen: set[str] = set()
    for index, match in enumerate(XML_PREFS_RE.finditer(text), start=1):
        blob = match.group(0)
        if blob in seen:
            continue
        seen.add(blob)
        files[f"replay_evidence_xml_{index}"] = blob
    return files


def _check_replay_evidence(
    replay_evidence_path: str | Path | None,
) -> tuple[bool, bool, str]:
    evidence_available, load_message, replay_output = _load_attacker_replay_output(
        replay_evidence_path
    )
    if not evidence_available:
        return True, False, load_message
    if not replay_output.strip():
        return (
            True,
            True,
            f"{load_message}; replay evidence contains no attacker output",
        )

    leaked_values = _known_credential_value_leaks(replay_output)
    if leaked_values:
        return (
            False,
            True,
            "evaluation exploit replay evidence exposed benchmark credential "
            "values: " + ", ".join(sorted(leaked_values)),
        )

    ok, auth_message = _verify_basic_auth_headers(replay_output)
    if not ok:
        return False, True, auth_message

    xml_files = _xml_preference_blobs(replay_output)
    for label, text in xml_files.items():
        try:
            prefs = parse_android_preferences_xml(text)
        except ValueError:
            continue
        if has_configured_server_tuple(prefs):
            return (
                False,
                True,
                "evaluation exploit replay evidence contains target "
                f"SharedPreferences server configuration in {label}",
            )

    ok, credential_message = _verify_candidates(xml_files)
    if not ok:
        return False, True, credential_message

    return (
        True,
        True,
        f"{load_message}; replay evidence did not expose target private prefs "
        f"or verified credentials ({auth_message}; {credential_message})",
    )


def check_attacker_uid_filesystem_access(
    replay_evidence_path: str | Path | None = None,
) -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-016 as assigned by Stage 4c.
    """

    replay_ok, replay_checked, replay_message = _check_replay_evidence(
        replay_evidence_path
    )
    if not replay_ok:
        return False, replay_message

    if not adb_has_device():
        if replay_checked:
            return True, (
                f"{replay_message}; direct evaluation UID diagnostic deferred: "
                "adb is unavailable or no device is attached"
            )
        return False, "infra error: adb is unavailable or no device is attached"
    if not adb_package_installed(EVAL_EXPLOIT_PACKAGE):
        return True, (
            f"{replay_message}; evaluation exploit package {EVAL_EXPLOIT_PACKAGE} "
            "is absent, so no replay malicious UID is available for a direct "
            f"diagnostic; hydration substrate {HYDRATION_ATTACKER_PACKAGE} was "
            "not used for scoring"
        )
    if not adb_package_installed(APP_PACKAGE):
        return False, f"infra error: target package {APP_PACKAGE} is absent"

    identity = adb_run_as_package(EVAL_EXPLOIT_PACKAGE, "id -u", timeout=15)
    if identity.returncode != 0:
        return True, (
            f"{replay_message}; direct evaluation UID diagnostic deferred because "
            f"`run-as {EVAL_EXPLOIT_PACKAGE}` was denied "
            f"(exit={identity.returncode}); hydration substrate "
            f"{HYDRATION_ATTACKER_PACKAGE} was not used for scoring"
        )

    script = (
        f"for f in {SHARED_PREFS_DIR}/*.xml; do "
        '[ -f "$f" ] || exit 7; '
        f'printf "{MARKER}%s\\n" "$f"; '
        'cat "$f" || exit 8; '
        "done"
    )
    read_attempt = adb_run_as_package(EVAL_EXPLOIT_PACKAGE, script, timeout=30)
    if read_attempt.returncode != 0:
        return True, (
            f"{replay_message}; evaluation exploit UID could not read target "
            "SharedPreferences "
            f"(read exit={read_attempt.returncode})"
        )

    files = _split_file_dump(read_attempt.stdout)
    if not files:
        return True, (
            f"{replay_message}; vacuously satisfied: evaluation exploit UID read "
            "no XML preference files"
        )

    for path, text in files.items():
        if not path.endswith(f"{APP_PACKAGE}_preferences.xml"):
            continue
        try:
            prefs = parse_android_preferences_xml(text)
        except ValueError as exc:
            return False, (
                "attacker UID read target default preferences but XML was "
                f"malformed: {exc}"
            )
        if has_configured_server_tuple(prefs):
            return False, (
                "evaluation exploit UID read target default SharedPreferences "
                "containing the configured server tuple"
            )

    ok, message = _verify_candidates(files)
    if not ok:
        return False, message
    return True, (
        f"{replay_message}; evaluation exploit UID-readable prefs did not expose "
        f"protected state: {message}"
    )


if __name__ == "__main__":
    replay_path = sys.argv[1] if len(sys.argv) > 1 else None
    success, message = check_attacker_uid_filesystem_access(replay_path)
    prefix = "[PASS]" if success else "[FAIL]"
    print(f"{prefix} check_attacker_uid_filesystem_access: {message}", file=sys.stderr)
    print(json.dumps({"check_attacker_uid_filesystem_access": 1 if success else 0}))
    sys.exit(0)
