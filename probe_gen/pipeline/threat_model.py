"""Parse ``threat_model.md`` shall-not statements into Invariant objects.

The canonical layout (see ``apps/home-assistant-android/threat_model.md``):

    ## "Shall Not" threat model

    ### malicious_app

    - MA-C: <one-line shall-not statement>
    - MA-I: <statement>
    - ...

    ### remote_attacker

    - RA-C: <statement>
    - ...

This parser extracts the (id, statement, attacker_model) tuple per bullet
and produces :class:`~probe_gen.pipeline.models.Invariant` objects. It
does not assign severity automatically — that's a downstream pass over
historic CVE pairings or per-shall-not severity annotations.

Robust to:
  - Multi-line bullets (continuation lines indented or wrapped)
  - Other ``###`` subsections between attacker-model sections (just
    ignored unless they match a known model name)
  - Markdown decorations (``**bold**``, backticks)

Stops at the next top-level ``##`` heading after the "Shall Not" section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from probe_gen.pipeline.models import AttackerModel, Invariant

_SHALL_NOT_HEADING_RE = re.compile(r'^##\s+.*"?[Ss]hall\s*[Nn]ot.*"?\s*$', re.MULTILINE)
_NEXT_TOP_LEVEL_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
_ATTACKER_HEADING_RE = re.compile(
    r"^###\s+(malicious_app|remote_attacker)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_BULLET_RE = re.compile(
    r"^-\s+\**(?P<id>[A-Z]+(?:-[A-Z0-9]+)+)\**[\s:.\-—]*\s*(?P<statement>.+?)\s*$"
)


@dataclass
class ParsedShallNot:
    invariant_id: str
    statement: str
    attacker_model: AttackerModel


def parse_threat_model(text: str) -> list[ParsedShallNot]:
    """Extract shall-not bullets from a threat_model.md document.

    Returns the bullets in document order. Empty list if no
    "Shall Not" section is present.
    """
    heading_match = _SHALL_NOT_HEADING_RE.search(text)
    if not heading_match:
        return []
    section_start = heading_match.end()

    # Section ends at the next top-level ``##`` heading (or end of doc).
    next_section = _NEXT_TOP_LEVEL_HEADING_RE.search(text, pos=section_start)
    section_end = next_section.start() if next_section else len(text)
    section = text[section_start:section_end]

    out: list[ParsedShallNot] = []
    current_model: Optional[AttackerModel] = None
    last_idx = 0

    for match in _ATTACKER_HEADING_RE.finditer(section):
        if current_model is not None:
            block = section[last_idx : match.start()]
            out.extend(_extract_bullets(block, current_model))
        current_model = match.group(1).lower()  # type: ignore[assignment]
        last_idx = match.end()

    if current_model is not None:
        out.extend(_extract_bullets(section[last_idx:], current_model))

    return out


def _extract_bullets(block: str, model: AttackerModel) -> list[ParsedShallNot]:
    """Extract ``- ID: statement`` bullets from a markdown block."""
    found: list[ParsedShallNot] = []
    current_lines: list[str] = []
    current_id: Optional[str] = None

    for line in block.splitlines():
        bullet = _BULLET_RE.match(line)
        if bullet:
            # Flush the previous bullet, if any
            if current_id is not None:
                found.append(
                    ParsedShallNot(
                        invariant_id=current_id,
                        statement=" ".join(current_lines).strip(),
                        attacker_model=model,
                    )
                )
            current_id = bullet.group("id").strip()
            current_lines = [bullet.group("statement").strip()]
            continue
        # Continuation line: indented continuation of the current bullet
        if current_id is not None and line.startswith(("  ", "\t")) and line.strip():
            current_lines.append(line.strip())

    if current_id is not None:
        found.append(
            ParsedShallNot(
                invariant_id=current_id,
                statement=" ".join(current_lines).strip(),
                attacker_model=model,
            )
        )
    return found


def parse_threat_model_file(path: Path) -> list[ParsedShallNot]:
    """Convenience: read a threat_model.md path and parse it."""
    return parse_threat_model(path.read_text(encoding="utf-8"))


def shall_nots_to_invariants(
    shall_nots: list[ParsedShallNot],
    *,
    severity_overrides: Optional[dict[str, str]] = None,
) -> list[Invariant]:
    """Convert parsed shall-nots to Invariant objects.

    Severity is left as ``None`` unless ``severity_overrides`` provides a
    mapping (invariant_id → severity literal). Downstream passes can fill
    severities from historic CVE pairings.
    """
    overrides = severity_overrides or {}
    return [
        Invariant(
            invariant_id=sn.invariant_id,
            statement=sn.statement,
            attacker_model=sn.attacker_model,
            cwe_ids=[],
            cvss=None,
            linked_historic_cves=[],
            threat_model_anchor=f"threat_model.md#shall-not-{sn.invariant_id.lower()}",
            notes=overrides.get(sn.invariant_id, ""),
        )
        for sn in shall_nots
    ]


__all__ = [
    "ParsedShallNot",
    "parse_threat_model",
    "parse_threat_model_file",
    "shall_nots_to_invariants",
]
