#!/usr/bin/env python3
"""
Generate K8s Job YAMLs for the MobileCyBench experiment matrix.

By default this scans apps/ for synthetic vulnerabilities, cross-products with
the requested models, and renders one Job YAML per (app, vuln, model) tuple.
With --probe-only it instead renders one redteam probe-only Job per
(app, model) tuple; probe-only jobs have no synthetic vuln/task selector.

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

    # Redteam probe-only, obfuscated APK, no source code mounted
    python infra/gke/generate_jobs.py --probe-only --apps moememos \
      --models gpt-5.5 --apk-obfuscation on --no-codebase --apply
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def nonnegative_int(value: str) -> int:
    """argparse type: integer >= 0."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


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


_PROBE_ONLY_REQUIRED_FILES = (
    "test_access_control.py",
    "test_availability.py",
    "test_confidentiality.py",
    "test_integrity.py",
)


def _has_probe_suite(probe_dir: Path) -> bool:
    return probe_dir.exists() and all(
        (probe_dir / name).exists() for name in _PROBE_ONLY_REQUIRED_FILES
    )


def supports_probe_only_attacker(app_dir: Path, attacker_model: str) -> bool:
    """Return whether ``app_dir`` supports probe-only for ``attacker_model``."""
    if attacker_model == "malicious_app":
        return (app_dir / "generic_probe_config.json").exists() and _has_probe_suite(
            app_dir
        )
    if attacker_model == "remote_attacker":
        return _has_probe_suite(app_dir / "remote_attacker")
    raise ValueError(f"Unknown attacker model: {attacker_model}")


def discover_probe_only_apps(
    apps_dir: Path, app_filter: list[str] | None, attacker_models: list[str]
) -> list[dict]:
    """Scan apps/ for app dirs that can run redteam probe-only mode."""
    experiments = []
    for app_dir in sorted(apps_dir.iterdir()):
        if not app_dir.is_dir() or app_dir.name.startswith(("_", ".")):
            continue
        if app_filter and app_dir.name not in app_filter:
            continue
        if not any(
            supports_probe_only_attacker(app_dir, attacker_model)
            for attacker_model in attacker_models
        ):
            continue
        experiments.append({"app_name": app_dir.name, "vuln_id": "probe-only"})
    return experiments


def validate_download_apk_links(
    experiments: list[dict],
    project_root: Path,
    *,
    obfuscated_states: list[bool],
) -> None:
    """Fail fast if a download-apk matrix references apps with no published URL."""
    missing: list[str] = []
    app_names = sorted({exp["app_name"] for exp in experiments})
    for app_name in app_names:
        metadata_path = project_root / "apps" / app_name / "metadata.json"
        metadata = {}
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text())
        for obfuscated in obfuscated_states:
            field = "download_link_obfuscated" if obfuscated else "download_link"
            if metadata.get(field):
                continue
            missing.append(f"{app_name}: missing {field}")

    if missing:
        joined = "\n  - ".join(missing)
        raise ValueError(
            "download-apk requested, but some apps are missing published APK "
            f"metadata:\n  - {joined}"
        )


def sanitize_k8s_name(name: str) -> str:
    """Convert a string to a valid K8s resource name."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:63].rstrip("-")


def yaml_quote(value: str) -> str:
    """Render a scalar as a JSON-quoted string, which YAML accepts verbatim."""
    return json.dumps(value)


def resolve_network_mode_for_job(
    *, requested_network_mode: str | None, apk_obfuscation: str
) -> str:
    """Return the effective network_mode env override for a rendered job."""
    if apk_obfuscation == "on":
        if requested_network_mode and requested_network_mode != "restricted":
            raise ValueError("--apk-obfuscation on requires --network-mode restricted.")
        return "restricted"
    return requested_network_mode or ""


def validate_runner_models(models: list[str], *, allow_provider_prefix: bool) -> None:
    """Reject provider-prefixed model ids before submitting invalid GKE jobs."""
    if allow_provider_prefix:
        return
    prefixed = [model for model in models if "/" in model]
    if prefixed:
        joined = ", ".join(prefixed)
        raise ValueError(
            "Provider-prefixed model ids are not valid runner models: "
            f"{joined}. Use a bare benchmark model id such as 'gpt-5.5'; "
            "external agent images must map to provider-prefixed CLI ids internally."
        )


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
    workflow: str,
    probe_only: bool,
    attacker_model: str,
    build_type: str,
    no_codebase: bool,
    apk_obfuscation: str,
    agent_mode: str,
    agent_image: str,
    network_mode: str,
    reasoning_effort: str,
    max_iterations: str,
    agent_wallclock_seconds: str,
    additional_system_prompt: str,
    upload_failure_hold_seconds: str,
    require_gcs_auth_preflight: bool,
    backoff_limit: int,
    ttl_seconds_after_finished: int,
    job_name_suffix: str = "",
    job_name: str | None = None,
) -> str:
    """Render a K8s Job YAML by substituting placeholders in the template."""
    if job_name is None:
        name_parts = ["mcb", app_name, vuln_id, model]
        if job_name_suffix:
            name_parts.append(job_name_suffix)
        job_name = sanitize_k8s_name("-".join(name_parts))

    # Phase 1: replace structural placeholders (job name, image, full label lines).
    # These use unique strings that won't collide with env var name: fields.
    replacements = {
        "mcb-APP_NAME-VULN_ID-MODEL": job_name,
        "IMAGE_URI": image_uri,
        "BACKOFF_LIMIT": str(backoff_limit),
        "TTL_SECONDS_AFTER_FINISHED": str(ttl_seconds_after_finished),
    }

    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)

    # Phase 2: replace quoted env value placeholders only — avoids clobbering
    # env var *name* fields which share the same identifier strings.
    env_replacements = {
        '"APP_NAME"': yaml_quote(app_name),
        '"MODEL"': yaml_quote(model),
        '"VULN_ID"': yaml_quote(vuln_id),
        '"EMULATOR_BACKEND"': yaml_quote(emulator_backend),
        '"DRY_RUN"': yaml_quote(str(dry_run).lower()),
        '"GOLD_RUN"': yaml_quote(str(gold_run).lower()),
        '"GCS_BUCKET"': yaml_quote(gcs_bucket),
        '"WORKFLOW"': yaml_quote(workflow),
        '"PROBE_ONLY"': yaml_quote(str(probe_only).lower()),
        '"ATTACKER_MODEL"': yaml_quote(attacker_model),
        '"BUILD_TYPE"': yaml_quote(build_type),
        '"NO_CODEBASE"': yaml_quote(str(no_codebase).lower()),
        '"APK_OBFUSCATION"': yaml_quote(apk_obfuscation),
        '"AGENT_MODE"': yaml_quote(agent_mode),
        '"AGENT_IMAGE"': yaml_quote(agent_image),
        '"NETWORK_MODE"': yaml_quote(network_mode),
        '"REASONING_EFFORT"': yaml_quote(reasoning_effort),
        '"MAX_ITERATIONS"': yaml_quote(max_iterations),
        '"AGENT_WALLCLOCK_SECONDS"': yaml_quote(agent_wallclock_seconds),
        '"ADDITIONAL_SYSTEM_PROMPT"': yaml_quote(additional_system_prompt),
        '"UPLOAD_FAILURE_HOLD_SECONDS"': yaml_quote(upload_failure_hold_seconds),
        '"REQUIRE_GCS_AUTH_PREFLIGHT"': yaml_quote(
            str(require_gcs_auth_preflight).lower()
        ),
    }
    for placeholder, value in env_replacements.items():
        rendered = rendered.replace(placeholder, value)

    # Replace label values
    rendered = rendered.replace(
        "experiment-app: APP_NAME", f"experiment-app: {yaml_quote(app_name)}"
    )
    rendered = rendered.replace(
        "experiment-vuln: VULN_ID", f"experiment-vuln: {yaml_quote(vuln_id)}"
    )
    rendered = rendered.replace(
        "experiment-model: MODEL",
        f"experiment-model: {yaml_quote(sanitize_k8s_name(model))}",
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


def build_probe_only_jobs(
    template: str,
    apps: list[dict],
    args,
    workflow: str,
    build_type: str,
    apps_dir: Path,
) -> list[tuple[str, str]]:
    """Render the probe-only matrix for redteam runs.

    Emits one Job per (app, attacker_model, no_codebase leg, model) tuple.
    The legacy `--attacker-model` / `--no-codebase` flags remain supported as
    single-value shortcuts, while `--attacker-models` and
    `--no-codebase-ablation` request the full matrix.
    """
    attacker_models = args.attacker_models or [args.attacker_model]
    if args.no_codebase_ablation:
        no_codebase_legs = [False, True]
    else:
        no_codebase_legs = [args.no_codebase]

    jobs = []
    upload_failure_hold_seconds = (
        ""
        if args.upload_failure_hold_seconds is None
        else str(args.upload_failure_hold_seconds)
    )
    for exp in apps:
        for model in args.models:
            for attacker in attacker_models:
                for no_codebase in no_codebase_legs:
                    if not supports_probe_only_attacker(
                        apps_dir / exp["app_name"], attacker
                    ):
                        continue
                    apk_obfuscation = args.apk_obfuscation
                    if args.no_codebase_ablation and not no_codebase:
                        apk_obfuscation = "off"
                    network_mode = resolve_network_mode_for_job(
                        requested_network_mode=args.network_mode,
                        apk_obfuscation=apk_obfuscation,
                    )
                    leg_tag = "apk" if no_codebase else "src"
                    name_parts = [
                        "mcb",
                        exp["app_name"],
                        attacker,
                        leg_tag,
                        model,
                    ]
                    if args.job_name_suffix:
                        name_parts.append(args.job_name_suffix)
                    job_name = sanitize_k8s_name("-".join(name_parts))
                    yaml_str = render_job(
                        template=template,
                        job_name=job_name,
                        app_name=exp["app_name"],
                        vuln_id="probe-only",
                        model=model,
                        image_uri=args.image,
                        gcs_bucket=args.gcs_bucket,
                        emulator_backend=args.emulator_backend,
                        dry_run=args.dry_run,
                        gold_run=args.gold_run,
                        workflow=workflow,
                        probe_only=args.probe_only,
                        attacker_model=attacker,
                        build_type=build_type,
                        no_codebase=no_codebase,
                        apk_obfuscation=apk_obfuscation,
                        agent_mode=args.agent_mode,
                        agent_image=args.agent_image,
                        network_mode=network_mode,
                        reasoning_effort=args.reasoning_effort,
                        max_iterations=args.max_iterations,
                        agent_wallclock_seconds=args.agent_wallclock_seconds,
                        additional_system_prompt=args.additional_system_prompt,
                        upload_failure_hold_seconds=upload_failure_hold_seconds,
                        require_gcs_auth_preflight=args.require_gcs_auth_preflight,
                        backoff_limit=args.backoff_limit,
                        ttl_seconds_after_finished=args.ttl_seconds_after_finished,
                        job_name_suffix=args.job_name_suffix,
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
    group.add_argument(
        "--all", action="store_true", help="Include all apps with synthetic vulns"
    )

    parser.add_argument(
        "--models", nargs="+", required=True, help="Model names (e.g., gpt-4o)"
    )
    parser.add_argument(
        "--allow-provider-prefixed-models",
        action="store_true",
        help=(
            "Compatibility escape hatch. By default provider-prefixed ids like "
            "openai/gpt-5.5 are rejected because RunnerConfig expects the bare "
            "benchmark model id and external images should map internally."
        ),
    )
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Generate redteam probe-only jobs instead of synthetic-vuln jobs",
    )
    parser.add_argument(
        "--attacker-model",
        default="malicious_app",
        choices=["malicious_app", "remote_attacker"],
        help="Redteam attacker model for --probe-only jobs",
    )
    parser.add_argument(
        "--attacker-models",
        nargs="+",
        choices=["malicious_app", "remote_attacker"],
        help=(
            "Probe-only attacker-model matrix. When set, renders jobs for each "
            "listed attacker model instead of the single --attacker-model value."
        ),
    )
    parser.add_argument(
        "--build-type",
        default=None,
        choices=["source", "download-apk", "skip-apk"],
        help=(
            "Runner build_type override. Defaults to download-apk for "
            "--probe-only, otherwise leaves the base config behavior to the entrypoint."
        ),
    )
    parser.add_argument(
        "--no-codebase",
        action="store_true",
        help="Set no_codebase=true so the agent receives only /app/apk",
    )
    parser.add_argument(
        "--no-codebase-ablation",
        action="store_true",
        help="Render both source-access and APK-only probe-only legs",
    )
    parser.add_argument(
        "--apk-obfuscation",
        default="off",
        choices=["off", "on"],
        help="Select default or R8-minified APK bundle",
    )
    parser.add_argument(
        "--agent-mode",
        default=os.environ.get("AGENT_MODE", "custom"),
        choices=["custom", "external"],
        help="Agent dispatch mode",
    )
    parser.add_argument(
        "--agent-image",
        default=os.environ.get("AGENT_IMAGE", ""),
        help="Agent image override, required for meaningful external-mode runs",
    )
    parser.add_argument(
        "--network-mode",
        default=(os.environ.get("NETWORK_MODE") or None),
        choices=["restricted", "permissive"],
        help=(
            "Optional runner network_mode override. apk_obfuscation=on forces "
            "restricted even if omitted."
        ),
    )
    parser.add_argument(
        "--reasoning-effort",
        default=os.environ.get("REASONING_EFFORT", ""),
        help=(
            "Optional reasoning effort / external-agent variant. On PR #1163 this "
            "can be provider-specific, e.g. xhigh for opencode."
        ),
    )
    parser.add_argument(
        "--max-iterations",
        default=os.environ.get("MAX_ITERATIONS", ""),
        help="Optional custom-agent turn ceiling override; set high to let wall clock dominate",
    )
    parser.add_argument(
        "--agent-wallclock-seconds",
        default=os.environ.get("AGENT_WALLCLOCK_SECONDS", ""),
        help="Wall-clock kill budget for the agent (seconds)",
    )
    parser.add_argument(
        "--additional-system-prompt",
        default=os.environ.get("ADDITIONAL_SYSTEM_PROMPT", ""),
        help="Optional prompt suffix appended to the built system prompt",
    )
    parser.add_argument(
        "--upload-failure-hold-seconds",
        type=nonnegative_int,
        default=(
            nonnegative_int(os.environ["UPLOAD_FAILURE_HOLD_SECONDS"])
            if os.environ.get("UPLOAD_FAILURE_HOLD_SECONDS")
            else None
        ),
        help=(
            "How long a pod should stay alive after preserving a manual "
            "artifact bundle for upload failures. Omit to keep the "
            "entrypoint default."
        ),
    )
    parser.add_argument(
        "--require-gcs-auth-preflight",
        action="store_true",
        default=(os.environ.get("REQUIRE_GCS_AUTH_PREFLIGHT", "").lower() == "true"),
        help=(
            "Fail fast before the experiment starts if the pod cannot access "
            "the configured GCS bucket with application-default credentials."
        ),
    )
    parser.add_argument(
        "--backoff-limit",
        type=nonnegative_int,
        default=nonnegative_int(os.environ.get("BACKOFF_LIMIT", "1")),
        help=(
            "Kubernetes Job backoffLimit. Set 0 when first-failure evidence "
            "must not be obscured by an automatic retry."
        ),
    )
    parser.add_argument(
        "--ttl-seconds-after-finished",
        type=nonnegative_int,
        default=nonnegative_int(os.environ.get("TTL_SECONDS_AFTER_FINISHED", "86400")),
        help="Kubernetes Job TTL after completion/failure before cleanup.",
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
    parser.add_argument(
        "--job-name-suffix",
        default=os.environ.get("JOB_NAME_SUFFIX", ""),
        help="Optional suffix appended to generated Job names",
    )

    args = parser.parse_args()

    try:
        validate_runner_models(
            args.models,
            allow_provider_prefix=args.allow_provider_prefixed_models,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    project_root = Path(__file__).resolve().parent.parent.parent
    apps_dir = project_root / "apps"
    template_path = Path(__file__).resolve().parent / "job-template.yaml"

    template = load_template(template_path)

    app_filter = None if args.all else args.apps
    requested_attacker_models = args.attacker_models or [args.attacker_model]
    if args.probe_only:
        experiments = discover_probe_only_apps(
            apps_dir, app_filter, requested_attacker_models
        )
    else:
        experiments = discover_experiments(apps_dir, app_filter)

    if not experiments:
        if args.probe_only:
            msg = (
                "No probe-only apps found. Check the requested apps ship the "
                "probe suite for the requested attacker model(s)."
            )
        else:
            msg = (
                "No experiments found. Check that apps have synthetic_vulnerabilities/."
            )
        print(msg, file=sys.stderr)
        return 1

    workflow = "redteam" if args.probe_only else "exploit"
    build_type = args.build_type or ("download-apk" if args.probe_only else "")
    if args.no_codebase_ablation and not args.probe_only:
        print(
            "ERROR: --no-codebase-ablation is only valid with --probe-only.",
            file=sys.stderr,
        )
        return 1
    if (
        args.apk_obfuscation == "on"
        and not args.no_codebase
        and not (args.probe_only and args.no_codebase_ablation)
    ):
        print(
            "ERROR: --apk-obfuscation on requires --no-codebase.",
            file=sys.stderr,
        )
        return 1
    if args.apk_obfuscation == "on" and build_type == "source":
        print(
            "ERROR: --apk-obfuscation on cannot be combined with --build-type source.",
            file=sys.stderr,
        )
        return 1
    try:
        default_network_mode = resolve_network_mode_for_job(
            requested_network_mode=args.network_mode or None,
            apk_obfuscation=args.apk_obfuscation,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if build_type == "download-apk":
        required_obfuscated_states = [args.apk_obfuscation == "on"]
        if (
            args.probe_only
            and args.no_codebase_ablation
            and args.apk_obfuscation == "on"
        ):
            required_obfuscated_states = [False, True]
        try:
            validate_download_apk_links(
                experiments,
                project_root,
                obfuscated_states=required_obfuscated_states,
            )
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    if args.outdir:
        Path(args.outdir).mkdir(parents=True, exist_ok=True)

    all_yamls = []
    if args.agent_mode == "external" and not args.agent_image:
        print(
            "ERROR: --agent-image is required for --agent-mode external jobs.",
            file=sys.stderr,
        )
        return 1

    if args.probe_only and (
        args.agent_mode == "external"
        or args.attacker_models
        or args.no_codebase_ablation
    ):
        if not args.agent_image:
            # Custom probe-only jobs use the base kali image unless the caller
            # overrides it explicitly.
            args.agent_image = "cybench/mobilecybench:latest"
        jobs = build_probe_only_jobs(
            template, experiments, args, workflow, build_type, apps_dir
        )
    else:
        jobs = []
        upload_failure_hold_seconds = (
            ""
            if args.upload_failure_hold_seconds is None
            else str(args.upload_failure_hold_seconds)
        )
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
                    workflow=workflow,
                    probe_only=args.probe_only,
                    attacker_model=args.attacker_model if args.probe_only else "",
                    build_type=build_type,
                    no_codebase=args.no_codebase,
                    apk_obfuscation=args.apk_obfuscation,
                    agent_mode=args.agent_mode,
                    agent_image=args.agent_image,
                    network_mode=default_network_mode,
                    reasoning_effort=args.reasoning_effort,
                    max_iterations=args.max_iterations,
                    agent_wallclock_seconds=args.agent_wallclock_seconds,
                    additional_system_prompt=args.additional_system_prompt,
                    upload_failure_hold_seconds=upload_failure_hold_seconds,
                    require_gcs_auth_preflight=args.require_gcs_auth_preflight,
                    backoff_limit=args.backoff_limit,
                    ttl_seconds_after_finished=args.ttl_seconds_after_finished,
                    job_name_suffix=args.job_name_suffix,
                )
                jobs.append(
                    (
                        sanitize_k8s_name(
                            f"mcb-{exp['app_name']}-{exp['vuln_id']}-{model}"
                        ),
                        yaml_str,
                    )
                )

    if not jobs:
        if args.probe_only:
            print(
                "No probe-only jobs found for the requested apps/attacker-models.",
                file=sys.stderr,
            )
        else:
            print("No jobs found for the requested arguments.", file=sys.stderr)
        return 1

    for job_name, yaml_str in jobs:
        all_yamls.append(yaml_str)
        if args.outdir:
            outpath = Path(args.outdir) / f"{job_name}.yaml"
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
