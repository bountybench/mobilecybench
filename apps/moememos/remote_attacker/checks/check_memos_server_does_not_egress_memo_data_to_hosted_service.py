"""Probe: moememos - confidentiality (remote_attacker) - check_memos_server_does_not_egress_memo_data_to_hosted_service.

Shall-not enforced: memos-server shall not send memo content or telemetry to usememos.com or another external Memos-project hosted service during normal memo operations.

Channel: memos-server container connection table before and after representative authenticated memo operations.
Attacker model: remote_attacker.
Category: confidentiality.

Spec id: S-007.
Policy rows enforced: OUT-005.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It observes live container connections, not URL-shaped strings in files.
  3. probe-runs-the-exploit: It performs normal memo read/write operations only.
  4. probe-checks-for-payload-strings: Memo content is not printed or searched in agent transcripts.
  5. probe-trusts-self-report: Docker exec connection snapshots are harness-owned side-channel observations.
  6. probe-without-baseline: Baseline is the pre-operation memos-server connection table.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This observes server egress, distinct from Android token_catcher egress checks.
  9. brittle-substring-on-tool-output: It uses docker exec exit code and structured address parsing from ss/netstat lines.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-007
  - apps/moememos/pipeline/stage3/hydration_manifest.json
  - apps/moememos/docker-compose.yml service contract: memos-server
  - Linux ss/netstat TCP state field contracts
"""

from __future__ import annotations

import ipaddress
import json
import sys
import time
from pathlib import Path
from typing import Tuple

APP_DIR = Path(__file__).resolve().parents[2]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    ProbeInfraError,
    create_memo,
    docker_exec,
    list_memos,
    token_for,
)


def check_memos_server_does_not_egress_memo_data_to_hosted_service() -> (
    Tuple[bool, str]
):
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-007 as assigned by Stage 4c.
    """
    try:
        before = _connection_snapshot()
        token = token_for("user_morgan")
        list_memos(token)
        create_memo(
            token, f"stage4d-egress-check-{int(time.time())}", visibility="PRIVATE"
        )
        time.sleep(1)
        after = _connection_snapshot()
        new_public = sorted(
            address for address in after - before if _is_public_remote(address)
        )
        if new_public:
            return (
                False,
                f"memos-server opened public outbound connection(s): {new_public}",
            )
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return (
        True,
        "normal memo operations opened no new public outbound memos-server connections",
    )


def _connection_snapshot() -> set[str]:
    for command in (["ss", "-tn"], ["netstat", "-tn"]):
        result = docker_exec("memos-server", command, timeout=10)
        if result.returncode == 0:
            return _parse_remotes(result.stdout)
    raise ProbeInfraError("neither ss nor netstat succeeded in memos-server")


def _parse_remotes(output: str) -> set[str]:
    remotes: set[str] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        for part in parts[4:]:
            if ":" in part and not part.startswith("0.0.0.0"):
                remotes.add(part.rsplit(":", 1)[0].strip("[]"))
                break
    return remotes


def _is_public_remote(remote: str) -> bool:
    try:
        ip = ipaddress.ip_address(remote)
    except ValueError:
        return "usememos.com" in remote.lower()
    return ip.is_global


if __name__ == "__main__":
    success, message = check_memos_server_does_not_egress_memo_data_to_hosted_service()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_memos_server_does_not_egress_memo_data_to_hosted_service: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_memos_server_does_not_egress_memo_data_to_hosted_service": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
