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


def _entrypoint_upload_path_block() -> str:
    text = ENTRYPOINT.read_text()
    start = text.index("    RUN_ID=")
    end = text.index('    echo "Uploading results to $GCS_PATH"', start)
    lines = text[start:end].splitlines()
    return "\n".join(line[4:] if line.startswith("    ") else line for line in lines)


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


def test_collect_results_parses_probe_only_summary_and_upload_path(
    tmp_path: Path,
) -> None:
    from infra.gke.collect_results import parse_experiment_dir

    run_dir = tmp_path / "wallabag" / "openai_gpt-5.5" / "run-1" / "run-log"
    run_dir.mkdir(parents=True)
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "context": {
                    "app_name": "wallabag",
                    "workflow": "redteam",
                    "vuln_id": None,
                    "model": "openai/gpt-5.5",
                },
                "results": {"status": "signal", "score": 1},
                "metrics": {"turn_count": 7},
            }
        )
    )

    parsed = parse_experiment_dir(run_dir)

    assert parsed is not None
    assert parsed["app_name"] == "wallabag"
    assert parsed["vuln_id"] == ""
    assert parsed["model"] == "openai/gpt-5.5"
    assert parsed["status"] == "signal"
    assert parsed["score"] == "1"
    assert parsed["turns"] == "7"


def test_collect_results_fallback_parses_legacy_synthetic_path(tmp_path: Path) -> None:
    from infra.gke.collect_results import parse_experiment_dir

    run_dir = tmp_path / "moememos" / "vuln_0" / "gpt-5-5" / "run-1" / "run-log"
    run_dir.mkdir(parents=True)
    (run_dir / "run_summary.json").write_text(json.dumps({"status": "completed"}))

    parsed = parse_experiment_dir(run_dir)

    assert parsed is not None
    assert parsed["app_name"] == "moememos"
    assert parsed["vuln_id"] == "vuln_0"
    assert parsed["model"] == "gpt-5-5"


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


def test_entrypoint_gke_script_uploads_block_dry_run(tmp_path: Path) -> None:
    """End-to-end smoke of the entrypoint's upload block with a fake gsutil shim.

    We can't talk to real GCS in a unit test, so we shim ``gsutil`` to a
    no-op script on PATH and run the relevant snippet. Verifies that
    (a) the `find`-derived ``dirs`` array is non-empty and (b) gsutil gets
    invoked with the right set of run dirs.
    """
    paths = _make_fixture(tmp_path)

    # Fake gsutil that just prints its args, one per line.
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    fake_gsutil = shim_dir / "gsutil"
    fake_gsutil.write_text(
        "#!/usr/bin/env bash\n" 'for arg in "$@"; do echo "GSUTIL_ARG=$arg"; done\n'
    )
    fake_gsutil.chmod(0o755)

    # Execute the real entrypoint path-building block in isolation. We don't
    # run the whole entrypoint script because it expects DinD/emulator setup.
    block = (
        "set -e\n"
        f"export MOBILECYBENCH_LOGS_DIR={tmp_path!s}\n"
        "GCS_BUCKET=fake-bucket\n"
        "APP_NAME=ntfy-android\n"
        "MODEL=openai/gpt-5.5\n"
        "RUN_ID=fake-run\n"
        f"{_entrypoint_upload_path_block()}\n"
        "dirs=()\n"
        "while IFS= read -r summary; do\n"
        '  dirs+=("$(dirname "$summary")")\n'
        'done < <(find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 3 -name run_summary.json -type f 2>/dev/null)\n'
        "if [ ${#dirs[@]} -gt 0 ]; then\n"
        '  gsutil -m cp -r "${dirs[@]}" "$GCS_PATH"\n'
        "else\n"
        "  echo NO_DIRS_FOUND\n"
        "fi\n"
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

    # gsutil should have been called with the 4 run dirs + the gs:// dest.
    gsutil_args = [
        ln.removeprefix("GSUTIL_ARG=")
        for ln in proc.stdout.splitlines()
        if ln.startswith("GSUTIL_ARG=")
    ]
    assert gsutil_args[:3] == ["-m", "cp", "-r"], f"got {gsutil_args!r}"

    dir_args = gsutil_args[3:-1]  # everything between -r and the gs:// dest
    dest = gsutil_args[-1]

    assert dest == "gs://fake-bucket/ntfy-android/openai_gpt-5.5/fake-run/"
    assert sorted(Path(d).name for d in dir_args) == sorted(
        [
            paths["real_a"].name,
            paths["real_b"].name,
            paths["bare"].name,
            paths["gold"].name,
        ]
    )
    # 'NO_DIRS_FOUND' should not appear.
    assert "NO_DIRS_FOUND" not in proc.stdout
