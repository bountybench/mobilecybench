#!/usr/bin/env python3
"""
Generate K8s Job YAMLs for the MobileCyBench experiment matrix.

Two modes, selected by whether ``--agent-image`` is given:

1. Legacy synthetic-vuln path (no ``--agent-image``): scans apps/ for synthetic
   vulnerabilities and renders one Job per (app, vuln, model) tuple. Requires
   ``--models``.

2. External-agent path (``--agent-image``): runs a BYO coding-agent image
   (agent_mode=external) over the redteam workflow. Renders one Job per
   (app, attacker_model, no_codebase leg) tuple; ``--models`` is optional (the
   image carries the model, but a passed model is still plumbed through for
   labeling / runner_config.model). synthetic_vuln_id / VULN_ID are unused.

Usage:
    # Legacy: single app + model — print YAML
    python infra/gke/generate_jobs.py --apps moememos --models gpt-4o

    # Legacy: full matrix (all apps × all vulns × multiple models)
    python infra/gke/generate_jobs.py --all --models gpt-4o claude-sonnet-4-5-20250929 --apply

    # External agent, probe-only redteam, both attacker models, source-vs-APK ablation
    python infra/gke/generate_jobs.py \\
        --apps conversations \\
        --agent-image cybench/mobilecybench:opencode_1.15.6-r1 \\
        --probe-only --attacker-models malicious_app remote_attacker \\
        --no-codebase-ablation --gcs-bucket $BUCKET --apply

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


def discover_apps(apps_dir: Path, app_filter: list[str] | None) -> list[str]:
    """Return app names for the external-agent path (no synthetic-vuln scan).

    The external path does not need a synthetic vulnerability — it runs the
    redteam workflow against the app's baseline. ``--all`` lists every app
    directory; ``--apps`` validates the requested names exist on disk.
    """
    available = sorted(
        d.name
        for d in apps_dir.iterdir()
        if d.is_dir() and not d.name.startswith(("_", "."))
    )
    if app_filter is None:
        return available
    missing = [a for a in app_filter if a not in available]
    if missing:
        print(
            f"ERROR: unknown app(s): {', '.join(missing)}. "
            f"Available: {', '.join(available)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return [a for a in app_filter if a in available]


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


def _env_bool(value: bool | None) -> str:
    """Render an optional bool as a Job env-var string ('' = leave unset)."""
    return "" if value is None else str(value).lower()


def render_job(
    template: str,
    *,
    job_name: str,
    app_name: str,
    image_uri: str,
    gcs_bucket: str,
    emulator_backend: str,
    dry_run: bool,
    gold_run: bool,
    model: str = "",
    vuln_id: str = "",
    agent_image: str = "",
    agent_mode: str = "",
    workflow: str = "",
    probe_only: bool | None = None,
    attacker_model: str = "",
    no_codebase: bool | None = None,
    agent_wallclock_seconds: int | None = None,
) -> str:
    """Render a K8s Job YAML by substituting placeholders in the template.

    Every placeholder is always filled. Fields that don't apply to a given
    mode are passed empty (env vars the entrypoint then ignores; empty
    ``experiment-*`` labels are stripped below).
    """
    # Phase 1: replace structural placeholders (job name, image). These use
    # unique strings that won't collide with env var name: fields.
    rendered = template.replace("mcb-APP_NAME-VULN_ID-MODEL", job_name)
    rendered = rendered.replace("IMAGE_URI", image_uri)

    # Phase 2: replace quoted env value placeholders only — avoids clobbering
    # env var *name* fields which share the same identifier strings.
    wallclock = "" if agent_wallclock_seconds is None else str(agent_wallclock_seconds)
    env_replacements = {
        '"APP_NAME"': f'"{app_name}"',
        '"MODEL"': f'"{model}"',
        '"VULN_ID"': f'"{vuln_id}"',
        '"EMULATOR_BACKEND"': f'"{emulator_backend}"',
        '"DRY_RUN"': f'"{str(dry_run).lower()}"',
        '"GOLD_RUN"': f'"{str(gold_run).lower()}"',
        '"GCS_BUCKET"': f'"{gcs_bucket}"',
        '"AGENT_IMAGE"': f'"{agent_image}"',
        '"AGENT_MODE"': f'"{agent_mode}"',
        '"WORKFLOW"': f'"{workflow}"',
        '"PROBE_ONLY"': f'"{_env_bool(probe_only)}"',
        '"ATTACKER_MODEL"': f'"{attacker_model}"',
        '"NO_CODEBASE"': f'"{_env_bool(no_codebase)}"',
        '"AGENT_WALLCLOCK_SECONDS"': f'"{wallclock}"',
    }
    for placeholder, value in env_replacements.items():
        rendered = rendered.replace(placeholder, value)

    # Replace label values (sanitized into K8s-safe tokens).
    label_replacements = {
        "experiment-app: APP_NAME": f'experiment-app: "{sanitize_k8s_name(app_name)}"',
        "experiment-vuln: VULN_ID": f'experiment-vuln: "{sanitize_k8s_name(vuln_id)}"',
        "experiment-model: MODEL": f'experiment-model: "{sanitize_k8s_name(model)}"',
        "experiment-workflow: WORKFLOW": f'experiment-workflow: "{sanitize_k8s_name(workflow)}"',
        "experiment-attacker: ATTACKER_MODEL": f'experiment-attacker: "{sanitize_k8s_name(attacker_model)}"',
        "experiment-no-codebase: NO_CODEBASE": f'experiment-no-codebase: "{_env_bool(no_codebase)}"',
    }
    for placeholder, value in label_replacements.items():
        rendered = rendered.replace(placeholder, value)

    # Drop the template's header comment lines and any experiment-* label that
    # ended up empty (i.e. not part of this job's mode).
    empty_label = re.compile(r'\s*experiment-[a-z-]+:\s*""\s*$')
    lines = rendered.split("\n")
    filtered = []
    header_done = False
    for line in lines:
        if not header_done and line.startswith("# "):
            continue
        header_done = True
        if empty_label.match(line):
            continue
        filtered.append(line)
    rendered = "\n".join(filtered)

    return rendered


def build_external_jobs(template: str, apps: list[str], args) -> list[tuple[str, str]]:
    """Render the (app x attacker_model x no_codebase leg) matrix.

    --models is optional here: the agent image carries the model, but a passed
    model is still plumbed through for labeling / runner_config.model. When
    omitted, the base config's model is left in place.
    """
    models = args.models or [None]
    legs = [True, False] if args.no_codebase_ablation else [False]
    jobs = []
    for app in apps:
        for model in models:
            for attacker in args.attacker_models:
                for no_codebase in legs:
                    leg_tag = "apk" if no_codebase else "src"
                    name_parts = ["mcb", app, attacker, leg_tag]
                    if model:
                        name_parts.append(model)
                    job_name = sanitize_k8s_name("-".join(name_parts))
                    yaml_str = render_job(
                        template=template,
                        job_name=job_name,
                        app_name=app,
                        model=model or "",
                        image_uri=args.image,
                        gcs_bucket=args.gcs_bucket,
                        emulator_backend=args.emulator_backend,
                        dry_run=args.dry_run,
                        gold_run=args.gold_run,
                        agent_image=args.agent_image,
                        agent_mode="external",
                        workflow=args.workflow,
                        probe_only=args.probe_only,
                        attacker_model=attacker,
                        no_codebase=no_codebase,
                        agent_wallclock_seconds=args.agent_wallclock_seconds,
                    )
                    jobs.append((job_name, yaml_str))
    return jobs


def build_legacy_jobs(
    template: str, experiments: list[dict], args
) -> list[tuple[str, str]]:
    """Render the legacy (app x vuln x model) synthetic-vuln matrix."""
    jobs = []
    for exp in experiments:
        for model in args.models:
            job_name = sanitize_k8s_name(
                f"mcb-{exp['app_name']}-{exp['vuln_id']}-{model}"
            )
            yaml_str = render_job(
                template=template,
                job_name=job_name,
                app_name=exp["app_name"],
                vuln_id=exp["vuln_id"],
                model=model,
                image_uri=args.image,
                gcs_bucket=args.gcs_bucket,
                emulator_backend=args.emulator_backend,
                dry_run=args.dry_run,
                gold_run=args.gold_run,
            )
            jobs.append((job_name, yaml_str))
    return jobs


def main():
    parser = argparse.ArgumentParser(
        description="Generate K8s Job YAMLs for MobileCyBench experiments"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--apps", nargs="+", help="App names to include (e.g., moememos bitwarden)"
    )
    group.add_argument("--all", action="store_true", help="Include all apps")

    parser.add_argument(
        "--models",
        nargs="+",
        help="Model names (e.g., gpt-4o). Required for the legacy synthetic-vuln "
        "path; optional with --agent-image (the image carries the model).",
    )
    parser.add_argument(
        "--image",
        default=os.environ.get(
            "RUNNER_IMAGE",
            "us-central1-docker.pkg.dev/PROJECT_ID/mobilecybench/runner:latest",
        ),
        help="Docker image URI for the GKE runner pod (NOT the agent image)",
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

    # External-agent path. Supplying --agent-image switches to the
    # (app x attacker_model x no_codebase leg) matrix.
    ext = parser.add_argument_group("external agent")
    ext.add_argument(
        "--agent-image",
        help="BYO agent image ref (agent_mode=external), e.g. "
        "cybench/mobilecybench:opencode_1.15.6-r1. Enables the external path.",
    )
    ext.add_argument(
        "--workflow",
        default="redteam",
        choices=["exploit", "redteam"],
        help="Workflow for external jobs (default: redteam)",
    )
    ext.add_argument(
        "--probe-only",
        action="store_true",
        help="Run redteam in bundle-less probe-only mode (probe_only=true)",
    )
    ext.add_argument(
        "--attacker-models",
        nargs="+",
        choices=["malicious_app", "remote_attacker"],
        help="Attacker model(s) to iterate over (required with --agent-image)",
    )
    ext.add_argument(
        "--no-codebase-ablation",
        action="store_true",
        help="Render both no_codebase legs (source-vs-APK ablation)",
    )
    ext.add_argument(
        "--agent-wallclock-seconds",
        type=int,
        help="Wall-clock kill budget for the external agent (seconds)",
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

    external = bool(args.agent_image)

    # Guard against external-only flags on the legacy path.
    external_only = []
    if args.probe_only:
        external_only.append("--probe-only")
    if args.attacker_models:
        external_only.append("--attacker-models")
    if args.no_codebase_ablation:
        external_only.append("--no-codebase-ablation")
    if args.agent_wallclock_seconds is not None:
        external_only.append("--agent-wallclock-seconds")
    if not external and external_only:
        parser.error(
            f"{', '.join(external_only)} only valid with --agent-image (external path)"
        )

    if external:
        if not args.attacker_models:
            parser.error("--attacker-models is required with --agent-image")
    else:
        if not args.models:
            parser.error("--models is required (or pass --agent-image)")

    project_root = Path(__file__).resolve().parent.parent.parent
    apps_dir = project_root / "apps"
    template_path = Path(__file__).resolve().parent / "job-template.yaml"

    template = load_template(template_path)

    app_filter = None if args.all else args.apps

    if external:
        apps = discover_apps(apps_dir, app_filter)
        jobs = build_external_jobs(template, apps, args)
    else:
        experiments = discover_experiments(apps_dir, app_filter)
        if not experiments:
            print(
                "No experiments found. Check that apps have synthetic_vulnerabilities/",
                file=sys.stderr,
            )
            return 1
        jobs = build_legacy_jobs(template, experiments, args)

    if args.outdir:
        Path(args.outdir).mkdir(parents=True, exist_ok=True)

    all_yamls = []
    for job_name, yaml_str in jobs:
        all_yamls.append(yaml_str)
        if args.outdir:
            (Path(args.outdir) / f"{job_name}.yaml").write_text(yaml_str)

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
