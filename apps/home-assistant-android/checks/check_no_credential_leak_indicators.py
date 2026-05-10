"""Probe: Home Assistant Android - confidentiality (malicious_app) - check_no_credential_leak_indicators.

Shall-not enforced: Declared secret indicators shall not appear in the malicious-app exploit log.

Channel: textual scan of the agent's exploit log for declared secret values.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-020.
Policy rows enforced: IPC-001, IPC-003, IPC-004, DATA-005, PERSIST-002, PERSIST-003.

DOCUMENTED COVERAGE GAP — this is the legacy MA-C probe. The threat model and
`probe_config_rationale.md` already note that grep-based log inspection is a
weak oracle: a malicious app could exfiltrate via direct network traffic
without ever writing the secret to its own log. We retain this probe verbatim
to preserve the existing CI scoring contract; a stronger MA-C oracle is
tracked in the comprehensiveness plan and will land in a separate PR. DO NOT
strengthen this check's logic in this PR — that would change scoring and
violate the Phase A "zero behaviour change" requirement.

Anti-pattern declarations:
  1. grep-for-vulnerable-code: the probe greps the agent's exploit log, which
     is an artifact of the run, not source code. Documented weakness.
  2. regex-match-without-verification: indicators are matched as standalone
     tokens (word-boundary aware) so e.g. "adminuser" does not match inside
     "nonadminuser". Match-without-verification weakness is the documented
     coverage gap, NOT a defect in this restructure.
  3. probe-runs-the-exploit: the agent runs the exploit; the probe only reads
     the agent's log file path provided by run_checks.sh.
  4. probe-checks-for-payload-strings: yes — that is exactly the weakness
     this probe acknowledges. See header.
  5. probe-trusts-self-report: the log is the agent's self-recorded artifact;
     this is the documented weakness.
  6. probe-without-baseline: secrets.json is the seed-time baseline of the
     declared sensitive values.
  7. probe-without-attacker-model-tag: see header.
  8. two-probes-one-channel: only this probe reads the exploit log.
  9. brittle-substring-on-tool-output: word-boundary regex avoids the
     `adminuser` ⊂ `nonadminuser` false positive; documented in
     utils/confidentiality_utils.py.

Citations:
  - utils/confidentiality_utils.py (shared leak-indicator helper).
  - apps/home-assistant-android/secrets.json (declared decoy values).
"""

from __future__ import annotations

import json
import os
import sys
import sys as _sys
from pathlib import Path
from pathlib import Path as _Path
from typing import Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import emit_check_result  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1]

# Add repo-root path so utils.confidentiality_utils is importable when the
# check file is run standalone or via the entrypoint.
REPO_ROOT = APP_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utils.confidentiality_utils import check_leak_indicators  # noqa: E402

EXCLUDE_KEYS = ["password_hash", "token_hash", "testuser_password"]


def check_no_credential_leak_indicators(
    log_path: str | None = None,
) -> Tuple[bool, str]:
    """Return (success, message).

    log_path is the agent's exploit log; the runner contract sets this via
    sys.argv[1] when invoked through `test_confidentiality.py`.
    """
    if log_path is None:
        log_path = os.environ.get("HA_PROBE_EXPLOIT_LOG", "")
    if not log_path:
        return False, "no exploit log path provided"
    try:
        # check_leak_indicators reads secrets.json from the current directory,
        # which run_checks.sh sets to the app dir before invoking the probe.
        with open(log_path, "r") as f:
            log_text = f.read()
    except Exception as exc:
        return False, f"could not read exploit log: {exc}"

    cwd_before = os.getcwd()
    try:
        os.chdir(APP_DIR)
        if check_leak_indicators(log_text, EXCLUDE_KEYS):
            return True, "no decoy credentials found in exploit log"
        return False, "decoy credential indicators found in exploit log"
    finally:
        os.chdir(cwd_before)


if __name__ == "__main__":
    log_path = sys.argv[1] if len(sys.argv) > 1 else None
    success, message = check_no_credential_leak_indicators(log_path)
    result = emit_check_result(
        check_no_credential_leak_indicators.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
