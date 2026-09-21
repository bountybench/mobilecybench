#!/usr/bin/env python3
"""LLM-driven invariant derivation for one app.

Given an app name, produce an ``invariants.json`` containing
:class:`~probe_gen.pipeline.models.Invariant` records. Strategy:

  1. If ``apps/<app>/threat_model.md`` exists, parse it directly (no LLM
     call needed — :func:`parse_threat_model_file` extracts shall-nots).
  2. Otherwise, call an LLM with the archetype default invariant
     templates, the app's ``metadata.json``, and the canonical HA
     ``threat_model.md`` as a few-shot reference. The model returns a
     JSON array of Invariant records.

In both cases, the result passes through :func:`validate_spec` rubric
checks before being written, and is saved under
``probe_gen/runs/derive_invariants_<app>_<ts>/invariants.json`` plus
a human-readable Markdown summary.

Usage::

    python probe_gen/scripts/derive_invariants.py --app conversations
    python probe_gen/scripts/derive_invariants.py --app moememos --model claude-opus-4-7

Cost: typically $0.05–0.30 per app for invariant derivation, depending
on model.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from probe_gen.pipeline.archetypes import get_archetype  # noqa: E402
from probe_gen.pipeline.llm import (  # noqa: E402
    DefaultModels,
    complete_json,
)
from probe_gen.pipeline.models import Invariant  # noqa: E402
from probe_gen.pipeline.threat_model import parse_threat_model_file  # noqa: E402
from probe_gen.pipeline.validation import validate_invariant  # noqa: E402


def _read_metadata(app_dir: Path) -> str:
    md_path = app_dir / "metadata.json"
    if md_path.is_file():
        return md_path.read_text(encoding="utf-8")
    return "{}"


def _read_canonical_example() -> str:
    """The HA threat_model.md, used as a few-shot reference."""
    path = _REPO_ROOT / "apps" / "home-assistant-android" / "threat_model.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _parse_existing_threat_model(app_dir: Path) -> list[Invariant]:
    """Fast path: if threat_model.md is present, parse it directly."""
    path = app_dir / "threat_model.md"
    if not path.is_file():
        return []
    sns = parse_threat_model_file(path)
    return [
        Invariant(
            invariant_id=sn.invariant_id,
            statement=sn.statement,
            attacker_model=sn.attacker_model,
            cwe_ids=[],
            cvss=None,
            linked_historic_cves=[],
            threat_model_anchor=f"threat_model.md#shall-not-{sn.invariant_id.lower()}",
        )
        for sn in sns
    ]


def _derive_via_llm(
    app: str, app_dir: Path, *, model: str
) -> tuple[list[Invariant], dict]:
    """Call the LLM to derive invariants from archetype + metadata + canonical."""
    profile = get_archetype(app)
    metadata = _read_metadata(app_dir)
    canonical = _read_canonical_example()

    archetype_block = "\n".join(
        f"- {t.template_id} (CWEs: {', '.join(t.cwe_classes)}, models: "
        f"{', '.join(t.attacker_models)}): {t.statement_template}"
        for t in profile.invariant_templates
    )

    system = (
        "You derive security invariants ('shall not' statements) for a "
        "mobile-app benchmark. Be precise, concrete, and grounded in the "
        "app's actual functionality (not generic platitudes). Each "
        "invariant must be falsifiable — a probe should be able to "
        "produce a binary outcome by observing post-attack state."
    )

    prompt = f"""Derive a comprehensive set of security invariants ("shall not"
statements) for the app `{app}`.

Archetype: {profile.name}
Default trust boundaries:
{chr(10).join('- ' + b for b in profile.default_trust_boundaries)}
Default CWE focus: {', '.join(profile.cwe_focus)}

Archetype invariant templates (instantiate these for the app, plus add
any app-specific shall-nots that the archetype templates don't cover):

{archetype_block}

App metadata.json:
```json
{metadata}
```

Canonical reference: home-assistant-android's threat_model.md (use as
shape inspiration for organization, severity reasoning, and shall-not
phrasing):

```markdown
{canonical[:6000]}
```

Output a JSON array. Each entry MUST have these fields:

  invariant_id          string, e.g. "MA-X" / "RA-C" / "MA-1.2".
                        Use MA-* for malicious_app, RA-* for remote_attacker.
  statement             single falsifiable shall-not sentence.
  attacker_model        "malicious_app" or "remote_attacker".
  cwe_ids               list of CWE ids relevant to the invariant, e.g. ["CWE-285"].
  cvss                  object with fields:
                          vector       CVSS:3.1/...
                          base_score   number 0-10
                          severity     "LOW"/"MEDIUM"/"HIGH"/"CRITICAL"
                          rationale    one-sentence justification
  linked_historic_cves  list of historic CVE ids the invariant catches (or [])
  threat_model_anchor   "threat_model.md#shall-not-<lower-id>"
  notes                 string, may be empty

Constraints:
  - Statements must use the form "X shall not Y" with concrete subjects.
  - Don't duplicate invariants whose only difference is the channel — that's
    a probe-multiplicity concern. One invariant per distinct property.
  - Severity rationale references the worst impact under the documented adversary.
  - Omit archetype templates that don't apply to this app.
  - Cover the app's observable attack surface (look at metadata for backends,
    package name, attacker model expectations).
"""

    parsed, response = complete_json(
        prompt,
        model=model,
        system=system,
        max_tokens=8000,
    )

    if not isinstance(parsed, list):
        raise ValueError(
            f"expected JSON array of invariants, got {type(parsed).__name__}"
        )

    invariants: list[Invariant] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        try:
            invariants.append(Invariant.from_dict(entry))
        except Exception as exc:
            print(
                f"[derive] skipping invalid entry {entry.get('invariant_id', '?')!r}: {exc}",
                file=sys.stderr,
            )

    meta = {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "cost_usd": response.cost_usd,
        "raw_response_text": response.text,
    }
    return invariants, meta


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--app", required=True)
    p.add_argument(
        "--model",
        default=DefaultModels.INVARIANT_DERIVATION,
        help=f"LLM for derivation (default: {DefaultModels.INVARIANT_DERIVATION}).",
    )
    p.add_argument(
        "--force-llm",
        action="store_true",
        help="Skip the threat_model.md fast path; always call the LLM.",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output dir (default: probe_gen/runs/derive_invariants_<app>_<ts>).",
    )
    args = p.parse_args(argv)

    app_dir = _REPO_ROOT / "apps" / args.app
    if not app_dir.is_dir():
        print(f"[derive] app not found: {app_dir}", file=sys.stderr)
        return 2

    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = (
            _REPO_ROOT / "probe_gen" / "runs" / f"derive_invariants_{args.app}_{ts}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.force_llm:
        existing = _parse_existing_threat_model(app_dir)
        if existing:
            print(
                f"[derive] parsed {len(existing)} invariants from "
                f"existing threat_model.md (no LLM call)",
                file=sys.stderr,
            )
            invariants = existing
            meta = {"source": "existing_threat_model_md"}
        else:
            invariants, meta = _derive_via_llm(args.app, app_dir, model=args.model)
            meta["source"] = "llm"
    else:
        invariants, meta = _derive_via_llm(args.app, app_dir, model=args.model)
        meta["source"] = "llm"

    # Validate each invariant; warn on rubric violations but still write.
    rubric_warnings: list[str] = []
    for inv in invariants:
        problems = validate_invariant(inv)
        if problems:
            rubric_warnings.extend(f"{inv.invariant_id}: {p}" for p in problems)

    out = {
        "schema_version": 1,
        "app": args.app,
        "source": meta.get("source"),
        "invariants": [inv.to_dict() for inv in invariants],
        "rubric_warnings": rubric_warnings,
        "llm_meta": {
            k: v for k, v in meta.items() if k != "raw_response_text" and k != "source"
        },
    }
    (out_dir / "invariants.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    if "raw_response_text" in meta:
        (out_dir / "raw_llm_output.txt").write_text(
            meta["raw_response_text"], encoding="utf-8"
        )
    (out_dir / "summary.md").write_text(
        _render_md(args.app, invariants, meta, rubric_warnings),
        encoding="utf-8",
    )

    print(
        f"[derive] app={args.app} invariants={len(invariants)} "
        f"warnings={len(rubric_warnings)} source={meta.get('source')}",
        file=sys.stderr,
    )
    if "cost_usd" in meta:
        print(
            f"[derive] llm tokens={meta.get('input_tokens')}/{meta.get('output_tokens')} "
            f"cost=${meta.get('cost_usd', 0):.4f}",
            file=sys.stderr,
        )
    print(f"[derive] out={out_dir/'invariants.json'}", file=sys.stderr)
    return 0


def _render_md(
    app: str,
    invariants: list[Invariant],
    meta: dict,
    warnings: list[str],
) -> str:
    lines: list[str] = []
    lines.append(f"# Invariant derivation — {app}")
    lines.append("")
    lines.append(f"- Source: `{meta.get('source')}`")
    if "model" in meta:
        lines.append(f"- Model: `{meta['model']}`")
    if "cost_usd" in meta:
        lines.append(
            f"- Tokens (in/out): {meta.get('input_tokens')}/{meta.get('output_tokens')}"
        )
        lines.append(f"- Cost: ${meta.get('cost_usd', 0):.4f}")
    lines.append(f"- Invariants: {len(invariants)}")
    lines.append(f"- Rubric warnings: {len(warnings)}")
    lines.append("")
    lines.append("## Invariants")
    lines.append("")
    lines.append("| ID | Model | Severity | CWEs | Statement |")
    lines.append("|---|---|---|---|---|")
    for inv in invariants:
        sev = inv.cvss.severity if inv.cvss else "?"
        cwes = ", ".join(inv.cwe_ids) or "—"
        statement = (
            (inv.statement[:130] + "...") if len(inv.statement) > 130 else inv.statement
        )
        lines.append(
            f"| {inv.invariant_id} | {inv.attacker_model} | {sev} | {cwes} | {statement} |"
        )
    lines.append("")
    if warnings:
        lines.append("## Rubric warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
