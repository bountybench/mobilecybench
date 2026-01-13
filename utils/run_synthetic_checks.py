#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path


def _last_json_line(text: str) -> dict | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def _coerce_score(payload: dict) -> int:
    raw = payload.get("score", None)
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, (int, float)):
        return 1 if int(raw) == 1 else 0

    numeric = [
        v
        for k, v in payload.items()
        if k != "score" and isinstance(v, (bool, int, float))
    ]
    if numeric:
        return 1 if all(int(v) == 1 for v in numeric) else 0
    return 0


def discover_synthetic_probes(app_dir: Path) -> list[Path]:
    probes: list[Path] = []

    synth_dir = app_dir / "synthetic_vulnerabilities"
    if synth_dir.is_dir():
        probes.extend(
            sorted(
                p
                for p in synth_dir.glob("*/test_synthetic.py")
                if p.is_file()
            )
        )

    # De-dupe while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in probes:
        rp = p.resolve()
        if rp not in seen:
            out.append(p)
            seen.add(rp)
    return out


def _derive_vuln_key(app_dir: Path, probe: Path) -> str:
    try:
        rel = probe.relative_to(app_dir)
    except Exception:
        rel = probe

    if len(rel.parts) >= 2 and rel.parts[0] == "synthetic_vulnerabilities":
        return rel.parts[1]
    return rel.as_posix()


def run_synthetic_checks(app_dir: Path, exploit_log: Path | None = None) -> dict:
    probes = discover_synthetic_probes(app_dir)
    if not probes:
        return {"status": "no_probes_found", "scores": {}, "details": {}}

    scores: dict[str, int] = {}
    details: dict[str, dict] = {}

    for probe in probes:
        key = _derive_vuln_key(app_dir, probe)
        if key in scores:
            suffix = 2
            while f"{key}__{suffix}" in scores:
                suffix += 1
            key = f"{key}__{suffix}"

        cmd = [sys.executable, str(probe)]
        if exploit_log:
            cmd.append(str(exploit_log))

        proc = subprocess.run(cmd, cwd=app_dir, capture_output=True, text=True)
        payload = _last_json_line(proc.stdout or "")
        if proc.returncode != 0 or not isinstance(payload, dict):
            scores[key] = 0
            details[key] = {"score": 0}
            continue

        if "score" not in payload:
            scores[key] = 0
            payload = dict(payload)
            payload["score"] = 0
            details[key] = payload
            continue

        score = _coerce_score(payload)
        payload = dict(payload)
        payload["score"] = score
        scores[key] = score
        details[key] = payload

    return {"status": "ok", "scores": scores, "details": details}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run synthetic vulnerability checks")
    parser.add_argument("--app", required=True, help="Path to app directory")
    parser.add_argument("--log", default=None, help="Path to agent/exploit log")
    args = parser.parse_args(argv)

    app_dir = Path(args.app).expanduser().resolve()
    exploit_log = Path(args.log).expanduser().resolve() if args.log else None
    if exploit_log is not None and not exploit_log.is_file():
        exploit_log = None

    try:
        result = run_synthetic_checks(app_dir, exploit_log=exploit_log)
    except Exception as e:
        print(json.dumps({"status": "error", "scores": {}, "details": {}}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
