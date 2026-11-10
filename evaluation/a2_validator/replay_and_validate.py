"""Replay one saved exploit -> run the probes -> run the A2-style Validator on
the same post-replay state, then let the harness tear down.

runner.py always tears down (Workflow.cleanup: backend `compose down -v`,
emulator kill) right after the probes, and has no keep-alive flag. Rather than
change shared code, this wrapper patches Workflow.cleanup in-process so the
Validator runs first, then calls the original cleanup.

Run from the repo (worktree) root, with no emulator already running:

    python -m evaluation.a2_validator.replay_and_validate \
        --cell GPT-5.5__apk_only__malicious_app__termux__a1 \
        --claim-json <results>/agent_run/result.json \
        --exploit-dir <results>/agent_exploit \
        --source-dir <app source without .git> --out <dir>   # --cli defaults to claude
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import runpy
import sys
import time
import traceback
from pathlib import Path

from evaluation.a2_validator import validate as V

REPO = V.REPO


def runner_config(threat: str, exploit_dir: Path) -> dict:
    cfg = {
        "workflow": "redteam",
        "probe_only": True,
        "attacker_model": threat,
        "task": None,
        "synthetic_vuln_id": None,
        "no_codebase": False,
        "agent_mode": "external",
        "model": "openai/gpt-5.5",  # inert in replay: no agent runs
        "max_iterations": 30,
        "max_model_response_tokens": 8192,
        "agent_wallclock_seconds": 600,
        "agent_image": "cybench/mobilecybench:opencode_1.15.6-r1",
        "build_type": "download-apk",
        "emulator_backend": "native",
        "emulator_display": "headless",
        "network_mode": "permissive",
        "replay_exploit_dir": str(exploit_dir),
        "dry_run": False,
        "gold_run": False,
    }
    if (
        threat == "malicious_app"
    ):  # same as mcb-fleet/regrade: MA -> delta scoring, RA -> plain replay
        cfg["probe_baseline_diff"] = True
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True, help="model__visibility__threat__app__aN")
    ap.add_argument("--claim-json", type=Path, required=True)
    ap.add_argument("--exploit-dir", type=Path, required=True)
    ap.add_argument("--source-dir", type=Path)
    ap.add_argument("--backend-json", type=Path)
    ap.add_argument(
        "--cli",
        choices=["claude"],
        nargs="+",
        default=["claude"],
        help="validators to run back to back on the same post-probe state "
        "(codex/gemini paths exist in validate.py but are unused)",
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument(
        "--env-file", type=Path, default=REPO.parent / "mobilecybench" / ".env"
    )
    a = ap.parse_args()
    V.load_env(a.env_file)

    _model, _vis, threat, app, _att = a.cell.split("__")
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cfg_path = out / "runner_config.json"
    cfg_path.write_text(
        json.dumps(runner_config(threat, a.exploit_dir.resolve()), indent=1)
    )
    logs = out / "harness_logs"
    os.environ["MOBILECYBENCH_LOGS_DIR"] = str(logs)
    os.environ.setdefault("ANDROID_HOME", str(Path.home() / ".android-sdk"))
    backend = json.loads(a.backend_json.read_text()) if a.backend_json else None
    record: dict = {"cell": a.cell, "clis": a.cli, "validations": {}}
    creds = {"claude": ("CLAUDE_CODE_OAUTH_TOKEN",)}
    if not os.environ.get(
        "CLAUDE_CODE_OAUTH_TOKEN"
    ):  # don't spend a replay when the Validator can't run
        sys.exit(
            "CLAUDE_CODE_OAUTH_TOKEN not set (run `claude setup-token`, add it to mobilecybench/.env)"
        )

    import workflows.base as wb

    orig_cleanup = wb.Workflow.cleanup

    def cleanup_with_validator(self):
        try:
            em = getattr(self, "emulator", None)
            serial = getattr(em, "device_id", None) if em else None
            scores = glob.glob(str(logs / "*" / "redteam_scores.json"))
            record["probe_scores_written_before_validator"] = bool(scores)
            if not serial:
                record["validator_error"] = (
                    "no live emulator at cleanup (replay failed before device came up)"
                )
            else:
                for cli in a.cli:
                    if not any(os.environ.get(k) for k in creds[cli]):
                        record["validations"][cli] = {
                            "skipped": f"no credential ({' or '.join(creds[cli])})"
                        }
                        continue
                    try:
                        record["validations"][cli] = V.validate(
                            cli=cli,
                            model=V.DEFAULT_MODELS[cli],
                            claim_json=a.claim_json,
                            app=app,
                            threat=threat,
                            source_dir=a.source_dir,
                            out=out / f"validator_{cli}",
                            serial=serial,
                            backend=backend,
                            timeout_s=a.timeout,
                        )
                    except Exception:
                        record["validations"][cli] = {"error": traceback.format_exc()}
        except Exception:  # never block harness teardown
            record["validator_error"] = traceback.format_exc()
        finally:
            orig_cleanup(self)

    wb.Workflow.cleanup = cleanup_with_validator
    sys.path[:0] = [str(REPO / "apps" / app), str(REPO)]
    sys.argv = ["runner.py", app, "--config", str(cfg_path)]
    t0 = time.time()
    try:
        runpy.run_path(str(REPO / "runner.py"), run_name="__main__")
    except (
        SystemExit
    ) as e:  # runner exit code mirrors the probe result (triggered -> 0)
        record["runner_exit"] = e.code
    record["total_wall_s"] = round(time.time() - t0, 1)

    sc = sorted(glob.glob(str(logs / "*" / "redteam_scores.json")))
    if sc:
        s = json.loads(Path(sc[-1]).read_text())
        record["probe_status"], record["probe_score"] = s.get("status"), s.get("score")
        record["harness_run_dir"] = str(Path(sc[-1]).parent)
    (out / "e2e_record.json").write_text(json.dumps(record, indent=1, default=str))
    print(
        json.dumps(
            {
                "cell": a.cell,
                "probe_status": record.get("probe_status"),
                "probe_scores_written_before_validator": record.get(
                    "probe_scores_written_before_validator"
                ),
                "validator_error": record.get("validator_error"),
                "total_wall_s": record["total_wall_s"],
                "validators": {
                    cli: {
                        k: v.get(k)
                        for k in (
                            "skipped",
                            "error",
                            "schema_errors",
                            "wall_clock_s",
                            "timed_out",
                            "cost_usd",
                            "cost_source",
                        )
                    }
                    | {
                        "verdict": (v.get("verdict") or {}).get("verdict"),
                        "state_unchanged": (v.get("state") or {}).get("unchanged"),
                    }
                    for cli, v in record["validations"].items()
                },
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
