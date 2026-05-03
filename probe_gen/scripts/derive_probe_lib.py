#!/usr/bin/env python3
"""LLM-driven per-app ``probe_lib.py`` generation.

Probes need app-specific constants (container names, paths, package name)
and app-specific helpers (XMPP-roster parsing, HA-REST routing, etc.).
Hand-authoring per-app probe_libs is the bottleneck that prevents the
probe synthesizer from producing accurate code — without a probe_lib,
the synthesizer hallucinates HA-only constants like ``SERVER_CONTAINER``
into other apps' probes.

This script generates ``apps/<app>/probe_lib.py`` by combining:
  - The app's ``docker-compose.yml`` (container names + networks)
  - The app's ``metadata.json`` (package, servers, credentials)
  - The app's ``start_runtime.sh`` and any seed scripts
  - The cross-app menu from ``probe_gen.shared_helpers``
  - HA's canonical ``probe_lib.py`` as a few-shot example

The LLM is constrained to:
  - Re-export from ``probe_gen.shared_helpers`` for cross-app primitives
  - Define only constants and helpers that are *grounded* in the app's
    actual deployment (no symbols invented from thin air)
  - Use stable contracts (REST endpoints, file paths) cited inline as
    comments, never commit-pinned URLs
  - Produce parseable Python (validated post-generation)

Output is dry-run by default; ``--apply`` writes
``apps/<app>/probe_lib.py``.

Usage::

    python probe_gen/scripts/derive_probe_lib.py --app conversations
    python probe_gen/scripts/derive_probe_lib.py --app openvpn --apply

Cost: typically $0.05–0.20 depending on model and app complexity.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from probe_gen.pipeline.llm import (  # noqa: E402
    DefaultModels,
    complete,
    extract_json,
)
from probe_gen.shared_helpers import __all__ as SHARED_HELPERS_EXPORTS  # noqa: E402

CANONICAL_PROBE_LIB_PATH = (
    _REPO_ROOT / "apps" / "home-assistant-android" / "probe_lib.py"
)


def _read_optional(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _gather_app_context(app_dir: Path) -> dict[str, str]:
    """Collect text snippets that ground the LLM in the app's deployment."""
    return {
        "metadata.json": _read_optional(app_dir / "metadata.json"),
        "docker-compose.yml": _read_optional(app_dir / "docker-compose.yml"),
        "docker-compose.yaml": _read_optional(app_dir / "docker-compose.yaml"),
        "start_runtime.sh": _read_optional(app_dir / "start_runtime.sh"),
        "build.sh": _read_optional(app_dir / "build.sh"),
        # Some apps have a Dockerfile or seed script that defines paths
        "seed_messages.py": _read_optional(app_dir / "seed_messages.py"),
    }


def _build_prompt(app: str, ctx: dict[str, str], canonical: str) -> str:
    helpers_list = ", ".join(sorted(SHARED_HELPERS_EXPORTS))
    blocks = []
    for name, content in ctx.items():
        if not content:
            continue
        # Truncate long files so the prompt stays bounded
        truncated = content[:6000]
        blocks.append(f"### {name}\n```\n{truncated}\n```")
    context_block = "\n\n".join(blocks) if blocks else "(no app context files found)"

    return f"""Generate ``apps/{app}/probe_lib.py`` — the per-app helper library
that probes import from. The canonical reference is HA's probe_lib.py
(included below). Follow its structure: constants → output helpers →
subprocess helpers → docker helpers → app-specific helpers → baseline
helpers → REST helpers (if applicable).

App context (real files from this app):

{context_block}

Cross-app shared helpers available via ``probe_gen.shared_helpers``
(re-export the ones probes will use; do not duplicate their bodies):

{helpers_list}

Canonical reference (HA's probe_lib.py):

```python
{canonical[:8000]}
```

Constraints:

  - Constants must be **grounded** in the app's actual deployment files.
    Server / container names come from docker-compose.yml. Package name
    from metadata.json. File paths from start_runtime.sh, seed scripts,
    or the upstream documentation cited inline.

  - For each constant, add a comment with the ground-truth source
    (e.g. ``# from docker-compose.yml service name``).

  - Re-export from ``probe_gen.shared_helpers`` rather than duplicating
    helpers. Use:
        from probe_gen.shared_helpers import (
            docker_running, docker_exec, ...
        )
    Don't redefine these.

  - Add app-specific helpers only if they encode a stable contract that
    the canonical shared_helpers can't express. Examples:
        - parse_xmpp_roster(xml: str) -> list[dict]
        - ha_login_flow(username, password) -> str  (returns access token)
        - openvpn_status() -> dict

  - Define ``BASELINE_FILE = APP_DIR / "baseline_manifest.json"`` and a
    ``load_baseline()`` wrapper that calls
    ``probe_gen.shared_helpers.load_baseline_at(BASELINE_FILE, ...)``.

  - Define ``emit_check_result`` either by re-export or local definition
    matching the shared_helpers signature.

  - All helpers MUST be observer-only (no exploit code). No
    authentication-as-attacker flows.

  - Produce parseable Python. Don't include import statements for
    modules you don't use. Don't reference undefined symbols.

Output the complete contents of probe_lib.py wrapped in a triple-backtick
fenced code block. No prose outside the fence. The output will be parsed
with ``ast.parse`` and rejected if it doesn't compile.
"""


_FENCE_RE_PYTHON = "```python\n"
_FENCE_RE_PLAIN = "```\n"


def _extract_python_source(text: str) -> str:
    """Pull the Python source out of a fenced block (or treat whole text as source)."""
    text = text.strip()
    # Try ```python ... ```
    for fence_open in (_FENCE_RE_PYTHON, _FENCE_RE_PLAIN):
        if fence_open in text:
            after_open = text.split(fence_open, 1)[1]
            if "```" in after_open:
                return after_open.rsplit("```", 1)[0].strip()
    # Fallback: if it parses as Python, take the whole thing
    return text


def derive_probe_lib(
    app: str,
    *,
    model: str,
    canonical_path: Path = CANONICAL_PROBE_LIB_PATH,
) -> tuple[str, dict]:
    """Generate the probe_lib source. Returns (source_text, meta)."""
    app_dir = _REPO_ROOT / "apps" / app
    if not app_dir.is_dir():
        raise FileNotFoundError(f"app not found: {app_dir}")

    ctx = _gather_app_context(app_dir)
    canonical = (
        canonical_path.read_text(encoding="utf-8") if canonical_path.is_file() else ""
    )
    if not canonical:
        raise FileNotFoundError(
            f"canonical probe_lib not found at {canonical_path}; "
            "needed as a few-shot reference"
        )

    prompt = _build_prompt(app, ctx, canonical)
    response = complete(prompt, model=model, max_tokens=8000)
    source = _extract_python_source(response.text)

    # Validate it's parseable Python
    try:
        ast.parse(source)
        parse_error = None
    except SyntaxError as exc:
        parse_error = str(exc)

    meta = {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "cost_usd": response.cost_usd,
        "parse_error": parse_error,
        "raw_response_text": response.text,
    }
    return source, meta


def _retry_with_repair(
    app: str,
    initial_source: str,
    parse_error: str,
    *,
    model: str,
) -> tuple[str, dict]:
    """Ask the LLM to fix a syntax error in its previous output.

    Single-shot repair attempt — if it still doesn't parse, return whatever
    came back so the human reviewer can see what happened.
    """
    prompt = f"""The Python you generated for ``apps/{app}/probe_lib.py``
contains a syntax error:

  {parse_error}

Original source:
```python
{initial_source[:6000]}
```

Output the *complete* fixed probe_lib.py wrapped in a single triple-backtick
fence. No prose outside the fence."""
    response = complete(prompt, model=model, max_tokens=8000)
    fixed = _extract_python_source(response.text)
    try:
        ast.parse(fixed)
        new_error = None
    except SyntaxError as exc:
        new_error = str(exc)
    return fixed, {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "cost_usd": response.cost_usd,
        "parse_error": new_error,
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--app", required=True)
    p.add_argument(
        "--model",
        default=DefaultModels.PROBE_BODY,
        help=f"LLM (default: {DefaultModels.PROBE_BODY}).",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Write apps/<app>/probe_lib.py. Without this, dry-run only.",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output dir (default: probe_gen/runs/derive_probe_lib_<app>_<ts>).",
    )
    p.add_argument(
        "--no-repair",
        action="store_true",
        help="Don't attempt single-shot syntax repair on parse failure.",
    )
    args = p.parse_args(argv)

    app_dir = _REPO_ROOT / "apps" / args.app
    if not app_dir.is_dir():
        print(f"[probe_lib] app not found: {app_dir}", file=sys.stderr)
        return 2

    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = (
            _REPO_ROOT / "probe_gen" / "runs" / f"derive_probe_lib_{args.app}_{ts}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[probe_lib] app={args.app} model={args.model}", file=sys.stderr)
    source, meta = derive_probe_lib(args.app, model=args.model)
    total_cost = meta["cost_usd"]
    repair_meta = None

    if meta["parse_error"] and not args.no_repair:
        print(
            f"[probe_lib] initial output failed to parse: {meta['parse_error']}; "
            "attempting one-shot repair",
            file=sys.stderr,
        )
        source, repair_meta = _retry_with_repair(
            args.app, source, meta["parse_error"], model=args.model
        )
        total_cost += repair_meta["cost_usd"]

    final_parses = (meta["parse_error"] is None) or (
        repair_meta is not None and repair_meta["parse_error"] is None
    )

    # Write the rendered output for review (always, regardless of --apply)
    rendered_path = out_dir / "probe_lib.py"
    rendered_path.write_text(source, encoding="utf-8")
    (out_dir / "raw_llm_output.txt").write_text(
        meta.get("raw_response_text") or "", encoding="utf-8"
    )
    summary = {
        "app": args.app,
        "model": args.model,
        "input_tokens": meta["input_tokens"]
        + (repair_meta["input_tokens"] if repair_meta else 0),
        "output_tokens": meta["output_tokens"]
        + (repair_meta["output_tokens"] if repair_meta else 0),
        "cost_usd": round(total_cost, 6),
        "initial_parse_error": meta["parse_error"],
        "repair_attempted": repair_meta is not None,
        "final_parse_error": (
            repair_meta["parse_error"] if repair_meta else meta["parse_error"]
        ),
        "final_parses": final_parses,
        "lines": len(source.splitlines()),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(
        f"[probe_lib] {summary['lines']} lines, "
        f"{summary['input_tokens']}/{summary['output_tokens']} tokens, "
        f"${total_cost:.4f}, parses={final_parses}",
        file=sys.stderr,
    )
    print(f"[probe_lib] rendered={rendered_path}", file=sys.stderr)

    if args.apply:
        if not final_parses:
            print(
                "[probe_lib] refusing to apply: output does not parse. "
                "Inspect probe_gen/runs/.../probe_lib.py and fix manually, "
                "or re-run with a different --model.",
                file=sys.stderr,
            )
            return 1
        target = app_dir / "probe_lib.py"
        if target.is_file():
            backup = app_dir / "probe_lib.py.bak"
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[probe_lib] backup={backup}", file=sys.stderr)
        target.write_text(source, encoding="utf-8")
        print(f"[probe_lib] applied={target}", file=sys.stderr)

    return 0 if final_parses else 1


if __name__ == "__main__":
    raise SystemExit(main())


# Silence unused-import warning if extract_json is added later
_ = extract_json
