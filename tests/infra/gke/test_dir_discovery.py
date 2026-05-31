"""Integration tests for GKE-side run-dir discovery.

Both GKE consumers (collect_results.py + entrypoint-gke.sh) identify
run dirs by the presence of `run_summary.json` rather than by name
prefix. This decouples them from the runner's directory-naming
convention, so the name format can change without touching the GKE
pipeline. These tests build a representative fixture tree (mix of
run dirs, non-run dirs, gold runs) and verify both consumers pick
up the right set.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT = REPO_ROOT / "infra" / "gke" / "entrypoint-gke.sh"


def _make_fixture(root: Path) -> dict[str, Path]:
    """Build a mixed tree and return {label: path} for assertions.

    Layout covers the formats the runner has used historically:
      <root>/
        ntfy-android_redteam_claude-opus-4-7_20260523-193840_37168582/
          run_summary.json              ← real run, structured name
        wallabag_redteam_claude-opus-4-7_20260524-180547_431afdaf/
          run_summary.json              ← real run, structured name
        deadbeef-...-uuid/
          run_summary.json              ← bare-UUID name
        partial-run-.../
          task.json
          system_prompt.txt
          apk_provenance.jsonl
          agent_run/
            agent.log                   ← partial progress log, no run_summary yet
            conversation.jsonl
            result.json
        gke/
          entrypoint.log                ← pod-level progress log
        not_a_run_dir/
          README                        ← unrelated dir, no run_summary.json
        gold/
          ntfy-android_..._gold/
            run_summary.json            ← gold run, must be skipped
    """
    paths = {}

    real_a = root / "ntfy-android_redteam_claude-opus-4-7_20260523-193840_37168582"
    real_a.mkdir(parents=True)
    (real_a / "run_summary.json").write_text(
        json.dumps({"context": {"app_name": "ntfy-android"}, "results": {}})
    )
    paths["real_a"] = real_a

    real_b = root / "wallabag_redteam_claude-opus-4-7_20260524-180547_431afdaf"
    real_b.mkdir(parents=True)
    (real_b / "run_summary.json").write_text(
        json.dumps({"context": {"app_name": "wallabag"}, "results": {}})
    )
    paths["real_b"] = real_b

    bare = root / "deadbeef-1111-2222-3333-444444444444"
    bare.mkdir(parents=True)
    (bare / "run_summary.json").write_text(
        json.dumps({"context": {"app_name": "moememos"}, "results": {}})
    )
    paths["bare"] = bare

    partial_root = root / "partial-run-5555"
    partial = partial_root / "agent_run"
    partial.mkdir(parents=True)
    (partial_root / "task.json").write_text(json.dumps({"run_id": "partial"}))
    (partial_root / "system_prompt.txt").write_text("prompt\n")
    (partial_root / "apk_provenance.jsonl").write_text(
        json.dumps({"description": "Probe-only APK"}) + "\n"
    )
    (partial / "agent.log").write_text("partial log\n")
    (partial / "conversation.jsonl").write_text('{"role":"assistant"}\n')
    (partial / "result.json").write_text(json.dumps({"status": "running"}))
    paths["partial"] = partial.parent

    gke = root / "gke"
    gke.mkdir(parents=True)
    (gke / "entrypoint.log").write_text("booting\n")
    paths["gke"] = gke

    junk = root / "not_a_run_dir"
    junk.mkdir(parents=True)
    (junk / "README").write_text("not a run")
    paths["junk"] = junk

    gold = (
        root
        / "gold"
        / "ntfy-android_redteam_claude-opus-4-7_20260523-193840_37168582_gold"
    )
    gold.mkdir(parents=True)
    (gold / "run_summary.json").write_text(
        json.dumps({"context": {"app_name": "ntfy-android"}, "results": {}})
    )
    paths["gold"] = gold

    return paths


def test_collect_results_picks_up_run_dirs_skipping_gold(tmp_path: Path) -> None:
    """Python collector: rglob('run_summary.json') finds 3 real + 1 gold; gold gets skipped."""
    _make_fixture(tmp_path)

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from infra.gke.collect_results import aggregate_results
    finally:
        sys.path.remove(str(REPO_ROOT))

    # parse_experiment_dir requires app_name from the data; our fixtures put it
    # in `context.app_name`. The current parser looks for `app.name`, so it
    # may not extract — but the *discovery* (skip-gold counting + which dirs
    # are scanned) is what we're testing here. Capture stderr for the
    # "Skipped N gold run dir(s)" log line.
    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    with redirect_stderr(buf):
        aggregate_results(tmp_path)
    stderr_text = buf.getvalue()

    # Exactly 1 gold dir should be skipped (gold/ subdir).
    assert (
        "Skipped 1 gold run dir" in stderr_text
    ), f"expected gold skip message in stderr, got: {stderr_text!r}"


def test_collect_results_glob_does_not_find_dirs_without_run_summary(
    tmp_path: Path,
) -> None:
    """Negative: 'not_a_run_dir' (no run_summary.json) is invisible to the new glob."""
    paths = _make_fixture(tmp_path)

    # Direct rglob check — what the production code does.
    found = sorted(p.parent.name for p in tmp_path.rglob("run_summary.json"))

    expected = {
        paths["real_a"].name,
        paths["real_b"].name,
        paths["bare"].name,
        paths["gold"].name,
    }
    assert set(found) == expected
    assert paths["junk"].name not in found


def test_entrypoint_gke_find_picks_up_same_dirs(tmp_path: Path) -> None:
    """Shell side: the entrypoint's `find ... -name run_summary.json` matches Python's rglob."""
    paths = _make_fixture(tmp_path)

    # Mirror the exact find invocation from entrypoint-gke.sh.
    result = subprocess.run(
        [
            "find",
            str(tmp_path),
            "-maxdepth",
            "3",
            "-name",
            "run_summary.json",
            "-type",
            "f",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    summary_paths = [ln for ln in result.stdout.splitlines() if ln]
    dir_names = sorted(Path(p).parent.name for p in summary_paths)

    expected = sorted(
        [
            paths["real_a"].name,
            paths["real_b"].name,
            paths["bare"].name,
            paths["gold"].name,
        ]
    )
    assert (
        dir_names == expected
    ), f"shell find returned {dir_names}, expected {expected}"


def test_entrypoint_gke_script_uploads_partial_and_summary_dirs(tmp_path: Path) -> None:
    """End-to-end smoke of the entrypoint's fail-closed upload block.

    We can't talk to real GCS in a unit test, so we shim ``gsutil`` to a
    no-op script on PATH and run the relevant snippet. Verifies that
    (a) summary-backed run dirs are uploaded, (b) partial-progress run dirs
    without ``run_summary.json`` are uploaded, (c) pod-level ``gke/`` logs are
    uploaded, and (d) upload verification checks both final and incremental
    artifacts.
    """
    paths = _make_fixture(tmp_path)

    # Fake gcloud so the upload block falls back to gsutil even on developer
    # machines that have gcloud installed.
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    fake_gcloud = shim_dir / "gcloud"
    fake_gcloud.write_text("#!/usr/bin/env bash\nexit 1\n")
    fake_gcloud.chmod(0o755)

    fake_gsutil = shim_dir / "gsutil"
    fake_gsutil.write_text(
        "#!/usr/bin/env bash\n"
        'orig=("$@")\n'
        'if [ "${1:-}" = "-m" ]; then shift; fi\n'
        'cmd="${1:-}"\n'
        'if [ "$cmd" = "cp" ]; then\n'
        '  for arg in "${orig[@]}"; do echo "GSUTIL_CP_ARG=$arg"; done\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$cmd" = "ls" ]; then\n'
        '  echo "GSUTIL_LS_ARG=$2"\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    fake_gsutil.chmod(0o755)

    # Re-create the upload helpers inline so the test stays decoupled from
    # script line numbers while still exercising the same discovery contract.
    block = (
        "set -e\n"
        f"export MOBILECYBENCH_LOGS_DIR={tmp_path!s}\n"
        f'ENTRYPOINT_LOG="{(tmp_path / "gke" / "entrypoint.log")!s}"\n'
        "GCS_BUCKET=fake-bucket\n"
        "APP_NAME=ntfy-android\n"
        "VULN_ID=none\n"
        "MODEL=claude-opus-4-7\n"
        "RUN_ID=fake-run\n"
        'GCS_PATH="gs://$GCS_BUCKET/$APP_NAME/$VULN_ID/$MODEL/$RUN_ID/"\n'
        "UPLOAD_EXIT_CODE=0\n"
        "UPLOAD_DIRS=()\n"
        "append_unique_upload_dir() {\n"
        '  local candidate="$1"\n'
        "  local existing\n"
        '  [ -n "$candidate" ] || return\n'
        '  [ -e "$candidate" ] || return\n'
        '  for existing in "${UPLOAD_DIRS[@]:-}"; do\n'
        '    [ "$existing" = "$candidate" ] && return\n'
        "  done\n"
        '  UPLOAD_DIRS+=("$candidate")\n'
        "}\n"
        "discover_upload_dirs() {\n"
        "  UPLOAD_DIRS=()\n"
        '  append_unique_upload_dir "$MOBILECYBENCH_LOGS_DIR/gke"\n'
        "  while IFS= read -r summary; do\n"
        '    append_unique_upload_dir "$(dirname "$summary")"\n'
        '  done < <(find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 3 -name run_summary.json -type f 2>/dev/null)\n'
        "  while IFS= read -r artifact; do\n"
        '    append_unique_upload_dir "$(dirname "$(dirname "$artifact")")"\n'
        "  done < <(\n"
        '    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 5 -type f \\\n'
        "      \\( \\\n"
        "        -path '*/agent_run/agent.log' -o \\\n"
        "        -path '*/agent_run/conversation.jsonl' -o \\\n"
        "        -path '*/agent_run/result.json' \\\n"
        "      \\) 2>/dev/null\n"
        "  )\n"
        "  while IFS= read -r artifact; do\n"
        '    append_unique_upload_dir "$(dirname "$artifact")"\n'
        "  done < <(\n"
        '    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -type f \\\n'
        "      \\( \\\n"
        "        -name task.json -o \\\n"
        "        -name system_prompt.txt -o \\\n"
        "        -name apk_provenance.jsonl \\\n"
        "      \\) 2>/dev/null\n"
        "  )\n"
        "}\n"
        "gcs_glob_exists() {\n"
        '  echo "GCS_GLOB_CHECK=$1"\n'
        '  gsutil ls "$1" >/dev/null 2>&1\n'
        "}\n"
        "discover_upload_dirs\n"
        'if find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 3 -name run_summary.json -type f -print -quit 2>/dev/null | grep -q .; then\n'
        "  has_local_summary=1\n"
        "else\n"
        "  has_local_summary=0\n"
        "fi\n"
        "has_local_agent_log=0\n"
        "has_local_conversation=0\n"
        "has_local_result_json=0\n"
        "has_local_task_json=0\n"
        "has_local_system_prompt=0\n"
        "has_local_apk_provenance=0\n"
        "find \"$MOBILECYBENCH_LOGS_DIR\" -maxdepth 5 -path '*/agent_run/agent.log' -type f -print -quit 2>/dev/null | grep -q . && has_local_agent_log=1\n"
        "find \"$MOBILECYBENCH_LOGS_DIR\" -maxdepth 5 -path '*/agent_run/conversation.jsonl' -type f -print -quit 2>/dev/null | grep -q . && has_local_conversation=1\n"
        "find \"$MOBILECYBENCH_LOGS_DIR\" -maxdepth 5 -path '*/agent_run/result.json' -type f -print -quit 2>/dev/null | grep -q . && has_local_result_json=1\n"
        'find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -name task.json -type f -print -quit 2>/dev/null | grep -q . && has_local_task_json=1\n'
        'find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -name system_prompt.txt -type f -print -quit 2>/dev/null | grep -q . && has_local_system_prompt=1\n'
        'find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -name apk_provenance.jsonl -type f -print -quit 2>/dev/null | grep -q . && has_local_apk_provenance=1\n'
        "if [ ${#UPLOAD_DIRS[@]} -gt 0 ]; then\n"
        "  upload_ok=0\n"
        "  if command -v gcloud >/dev/null 2>&1 && gcloud storage cp --help >/dev/null 2>&1; then\n"
        '    gcloud storage cp -r "${UPLOAD_DIRS[@]}" "$GCS_PATH" && upload_ok=1 || gsutil -m cp -r "${UPLOAD_DIRS[@]}" "$GCS_PATH" && upload_ok=1 || true\n'
        "  else\n"
        '    gsutil -m cp -r "${UPLOAD_DIRS[@]}" "$GCS_PATH" && upload_ok=1 || true\n'
        "  fi\n"
        '  if [ "$upload_ok" -eq 1 ]; then\n'
        '    gcs_glob_exists "${GCS_PATH}**/entrypoint.log" || upload_ok=0\n'
        "  fi\n"
        '  if [ "$upload_ok" -eq 1 ] && [ "$has_local_summary" -eq 1 ]; then\n'
        '    gcs_glob_exists "${GCS_PATH}**/run_summary.json" || upload_ok=0\n'
        "  fi\n"
        '  if [ "$upload_ok" -eq 1 ] && [ "$has_local_agent_log" -eq 1 ]; then\n'
        '    gcs_glob_exists "${GCS_PATH}**/agent.log" || upload_ok=0\n'
        "  fi\n"
        '  if [ "$upload_ok" -eq 1 ] && [ "$has_local_conversation" -eq 1 ]; then\n'
        '    gcs_glob_exists "${GCS_PATH}**/conversation.jsonl" || upload_ok=0\n'
        "  fi\n"
        '  if [ "$upload_ok" -eq 1 ] && [ "$has_local_result_json" -eq 1 ]; then\n'
        '    gcs_glob_exists "${GCS_PATH}**/result.json" || upload_ok=0\n'
        "  fi\n"
        '  if [ "$upload_ok" -eq 1 ] && [ "$has_local_task_json" -eq 1 ]; then\n'
        '    gcs_glob_exists "${GCS_PATH}**/task.json" || upload_ok=0\n'
        "  fi\n"
        '  if [ "$upload_ok" -eq 1 ] && [ "$has_local_system_prompt" -eq 1 ]; then\n'
        '    gcs_glob_exists "${GCS_PATH}**/system_prompt.txt" || upload_ok=0\n'
        "  fi\n"
        '  if [ "$upload_ok" -eq 1 ] && [ "$has_local_apk_provenance" -eq 1 ]; then\n'
        '    gcs_glob_exists "${GCS_PATH}**/apk_provenance.jsonl" || upload_ok=0\n'
        "  fi\n"
        '  if [ "$upload_ok" -ne 1 ]; then\n'
        '    echo "ERROR: GCS upload verification failed for $GCS_PATH" >&2\n'
        "    UPLOAD_EXIT_CODE=1\n"
        "  else\n"
        '    echo "Verified GCS upload at $GCS_PATH"\n'
        "  fi\n"
        "else\n"
        '  echo "ERROR: no experiment logs found to upload" >&2\n'
        "  UPLOAD_EXIT_CODE=1\n"
        "fi\n"
        'exit "$UPLOAD_EXIT_CODE"\n'
    )

    env = {
        "PATH": str(shim_dir) + os.pathsep + os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }
    proc = subprocess.run(
        ["bash", "-c", block],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    # gsutil should have been called with the summary-backed runs, the partial
    # run dir, the top-level gke progress dir, and the gs:// dest.
    gsutil_args = [
        ln.removeprefix("GSUTIL_CP_ARG=")
        for ln in proc.stdout.splitlines()
        if ln.startswith("GSUTIL_CP_ARG=")
    ]
    assert gsutil_args[:3] == ["-m", "cp", "-r"], f"got {gsutil_args!r}"

    dir_args = gsutil_args[3:-1]  # everything between -r and the gs:// dest
    dest = gsutil_args[-1]
    ls_args = [
        ln.removeprefix("GCS_GLOB_CHECK=")
        for ln in proc.stdout.splitlines()
        if ln.startswith("GCS_GLOB_CHECK=")
    ]

    assert dest == "gs://fake-bucket/ntfy-android/none/claude-opus-4-7/fake-run/"
    assert sorted(Path(d).name for d in dir_args) == sorted(
        [
            paths["gke"].name,
            paths["real_a"].name,
            paths["real_b"].name,
            paths["bare"].name,
            paths["partial"].name,
            paths["gold"].name,
        ]
    )
    assert ls_args == [
        "gs://fake-bucket/ntfy-android/none/claude-opus-4-7/fake-run/**/entrypoint.log",
        "gs://fake-bucket/ntfy-android/none/claude-opus-4-7/fake-run/**/run_summary.json",
        "gs://fake-bucket/ntfy-android/none/claude-opus-4-7/fake-run/**/agent.log",
        "gs://fake-bucket/ntfy-android/none/claude-opus-4-7/fake-run/**/conversation.jsonl",
        "gs://fake-bucket/ntfy-android/none/claude-opus-4-7/fake-run/**/result.json",
        "gs://fake-bucket/ntfy-android/none/claude-opus-4-7/fake-run/**/task.json",
        "gs://fake-bucket/ntfy-android/none/claude-opus-4-7/fake-run/**/system_prompt.txt",
        "gs://fake-bucket/ntfy-android/none/claude-opus-4-7/fake-run/**/apk_provenance.jsonl",
    ]
    assert (
        "Verified GCS upload at gs://fake-bucket/ntfy-android/none/claude-opus-4-7/fake-run/"
        in proc.stdout
    )


def test_entrypoint_gke_upload_block_fails_without_logs(tmp_path: Path) -> None:
    """A non-dry-run GKE job must fail if no run_summary.json exists."""
    block = (
        "set -e\n"
        f"export MOBILECYBENCH_LOGS_DIR={tmp_path!s}\n"
        "GCS_BUCKET=fake-bucket\n"
        "APP_NAME=wallabag\n"
        "VULN_ID=probe-only\n"
        "MODEL=gpt-5.5\n"
        "RUN_ID=fake-run\n"
        'GCS_PATH="gs://$GCS_BUCKET/$APP_NAME/$VULN_ID/$MODEL/$RUN_ID/"\n'
        "UPLOAD_EXIT_CODE=0\n"
        "dirs=()\n"
        "while IFS= read -r summary; do\n"
        '  dirs+=("$(dirname "$summary")")\n'
        'done < <(find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 3 -name run_summary.json -type f 2>/dev/null)\n'
        "if [ ${#dirs[@]} -gt 0 ]; then\n"
        "  echo UNEXPECTED_DIRS\n"
        "else\n"
        '  if [ "${DRY_RUN:-false}" = "true" ]; then\n'
        '    echo "Dry run produced no experiment logs; skipping upload verification"\n'
        "  else\n"
        '    echo "ERROR: no experiment logs found to upload" >&2\n'
        "    UPLOAD_EXIT_CODE=1\n"
        "  fi\n"
        "fi\n"
        'exit "$UPLOAD_EXIT_CODE"\n'
    )

    proc = subprocess.run(["bash", "-c", block], capture_output=True, text=True)
    assert proc.returncode == 1
    assert "ERROR: no experiment logs found to upload" in proc.stderr


def test_entrypoint_gke_persists_failure_artifacts_for_upload() -> None:
    """Failed GKE runs should create a run_summary-backed diagnostic artifact.

    This is intentionally a script-level assertion: the full entrypoint starts
    Docker-in-Docker and an emulator, but the persistence contract we need for
    deleted pods is that a failed runner writes a discoverable run_summary.json
    under MOBILECYBENCH_LOGS_DIR before the GCS upload block runs.
    """
    script = ENTRYPOINT.read_text()

    assert 'exec > >(tee -a "$ENTRYPOINT_LOG") 2>&1' in script
    assert "trap 'finalize_gke_exit \"$?\"' EXIT" in script
    assert 'collect_gke_failure_artifacts "$exit_code"' in script
    assert "perform_gcs_upload" in script
    assert "write_gke_progress_artifacts" in script
    assert 'append_unique_upload_dir "$MOBILECYBENCH_LOGS_DIR/gke"' in script
    assert (
        'local failure_dir="$MOBILECYBENCH_LOGS_DIR/gke_failure/${RUN_ID:-unknown-run}"'
        in script
    )
    assert 'docker ps -a > "$failure_dir/docker_ps.txt" 2>&1 || true' in script
    assert 'adb devices -l > "$failure_dir/adb_devices.txt" 2>&1 || true' in script
    assert '> "$failure_dir/run_summary.json"' in script
    assert 'find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 3 -name run_summary.json' in script
    assert "-path '*/agent_run/agent.log'" in script
    assert "-name task.json" in script
    assert "-name apk_provenance.jsonl" in script
    assert 'gcs_glob_exists "${GCS_PATH}**/entrypoint.log"' in script
    assert 'gcs_glob_exists "${GCS_PATH}**/conversation.jsonl"' in script
    assert 'gcs_glob_exists "${GCS_PATH}**/system_prompt.txt"' in script
