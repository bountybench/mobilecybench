#!/usr/bin/env python3
"""LLM-driven adversarial decoy generation (Phase 2.5).

Given a probe (filesystem path) and the invariant it enforces, generates
cross-family decoy attempts — concrete commands that try to satisfy the
probe's observable signal without triggering the underlying bug.

The decoy model is chosen from a *different* family than the synthesizer
(specified via ``--synthesizer-model``). This is the load-bearing
cross-family gate against same-model blindspots.

Output:
  probe_gen/runs/decoys_<probe_id>_<ts>/decoys.json   structured batch
  probe_gen/runs/decoys_<probe_id>_<ts>/decoys.md     human-readable report

Each decoy attempt comes with a model-claimed ``would_satisfy_probe``
flag — but that's just a triage hint. The full FP-defense gate runs
each attempt against the clean build and *empirically* confirms whether
the probe is fooled. This script just produces the candidates.

Usage::

    python probe_gen/scripts/generate_decoys.py \\
        --probe apps/home-assistant-android/checks/check_no_new_admin_refresh_tokens.py \\
        --invariant-id RA-C \\
        --invariant-statement "The companion APK shall not contain hardcoded credentials..." \\
        --synthesizer-model claude-opus-4-7

Cost: typically $0.10–0.50 per probe across all 5 decoy classes.
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

from probe_gen.pipeline.decoys import (  # noqa: E402
    ALL_DECOY_CLASSES,
    generate_decoys,
    render_decoy_md,
)
from probe_gen.pipeline.discovery import _parse_probe_header  # noqa: E402


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--probe", required=True, help="Path to checks/check_*.py")
    p.add_argument(
        "--invariant-id",
        default=None,
        help="Override invariant id (default: parsed from probe header)",
    )
    p.add_argument(
        "--invariant-statement",
        default=None,
        help="Override invariant statement (default: parsed from probe header)",
    )
    p.add_argument(
        "--synthesizer-model",
        default="claude-opus-4-7",
        help=(
            "The model that generated the probe — the decoy generator will "
            "automatically pick a different family. Default: claude-opus-4-7."
        ),
    )
    p.add_argument(
        "--classes",
        default=",".join(ALL_DECOY_CLASSES),
        help=(
            f"Comma-separated decoy classes (default: all 5). "
            f"Choices: {','.join(ALL_DECOY_CLASSES)}."
        ),
    )
    p.add_argument(
        "--n-per-class",
        type=int,
        default=3,
        help="Decoy attempts per class (default: 3).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output dir (default: probe_gen/runs/decoys_<probe_id>_<ts>).",
    )
    args = p.parse_args(argv)

    probe_path = Path(args.probe).resolve()
    if not probe_path.is_file():
        print(f"[decoy] probe not found: {probe_path}", file=sys.stderr)
        return 2

    probe_source = probe_path.read_text(encoding="utf-8")

    # Try to parse the header for invariant id / statement if not given
    invariant_id = args.invariant_id
    invariant_statement = args.invariant_statement
    if not invariant_id or not invariant_statement:
        # The probe-header parser only gives us invariant_id (single token);
        # for the statement we need to look at the docstring directly.
        try:
            probe_spec = _parse_probe_header(
                probe_path, fallback_attacker_model="remote_attacker"
            )
            invariant_id = invariant_id or probe_spec.invariant_id
        except Exception:
            pass

    if not invariant_id or invariant_id == "UNKNOWN":
        print(
            "[decoy] could not infer invariant id from probe; pass --invariant-id",
            file=sys.stderr,
        )
        return 2
    if not invariant_statement:
        # Fall back to a short generic statement; quality of decoys depends
        # heavily on this, so callers should ideally pass the real one.
        invariant_statement = (
            f"The invariant {invariant_id} (extract the full statement from "
            f"threat_model.md and pass via --invariant-statement)"
        )
        print(
            f"[decoy] WARNING: using placeholder statement for {invariant_id}; "
            "decoy quality will suffer. Pass --invariant-statement.",
            file=sys.stderr,
        )

    classes = [c.strip() for c in args.classes.split(",") if c.strip()]
    invalid = [c for c in classes if c not in ALL_DECOY_CLASSES]
    if invalid:
        print(f"[decoy] unknown decoy classes: {invalid}", file=sys.stderr)
        return 2

    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = _REPO_ROOT / "probe_gen" / "runs" / f"decoys_{probe_path.stem}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[decoy] probe={probe_path.stem} invariant={invariant_id} "
        f"classes={','.join(classes)} synthesizer_model={args.synthesizer_model}",
        file=sys.stderr,
    )

    batch = generate_decoys(
        invariant_id=invariant_id,
        invariant_statement=invariant_statement,
        probe_id=probe_path.stem,
        probe_source=probe_source,
        classes=classes,  # type: ignore[arg-type]
        n_per_class=args.n_per_class,
        synthesizer_model=args.synthesizer_model,
    )

    (out_dir / "decoys.json").write_text(
        json.dumps(batch.to_dict(), indent=2), encoding="utf-8"
    )
    (out_dir / "decoys.md").write_text(render_decoy_md(batch), encoding="utf-8")

    claimed = sum(1 for a in batch.attempts if a.would_satisfy_probe)
    print(
        f"[decoy] DONE — attempts={len(batch.attempts)} "
        f"claimed_successful={claimed} cost=${batch.cost_usd:.4f}",
        file=sys.stderr,
    )
    print(f"[decoy] md={out_dir/'decoys.md'}", file=sys.stderr)
    print(f"[decoy] json={out_dir/'decoys.json'}", file=sys.stderr)

    # Non-zero exit if the model claims any decoy succeeds — caller can use
    # this to gate probe acceptance pre-execution. The empirical gate is
    # the load-bearing one but this gives a triage signal.
    return 0 if claimed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
