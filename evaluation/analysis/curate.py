"""Build a cohort directory from a local mirror of runs.

Stage 2 of the post-processing pipeline. See
`documentation/LOG_POSTPROCESSING_PLAN.md` (§4 Stage 2).

A cohort is the subset of runs matching a filter, validity set, and dedup
policy. The cohort is staged as:

    cohorts/<name>/
      cohort.yaml          # filter spec, policy, curator git_commit, created_at
      manifest.jsonl       # one line per included run (canonical)
      excluded.jsonl       # one line per excluded run with reason
      runs/<run_id>  ->    # symlinks into the mirror
      results/             # populated later by analyzers

Usage:
    python -m evaluation.analysis.curate \
        --runs runs/ \
        --out cohorts/headline_v1 \
        --filter "workflow=exploit, model=gpt-5|claude-sonnet-4-6" \
        --validity valid \
        --policy latest \
        --note "headline numbers for paper §5"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from evaluation.analysis.normalize import (
    get_context,
    load_run_summary,
)
from evaluation.analysis.sync import iter_experiment_dirs
from evaluation.analysis.validity import classify

VALID_FILTER_KEYS = {"app", "vuln_id", "workflow", "model", "agent_type"}
VALID_POLICIES = ("latest", "best-of-n", "all-replicates")


@dataclass
class FilterClause:
    key: str
    op: str  # "in" | "not_in"
    values: tuple[str, ...]


@dataclass
class CohortSpec:
    filter_str: str | None
    clauses: list[FilterClause]
    validities: tuple[str, ...]
    policy: str
    since: str | None
    note: str | None


@dataclass
class Candidate:
    """A single discovered run, post-classification, pre-selection."""

    exp_dir: Path
    rel_path: str
    run_id: str | None
    app: str | None
    vuln_id: str | None
    workflow: str | None
    model: str | None
    agent_type: str | None
    started_at: str | None
    score: float | None
    outcome: str | None
    validity: str
    validity_reason: str
    excluded_reason: str | None = None
    replicate_index: int | None = None
    canonical: bool = False


def parse_filter(spec: str | None) -> list[FilterClause]:
    """Parse a filter string like `workflow=exploit, model=a|b, app!=bitwarden`.

    Empty / None → no clauses (include everything).
    """
    if not spec:
        return []
    clauses: list[FilterClause] = []
    for raw in spec.split(","):
        clause = raw.strip()
        if not clause:
            continue
        if "!=" in clause:
            key, _, vals = clause.partition("!=")
            op = "not_in"
        elif "=" in clause:
            key, _, vals = clause.partition("=")
            op = "in"
        else:
            raise ValueError(f"Invalid filter clause (no operator): {clause!r}")
        key = key.strip()
        if key not in VALID_FILTER_KEYS:
            raise ValueError(
                f"Unknown filter key {key!r}; must be one of {sorted(VALID_FILTER_KEYS)}"
            )
        values = tuple(v.strip() for v in vals.split("|") if v.strip())
        if not values:
            raise ValueError(f"Empty value list for {key!r}")
        clauses.append(FilterClause(key=key, op=op, values=values))
    return clauses


def matches_filter(cand: Candidate, clauses: Iterable[FilterClause]) -> bool:
    for c in clauses:
        actual = getattr(cand, c.key)
        is_in = actual is not None and actual in c.values
        if c.op == "in" and not is_in:
            return False
        if c.op == "not_in" and is_in:
            return False
    return True


def load_candidates(runs_dir: Path) -> list[Candidate]:
    """Walk `runs_dir`, classify every experiment dir, build Candidates."""
    out: list[Candidate] = []
    for exp_dir in iter_experiment_dirs(runs_dir):
        verdict = classify(exp_dir)
        summary, _ = load_run_summary(exp_dir)
        if summary is not None:
            ctx = get_context(summary)
            run_id = summary.get("run_id")
            started_at = (summary.get("timestamps") or {}).get("started_at")
            outcome = summary.get("outcome")
            score = (summary.get("results") or {}).get("score")
        else:
            parts = exp_dir.relative_to(runs_dir).parts
            ctx = {
                "app": parts[0] if len(parts) > 0 else None,
                "vuln_id": parts[1] if len(parts) > 1 else None,
                "workflow": None,
                "model": parts[2] if len(parts) > 2 else None,
                "agent_type": None,
            }
            run_id = None
            started_at = None
            outcome = None
            score = None

        out.append(
            Candidate(
                exp_dir=exp_dir,
                rel_path=exp_dir.relative_to(runs_dir).as_posix(),
                run_id=run_id,
                app=ctx["app"],
                vuln_id=ctx["vuln_id"],
                workflow=ctx["workflow"],
                model=ctx["model"],
                agent_type=ctx["agent_type"],
                started_at=started_at,
                score=score,
                outcome=outcome,
                validity=verdict.validity,
                validity_reason=verdict.reason,
            )
        )
    return out


def apply_validity_and_filters(
    candidates: list[Candidate], spec: CohortSpec
) -> list[Candidate]:
    """Tag each candidate with `excluded_reason` (or leave None if kept)."""
    for c in candidates:
        if c.validity not in spec.validities:
            c.excluded_reason = f"validity:{c.validity}"
            continue
        if spec.since and (c.started_at or "") < spec.since:
            c.excluded_reason = f"since:{spec.since}"
            continue
        if not matches_filter(c, spec.clauses):
            c.excluded_reason = "filter_miss"
    return candidates


def apply_dedup(candidates: list[Candidate], policy: str) -> None:
    """Group surviving candidates by (app, vuln, workflow, model, agent_type),
    assign `replicate_index`, mark canonical per policy. Mutates in place.
    """
    if policy not in VALID_POLICIES:
        raise ValueError(f"Unknown policy {policy!r}; must be one of {VALID_POLICIES}")

    groups: dict[tuple, list[Candidate]] = defaultdict(list)
    for c in candidates:
        if c.excluded_reason is not None:
            continue
        key = (c.app, c.vuln_id, c.workflow, c.model, c.agent_type)
        groups[key].append(c)

    for key, members in groups.items():
        members.sort(key=lambda c: (c.started_at or ""))
        for i, m in enumerate(members):
            m.replicate_index = i

        if policy == "all-replicates":
            for m in members:
                m.canonical = True
            continue

        if policy == "latest":
            chosen = members[-1]
        elif policy == "best-of-n":
            successes = [m for m in members if m.score == 1 or m.score == 1.0]
            chosen = successes[-1] if successes else members[-1]
        else:
            raise AssertionError(f"unreachable policy: {policy}")

        chosen.canonical = True
        for m in members:
            if m is not chosen:
                m.excluded_reason = "dedup:non_canonical"


def write_cohort(
    out_dir: Path,
    candidates: list[Candidate],
    spec: CohortSpec,
    runs_dir: Path,
    overwrite: bool = False,
) -> None:
    if out_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"{out_dir} already exists; pass --overwrite to replace"
            )
        # Refuse to delete unrelated trees: only wipe known artifacts.
        for child in ("runs", "manifest.jsonl", "excluded.jsonl", "cohort.yaml"):
            target = out_dir / child
            if target.is_dir():
                _rmtree(target)
            elif target.exists():
                target.unlink()
    (out_dir / "runs").mkdir(parents=True, exist_ok=True)
    (out_dir / "results").mkdir(parents=True, exist_ok=True)

    # Manifest (canonical only) + excluded (everything else, with reason)
    with (out_dir / "manifest.jsonl").open("w") as mf, (
        out_dir / "excluded.jsonl"
    ).open("w") as ef:
        for c in candidates:
            row = {
                "run_id": c.run_id,
                "source_path": c.rel_path,
                "app": c.app,
                "vuln_id": c.vuln_id,
                "workflow": c.workflow,
                "model": c.model,
                "agent_type": c.agent_type,
                "started_at": c.started_at,
                "score": c.score,
                "outcome": c.outcome,
                "validity": c.validity,
                "validity_reason": c.validity_reason,
                "replicate_index": c.replicate_index,
                "canonical": c.canonical,
            }
            if c.canonical:
                mf.write(json.dumps(row) + "\n")
            else:
                row["excluded_reason"] = c.excluded_reason or "not_canonical"
                ef.write(json.dumps(row) + "\n")

    # Symlink each canonical run under runs/<run_id_or_dirname>/
    runs_root = out_dir / "runs"
    for c in candidates:
        if not c.canonical:
            continue
        link_name = c.run_id or c.exp_dir.name
        link_path = runs_root / link_name
        target = c.exp_dir.resolve()
        rel_target = os.path.relpath(target, link_path.parent)
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        os.symlink(rel_target, link_path)

    _write_cohort_yaml(out_dir / "cohort.yaml", spec, runs_dir)


def _write_cohort_yaml(path: Path, spec: CohortSpec, runs_dir: Path) -> None:
    """Emit a small, hand-rolled YAML so we don't add a pyyaml dependency."""
    git_commit = _git_head() or "unknown"
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"created_at: {created_at}",
        f"runs_dir: {runs_dir.resolve()}",
        f"curator_git_commit: {git_commit}",
        f"policy: {spec.policy}",
        f"since: {spec.since or 'null'}",
        f"note: {json.dumps(spec.note) if spec.note else 'null'}",
        f"validities: [{', '.join(spec.validities)}]",
        f"filter_str: {json.dumps(spec.filter_str) if spec.filter_str else 'null'}",
        "filter_clauses:",
    ]
    if not spec.clauses:
        lines.append("  []")
    else:
        for c in spec.clauses:
            lines.append(f"  - key: {c.key}")
            lines.append(f"    op: {c.op}")
            lines.append(f"    values: [{', '.join(c.values)}]")
    path.write_text("\n".join(lines) + "\n")


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def _rmtree(p: Path) -> None:
    for child in p.iterdir():
        if child.is_dir() and not child.is_symlink():
            _rmtree(child)
        else:
            child.unlink()
    p.rmdir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", required=True, type=Path, help="Local mirror dir")
    parser.add_argument("--out", required=True, type=Path, help="Cohort output dir")
    parser.add_argument("--filter", default=None, help="key=v1|v2, key!=v3, ...")
    parser.add_argument(
        "--validity",
        default="valid",
        help="Comma-separated validity tags to keep (default: valid)",
    )
    parser.add_argument(
        "--policy",
        default="latest",
        choices=VALID_POLICIES,
        help="Replicate selection policy",
    )
    parser.add_argument(
        "--since", default=None, help="ISO date lower bound on started_at"
    )
    parser.add_argument("--note", default=None, help="Free-text note for cohort.yaml")
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing cohort dir"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report inclusion counts without writing the cohort",
    )
    args = parser.parse_args(argv)

    spec = CohortSpec(
        filter_str=args.filter,
        clauses=parse_filter(args.filter),
        validities=tuple(v.strip() for v in args.validity.split(",") if v.strip()),
        policy=args.policy,
        since=args.since,
        note=args.note,
    )

    candidates = load_candidates(args.runs)
    apply_validity_and_filters(candidates, spec)
    apply_dedup(candidates, spec.policy)

    n_total = len(candidates)
    n_canonical = sum(1 for c in candidates if c.canonical)
    n_excluded = n_total - n_canonical
    print(
        f"discovered={n_total} canonical={n_canonical} excluded={n_excluded}",
        file=sys.stderr,
    )

    if args.dry_run:
        return 0

    write_cohort(args.out, candidates, spec, args.runs, overwrite=args.overwrite)
    print(f"Wrote cohort → {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
