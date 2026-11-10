#!/usr/bin/env python3
"""Static LLM-judge baseline: Claude Code headless judges each exploit cell.

The judge workdir holds only exploit/ (the cell's files) and app_source/ (the
pinned app source, no .git). Labels from index.csv are used only to choose
pilot cells and are never written into the workdir or prompt.

  run_judge.py select-pilot --out pilot_cells.txt
  run_judge.py run --cells pilot_cells.txt --out results.jsonl [--repeats 1]
  run_judge.py select-paper --out paper_runs.jsonl
  run_judge.py run --runs paper_runs.jsonl --out results.jsonl --jobs 5
"""
import argparse
import csv
import json
import random
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The corpus is untracked, so it lives only in the main checkout; read-only.
CORPUS = Path(
    "/Users/joey/VScode/Cyber/Mobilebench-all/mobilecybench/paper_planning/exploit_corpus"
)
SCRATCH = Path(
    "/private/tmp/claude-501/-Users-joey-VScode-Cyber-Mobilebench-all-mobilecybench/"
    "a4cbb44a-6121-41ec-97f2-1b5385b37587/scratchpad/llm_judge"
)
MODEL = "claude-opus-5-5"
SCORED = {"TRIGGERED", "DELIVERED-BUT-UNSCORED"}
# Original paper runs, all 5 models; read-only.
PAPER_RUNS = Path(
    "/Users/joey/VScode/Cyber/Mobilebench-all/mobilecybench/organized_all"
)
# Kept out of the judge's exploit/: agent writeups and build outputs.
EXCLUDE_EXT = {".md", ".pyc", ".class", ".jar", ".pid", ".keystore", ".apk"}
PROPERTIES = {"confidentiality", "integrity", "access_control", "availability"}


def load_index():
    with open(CORPUS / "index.csv") as f:
        return {r["cell_id"]: r for r in csv.DictReader(f)}


def select_pilot(args):
    """One cell per (threat, model, triggered?) stratum = 20 cells, spreading apps and visibility."""
    rows = [r for r in load_index().values() if r["outcome"] in SCORED]
    rng = random.Random(args.seed)
    strata = sorted(
        {(r["threat"], r["model"], r["outcome"] == "TRIGGERED") for r in rows}
    )
    rng.shuffle(strata)
    apps, vis, picked = Counter(), Counter(), []
    for threat, model, trig in strata:
        cands = [
            r
            for r in rows
            if (r["threat"], r["model"], r["outcome"] == "TRIGGERED")
            == (threat, model, trig)
        ]
        rng.shuffle(cands)
        best = min(cands, key=lambda r: (apps[r["app"]], vis[r["visibility"]]))
        apps[best["app"]] += 1
        vis[best["visibility"]] += 1
        picked.append(best["cell_id"])
    Path(args.out).write_text("\n".join(picked) + "\n")
    print(
        f"{len(picked)} cells -> {args.out}; apps={dict(apps)}; visibility={dict(vis)}"
    )


def select_paper(args):
    """The paper's 441 scored runs with an exploit: base_signal True, or untriggered with
    auth_status no_signal/not_triggered. Exploit copy: _regrade/agent_exploit if present (its
    replay status equals the paper's auth_status in every such run), else agent_exploit,
    else original/agent_exploit. Runs with no copy are written with exploit_dir null."""
    rows = list(csv.DictReader(open(PAPER_RUNS / "MANIFEST.csv")))
    sel = [
        r
        for r in rows
        if r["base_signal"] == "True"
        or r["auth_status"] in ("no_signal", "not_triggered")
    ]
    n_missing = 0
    with open(args.out, "w") as f:
        for r in sel:
            d = PAPER_RUNS / r["rel_target"]
            ex = next(
                (
                    d / s
                    for s in (
                        "_regrade/agent_exploit",
                        "agent_exploit",
                        "original/agent_exploit",
                    )
                    if (d / s).is_dir()
                ),
                None,
            )
            src = ex.parent if ex else None
            try:
                rs = json.load(open(src / "redteam_scores.json"))
                fired = sorted(
                    k
                    for grp in ("app_specific", "generic")
                    for k, v in rs["probe_results"]["probe"].get(grp, {}).items()
                    if v.get("triggered")
                )
                rs_status = rs.get("status")
            except Exception:
                fired, rs_status = None, None
            n_missing += ex is None
            f.write(
                json.dumps(
                    {
                        "cell_id": r["rel_target"],
                        "app": r["app"],
                        "threat": r["attack_setting"],
                        "visibility": r["visibility"],
                        "exploit_dir": str(ex) if ex else None,
                        # labels: scoring only, never shown to the judge
                        "agent": r["agent"],
                        "auth_status": r["auth_status"],
                        "base_signal": r["base_signal"] == "True",
                        "regrade_signal": {"True": True, "False": False}.get(
                            r["regrade_signal"]
                        ),
                        "copy_status": rs_status,
                        "probes_fired": fired,
                    }
                )
                + "\n"
            )
    print(
        f"{len(sel)} runs ({sum(r['base_signal'] == 'True' for r in sel)} triggered) -> {args.out}; {n_missing} without any exploit copy"
    )


def build_prompt(row):
    tm = json.loads((HERE / "threat_models.json").read_text())
    return (
        (HERE / "prompt_template.md")
        .read_text()
        .replace("{threat_model}", tm["threat"][row["threat"]])
        .replace("{visibility_text}", tm["visibility"][row["visibility"]])
    )


def make_workdir(row, work_root):
    wd = work_root / uuid.uuid4().hex[:12]
    wd.mkdir(parents=True)
    shutil.copytree(
        row["exploit_dir"],
        wd / "exploit",
        ignore=lambda d, names: [
            n for n in names if n == "__pycache__" or Path(n).suffix in EXCLUDE_EXT
        ],
    )
    # APFS clone copy: instant, no extra disk.
    subprocess.run(
        ["cp", "-cR", str(SCRATCH / "sources" / row["app"]), str(wd / "app_source")],
        check=True,
    )
    return wd


def parse_verdict(text):
    for m in reversed(list(re.finditer(r"\{\s*\"verdict\"", text))):
        try:
            v, _ = json.JSONDecoder().raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        ok = (
            v.get("verdict") in ("triggered", "not_triggered")
            and (
                v.get("violated_property") in PROPERTIES
                or v.get("violated_property") is None
            )
            and isinstance(v.get("confidence"), (int, float))
            and 0 <= v["confidence"] <= 1
            and isinstance(v.get("rationale"), str)
        )
        return v, ok
    return None, False


STOP = threading.Event()


def is_blocked(rec):
    """A hard safety refusal ('[cyber]'): recorded and skipped, never retried, run continues."""
    return bool(rec.get("is_error")) and "[cyber]" in (rec.get("result_tail") or "")


def judge(row, repeat, work_root, keep):
    if STOP.is_set():
        return {
            "cell_id": row["cell_id"],
            "repeat": repeat,
            "skipped": "stopped after an earlier error",
        }
    wd = make_workdir(row, work_root)
    cmd = [
        "claude",
        "-p",
        build_prompt(row),
        "--model",
        MODEL,
        "--output-format",
        "json",
        "--tools",
        "Read,Grep,Glob",
        "--permission-mode",
        "dontAsk",  # reads outside the workdir are denied
        "--setting-sources",
        "",  # no user/project settings, hooks, or plugins
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--max-budget-usd",
        "10",
    ]
    t0 = time.time()
    p = subprocess.run(
        cmd,
        cwd=wd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    wall = time.time() - t0
    rec = {
        "cell_id": row["cell_id"],
        "repeat": repeat,
        "workdir": str(wd),
        "wall_s": round(wall, 1),
        "exit": p.returncode,
    }
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        rec["error"] = (p.stdout + p.stderr)[-2000:]
        STOP.set()  # e.g. a usage limit: stop launching, do not retry
        return rec
    verdict, ok = parse_verdict(out.get("result") or "")
    rec.update(
        judgment=verdict,
        schema_valid=ok,
        duration_ms=out.get("duration_ms"),
        total_cost_usd=out.get("total_cost_usd"),
        num_turns=out.get("num_turns"),
        models=list((out.get("modelUsage") or {}).keys()),
        is_error=out.get("is_error"),
        usage=out.get("usage"),
    )
    if not ok:
        rec["result_tail"] = (out.get("result") or "")[-2000:]
    if is_blocked(rec):
        rec["status"] = "blocked"
    elif out.get("is_error"):
        STOP.set()  # usage/rate limits and other API errors pause the run
    if not keep:
        shutil.rmtree(wd, ignore_errors=True)
    return rec


def run(args):
    if args.runs:
        rows = [json.loads(line) for line in open(args.runs)]
        rows = [r for r in rows if r["exploit_dir"]]
    else:
        idx = load_index()
        rows = [idx[c] for c in Path(args.cells).read_text().split("\n") if c.strip()]
        for r in rows:
            r["exploit_dir"] = str(CORPUS / r["dir"])
    if args.skip_done:
        done = {
            r["cell_id"]
            for r in map(json.loads, open(args.skip_done))
            if r.get("schema_valid") or is_blocked(r)
        }
        print(
            f"skipping {sum(r['cell_id'] in done for r in rows)} runs already judged or blocked in {args.skip_done}"
        )
        rows = [r for r in rows if r["cell_id"] not in done]
    jobs = [(row, r) for row in rows for r in range(args.repeats)]
    work_root = SCRATCH / "work"
    version = subprocess.run(
        ["claude", "--version"], capture_output=True, text=True
    ).stdout.strip()
    with open(args.out, "a") as f, ThreadPoolExecutor(args.jobs) as ex:
        futs = [ex.submit(judge, row, r, work_root, args.keep) for row, r in jobs]
        for fu in as_completed(futs):
            rec = fu.result()
            rec.update(model=MODEL, claude_code=version)
            f.write(json.dumps(rec) + "\n")
            f.flush()
            j = rec.get("judgment") or {}
            print(
                rec["cell_id"],
                rec.get("schema_valid"),
                j.get("verdict"),
                rec.get("duration_ms"),
                rec.get("total_cost_usd"),
                rec.get("skipped") or rec.get("error", "")[:200],
                flush=True,
            )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(required=True)
    s = sub.add_parser("select-pilot")
    s.add_argument("--out", required=True)
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(fn=select_pilot)
    r = sub.add_parser("run")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--cells")
    g.add_argument("--runs")
    r.add_argument("--out", required=True)
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--jobs", type=int, default=4)
    r.add_argument("--keep", action="store_true", help="keep judge workdirs")
    r.add_argument(
        "--skip-done",
        help="results jsonl; skip runs with a schema-valid or blocked record",
    )
    r.set_defaults(fn=run)
    p = sub.add_parser("select-paper")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=select_paper)
    a = ap.parse_args()
    a.fn(a)
