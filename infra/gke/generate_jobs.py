#!/usr/bin/env python3
"""
Generate K8s Job YAMLs for the MobileCyBench external-agent matrix.

The GKE path runs a BYO coding-agent image (agent_mode=external) over the
redteam probe-only workflow. It renders one Job per
(app, attacker_model, no_codebase leg) tuple. ``--models`` is optional: the
agent image carries the model, but a passed model is still plumbed through for
labeling / runner_config.model. synthetic_vuln_id / VULN_ID are not emitted.

The defaults ARE the full grid: probe-only, both attacker models, both
visibility legs (source + apk_only). You supply the agent image + model (coupled
CLI/model — no default) and the runner image / results bucket. So the full
13-app x 2 attacker x 2 visibility = 52-cell grid is:

    RUNNER_IMAGE=...  GCS_BUCKET=...  # or pass --image / --gcs-bucket
    python infra/gke/generate_jobs.py --all \\
        --agent-image cybench/mobilecybench:claudecode_2.1.170-r1 \\
        --models claude-opus-4-8 --apply

Published agent images (pull from Docker Hub, pick the CLI you want):
    Claude Code  cybench/mobilecybench:claudecode_2.1.170-r1   (Anthropic models)
    opencode     cybench/mobilecybench:opencode_1.15.6-r1      (provider/model ids)
    codex        cybench/mobilecybench:codex_0.130.0-r2        (OpenAI models)

Usage (narrowing from the defaults):
    # One app, one leg, one attacker (quick smoke)
    python infra/gke/generate_jobs.py \\
        --apps conversations \\
        --agent-image cybench/mobilecybench:claudecode_2.1.170-r1 \\
        --models claude-opus-4-8 \\
        --visibility source --attacker-models malicious_app \\
        --image $RUNNER_IMAGE --gcs-bucket $BUCKET --apply
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

EMULATOR_GPU_ENV = "MOBILECYBENCH_EMULATOR_GPU"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
APP_CATALOG = PROJECT_ROOT / "apps" / "app_catalog.json"

# Defaults chosen so the common case — the full grid — is short:
#   generate_jobs.py --all --agent-image <img> --models <model> --apply
# i.e. attacker = both, visibility = both legs, probe-only. --agent-image and
# --models are deliberately NOT defaulted: the agent CLI and its model string
# are coupled (a claudecode_* image needs an Anthropic model, opencode_*/codex_*
# need their own), so a wrong default would silently mis-run every cell.
DEFAULT_ATTACKER_MODELS = ["malicious_app", "remote_attacker"]
# source-visible leg first (no_codebase=false), then apk-only (no_codebase=true).
VISIBILITY_LEGS = {"both": [False, True], "source": [False], "apk_only": [True]}


def load_active_apps(catalog_path: Path | None = None) -> list[str]:
    """Return the active app names from apps/app_catalog.json."""
    catalog_path = APP_CATALOG if catalog_path is None else catalog_path
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        apps = catalog["sets"]["in_scope"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(
            f"ERROR: failed to read active app catalog {catalog_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(apps, list) or not all(isinstance(app, str) for app in apps):
        print(
            f"ERROR: expected string list at {catalog_path}: sets.in_scope",
            file=sys.stderr,
        )
        sys.exit(1)
    return apps


def discover_apps(apps_dir: Path, app_filter: list[str] | None) -> list[str]:
    """Return active app names for the external-agent path."""
    available = load_active_apps()
    if app_filter is None:
        selected = available
    else:
        missing = [a for a in app_filter if a not in available]
        if missing:
            print(
                f"ERROR: unknown or archived app(s): {', '.join(missing)}. "
                f"Active apps: {', '.join(available)}",
                file=sys.stderr,
            )
            sys.exit(1)
        selected = list(app_filter)

    missing_dirs = [app for app in selected if not (apps_dir / app).is_dir()]
    if missing_dirs:
        print(
            f"ERROR: active catalog app(s) missing under apps/: {', '.join(missing_dirs)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return selected


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
    emulator_gpu: str,
    dry_run: bool,
    gold_run: bool,
    model: str = "",
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
    rendered = template.replace("JOB_NAME", job_name)
    rendered = rendered.replace("IMAGE_URI", image_uri)

    # Phase 2: replace quoted env value placeholders only — avoids clobbering
    # env var *name* fields which share the same identifier strings.
    wallclock = "" if agent_wallclock_seconds is None else str(agent_wallclock_seconds)
    env_replacements = {
        '"APP_NAME"': f'"{app_name}"',
        '"MODEL"': f'"{model}"',
        '"EMULATOR_BACKEND"': f'"{emulator_backend}"',
        f'"{EMULATOR_GPU_ENV}"': f'"{emulator_gpu}"',
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
    legs = VISIBILITY_LEGS[args.visibility]
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
                        emulator_gpu=args.emulator_gpu,
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


def main():
    parser = argparse.ArgumentParser(
        description="Generate K8s Job YAMLs for MobileCyBench external-agent jobs"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--apps", nargs="+", help="App names to include (e.g., moememos bitwarden)"
    )
    group.add_argument("--all", action="store_true", help="Include all active apps")

    parser.add_argument(
        "--models",
        nargs="+",
        help="Model names (e.g., gpt-4o). Optional because the agent image carries "
        "the model; when provided, values are used for labels and runner_config.model.",
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
    parser.add_argument(
        "--emulator-gpu",
        default=os.environ.get(EMULATOR_GPU_ENV, ""),
        help=(
            "Headless emulator -gpu mode for generated jobs. Empty keeps the "
            f"runner default (swiftshader). Defaults from {EMULATOR_GPU_ENV}."
        ),
    )

    # External-agent path: (app x attacker_model x no_codebase leg) matrix.
    ext = parser.add_argument_group("external agent")
    ext.add_argument(
        "--agent-image",
        required=True,
        help="BYO agent image ref (agent_mode=external). Required and coupled to "
        "--models (no default). Published tags: Claude Code "
        "cybench/mobilecybench:claudecode_2.1.170-r1 (Anthropic models), opencode "
        "cybench/mobilecybench:opencode_1.15.6-r1, codex "
        "cybench/mobilecybench:codex_0.130.0-r2.",
    )
    ext.add_argument(
        "--workflow",
        default="redteam",
        choices=["redteam"],
        help="Workflow for external jobs (default: redteam)",
    )
    ext.add_argument(
        "--probe-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Bundle-less probe-only mode (default: on; the only supported GKE "
        "external mode). --no-probe-only is rejected.",
    )
    ext.add_argument(
        "--attacker-models",
        nargs="+",
        choices=["malicious_app", "remote_attacker"],
        default=DEFAULT_ATTACKER_MODELS,
        help="Attacker model(s) to iterate over (default: both malicious_app and "
        "remote_attacker).",
    )
    ext.add_argument(
        "--visibility",
        choices=["both", "source", "apk_only"],
        default="both",
        help="Which visibility legs to render (default: both = the source-vs-APK "
        "ablation, i.e. the full grid). Use 'source' or 'apk_only' to "
        "render a single leg.",
    )
    ext.add_argument(
        "--no-codebase-ablation",
        action="store_true",
        help="Deprecated alias for --visibility both (kept for back-compat).",
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
    args.emulator_gpu = args.emulator_gpu.strip()

    # --no-codebase-ablation is a back-compat alias for the default --visibility both.
    if args.no_codebase_ablation:
        args.visibility = "both"

    if not args.probe_only:
        parser.error("GKE external-agent jobs are probe-only; remove --no-probe-only")
    if not args.models:
        print(
            "WARNING: --models not set; jobs use the base runner_config.json "
            "model. Ensure it matches the agent image's CLI (e.g. a claudecode_* "
            "image needs an Anthropic model).",
            file=sys.stderr,
        )

    if args.probe_only and (args.dry_run or args.gold_run):
        flag = "--dry-run" if args.dry_run else "--gold-run"
        parser.error(
            f"--probe-only cannot be combined with {flag}; RunnerConfig rejects "
            "probe-only dry/gold runs"
        )

    apps_dir = PROJECT_ROOT / "apps"
    template_path = Path(__file__).resolve().parent / "job-template.yaml"

    template = load_template(template_path)

    app_filter = None if args.all else args.apps

    apps = discover_apps(apps_dir, app_filter)
    jobs = build_external_jobs(template, apps, args)

    # Names are sanitized + truncated to 63 chars; collisions would make
    # `kubectl apply` silently overwrite an earlier job. Fail loudly instead.
    names = [name for name, _ in jobs]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        print(
            f"ERROR: duplicate job names after sanitization: {', '.join(dupes)}. "
            "Disambiguate inputs (e.g. use shorter/distinct model ids).",
            file=sys.stderr,
        )
        return 1

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
