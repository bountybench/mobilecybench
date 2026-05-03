#!/usr/bin/env python3
"""Materialize a probe-spec JSON into apps/<app>/ files.

Given a JSON spec describing invariants, probes (with bodies), and
synthetic vulnerabilities for one app, write all the corresponding files
into the app's directory. Deterministic — no LLM calls. The LLM-driven
synthesis steps will eventually produce these specs, then this script
realizes them on disk.

JSON spec shape (single document)::

  {
    "schema_version": 1,
    "app": "conversations",
    "invariants": [<Invariant.to_dict()>, ...],
    "probes": [
      {
        "spec": <Probe.to_dict()>,
        "body": {
          "imports_from_probe_lib": ["..."],
          "check_body": "    return True, \"ok\"",
          "citations": ["..."]
        }
      },
      ...
    ]
  }

Synthetic-vulnerability materialization is not yet handled here; that
needs additional fields (patch text, exploit files) and is owned by the
patch/exploit synthesis modules.

Dry-run by default. Pass ``--apply`` to actually write into apps/<app>/.

Usage::

    python probe_gen/scripts/materialize_probe_spec.py \\
        --spec probe_gen/runs/<id>/spec.json \\
        [--app-dir apps/<app>] \\
        [--apply]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from probe_gen.pipeline.models import Invariant, Probe  # noqa: E402
from probe_gen.pipeline.probes import (  # noqa: E402
    ProbeBody,
    render_probe_source,
)
from probe_gen.pipeline.validation import validate_spec  # noqa: E402


def _load_spec(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise ValueError("spec must be a JSON object")
    if spec.get("schema_version") != 1:
        raise ValueError(f"unsupported schema_version: {spec.get('schema_version')!r}")
    if not spec.get("app"):
        raise ValueError("spec.app is required")
    if not isinstance(spec.get("invariants", []), list):
        raise ValueError("spec.invariants must be a list")
    if not isinstance(spec.get("probes", []), list):
        raise ValueError("spec.probes must be a list")


def materialize(
    spec: dict,
    app_dir: Path,
    *,
    apply: bool,
    skip_rubric_validation: bool = False,
) -> list[tuple[Path, str]]:
    """Render every artifact and return (path, content) pairs.

    If ``apply`` is True, also writes them to disk.

    Performs structural validation (``_validate_spec``) and rubric
    validation (``probe_gen.pipeline.validation.validate_spec``) before
    rendering. Set ``skip_rubric_validation=True`` to bypass the rubric
    checks (useful when materializing partial / experimental specs).
    """
    _validate_spec(spec)
    if not skip_rubric_validation:
        rubric_problems = validate_spec(spec)
        if rubric_problems:
            raise ValueError(
                "spec failed rubric validation:\n  - " + "\n  - ".join(rubric_problems)
            )
    invariants = {
        inv["invariant_id"]: Invariant.from_dict(inv) for inv in spec["invariants"]
    }
    plan: list[tuple[Path, str]] = []

    for probe_entry in spec["probes"]:
        probe = Probe.from_dict(probe_entry["spec"])
        if probe.invariant_id not in invariants:
            raise ValueError(
                f"probe {probe.probe_id!r} references unknown invariant "
                f"{probe.invariant_id!r}"
            )
        body_dict = probe_entry.get("body", {})
        body = ProbeBody(
            imports_from_probe_lib=list(body_dict.get("imports_from_probe_lib", [])),
            check_body=body_dict.get(
                "check_body", '    return False, "not implemented"'
            ),
            citations=list(body_dict.get("citations", []) or []),
        )
        src = render_probe_source(invariants[probe.invariant_id], probe, body)
        if probe.attacker_model == "malicious_app":
            target = app_dir / "checks" / f"{probe.probe_id}.py"
        else:
            target = app_dir / "remote_attacker" / "checks" / f"{probe.probe_id}.py"
        plan.append((target, src))

    if apply:
        for path, content in plan:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    return plan


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--spec", required=True, help="Path to probe-spec JSON")
    p.add_argument(
        "--app-dir",
        default=None,
        help="Override target dir (default: <repo_root>/apps/<spec.app>).",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually write files. Without this flag, dry-run only.",
    )
    args = p.parse_args(argv)

    spec_path = Path(args.spec).resolve()
    if not spec_path.is_file():
        print(f"[materialize] spec not found: {spec_path}", file=sys.stderr)
        return 2
    spec = _load_spec(spec_path)
    try:
        _validate_spec(spec)
    except ValueError as exc:
        print(f"[materialize] invalid spec: {exc}", file=sys.stderr)
        return 2

    app_dir = (
        Path(args.app_dir).resolve()
        if args.app_dir
        else (_REPO_ROOT / "apps" / spec["app"])
    )

    plan = materialize(spec, app_dir, apply=args.apply)
    action = "WROTE" if args.apply else "WOULD WRITE"
    for path, _content in plan:
        rel = path.relative_to(_REPO_ROOT) if _REPO_ROOT in path.parents else path
        print(f"[materialize] {action}: {rel}", file=sys.stderr)
    print(
        f"[materialize] {len(plan)} probe file(s); "
        f"{'applied' if args.apply else 'dry-run only'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
