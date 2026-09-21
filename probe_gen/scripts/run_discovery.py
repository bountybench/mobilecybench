#!/usr/bin/env python3
"""Run Discovery-mode evaluation against an app's running runtime.

Discovers all ``check_*.py`` probes under ``apps/<app>/checks/`` and
``apps/<app>/remote_attacker/checks/``, runs each one, and produces a
severity-weighted score plus a per-probe report.

Used to score open-ended threat hunting: the agent runs against an
unmodified app, then this script scores any invariant violations the
agent's session left behind. No agent integration here — that's the
Workflow subclass's job (Phase 4.5). This CLI is the evaluation core.

Usage::

    python probe_gen/scripts/run_discovery.py --app conversations
    python probe_gen/scripts/run_discovery.py --app home-assistant-android \\
        --severity-json apps/home-assistant-android/invariants.json \\
        --attacker-model malicious_app
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from probe_gen.pipeline.discovery import (  # noqa: E402
    evaluate_discovery,
    load_invariants_severity_from_json,
    render_discovery_md,
)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--app", required=True, help="App under apps/")
    p.add_argument(
        "--attacker-model",
        choices=["malicious_app", "remote_attacker", "both"],
        default="both",
        help="Which probe scope to run. Default: both.",
    )
    p.add_argument(
        "--severity-json",
        default=None,
        help="Path to invariant_id→severity JSON. Default: lookup unset → MEDIUM weight.",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output dir (default: probe_gen/runs/discovery_<app>_<ts>).",
    )
    args = p.parse_args(argv)

    app_dir = _REPO_ROOT / "apps" / args.app
    if not app_dir.is_dir():
        print(f"[discovery] app not found: {app_dir}", file=sys.stderr)
        return 2

    severity = (
        load_invariants_severity_from_json(Path(args.severity_json))
        if args.severity_json
        else None
    )

    if args.attacker_model == "both":
        attacker_models = None
    else:
        attacker_models = [args.attacker_model]

    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = _REPO_ROOT / "probe_gen" / "runs" / f"discovery_{args.app}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    report = evaluate_discovery(
        app_dir=app_dir,
        repo_root=_REPO_ROOT,
        attacker_models=attacker_models,
        invariants_severity=severity,
    )
    (out_dir / "discovery.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    (out_dir / "discovery.md").write_text(render_discovery_md(report), encoding="utf-8")

    print(
        f"[discovery] app={args.app} probes_run={report.probes_run} "
        f"fired={report.probes_fired} error={report.probes_error} "
        f"score={report.severity_weighted_score}",
        file=sys.stderr,
    )
    print(f"[discovery] md={out_dir/'discovery.md'}", file=sys.stderr)
    print(f"[discovery] json={out_dir/'discovery.json'}", file=sys.stderr)
    # Non-zero exit if any probe fired (a "vulnerable" agent session).
    return 0 if report.probes_fired == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
