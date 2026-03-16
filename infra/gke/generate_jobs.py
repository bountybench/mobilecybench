#!/usr/bin/env python3
"""
Generate K8s Job YAMLs for the MobileCyBench experiment matrix.

Scans apps/ for synthetic vulnerabilities, cross-products with the requested
models, and renders one Job YAML per (app, vuln, model) tuple.

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


def render_job(
    app_name: str,
    vuln_id: str,
    model: str,
    image_uri: str,
    gcs_bucket: str,
    emulator_backend: str,
    dry_run: bool = False,
    gold_run: bool = False,
) -> str:
    """Render a K8s Job YAML for a single experiment."""
    job_name = sanitize_k8s_name(f"mcb-{app_name}-{vuln_id}-{model}")

    return f"""apiVersion: batch/v1
kind: Job
metadata:
  name: {job_name}
  namespace: mobilecybench
  labels:
    app: mobilecybench
    experiment-app: "{app_name}"
    experiment-vuln: "{vuln_id}"
    experiment-model: "{sanitize_k8s_name(model)}"
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        app: mobilecybench
        experiment-app: "{app_name}"
    spec:
      restartPolicy: Never
      containers:
        - name: runner
          image: {image_uri}
          securityContext:
            privileged: true
          resources:
            requests:
              cpu: "2"
              memory: "8Gi"
            limits:
              cpu: "4"
              memory: "16Gi"
          env:
            - name: APP_NAME
              value: "{app_name}"
            - name: MODEL
              value: "{model}"
            - name: VULN_ID
              value: "{vuln_id}"
            - name: EMULATOR_BACKEND
              value: "{emulator_backend}"
            - name: GCS_BUCKET
              value: "{gcs_bucket}"
            - name: DRY_RUN
              value: "{'true' if dry_run else 'false'}"
            - name: GOLD_RUN
              value: "{'true' if gold_run else 'false'}"
            - name: RUN_ID
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
          envFrom:
            - secretRef:
                name: llm-api-keys
          volumeMounts:
            - name: dev-kvm
              mountPath: /dev/kvm
            - name: docker-storage
              mountPath: /var/lib/docker
      volumes:
        - name: dev-kvm
          hostPath:
            path: /dev/kvm
            type: CharDevice
        - name: docker-storage
          emptyDir: {{}}
"""


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
    parser.add_argument(
        "--dry-run", action="store_true", help="Set DRY_RUN=true in generated jobs"
    )
    parser.add_argument(
        "--gold-run",
        action="store_true",
        help="Set GOLD_RUN=true and DRY_RUN=false in generated jobs",
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
            dry_run = args.dry_run and not args.gold_run
            yaml_str = render_job(
                app_name=exp["app_name"],
                vuln_id=exp["vuln_id"],
                model=model,
                image_uri=args.image,
                gcs_bucket=args.gcs_bucket,
                emulator_backend=args.emulator_backend,
                dry_run=dry_run,
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
