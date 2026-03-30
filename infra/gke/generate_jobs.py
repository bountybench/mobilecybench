#!/usr/bin/env python3
"""
Generate K8s Job YAMLs for the MobileCyBench experiment matrix.

Scans apps/ for synthetic vulnerabilities, cross-products with the requested
models, and renders one Job YAML per (app, vuln, model) tuple using
job-template.yaml.

Usage:
    # Single app + model — print YAML
    python infra/gke/generate_jobs.py --apps moememos --models gpt-4o

    # Apply directly to the cluster
    python infra/gke/generate_jobs.py --apps moememos --models gpt-4o --apply

    # Full matrix (all apps × all vulns × multiple models)
    python infra/gke/generate_jobs.py --all --models gpt-4o claude-sonnet-4-5-20250929 --apply

    # Write YAMLs to a directory instead of stdout/apply
    python infra/gke/generate_jobs.py --all --models gpt-4o --outdir /tmp/jobs

    # Dry run (no LLM calls) or gold run (reference exploits)
    python infra/gke/generate_jobs.py --apps moememos --models gpt-4o --dry-run
    python infra/gke/generate_jobs.py --apps moememos --models gpt-4o --gold-run
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
    return name[:63].rstrip("-")


def load_template(template_path: Path) -> str:
    """Load the job-template.yaml file."""
    if not template_path.exists():
        print(f"ERROR: Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)
    return template_path.read_text()


def render_job(
    template: str,
    app_name: str,
    vuln_id: str,
    model: str,
    image_uri: str,
    gcs_bucket: str,
    emulator_backend: str,
    dry_run: bool,
    gold_run: bool,
) -> str:
    """Render a K8s Job YAML by substituting placeholders in the template."""
    job_name = sanitize_k8s_name(f"mcb-{app_name}-{vuln_id}-{model}")

    # Phase 1: replace structural placeholders (job name, image, full label lines).
    # These use unique strings that won't collide with env var name: fields.
    replacements = {
        "mcb-APP_NAME-VULN_ID-MODEL": job_name,
        "IMAGE_URI": image_uri,
    }

    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)

    # Phase 2: replace quoted env value placeholders only — avoids clobbering
    # env var *name* fields which share the same identifier strings.
    env_replacements = {
        '"APP_NAME"': f'"{app_name}"',
        '"MODEL"': f'"{model}"',
        '"VULN_ID"': f'"{vuln_id}"',
        '"EMULATOR_BACKEND"': f'"{emulator_backend}"',
        '"DRY_RUN"': f'"{str(dry_run).lower()}"',
        '"GOLD_RUN"': f'"{str(gold_run).lower()}"',
        '"GCS_BUCKET"': f'"{gcs_bucket}"',
    }
    for placeholder, value in env_replacements.items():
        rendered = rendered.replace(placeholder, value)

    # Replace label values
    rendered = rendered.replace(
        "experiment-app: APP_NAME", f'experiment-app: "{app_name}"'
    )
    rendered = rendered.replace(
        "experiment-vuln: VULN_ID", f'experiment-vuln: "{vuln_id}"'
    )
    rendered = rendered.replace(
        "experiment-model: MODEL", f'experiment-model: "{sanitize_k8s_name(model)}"'
    )

    # Remove the header comment lines from the template (lines before the YAML doc)
    lines = rendered.split("\n")
    filtered = []
    header_done = False
    for line in lines:
        if not header_done and line.startswith("# "):
            continue
        header_done = True
        filtered.append(line)
    rendered = "\n".join(filtered)

    return rendered


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
            "us-central1-docker.pkg.dev/PROJECT_ID/mobilecybench/runner:latest",
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
    run_mode = parser.add_mutually_exclusive_group()
    run_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate jobs with dry_run=true (no LLM calls)",
    )
    run_mode.add_argument(
        "--gold-run",
        action="store_true",
        help="Generate jobs with gold_run=true (run reference exploits)",
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
                dry_run=args.dry_run,
                gold_run=args.gold_run,
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
