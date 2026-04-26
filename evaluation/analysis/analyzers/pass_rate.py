"""Pass-rate analyzer.

Reads the canonical runs in a cohort and emits a pass-rate table grouped by
the requested keys (default: model × app).

Usage:
    python -m evaluation.analysis.analyzers.pass_rate \
        --cohort cohorts/headline_v1
    python -m evaluation.analysis.analyzers.pass_rate \
        --cohort cohorts/headline_v1 --groupby model,workflow
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from evaluation.analysis.normalize import is_pass, load_run_summary


def iter_canonical(cohort_dir: Path):
    """Yield each canonical run from `cohort/manifest.jsonl`."""
    manifest = cohort_dir / "manifest.jsonl"
    if not manifest.exists():
        raise FileNotFoundError(f"No manifest at {manifest}")
    with manifest.open() as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def compute_pass_rate(cohort_dir: Path, groupby: list[str]) -> list[dict]:
    """Aggregate pass rate over canonical runs.

    Returns rows shaped as `{*groupby_keys, n, passes, pass_rate}`.
    """
    groups: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "passes": 0})
    runs_dir = cohort_dir / "runs"

    for entry in iter_canonical(cohort_dir):
        # Prefer the symlinked path inside the cohort so an analyzer always
        # works against the cohort's own view.
        link_name = entry.get("run_id") or Path(entry["source_path"]).name
        run_dir = runs_dir / link_name
        if not run_dir.exists():
            print(f"warning: missing run dir {run_dir}", file=sys.stderr)
            continue
        summary, err = load_run_summary(run_dir)
        if summary is None:
            print(f"warning: skip {run_dir}: {err}", file=sys.stderr)
            continue

        ctx = summary.get("context") or {}
        results = summary.get("results") or {}
        record = {
            "model": ctx.get("model"),
            "app": ctx.get("app_name"),
            "workflow": ctx.get("workflow"),
            "vuln_id": ctx.get("vuln_id"),
            "agent_type": ctx.get("agent_type"),
            "score": results.get("score"),
        }
        key = tuple(record.get(k) for k in groupby)
        groups[key]["n"] += 1
        if is_pass(summary):
            groups[key]["passes"] += 1

    rows: list[dict] = []
    for key, agg in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        n = agg["n"]
        passes = agg["passes"]
        rate = passes / n if n else 0.0
        rows.append(
            {
                **{k: v for k, v in zip(groupby, key)},
                "n": n,
                "passes": passes,
                "pass_rate": round(rate, 4),
            }
        )
    return rows


def write_csv(rows: list[dict], out_path: Path, groupby: list[str]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(groupby) + ["n", "passes", "pass_rate"]
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cohort", required=True, type=Path)
    parser.add_argument(
        "--groupby",
        default="model,app",
        help="Comma-separated grouping keys: any of model, app, workflow, vuln_id, agent_type",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Override output path (default: <cohort>/results/pass_rate.csv)",
    )
    args = parser.parse_args(argv)

    groupby = [k.strip() for k in args.groupby.split(",") if k.strip()]
    rows = compute_pass_rate(args.cohort, groupby)
    out = args.out or (args.cohort / "results" / "pass_rate.csv")
    write_csv(rows, out, groupby)
    print(f"Wrote {len(rows)} group rows → {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
