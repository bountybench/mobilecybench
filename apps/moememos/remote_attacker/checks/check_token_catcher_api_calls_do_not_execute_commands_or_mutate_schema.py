"""Probe: moememos - integrity (remote_attacker) - check_token_catcher_api_calls_do_not_execute_commands_or_mutate_schema.

Shall-not enforced: token_catcher acting as an ordinary network peer shall not execute commands or mutate Memos schema through normal v0/v1 API calls.

Channel: memos-server process, file, and optional schema snapshots around normal authenticated API reads.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-018.
Policy rows enforced: CEX-005.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It observes side-effect snapshots after successful normal API JSON reads.
  3. probe-runs-the-exploit: It calls only documented GET endpoints with a USER token.
  4. probe-checks-for-payload-strings: No command payload is sent or matched.
  5. probe-trusts-self-report: Docker process/file/schema snapshots are harness side channels.
  6. probe-without-baseline: Baseline is pre-call ps, file list, and schema snapshot when sqlite3 is available.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This checks normal API side effects; upload side effects are S-016.
  9. brittle-substring-on-tool-output: It checks command exit codes and parsed snapshot deltas.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-018
  - apps/moememos/pipeline/stage3/tokens.json
  - apps/moememos/docker-compose.yml service contract: memos-server
  - Memos REST API path contract: /api/v1/memos and /api/v1/auth/sessions/current
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple

APP_DIR = Path(__file__).resolve().parents[2]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    ProbeInfraError,
    changed_files,
    file_snapshot,
    list_memos,
    request,
    schema_snapshot,
    token_for,
    unexpected_executable_like_files,
)

from checks.check_resource_upload_does_not_create_server_execution_side_effects import (  # noqa: E402
    _process_commands,
)


def check_token_catcher_api_calls_do_not_execute_commands_or_mutate_schema() -> (
    Tuple[bool, str]
):
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-018 as assigned by Stage 4c.
    """
    try:
        token = token_for("user_riley")
        processes_before = _process_commands()
        files_before = file_snapshot()
        schema_before = schema_snapshot()
        list_memos(token)
        current = request("GET", "/api/v1/auth/sessions/current", token=token)
        if current.status != 200:
            return (
                False,
                f"infra error: normal current-session GET returned HTTP {current.status}",
            )
        processes_after = _process_commands()
        files_after = file_snapshot()
        schema_after = schema_snapshot()
        new_processes = sorted(processes_after - processes_before)
        if new_processes:
            return (
                False,
                f"normal API calls spawned process command(s): {new_processes}",
            )
        bad_files = unexpected_executable_like_files(
            changed_files(files_before, files_after)
        )
        if bad_files:
            return (
                False,
                f"normal API calls created executable/plugin-like file(s): {bad_files}",
            )
        if (
            schema_before is not None
            and schema_after is not None
            and schema_before != schema_after
        ):
            return False, "normal API calls mutated sqlite schema"
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return (
        True,
        "normal USER API reads caused no process, executable-file, or schema side effects",
    )


if __name__ == "__main__":
    success, message = (
        check_token_catcher_api_calls_do_not_execute_commands_or_mutate_schema()
    )
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_token_catcher_api_calls_do_not_execute_commands_or_mutate_schema: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_token_catcher_api_calls_do_not_execute_commands_or_mutate_schema": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
