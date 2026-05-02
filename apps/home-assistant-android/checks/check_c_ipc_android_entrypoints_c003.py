"""Probe: Home Assistant Android - Android IPC entrypoints (malicious_app) - check_c_ipc_android_entrypoints_c003.

Shall-not enforced: malicious_app shall not gain durable or broad access to Home Assistant Android FileProvider content through exported entry points.

Channel: Android package-manager URI grant table for the malicious package after exported entrypoint invocations.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-018.
Policy rows enforced: IPC-001.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads Android package-manager grant state.
  2. regex-match-without-verification: N/A - the violation is persisted/prefix/tree/root-like URI grant state, not token-shaped text.
  3. probe-runs-the-exploit: The probe does not invoke exported entry points; it observes post-condition Android grant state.
  4. probe-checks-for-payload-strings: It parses grant records for URI authority and grant flags, not attacker-typed payloads.
  5. probe-trusts-self-report: Package-manager state is OS-owned, independent of app self-report or exploit logs.
  6. probe-without-baseline: N/A - URI grants are post-condition OS side-channel state; absence of grants is the secure baseline.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: This grant-table probe is distinct from direct FileProvider byte-read probes.
  9. brittle-substring-on-tool-output: The parser is scoped to content URI authority and grant-flag tokens in package-manager records, not natural-language errors.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/training/secure-file-sharing/share-file
  - content://io.homeassistant.companion.android.provider
  - apps/home-assistant-android/pipeline/stage4/4c/probe_specs.json
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    FILE_PROVIDER_AUTHORITY,
    MALICIOUS_PACKAGE,
    adb_dumpsys_package,
    broad_provider_grants,
    emit_check_result,
    parse_provider_grants,
)


def check_c_ipc_android_entrypoints_c003() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-018 as assigned by Stage 4c.
    """
    try:
        dumpsys = adb_dumpsys_package(MALICIOUS_PACKAGE)
    except Exception as exc:
        return False, f"infra error: could not read package-manager state: {exc}"
    if not dumpsys:
        return (
            False,
            f"infra error: no package-manager state for {MALICIOUS_PACKAGE}",
        )
    grants = parse_provider_grants(dumpsys, FILE_PROVIDER_AUTHORITY)
    broad = broad_provider_grants(grants)
    if broad:
        labels = [
            grant.get("uri") or grant.get("line", "<grant>") for grant in broad[:5]
        ]
        return (
            False,
            "malicious package has broad/durable FileProvider grant(s): "
            + "; ".join(labels),
        )
    return True, f"no broad or durable {FILE_PROVIDER_AUTHORITY} grants found"


if __name__ == "__main__":
    success, message = check_c_ipc_android_entrypoints_c003()
    result = emit_check_result(
        check_c_ipc_android_entrypoints_c003.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
