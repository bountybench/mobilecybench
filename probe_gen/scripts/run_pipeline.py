#!/usr/bin/env python3
"""End-to-end pipeline CLI: validate → materialize → run gates.

Glue script that ties the LLM-free pieces of the pipeline into a single
command. Given a probe-spec JSON for one app, it:

  1. Validates the spec against rubrics (``validate_spec``).
  2. Materializes the spec into ``apps/<app>/`` files
     (``materialize_probe_spec.materialize``).
  3. Runs a configurable gate sequence against the materialized probes
     (``run_gate_suite``).
  4. Persists ``ProbeGenRun`` summary under ``probe_gen/runs/<run_id>/``.

Useful for:
  - Smoke-testing a hand-authored probe spec.
  - Acceptance testing once the LLM-driven synthesis emits specs.

By default, runs only the ``clean_baseline`` gate with a no-op setup
(useful for verifying probes don't false-positive on a clean app's
current state). Future revisions will wire in real setup hooks for
each FP-defense gate.

Usage::

    python probe_gen/scripts/run_pipeline.py \\
        --spec probe_gen/runs/<id>/spec.json \\
        [--apply]                  # actually write probe files into apps/<app>/
        [--gate clean_baseline]    # repeatable; default: clean_baseline only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from probe_gen.pipeline.gates import GateContext, noop_setup  # noqa: E402
from probe_gen.pipeline.models import Invariant, Probe  # noqa: E402
from probe_gen.pipeline.runner import run_gate_suite  # noqa: E402
from probe_gen.pipeline.validation import (  # noqa: E402
    assert_no_problems,
    validate_spec,
)


def _import_materializer():
    import sys as _sys
    from pathlib import Path as _Path

    scripts_dir = _Path(__file__).resolve().parent
    if str(scripts_dir) not in _sys.path:
        _sys.path.insert(0, str(scripts_dir))
    if "materialize_probe_spec" in _sys.modules:
        del _sys.modules["materialize_probe_spec"]
    import materialize_probe_spec  # type: ignore[import-not-found]

    return materialize_probe_spec


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--spec", required=True, help="Path to probe-spec JSON")
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually write probe files (default: dry-run, no FS writes).",
    )
    p.add_argument(
        "--gate",
        action="append",
        default=None,
        help=(
            "Gate to run (repeatable). Default: clean_baseline. "
            "Note: only clean_baseline currently uses a no-op setup hook; "
            "other gates need real setup hooks wired in."
        ),
    )
    p.add_argument(
        "--app-dir",
        default=None,
        help="Override target app dir (default: <repo_root>/apps/<spec.app>).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output dir for run artifacts (default: probe_gen/runs/pipeline_<app>_<ts>).",
    )
    args = p.parse_args(argv)

    spec_path = Path(args.spec).resolve()
    if not spec_path.is_file():
        print(f"[pipeline] spec not found: {spec_path}", file=sys.stderr)
        return 2
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    # 1. Validate
    print(f"[pipeline] validating spec for app={spec.get('app')!r}", file=sys.stderr)
    try:
        assert_no_problems(validate_spec(spec))
    except ValueError as exc:
        print(f"[pipeline] {exc}", file=sys.stderr)
        return 1
    print("[pipeline] spec is valid", file=sys.stderr)

    app_dir = (
        Path(args.app_dir).resolve()
        if args.app_dir
        else (_REPO_ROOT / "apps" / spec["app"])
    )

    # 2. Materialize (dry-run unless --apply)
    materialize_probe_spec = _import_materializer()
    plan = materialize_probe_spec.materialize(spec, app_dir, apply=args.apply)
    action = "WROTE" if args.apply else "WOULD WRITE"
    for path, _content in plan:
        rel = path.relative_to(_REPO_ROOT) if _REPO_ROOT in path.parents else path
        print(f"[pipeline] {action}: {rel}", file=sys.stderr)
    if not args.apply:
        print(
            "[pipeline] dry-run: skipping gate execution (no probe files on disk).",
            file=sys.stderr,
        )
        return 0

    # 3. Run gates against the materialized probes
    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = _REPO_ROOT / "probe_gen" / "runs" / f"pipeline_{spec['app']}_{ts}"

    invariants = [Invariant.from_dict(d) for d in spec.get("invariants", [])]
    probes = [Probe.from_dict(e["spec"]) for e in spec.get("probes", [])]
    gate_names = args.gate or ["clean_baseline"]
    gate_sequence = [(name, noop_setup) for name in gate_names]  # noqa: F821

    ctx = GateContext(
        repo_root=_REPO_ROOT,
        app_dir=app_dir,
        run_dir=out_dir,
        env=dict(os.environ),
    )

    run = run_gate_suite(
        app=spec["app"],
        invariants=invariants,
        probes=probes,
        gate_sequence=gate_sequence,
        ctx=ctx,
        label="pipeline",
    )

    # 4. Print outcome summary
    pass_n = sum(1 for r in run.gate_results if r.outcome == "pass")
    fail_n = sum(1 for r in run.gate_results if r.outcome == "fail")
    err_n = sum(1 for r in run.gate_results if r.outcome == "error")
    print(
        f"[pipeline] gates: {len(run.gate_results)} runs "
        f"({pass_n} pass, {fail_n} fail, {err_n} error)",
        file=sys.stderr,
    )
    print(f"[pipeline] summary_md={out_dir/'summary.md'}", file=sys.stderr)
    print(f"[pipeline] summary_json={out_dir/'summary.json'}", file=sys.stderr)
    return 0 if fail_n == 0 and err_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
