#!/usr/bin/env python3
"""Agreement of judge verdicts with probe `signal`, time/cost stats, full-run projection.

  summarize.py results.jsonl [--full-cells 386 --repeats 3 --jobs 5]
"""
import argparse
import csv
import json
import statistics
from pathlib import Path

INDEX = Path(
    "/Users/joey/VScode/Cyber/Mobilebench-all/mobilecybench/paper_planning/exploit_corpus/index.csv"
)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


ap = argparse.ArgumentParser()
ap.add_argument("results")
ap.add_argument("--full-cells", type=int, default=386)
ap.add_argument("--repeats", type=int, default=3)
ap.add_argument("--jobs", type=int, default=5)
a = ap.parse_args()

idx = {r["cell_id"]: r for r in csv.DictReader(open(INDEX))}
recs = [json.loads(line) for line in open(a.results)]
ok = [r for r in recs if r.get("schema_valid")]
print(
    f"judgments: {len(recs)}  schema-valid: {len(ok)}  failed: {[r['cell_id'] for r in recs if not r.get('schema_valid')]}"
)

cm = {(p, j): 0 for p in (True, False) for j in ("triggered", "not_triggered")}
rows = []
for r in ok:
    row = idx[r["cell_id"]]
    probe = row["signal"] == "True"
    j = r["judgment"]
    cm[(probe, j["verdict"])] += 1
    rows.append(
        (
            r["cell_id"],
            row["outcome"],
            row["probes_fired"],
            j["verdict"],
            j["violated_property"],
            j["confidence"],
            r["duration_ms"] / 1000,
            r["total_cost_usd"],
        )
    )

print("\nAgreement with probes (rows = probe signal, cols = judge verdict)")
print(f"{'':18}{'judge triggered':>17}{'judge not_trig':>16}")
for p in (True, False):
    print(
        f"{'probe ' + ('signal' if p else 'no signal'):18}{cm[(p, 'triggered')]:>17}{cm[(p, 'not_triggered')]:>16}"
    )
agree = cm[(True, "triggered")] + cm[(False, "not_triggered")]
print(f"agreement {agree}/{len(ok)}")

print("\nper cell:")
for x in sorted(rows):
    print(
        f"  {x[0]:55} {x[1]:23} probes={x[2] or '-':28} judge={x[3]:13} {str(x[4]):16} conf={x[5]:.2f} {x[6]:6.0f}s ${x[7]:.2f}"
    )

t = [r["duration_ms"] / 1000 for r in ok]
c = [r["total_cost_usd"] for r in ok]
print(
    f"\ntime s: median {statistics.median(t):.0f}  p90 {pct(t, .9):.0f}  mean {statistics.mean(t):.0f}  max {max(t):.0f}"
)
print(
    f"cost $: median {statistics.median(c):.2f}  p90 {pct(c, .9):.2f}  mean {statistics.mean(c):.2f}  max {max(c):.2f}  pilot total {sum(c):.2f}"
)
n = a.full_cells * a.repeats
print(f"\nprojection {a.full_cells} cells x {a.repeats} repeats = {n} judgments:")
print(
    f"  cost: ${n * statistics.mean(c):,.0f} (mean-based); ${n * pct(c, .9):,.0f} if every judgment cost the pilot p90"
)
print(
    f"  wall-clock at {a.jobs} parallel: {n * statistics.mean(t) / a.jobs / 3600:.1f} h; serial judge-time {n * statistics.mean(t) / 3600:.1f} h"
)
