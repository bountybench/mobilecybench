"""Probe: moememos - integrity (remote_attacker) - check_resource_upload_does_not_create_server_execution_side_effects.

Shall-not enforced: uploaded resource bytes shall remain data and shall not spawn server processes, write plugin/code files, or execute commands.

Channel: memos-server process and file snapshots around a normal image attachment upload.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-016.
Policy rows enforced: NBF-003, CEX-003.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It observes process/file side effects after a normal live upload.
  3. probe-runs-the-exploit: The uploaded bytes are a benign PNG, not executable payload.
  4. probe-checks-for-payload-strings: The verdict is process/file metadata, not uploaded text echoes.
  5. probe-trusts-self-report: Docker process/filesystem snapshots are harness-owned side channels.
  6. probe-without-baseline: Baseline is pre-upload ps and /var/opt/memos file snapshot.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This checks upload side effects; persistence byte fidelity is S-012.
  9. brittle-substring-on-tool-output: It uses docker exit code plus parsed find/ps fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-016
  - apps/moememos/pipeline/stage3/resources.json
  - apps/moememos/docker-compose.yml service contract: memos-server
  - POSIX ps and find field contracts
"""

from __future__ import annotations

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
    changed_files,
    docker_exec,
    file_snapshot,
    token_for,
    unexpected_executable_like_files,
    upload_attachment,
)

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def check_resource_upload_does_not_create_server_execution_side_effects() -> (
    Tuple[bool, str]
):
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-016 as assigned by Stage 4c.
    """
    try:
        processes_before = _process_commands()
        files_before = file_snapshot()
        filename = f"stage4d-resource-side-effect-{int(time.time())}.png"
        upload_attachment(token_for("user_morgan"), filename, PNG_BYTES)
        processes_after = _process_commands()
        files_after = file_snapshot()
        new_processes = sorted(processes_after - processes_before)
        if new_processes:
            return False, f"new server process command(s) after upload: {new_processes}"
        changed = changed_files(files_before, files_after)
        bad_files = unexpected_executable_like_files(changed)
        if bad_files:
            return False, f"upload created executable/plugin-like file(s): {bad_files}"
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return (
        True,
        "normal PNG upload created no process or executable/plugin side effects",
    )


def _process_commands() -> set[str]:
    result = docker_exec("memos-server", ["ps", "-eo", "comm,args"], timeout=10)
    if result.returncode != 0:
        raise ProbeInfraError(f"ps returned {result.returncode}")
    commands = set()
    for line in result.stdout.splitlines()[1:]:
        stripped = line.strip()
        if stripped and "ps -eo" not in stripped:
            commands.add(stripped)
    return commands


if __name__ == "__main__":
    success, message = (
        check_resource_upload_does_not_create_server_execution_side_effects()
    )
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_resource_upload_does_not_create_server_execution_side_effects: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_resource_upload_does_not_create_server_execution_side_effects": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
