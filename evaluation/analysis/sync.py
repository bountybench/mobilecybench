"""Sync experiment runs from a GCS bucket into a local mirror.

Stage 1 of the post-processing pipeline. See
`documentation/LOG_POSTPROCESSING_PLAN.md` (§4 Stage 1).

Usage:
    # Pull everything except per-turn screenshots (default).
    python -m evaluation.analysis.sync --bucket my-bucket --out runs/

    # Include screenshots (can multiply local size by ~10x).
    python -m evaluation.analysis.sync --bucket my-bucket --out runs/ \
        --with-screenshots

    # Build/refresh the inventory cache for fast cohort filtering.
    python -m evaluation.analysis.sync --inventory --runs-dir runs/

The mirror layout follows GCS:
    runs/{app}/{vuln_id}/{model}/{pod_name}/experiment_<uuid>/...
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from evaluation.analysis.normalize import (
    get_context,
    get_results,
    load_run_summary,
)
from evaluation.analysis.validity import classify

INVENTORY_FILE = "_inventory.jsonl"
SCREENSHOT_EXCLUDE_REGEX = r".*/screenshots/.*"


def gsutil_rsync(bucket: str, out_dir: Path, with_screenshots: bool) -> int:
    """Run `gsutil -m rsync -r` from gs://bucket/ to out_dir/."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["gsutil", "-m", "rsync", "-r"]
    if not with_screenshots:
        cmd += ["-x", SCREENSHOT_EXCLUDE_REGEX]
    cmd += [f"gs://{bucket}/", str(out_dir)]
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.call(cmd)


@dataclass
class InventoryRow:
    run_id: str | None
    path: str  # relative to runs_dir
    app: str | None
    vuln_id: str | None
    workflow: str | None
    model: str | None
    agent_type: str | None
    is_gold: bool
    started_at: str | None
    outcome: str | None
    score: float | None
    validity: str
    validity_reason: str


def _row_for(exp_dir: Path, runs_dir: Path) -> InventoryRow:
    """Build a single inventory row for an experiment directory."""
    rel = exp_dir.relative_to(runs_dir).as_posix()
    is_gold = exp_dir.name.endswith("_gold")
    summary, _ = load_run_summary(exp_dir)
    verdict = classify(exp_dir)

    if summary is None:
        # Fall back to path-derived metadata so missing-summary dirs are
        # still discoverable by the curator.
        parts = exp_dir.relative_to(runs_dir).parts
        # parts: (app, vuln_id, model, pod_name, experiment_<uuid>)
        return InventoryRow(
            run_id=None,
            path=rel,
            app=parts[0] if len(parts) > 0 else None,
            vuln_id=parts[1] if len(parts) > 1 else None,
            workflow=None,
            model=parts[2] if len(parts) > 2 else None,
            agent_type=None,
            is_gold=is_gold,
            started_at=None,
            outcome=None,
            score=None,
            validity=verdict.validity,
            validity_reason=verdict.reason,
        )

    ctx = get_context(summary)
    res = get_results(summary)
    return InventoryRow(
        run_id=summary.get("run_id"),
        path=rel,
        app=ctx["app"],
        vuln_id=ctx["vuln_id"],
        workflow=ctx["workflow"],
        model=ctx["model"],
        agent_type=ctx["agent_type"],
        is_gold=is_gold,
        started_at=(summary.get("timestamps") or {}).get("started_at"),
        outcome=summary.get("outcome"),
        score=res["score"],
        validity=verdict.validity,
        validity_reason=verdict.reason,
    )


def iter_experiment_dirs(runs_dir: Path):
    """Yield every `experiment_*` directory under `runs_dir`, sorted."""
    for exp_dir in sorted(runs_dir.rglob("experiment_*")):
        if exp_dir.is_dir():
            yield exp_dir


def build_inventory(runs_dir: Path) -> Path:
    """Walk `runs_dir` and write `_inventory.jsonl` at its root."""
    out = runs_dir / INVENTORY_FILE
    n = 0
    with out.open("w") as f:
        for exp_dir in iter_experiment_dirs(runs_dir):
            row = _row_for(exp_dir, runs_dir)
            f.write(json.dumps(asdict(row)) + "\n")
            n += 1
    print(f"Wrote {n} rows → {out}", file=sys.stderr)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bucket", help="GCS bucket name (omit with --inventory)")
    parser.add_argument(
        "--out",
        type=Path,
        help="Local mirror destination directory",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        help="Existing local mirror (used with --inventory)",
    )
    parser.add_argument(
        "--with-screenshots",
        action="store_true",
        help="Mirror per-turn screenshots (default: skipped, ~10x smaller)",
    )
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="Build _inventory.jsonl from a local mirror; skip GCS sync",
    )
    args = parser.parse_args(argv)

    if args.inventory:
        runs_dir = args.runs_dir or args.out
        if runs_dir is None:
            parser.error("--inventory requires --runs-dir or --out")
        build_inventory(runs_dir)
        return 0

    if not args.bucket or not args.out:
        parser.error("--bucket and --out are required (unless --inventory)")

    rc = gsutil_rsync(args.bucket, args.out, args.with_screenshots)
    if rc != 0:
        print(f"gsutil exited with {rc}", file=sys.stderr)
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
