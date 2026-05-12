"""Probe: Home Assistant Android - availability (remote_attacker) - check_companion_process_alive.

Shall-not enforced: A remote attacker shall not crash or hang the companion app process.

Channel: ADB shell `pidof <package>`.
Attacker model: remote_attacker.
Category: availability.

Spec id: S-049.
Policy rows enforced: NET-008.

Anti-pattern declarations:
  1. grep-for-vulnerable-code: probe never inspects source.
  2. regex-match-without-verification: assertion is "pidof returned a numeric
     PID," not a regex over noisy text.
  3. probe-runs-the-exploit: probe does not crash the process.
  4. probe-checks-for-payload-strings: not applicable.
  5. probe-trusts-self-report: pidof is a kernel-side query, not the app's
     own self-report.
  6. probe-without-baseline: process must be alive after the exploit window;
     baseline is "process exists at all" — independent of any captured state.
  7. probe-without-attacker-model-tag: see header.
  8. two-probes-one-channel: only ADB pidof is used here; container liveness
     is checked elsewhere.
  9. brittle-substring-on-tool-output: relies on `pidof` exit code, not output
     parsing.

Citations:
  - Android `pidof` is documented at developer.android.com/tools/adb.
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

from probe_lib import (  # noqa: E402  # noqa: E402
    PACKAGE_NAME,
    adb_shell,
    emit_check_result,
)


def check_companion_process_alive() -> Tuple[bool, str]:
    """Return (success, message). Companion app process is alive on the device."""
    result = adb_shell(["pidof", PACKAGE_NAME])
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or result.stdout.strip() or "no PID returned"
        return False, f"companion process is not alive: {detail}"
    return True, f"companion process pid={result.stdout.strip()}"


if __name__ == "__main__":
    success, message = check_companion_process_alive()
    result = emit_check_result(check_companion_process_alive.__name__, success, message)
    print(json.dumps(result))
    sys.exit(0)
