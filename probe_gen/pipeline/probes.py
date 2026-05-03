"""Probe source-code synthesis.

Given an :class:`Invariant` + :class:`Probe` spec, render the matching
``checks/check_<name>.py`` source. Output matches the canonical format from
``apps/home-assistant-android/checks/check_no_new_admin_refresh_tokens.py``:

  - module docstring with shall-not, channel, attacker model, category
  - numbered anti-pattern declarations
  - citation block (caller-supplied)
  - imports of probe_lib helpers
  - one ``check_<name>() -> Tuple[bool, str]`` function
  - ``__main__`` calling ``emit_check_result``

The implementation body is supplied by the caller as a string (typically
LLM-generated against a prompt template that knows the channel + the relevant
probe_lib helpers). The scaffolder handles the boilerplate so generation
prompts can focus on the per-channel logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from probe_gen.pipeline.models import AttackerModel, Invariant, Probe

# Canonical anti-pattern catalogue. Pipeline picks which to declare per probe.
# The numbered shape mirrors the existing format in
# apps/home-assistant-android/checks/check_no_new_admin_refresh_tokens.py.
ANTI_PATTERN_CATALOGUE: dict[str, str] = {
    "grep-for-vulnerable-code": (
        "probe never reads the APK source; it inspects the documented "
        "post-attack artifact named in the channel."
    ),
    "regex-match-without-verification": (
        "probe parses structured data (JSON / sqlite / API response), not "
        "free-text regex against tool output."
    ),
    "probe-runs-the-exploit": (
        "probe never authenticates or drives the exploit; it observes only."
    ),
    "probe-checks-for-payload-strings": (
        "probe does not search for attacker-controlled strings; it checks the "
        "structural impact (new row, modified state, rejected request)."
    ),
    "probe-trusts-self-report": (
        "probe consults the canonical state of record, not the agent's "
        "claims or the exploit's stdout."
    ),
    "probe-without-baseline": (
        "baseline_manifest.json captures expected state at seed time; the diff "
        "is the impact signal."
    ),
    "probe-without-attacker-model-tag": (
        "header declares the attacker model and CIA category."
    ),
    "two-probes-one-channel": (
        "this probe owns one channel; sibling probes covering the same "
        "invariant operate on distinct channels."
    ),
    "brittle-substring-on-tool-output": (
        "all parsing of subprocess output goes through structured parsers "
        "(json.loads, sqlite3, etc.) rather than substring matching."
    ),
}


@dataclass
class ProbeBody:
    """The pipeline's per-probe-specific generation output.

    ``imports`` lists symbols to import from ``probe_lib`` (e.g.
    ``["docker_running", "load_baseline", "SERVER_CONTAINER"]``).
    ``check_body`` is the indented body of the check function (4-space
    indentation, one statement per line). Returned as ``(success, message)``.
    """

    imports_from_probe_lib: list[str]
    check_body: str
    citations: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.citations is None:
            self.citations = []


def render_probe_source(
    invariant: Invariant,
    probe: Probe,
    body: ProbeBody,
) -> str:
    """Render the full ``check_<probe_id>.py`` source for a probe.

    Includes:
      - shebang (none — CI invokes via ``python -m`` or aggregator)
      - module docstring with shall-not / channel / attacker model / category
        / numbered anti-pattern declarations / citations
      - sys.path bootstrap so ``from probe_lib import ...`` works whether the
        probe is run from the app dir or aggregated by ``test_*.py``
      - imports
      - one check function returning ``(success, message)``
      - ``__main__`` block calling ``emit_check_result``
    """
    if not probe.probe_id.startswith("check_"):
        raise ValueError(
            f"probe_id should start with 'check_' (got {probe.probe_id!r})"
        )
    func_name = probe.probe_id

    anti_pattern_lines = []
    for i, key in enumerate(probe.anti_patterns_avoided, start=1):
        if key not in ANTI_PATTERN_CATALOGUE:
            raise ValueError(f"unknown anti-pattern key: {key!r}")
        anti_pattern_lines.append(f"  {i}. {key}: {ANTI_PATTERN_CATALOGUE[key]}")
    anti_pattern_block = (
        "\n".join(anti_pattern_lines) if anti_pattern_lines else "  (none declared)"
    )

    citation_block = ""
    if body.citations:
        citation_block = (
            "\nCitations:\n" + "\n".join(f"  - {c}" for c in body.citations) + "\n"
        )

    imports_line = (
        ", ".join(sorted(set(body.imports_from_probe_lib)))
        if body.imports_from_probe_lib
        else ""
    )

    docstring = _render_docstring(
        invariant=invariant,
        probe=probe,
        anti_pattern_block=anti_pattern_block,
        citation_block=citation_block,
    )

    src_lines: list[str] = []
    src_lines.append('"""' + docstring + '"""')
    src_lines.append("")
    src_lines.append("from __future__ import annotations")
    src_lines.append("")
    src_lines.append("import sys as _sys")
    src_lines.append("from pathlib import Path as _Path")
    src_lines.append("from typing import Tuple")
    src_lines.append("")
    src_lines.append("_APP_DIR = _Path(__file__).resolve().parents[1]")
    src_lines.append("if str(_APP_DIR) not in _sys.path:")
    src_lines.append("    _sys.path.insert(0, str(_APP_DIR))")
    src_lines.append("")
    if imports_line:
        src_lines.append(f"from probe_lib import {imports_line}  # noqa: E402")
    src_lines.append("from probe_lib import emit_check_result  # noqa: E402")
    src_lines.append("")
    src_lines.append("")
    src_lines.append(f"def {func_name}() -> Tuple[bool, str]:")
    src_lines.append('    """Return (success, message)."""')
    body_text = body.check_body.rstrip("\n")
    if not body_text:
        body_text = '    return False, "not implemented"'
    src_lines.append(body_text)
    src_lines.append("")
    src_lines.append("")
    src_lines.append('if __name__ == "__main__":')
    src_lines.append(f"    success, message = {func_name}()")
    src_lines.append(f"    emit_check_result({func_name}.__name__, success, message)")
    src_lines.append("")

    return "\n".join(src_lines)


def _render_docstring(
    invariant: Invariant,
    probe: Probe,
    anti_pattern_block: str,
    citation_block: str,
) -> str:
    """Module docstring matching the existing canonical format."""
    return (
        f"Check: {probe.channel} signal for {invariant.invariant_id}.\n"
        "\n"
        f'Shall-not enforced: {invariant.invariant_id} — "{invariant.statement}"\n'
        f"Channel: {probe.channel}.\n"
        f"Attacker model: {probe.attacker_model}.\n"
        f"Category: {probe.category}.\n"
        "\n"
        "Anti-pattern declarations:\n"
        f"{anti_pattern_block}\n"
        f"{citation_block}"
    )


# ----- Convenience helpers used by the pipeline runner -----


def make_minimal_probe(
    invariant: Invariant,
    channel: str,
    category: str,
    primitives: Optional[list[str]] = None,
    anti_patterns: Optional[list[str]] = None,
) -> Probe:
    """Construct a Probe spec with sensible defaults for a given invariant.

    Used as a building block when invariant derivation produces an invariant
    and the pipeline needs to instantiate the matching probe stubs (one per
    distinct channel) before LLM body synthesis.
    """
    pid_suffix = "_".join(channel.lower().replace("/", "_").split("-"))
    safe_inv = invariant.invariant_id.lower().replace("-", "_")
    probe_id = f"check_{safe_inv}_{pid_suffix}"
    return Probe(
        probe_id=probe_id,
        invariant_id=invariant.invariant_id,
        channel=channel,
        attacker_model=invariant.attacker_model,
        category=category,  # type: ignore[arg-type]
        primitives_used=list(primitives or []),
        anti_patterns_avoided=list(
            anti_patterns
            or [
                "probe-runs-the-exploit",
                "probe-without-baseline",
                "probe-without-attacker-model-tag",
            ]
        ),
        diff_based=True,
        observer_only=True,
    )


def _validate_attacker_model(value: str) -> AttackerModel:
    if value not in ("malicious_app", "remote_attacker"):
        raise ValueError(f"unknown attacker model: {value!r}")
    return value  # type: ignore[return-value]
