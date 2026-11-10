"""Jobs for the matched source-with-APK ablation.

Usage: make_jobs_aps.py <grid_tree> <model> <out_dir> [arms] [build_type]
  arms: "aps" (APK-plus-source only, default) or "aps,apk" (also a fresh APK-only
        run of each cell, interleaved so a partial pass still gives matched pairs).
Both arms are the existing APK-only cells (obfuscated APK, restricted network);
the APK-plus-source arm adds only source_with_apk: true.
"""
import json, sys
from pathlib import Path
root, model, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
arms = (sys.argv[4] if len(sys.argv) > 4 else "aps").split(",")
build_type = sys.argv[5] if len(sys.argv) > 5 else None
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(root))
import batch_runner
from models.config import BatchSpec

def expand(name):
    payload = json.loads((root / name).read_text())
    batch = BatchSpec.model_validate(payload.pop("batch"))
    payload["model"] = model
    if build_type: payload["build_type"] = build_type   # VMs: skip-apk, APKs pre-staged
    # Non-Claude agents: the paper grid's image and effort for that agent, e.g.
    # AGENT_IMAGE=cybench/mobilecybench:opencode_1.15.6-r1 REASONING_EFFORT=xhigh for GPT-5.6-Sol.
    import os
    if os.environ.get("AGENT_IMAGE"): payload["agent_image"] = os.environ["AGENT_IMAGE"]
    if os.environ.get("REASONING_EFFORT"): payload["reasoning_effort"] = os.environ["REASONING_EFFORT"]
    return batch_runner.expand_batch_jobs(payload, batch, root)

aps = {(j.app_name, j.config.attacker_model): j for j in expand("runner_config_batch_apk_plus_source.json")}
apk = {(j.app_name, j.config.attacker_model): j for j in expand("runner_config_batch.json") if j.config.no_codebase}
assert set(aps) == set(apk) and len(aps) == 25, (len(aps), len(apk))
lst, n = [], 0
for key in sorted(aps, key=lambda k: aps[k].index):
    for arm in arms:
        j = (aps if arm == "aps" else apk)[key]
        c = j.config.model_dump(mode="json")
        assert c["no_codebase"] and c["apk_obfuscation"] == "on" and c["network_mode"] == "restricted"
        assert c["source_with_apk"] == (arm == "aps")
        n += 1
        name = f"{n:02d}__{model.replace('/', '-')}__{'apk_plus_source' if arm == 'aps' else 'apk_only'}__{c['attacker_model']}__{j.app_name}"
        (out / f"{name}.json").write_text(json.dumps(c, indent=2))
        lst.append(f"{name} {j.app_name}")
(out / "jobs.txt").write_text("\n".join(lst) + "\n")
print(len(lst), "jobs ->", out)
