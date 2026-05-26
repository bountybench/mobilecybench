#!/usr/bin/env python3
"""
Collect and aggregate MobileCyBench experiment results from GCS.

Downloads experiment logs from GCS and produces a summary CSV.

Usage:
    python infra/gke/collect_results.py --bucket my-bucket --outdir ./results
    python infra/gke/collect_results.py --bucket my-bucket --csv results.csv
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def list_gcs_experiments(bucket: str) -> list[str]:
    """List experiment result prefixes in the GCS bucket."""
    result = subprocess.run(
        ["gsutil", "ls", f"gs://{bucket}/"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error listing bucket: {result.stderr}", file=sys.stderr)
        return []

    # Parse top-level prefixes (app names)
    prefixes = []
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            prefixes.append(line.strip())
    return prefixes


def download_results(bucket: str, outdir: Path) -> Path:
    """Download all results from GCS to local directory."""
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading results from gs://{bucket}/ to {outdir}/...")

    result = subprocess.run(
        ["gsutil", "-m", "cp", "-r", f"gs://{bucket}/*", str(outdir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Warning: gsutil returned non-zero: {result.stderr}", file=sys.stderr)

    return outdir


def parse_experiment_dir(exp_dir: Path) -> dict | None:
    """Parse a single experiment directory for results."""
    # Look for experiment log files
    result = {
        "app_name": "",
        "vuln_id": "",
        "model": "",
        "status": "unknown",
        "score": "",
        "turns": "",
        "error": "",
    }

    # Try to extract metadata from directory path: app/vuln/model/run_id/
    parts = (
        list(exp_dir.relative_to(exp_dir.parents[3]).parts)
        if len(exp_dir.parts) > 3
        else []
    )
    if len(parts) >= 3:
        result["app_name"] = parts[0]
        result["vuln_id"] = parts[1]
        result["model"] = parts[2]

    # Look for experiment_config.json or scores
    for json_file in exp_dir.rglob("*.json"):
        try:
            data = json.loads(json_file.read_text())

            if "scores" in data:
                result["score"] = json.dumps(data["scores"])
                result["status"] = "completed"

            if "status" in data:
                result["status"] = data["status"]

            if "turns" in data:
                result["turns"] = str(data["turns"])

            if "error" in data:
                result["error"] = data["error"]

            # Extract from experiment config
            if "app" in data and "name" in data["app"]:
                result["app_name"] = data["app"]["name"]
            if "runner" in data and "model" in data["runner"]:
                result["model"] = data["runner"]["model"]
            if "exploit" in data and "vuln_id" in data["exploit"]:
                result["vuln_id"] = data["exploit"]["vuln_id"]

        except (json.JSONDecodeError, KeyError):
            continue

    return result if result["app_name"] else None


def aggregate_results(results_dir: Path) -> list[dict]:
    """Walk the results directory and aggregate all experiment results.

    Gold runs (dirs ending in ``_gold``, see utils/logger.py) are excluded:
    they score 1.0 by construction and would inflate pass-rate metrics.
    """
    results = []
    skipped_gold = 0

    # Content-based detection: any directory with run_summary.json is a run dir.
    # Decouples this collector from the runner's directory-naming convention,
    # so the name can change without touching the GKE pipeline.
    for summary in sorted(results_dir.rglob("run_summary.json")):
        exp_dir = summary.parent
        if exp_dir.name.endswith("_gold") or exp_dir.parent.name == "gold":
            skipped_gold += 1
            continue
        parsed = parse_experiment_dir(exp_dir)
        if parsed:
            results.append(parsed)

    if skipped_gold:
        print(f"Skipped {skipped_gold} gold run dir(s)", file=sys.stderr)

    return results


def write_csv(results: list[dict], csv_path: Path):
    """Write aggregated results to CSV."""
    if not results:
        print("No results to write.", file=sys.stderr)
        return

    fieldnames = ["app_name", "vuln_id", "model", "status", "score", "turns", "error"]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"Wrote {len(results)} results to {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Collect MobileCyBench results from GCS"
    )
    parser.add_argument("--bucket", required=True, help="GCS bucket name")
    parser.add_argument(
        "--outdir",
        default=None,
        help="Local directory to download results to (default: temp dir)",
    )
    parser.add_argument(
        "--csv", default="results.csv", help="Output CSV path (default: results.csv)"
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip GCS download, use existing --outdir",
    )

    args = parser.parse_args()

    if args.outdir:
        results_dir = Path(args.outdir)
    else:
        results_dir = Path(tempfile.mkdtemp(prefix="mcb-results-"))

    if not args.skip_download:
        download_results(args.bucket, results_dir)

    results = aggregate_results(results_dir)

    if not results:
        print("No experiment results found.", file=sys.stderr)
        return 1

    # Print summary table
    print(f"\n{'App':<25} {'Vuln':<10} {'Model':<30} {'Status':<12} {'Score'}")
    print("-" * 90)
    for r in results:
        print(
            f"{r['app_name']:<25} {r['vuln_id']:<10} {r['model']:<30} "
            f"{r['status']:<12} {r.get('score', '')}"
        )

    write_csv(results, Path(args.csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
