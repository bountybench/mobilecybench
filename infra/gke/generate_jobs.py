#!/usr/bin/env python3
"""
Generate K8s Job YAMLs for the MobileCyBench experiment matrix.

Scans apps/ for synthetic vulnerabilities, cross-products with the requested
models, and renders one Job YAML per (app, vuln, model) tuple.

Uses job-template.yaml as the single source of truth for the Job spec.

Usage:
    # Single app + model — print YAML
    python infra/gke/generate_jobs.py --apps moememos --models gpt-4o

    # Apply directly to the cluster
    python infra/gke/generate_jobs.py --apps moememos --models gpt-4o --apply

    # Full matrix (all apps × all vulns × multiple models)
    python infra/gke/generate_jobs.py --all --models gpt-4o claude-sonnet-4-5-20250929 --apply

    # Write YAMLs to a directory instead of stdout/apply
    python infra/gke/generate_jobs.py --all --models gpt-4o --outdir /tmp/jobs
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def discover_experiments(apps_dir: Path, app_filter: list[str] | None) -> list[dict]:
    """Scan apps/ for (app_name, vuln_id) pairs with synthetic vulnerabilities."""
    experiments = []
    for app_dir in sorted(apps_dir.iterdir()):
        if not app_dir.is_dir() or app_dir.name.startswith(("_", ".")):
            continue
        if app_filter and app_dir.name not in app_filter:
            continue

        synth_dir = app_dir / "synthetic_vulnerabilities"
        if not synth_dir.exists():
            continue

        for vuln_dir in sorted(synth_dir.iterdir()):
            if not vuln_dir.is_dir() or vuln_dir.name.startswith("."):
                continue
            # Verify it has required files
            if (vuln_dir / "verify_files").exists():
                experiments.append({"app_name": app_dir.name, "vuln_id": vuln_dir.name})

    return experiments


def sanitize_k8s_name(name: str) -> str:
    """Convert a string to a valid K8s resource name."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:63]


def load_template(template_path: Path) -> str:
    """Load the job template YAML, stripping comment lines."""
    lines = template_path.read_text().splitlines()
    cleaned = []
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        # Strip inline comments (e.g., "value  # comment")
        if "  #" in line:
            line = line[: line.index("  #")]
        cleaned.append(line)
    return "\n".join(cleaned)


def render_job(
    template: str,
    app_name: str,
    vuln_id: str,
    model: str,
    image_uri: str,
    gcs_bucket: str,
    emulator_backend: str,
) -> str:
    """Render a Job YAML by substituting placeholders in the template."""
    job_name = sanitize_k8s_name(f"mcb-{app_name}-{vuln_id}-{model}")

    replacements = {
        "mcb-APP_NAME-VULN_ID-MODEL": job_name,
        "IMAGE_URI": image_uri,
    }

    result = template
    for old, new in replacements.items():
        result = result.replace(old, new)

    # Replace placeholder values in env and labels.
    # Use word-boundary-aware replacement to avoid partial matches.
    # The template uses bare APP_NAME, MODEL, etc. as placeholder values.
    env_replacements = [
        ("EMULATOR_BACKEND", emulator_backend),
        ("GCS_BUCKET", gcs_bucket),
        ("APP_NAME", app_name),
        ("VULN_ID", vuln_id),
        ("MODEL", model),
    ]
    for placeholder, value in env_replacements:
        # Replace quoted placeholder values: "PLACEHOLDER" -> "value"
        result = result.replace(f'"{placeholder}"', f'"{value}"')
        # Replace unquoted placeholder values in labels: PLACEHOLDER -> "value"
        # Match lines like `    experiment-app: APP_NAME`
        result = re.sub(
            rf"^(\s+experiment-\w+:\s*){placeholder}\s*$",
            rf'\1"{value}"',
            result,
            flags=re.MULTILINE,
        )

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate K8s Job YAMLs for MobileCyBench experiments"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--apps", nargs="+", help="App names to include (e.g., moememos bitwarden)"
    )
    group.add_argument(
        "--all", action="store_true", help="Include all apps with synthetic vulns"
    )

    parser.add_argument(
        "--models", nargs="+", required=True, help="Model names (e.g., gpt-4o)"
    )
    parser.add_argument(
        "--image",
        default=os.environ.get(
            "RUNNER_IMAGE",
            "cybench/mobilecybench-runner:latest",
        ),
        help="Docker image URI for the runner",
    )
    parser.add_argument(
        "--gcs-bucket",
        default=os.environ.get("GCS_BUCKET", ""),
        help="GCS bucket for result uploads",
    )
    parser.add_argument(
        "--emulator-backend",
        default="container",
        choices=["native", "container"],
        help="Emulator backend (default: container)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply jobs to cluster via kubectl"
    )
    parser.add_argument(
        "--outdir", help="Write individual YAML files to this directory"
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    apps_dir = project_root / "apps"
    template_path = Path(__file__).resolve().parent / "job-template.yaml"

    if not template_path.exists():
        print(f"ERROR: Template not found: {template_path}", file=sys.stderr)
        return 1

    template = load_template(template_path)

    app_filter = None if args.all else args.apps
    experiments = discover_experiments(apps_dir, app_filter)

    if not experiments:
        print(
            "No experiments found. Check that apps have synthetic_vulnerabilities/",
            file=sys.stderr,
        )
        return 1

    if args.outdir:
        Path(args.outdir).mkdir(parents=True, exist_ok=True)

    all_yamls = []
    for exp in experiments:
        for model in args.models:
            yaml_str = render_job(
                template=template,
                app_name=exp["app_name"],
                vuln_id=exp["vuln_id"],
                model=model,
                image_uri=args.image,
                gcs_bucket=args.gcs_bucket,
                emulator_backend=args.emulator_backend,
            )
            all_yamls.append(yaml_str)

            if args.outdir:
                fname = sanitize_k8s_name(
                    f"mcb-{exp['app_name']}-{exp['vuln_id']}-{model}"
                )
                outpath = Path(args.outdir) / f"{fname}.yaml"
                outpath.write_text(yaml_str)

    combined = "---\n".join(all_yamls)

    if args.apply:
        # Ensure the image-cache DaemonSet is deployed before submitting jobs.
        # Idempotent — kubectl apply is a no-op if it's already running.
        daemonset_path = Path(__file__).resolve().parent / "daemonset-image-cache.yaml"
        if daemonset_path.exists():
            print("Ensuring image-cache DaemonSet is deployed...", file=sys.stderr)
            ds_result = subprocess.run(
                ["kubectl", "apply", "-f", str(daemonset_path)],
                capture_output=True,
                text=True,
            )
            if ds_result.returncode == 0:
                print(
                    f"  {ds_result.stdout.strip()}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"  WARNING: Failed to apply DaemonSet: {ds_result.stderr.strip()}",
                    file=sys.stderr,
                )
        else:
            print(
                f"WARNING: DaemonSet not found at {daemonset_path}, skipping",
                file=sys.stderr,
            )

        print(f"Applying {len(all_yamls)} jobs to cluster...", file=sys.stderr)
        result = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=combined,
            text=True,
            capture_output=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            return 1
        print(
            f"Successfully submitted {len(all_yamls)} experiment jobs.",
            file=sys.stderr,
        )
    elif not args.outdir:
        print(combined)

    if args.outdir:
        print(
            f"Wrote {len(all_yamls)} job YAMLs to {args.outdir}/",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
