#!/bin/bash
# run_pass2.sh <repo> <jobs_dir> <results.jsonl>
# Per-VM queue for the second Opus 5 source-into-APK pass (one emulator, sequential).
# Resumable: skips cells already marked valid in <results.jsonl>. Relaunch over the same
# jobs.txt until every cell has "valid": true. See README.md.
set -u
G=$1; J=$2; OUT=$3; LOG=${OUT%.jsonl}.log
touch "$OUT"
while read -r name app <&3; do
  [ -z "$name" ] && continue
  grep -q "\"job\": \"$name\".*\"valid\": true" "$OUT" && continue   # resumable
  m=$J/.start_$name; touch "$m"; t0=$(date +%s)
  (cd "$G" && timeout 10800 python runner.py "$app" --config "$J/$name.json" \
      > "$J/$name.stdout" 2>&1 < /dev/null)
  d=$(find "$G/logs" -maxdepth 1 -type d -name "${app}_redteam_*" -newer "$m" | sort | tail -1)
  python3 - "$name" "$d" "$t0" >> "$OUT" <<'PY'
import json, sys, os, time
name, d, t0 = sys.argv[1], sys.argv[2], float(sys.argv[3])
row = {"job": name, "rundir": d or None, "wall_s": round(time.time()-t0)}
valid = False
if d:
    try: valid = "Evaluation complete" in open(os.path.join(d,"experiment.log"),errors="ignore").read()
    except OSError: pass
    for f,keys in (("redteam_scores.json",("status","reason")),
                   ("run_summary.json",("outcome","agent_status","exit_reason","refusal"))):
        try: row.update({k:v for k,v in json.load(open(os.path.join(d,f))).items() if k in keys})
        except Exception: pass
    try: valid = valid and os.path.getmtime(os.path.join(d,"redteam_scores.json")) >= t0-5
    except Exception: valid = False
row["valid"] = valid
print(json.dumps(row))
PY
  docker ps -aq --filter label=mobilecybench | xargs -r docker rm -f >/dev/null 2>&1
done 3< "$J/jobs.txt"
