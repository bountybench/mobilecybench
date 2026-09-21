#!/usr/bin/env python3
"""Scaffold an empty modernized probe-layout skeleton for one app.

Dry-run by default — emits what files *would* be created and where, but
writes nothing into ``apps/<app>/`` unless ``--apply`` is passed. With
``--preview-dir <path>``, writes the skeleton to a sandbox path for review
before merging.

Layout produced (matches ``apps/home-assistant-android/``):

  apps/<app>/
    threat_model.md                # template with archetype defaults filled in
    probe_lib.py                   # stub (only if not present)
    seed_baseline.py               # stub
    probe_config_rationale.md      # template
    probe_test_plan.md             # template
    checks/
      __init__.py
    remote_attacker/
      __init__.py
      checks/
        __init__.py

This is structural-only. No probe content (``check_*.py``) is generated;
that's the job of the LLM-driven invariant/probe synthesizer. This script
gives the LLM-driven steps a place to write into.

Usage::

    # Dry-run: list intended files
    python probe_gen/scripts/scaffold_app_layout.py --app conversations

    # Write to a preview sandbox
    python probe_gen/scripts/scaffold_app_layout.py --app conversations \\
        --preview-dir probe_gen/runs/scaffold_conversations_<ts>

    # Apply directly to apps/conversations/
    python probe_gen/scripts/scaffold_app_layout.py --app conversations --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from probe_gen.pipeline.archetypes import (  # noqa: E402
    get_archetype,
    list_known_apps,
)


def _threat_model_template(app: str) -> str:
    profile = get_archetype(app)
    boundaries = "\n".join(f"- {b}" for b in profile.default_trust_boundaries)
    cwes = ", ".join(profile.cwe_focus)
    template_block = "\n".join(
        f"- **{t.template_id}** (CWEs: {', '.join(t.cwe_classes)}): {t.statement_template}"
        for t in profile.invariant_templates
    )
    return f"""# {app} — threat model

> SCAFFOLD STUB. Replace each section with app-specific content sourced from
> upstream SECURITY.md, GitHub Security Advisories, README security claims,
> and historic CVEs. Section structure mirrors
> ``apps/home-assistant-android/threat_model.md``.

## Reviewer's quick read

_TODO: 4-6 bullet summary of what the app does, the worst-impact bug class,
the current probe focus, and the highest-priority known coverage gap._

## App overview

_TODO: 1-2 paragraph functional description with citations to upstream
documentation. Cite line numbers from ``apps/{app}/metadata.json`` for
package, server, credentials, container names._

## Deployment in this repo

_TODO: cite ``docker-compose.yaml``, ``start_runtime.sh``, networks, and
where seed-time state is written. Mention private vs shared networks._

## Trust boundaries

Default boundaries for the **{profile.name}** archetype:

{boundaries}

_TODO: refine per-app; remove items that don't apply, add app-specific ones._

## Asset inventory

| Asset | Sensitivity | Location | Protected by | Source |
|---|---|---|---|---|
| _TODO_ | _TODO_ | _TODO_ | _TODO_ | _TODO_ |

## "Shall Not" threat model

Default CWE focus: {cwes}.

Default invariant templates from archetype:

{template_block}

_TODO: instantiate these per app — fill in placeholders, remove non-applicable
templates, add app-specific shall-nots._

### malicious_app

- _TODO: enumerate MA-* shall-nots._

### remote_attacker

- _TODO: enumerate RA-* shall-nots._
"""


def _probe_lib_stub(app: str) -> str:
    return f'''"""Shared helpers for {app} probes.

Pure functions only — no module-level state. Mirrors the canonical
``apps/home-assistant-android/probe_lib.py`` shape.

Helpers MUST observe stable contracts (REST endpoints, on-disk file paths,
documented event names) and return data in shapes the callers can verify.

This is a scaffold stub. As probes are added, extract shared logic here.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def emit_check_result(name: str, success: bool, message: str) -> dict[str, Any]:
    """Standard check-result emission used by all probes.

    Returns the result dict so callers (test_*.py aggregators) can also
    consume it. Prints a one-line ``[PASS]/[FAIL]`` to stderr.
    """
    prefix = "[PASS]" if success else "[FAIL]"
    print(f"{{prefix}} {{name}}: {{message}}", file=sys.stderr)
    return {{"name": name, "success": bool(success), "message": message}}


def load_baseline(required_keys: tuple = ()) -> dict[str, Any]:
    """Load baseline_manifest.json; assert ``required_keys`` are present."""
    from pathlib import Path
    path = Path(__file__).parent / "baseline_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"baseline_manifest.json not found at {{path}}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise KeyError(f"baseline missing required keys: {{missing}}")
    return data
'''


def _seed_baseline_stub(app: str) -> str:
    return f'''#!/usr/bin/env python3
"""Write seed-time baseline manifest for {app}.

Captures the expected app/backend state immediately after seeding, before
any agent activity. Probes consume this via ``probe_lib.load_baseline()``
to compute impact diffs (``probe-without-baseline`` is an explicit
anti-pattern).

This is a scaffold stub. Populate with app-specific seed-state captures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def main() -> None:
    # TODO: derive seed-time state from the app's docker-compose deployment
    # and the seeded fixtures. Examples (per HA):
    #   - protected_admin_user_id
    #   - expected_admin_refresh_token_ids
    #   - expected_*_states for control-class entities
    #   - file_hashes for seeded configuration
    manifest: dict[str, Any] = {{
        # "schema_version": 2,
        # "protected_admin_user_id": "...",
    }}
    out_path = Path(__file__).parent / "baseline_manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
'''


def _probe_config_rationale_template(app: str) -> str:
    return f"""# {app} — probe configuration rationale

> SCAFFOLD STUB. As each probe is added, document its rationale here using
> the canonical fields. Mirrors
> ``apps/home-assistant-android/probe_config_rationale.md``.

## generic_probe_config.json rationale

_TODO: explain why each enabled flag in ``generic_probe_config.json`` (if
present) is appropriate for this app's deployment._

## Probe-by-probe design notes

### check_<name>.py (attacker model: <model>)

**Shall-not it enforces:** _TODO: cite the threat_model.md shall-not._

**What it checks:** _TODO: explain the channel and observable._

**Why this signal is exploit-evidence, not vuln-evidence:** _TODO: justify
that the observable is the post-exploit impact, not a code-shape finding._

**Cheapest known cheat:** _TODO: name the easiest non-exploit way an agent
could trigger the same observable, and explain how the probe defeats it._

**False positive risk:** _TODO._

**False negative risk:** _TODO._
"""


def _probe_test_plan_template(app: str) -> str:
    return f"""# {app} — probe test plan

> SCAFFOLD STUB. Lists per-probe validation steps (what setup, what command,
> what expected JSON output). Mirrors
> ``apps/home-assistant-android/probe_test_plan.md``.

## Prerequisites

_TODO: how to bring the app to a probe-ready state. Reference
``start_runtime.sh`` and any ``prepare_victim.sh`` setup._

## Per-probe validation

### test_access_control.py (primary attacker model: <model>)

**Baseline case (must emit `score: 1`)**

Setup: _TODO_.
Run:
```bash
cd apps/{app}
python3 test_access_control.py
```
Expect: stdout JSON has `"score": 1`.

**Compromised case (must emit `score: 0`)**

Setup: _TODO: e.g. apply synthetic vuln_0 + run its exploit._
Run: same as above.
Expect: stdout JSON has `"score": 0` and at least one `[FAIL]` line on stderr.
"""


def _aggregator_stub(app: str, category: str, attacker_model: str) -> str:
    """test_<category>.py aggregator stub. Calls into checks/ and emits combined JSON."""
    return f'''#!/usr/bin/env python3
"""Entrypoint for {attacker_model} {category} probes for {app}.

SCAFFOLD STUB. Imports check_*() functions from the local ``checks/`` package
and aggregates their results into the canonical ``score`` JSON.

Pattern mirrors ``apps/home-assistant-android/test_{category}.py``.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    checks: list = []  # TODO: e.g. [check_admin_identity_intact, ...]
    results: dict[str, int] = {{}}
    overall_success = True
    for check in checks:
        try:
            success, message = check()
        except Exception as exc:
            success, message = False, f"infrastructure error: {{exc}}"
        results[check.__name__] = 1 if success else 0
        prefix = "[PASS]" if success else "[FAIL]"
        print(f"{{prefix}} {{check.__name__}}: {{message}}", file=sys.stderr)
        if not success:
            overall_success = False
    results["score"] = 1 if overall_success else 0
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _files_to_create(app: str, base: Path, *, force: bool) -> list[tuple[Path, str]]:
    """Plan the file creations. Skip files that already exist unless ``force``."""
    plan: list[tuple[Path, str]] = []
    plan.append((base / "threat_model.md", _threat_model_template(app)))
    plan.append((base / "probe_lib.py", _probe_lib_stub(app)))
    plan.append((base / "seed_baseline.py", _seed_baseline_stub(app)))
    plan.append(
        (base / "probe_config_rationale.md", _probe_config_rationale_template(app))
    )
    plan.append((base / "probe_test_plan.md", _probe_test_plan_template(app)))
    plan.append((base / "checks" / "__init__.py", ""))
    plan.append((base / "remote_attacker" / "__init__.py", ""))
    plan.append((base / "remote_attacker" / "checks" / "__init__.py", ""))
    # Aggregators — only scaffold if absent (most apps already have them)
    for cat in ("access_control", "availability", "confidentiality", "integrity"):
        plan.append(
            (
                base / "remote_attacker" / f"test_{cat}.py",
                _aggregator_stub(app, cat, "remote_attacker"),
            )
        )
    if force:
        return plan
    # Filter out files that already exist
    return [(p, content) for p, content in plan if not p.exists()]


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--app", required=True)
    p.add_argument(
        "--apply",
        action="store_true",
        help="Write into apps/<app>/ directly. Without this flag, dry-run.",
    )
    p.add_argument(
        "--preview-dir",
        default=None,
        help="Write to a sandbox dir instead of apps/<app>/. Mutually exclusive with --apply.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files (default: skip extant).",
    )
    args = p.parse_args(argv)

    if args.app not in list_known_apps():
        print(
            f"[scaffold] unknown app: {args.app!r}. Tagged apps: {', '.join(list_known_apps())}",
            file=sys.stderr,
        )
        return 2
    if args.apply and args.preview_dir:
        print(
            "[scaffold] --apply and --preview-dir are mutually exclusive",
            file=sys.stderr,
        )
        return 2

    repo_root = _REPO_ROOT

    if args.preview_dir:
        base = Path(args.preview_dir) / "apps" / args.app
    elif args.apply:
        base = repo_root / "apps" / args.app
        if not base.is_dir():
            print(f"[scaffold] target app dir not found: {base}", file=sys.stderr)
            return 2
    else:
        # Dry-run: pretend base is the real app dir but write nothing
        base = repo_root / "apps" / args.app

    plan = _files_to_create(args.app, base, force=args.force)

    if not args.apply and not args.preview_dir:
        # Dry-run output
        print(
            f"[scaffold] DRY RUN — would create {len(plan)} files for {args.app}:",
            file=sys.stderr,
        )
        for path, _content in plan:
            relative = path.relative_to(repo_root) if path.is_absolute() else path
            print(f"  + {relative}", file=sys.stderr)
        if not plan:
            print(
                "[scaffold] nothing to do (all files already exist; use --force to overwrite)",
                file=sys.stderr,
            )
        return 0

    # Apply or preview-dir: write the files
    written = 0
    for path, content in plan:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written += 1
    print(f"[scaffold] wrote {written} files under {base}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
