#!/usr/bin/env python3
"""Agreement of judge verdicts with the paper's base_signal (and regrade_signal where present).

  summarize_full.py paper_runs.jsonl results.jsonl
"""
import json
import re
import statistics
import sys
from collections import defaultdict

from run_judge import MODEL, is_blocked

runs = {r["cell_id"]: r for r in map(json.loads, open(sys.argv[1]))}
latest = {}  # one record per run: the last non-skipped one
for r in map(json.loads, open(sys.argv[2])):
    if "skipped" not in r:
        latest[r["cell_id"]] = r
recs = list(latest.values())
blocked = [r for r in recs if is_blocked(r)]
ok = [r for r in recs if r.get("schema_valid")]
invalid = [r for r in recs if not r.get("schema_valid") and not is_blocked(r)]
fallback = {r["cell_id"] for r in ok if set(r.get("models") or []) != {MODEL}}
judgeable = sum(1 for r in runs.values() if r["exploit_dir"])
print(
    f"selected runs: {len(runs)}; with exploit: {judgeable}; judged: {len(recs)}; schema-valid: {len(ok)} "
    f"({len(fallback)} with fallback model); blocked: {len(blocked)}; other invalid: {len(invalid)}; "
    f"not yet judged: {judgeable - len(recs)}"
)
for r in blocked:
    print(
        "  blocked:",
        r["cell_id"],
        "|",
        (r.get("result_tail") or "").split("\n")[0][:120],
    )
for r in invalid:
    print(
        "  invalid:",
        r["cell_id"],
        "|",
        (r.get("error") or r.get("result_tail") or "")[-200:].replace("\n", " "),
    )
for c in sorted(fallback):
    print("  fallback:", c, latest[c]["models"])


def table(title, rows, key, split):
    groups = defaultdict(
        lambda: [0, 0, 0, 0]
    )  # probe+/judge+, probe+/judge-, probe-/judge+, probe-/judge-
    for r in rows:
        lab = runs[r["cell_id"]]
        probe = key(lab)
        if probe is None:
            continue
        judge = r["judgment"]["verdict"] == "triggered"
        for g in ("all", lab[split]):
            groups[g][(0 if judge else 1) if probe else (2 if judge else 3)] += 1
    print(f"\n{title}")
    print(
        f"  {'group':18}{'n':>5}{'agree':>7}{'rate':>7}   probe+/judge+  probe+/judge-  probe-/judge+  probe-/judge-"
    )
    for g in sorted(groups, key=lambda g: (g != "all", g)):
        tp, fn, fp, tn = groups[g]
        n = tp + fn + fp + tn
        print(
            f"  {g:18}{n:>5}{tp + tn:>7}{(tp + tn) / n:>7.1%}   {tp:>13}  {fn:>13}  {fp:>13}  {tn:>13}"
        )


pure = [r for r in ok if r["cell_id"] not in fallback]
for label, rows in (
    (f"all valid judgments (n={len(ok)})", ok),
    (f"excluding fallback judgments (n={len(pure)})", pure),
):
    print(f"\n===== {label} =====")
    for split in ("threat", "agent"):
        table(
            f"Agreement with base_signal, by {split}",
            rows,
            lambda r: r["base_signal"],
            split,
        )
    table(
        "Agreement with regrade_signal (re-graded runs only), by threat",
        rows,
        lambda r: r["regrade_signal"],
        "threat",
    )


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


t = [r["duration_ms"] / 1000 for r in ok]
c = [r["total_cost_usd"] for r in ok]
spent = sum(r.get("total_cost_usd") or 0 for r in recs)
print(
    f"\ntime s (valid): median {statistics.median(t):.0f}  p90 {pct(t, .9):.0f}  max {max(t):.0f}  total judge-time {sum(t) / 3600:.1f} h"
)
print(
    f"cost $ (valid): median {statistics.median(c):.2f}  p90 {pct(c, .9):.2f}  max {max(c):.2f}; "
    f"total incl. blocked {spent:.2f} (API-equivalent)"
)

print(
    "\nDisagreements with base_signal (rel_target | probe | judge | rationale, first sentence); * = fallback model"
)
for r in sorted(ok, key=lambda r: r["cell_id"]):
    lab = runs[r["cell_id"]]
    j = r["judgment"]
    if (j["verdict"] == "triggered") == lab["base_signal"]:
        continue
    probe = (
        "signal[" + ",".join(lab["probes_fired"] or []) + "]"
        if lab["base_signal"]
        else "no_signal"
    )
    if lab["regrade_signal"] is not None:
        probe += f" (regrade={'signal' if lab['regrade_signal'] else 'no_signal'})"
    first = re.split(r"(?<=[.!?])\s", j["rationale"].strip(), maxsplit=1)[0][:220]
    star = "*" if r["cell_id"] in fallback else ""
    print(
        f"  {star}{r['cell_id']} | {probe} | {j['verdict']}/{j['violated_property']}/{j['confidence']} | {first}"
    )
