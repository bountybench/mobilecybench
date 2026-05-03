#!/usr/bin/env python3
"""LLM-driven vulnerability patch synthesis (Phase 2.1).

Given a target invariant + a real CVE id + a target file in the app's
source tree, produce a ``vulnerability.patch`` git diff that introduces
the bug class. The patch must:

  - Apply cleanly to the app's pinned baseline commit (validated via
    ``git apply --check`` against the live submodule checkout).
  - Be small (≤5 files / ≤50 LOC by default; rationale-flagged otherwise).
  - Reintroduce a *security-check removal* / *validation bypass* /
    *unsafe-default* in the spirit of the historical CVE.

This is v1: it produces a candidate patch and runs ``git apply --check``.
Full validation (build + exploit-side gate + clean-side gate) requires
``run_ci_local.sh --test-synthetic-vuln``, which is the existing
dual-comparator gate. This script just gets a candidate to that gate.

Usage::

    python probe_gen/scripts/synthesize_patch.py \\
        --app conversations \\
        --invariant-id MA-1 \\
        --invariant-statement "..." \\
        --cve CVE-2025-27916 \\
        --target-file src/main/java/eu/siacs/conversations/parser/MessageParser.java

The CVE record is looked up automatically from
``experimental/android_*_enriched.jsonl`` for description / CWE / CVSS
context. Output: ``probe_gen/runs/synthesize_patch_<app>_<cve>_<ts>/``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from probe_gen.pipeline.coverage import (  # noqa: E402
    load_enriched_dataset,
)
from probe_gen.pipeline.llm import DefaultModels, complete  # noqa: E402


def _find_cve(cve_id: str) -> Optional[dict]:
    """Look up a CVE record across all enriched JSONL files."""
    paths = sorted((_REPO_ROOT / "experimental").glob("android_*_enriched.jsonl"))
    for cve in load_enriched_dataset(paths):
        if cve.cve_id == cve_id:
            return {
                "cve_id": cve.cve_id,
                "cwe_ids": list(cve.cwe_ids),
                "severity": cve.severity,
                "base_score": cve.base_score,
                "description": cve.description,
            }
    return None


def _read_target(app_dir: Path, rel_path: str) -> tuple[str, Path]:
    """Read the target file from the app's codebase submodule."""
    target = app_dir / "codebase" / rel_path
    if not target.is_file():
        # Try without the codebase prefix in case caller passed a full path
        alt = app_dir / rel_path
        if alt.is_file():
            return alt.read_text(encoding="utf-8"), alt
        raise FileNotFoundError(f"target file not found: {target} (or {alt})")
    return target.read_text(encoding="utf-8"), target


def _with_line_numbers(text: str) -> str:
    """Prefix each line with ``NNNN: `` so the LLM sees exact line numbers."""
    return "\n".join(f"{i:>5}: {line}" for i, line in enumerate(text.splitlines(), 1))


def _read_canonical_patch_examples() -> str:
    """Return the existing conversations vuln_0 patch as a few-shot anchor."""
    p = (
        _REPO_ROOT
        / "apps"
        / "conversations"
        / "synthetic_vulnerabilities"
        / "vuln_0"
        / "vulnerability.patch"
    )
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _build_prompt(
    *,
    app: str,
    invariant_id: str,
    invariant_statement: str,
    cve: dict,
    target_rel: str,
    target_src: str,
    canonical_patch: str,
) -> str:
    return f"""You are synthesizing a ``vulnerability.patch`` for the MobileCybench
benchmark. The patch reintroduces a security flaw similar to a real CVE,
turning a clean app into the vulnerable comparator that gets evaluated
against an exploit and a probe.

App: {app}
Target invariant {invariant_id}: "{invariant_statement}"
Reference CVE: {cve['cve_id']} (CWEs {', '.join(cve['cwe_ids'])}, severity {cve['severity']})
CVE description (for spirit, not literal mimicry — the patch should
introduce the *same class* of bug, grounded in this app's code):
  {cve['description'][:600]}

Target source file ({target_rel}) — full file with line numbers
(use these exact contents to build your diff context; do NOT invent
lines that aren't here):
```
{_with_line_numbers(target_src)}
```

Canonical example (conversations vuln_0 — XMPP carbon spoof, removes
``original.fromServer(account)`` origin check):
```
{canonical_patch}
```

Produce a unified-diff patch that:
  - Applies cleanly to the file shown above using ``git apply``.
  - Touches as few lines as possible (≤50 LOC; ≤5 files). Single-file
    patches are strongly preferred.
  - Reintroduces a security-check removal / validation bypass /
    unsafe-default consistent with the CVE's CWE class.
  - Compiles. Don't break unrelated callers; don't change function
    signatures unless absolutely necessary.
  - Uses standard git-diff format with ``diff --git a/<rel> b/<rel>``
    headers. The path shown should be relative to the repo root of the
    submodule (e.g. ``src/main/java/...``), exactly as ``git apply`` in
    the codebase dir would expect.

Output ONLY the unified diff in a fenced block (```diff ... ```). No
prose outside the fence. The output will be tested with
``git apply --check`` and rejected if it doesn't apply.

If the patch is multi-file or >50 LOC, prepend a single comment line
``# Rationale: <one-line>`` immediately after the closing fence in your
prose response — but the diff itself must remain inside the fence.
"""


def _extract_diff(text: str) -> str:
    """Pull a ``diff`` fence out of the response.

    Picks the *last* fenced diff/patch block — LLMs often emit a first
    attempt, then "let me reconsider...", then a corrected final attempt.
    Normalizes to LF and recomputes hunk header line counts (LLMs
    routinely miscount these and produce ``corrupt patch at line N``).
    """
    text = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    # Find every ```diff or ```patch fence and pick the last fully-closed one.
    fence_re = re.compile(
        r"```(?:diff|patch)?\n(.+?)```", re.DOTALL | re.IGNORECASE
    )
    matches = fence_re.findall(text)
    diff = matches[-1].strip() + "\n" if matches else text
    return _recount_hunk_headers(diff)


_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)


def _recount_hunk_headers(diff: str) -> str:
    """Recompute ``@@ -A,B +C,D @@`` line counts from actual hunk bodies.

    LLMs reliably miscount ``B`` and ``D`` (the line counts), producing
    ``corrupt patch at line N`` errors at ``git apply`` time. This pass
    walks the diff and rewrites each hunk header with the correct counts,
    leaving the start lines (A, C) and the trailing context as-is.
    """
    out_lines: list[str] = []
    lines = diff.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HUNK_HEADER_RE.match(line.rstrip("\n"))
        if not m:
            out_lines.append(line)
            i += 1
            continue
        old_start = int(m.group(1))
        new_start = int(m.group(3))
        trailing = m.group(5) or ""

        # Walk hunk body until next file header or hunk header
        body_start = i + 1
        j = body_start
        old_count = 0
        new_count = 0
        while j < len(lines):
            body_line = lines[j]
            stripped = body_line.rstrip("\n")
            if stripped.startswith("@@") or stripped.startswith("diff --git"):
                break
            if not stripped:
                # Empty line: typically belongs to the hunk if the next
                # line is still hunk content. Treat as context.
                old_count += 1
                new_count += 1
                j += 1
                continue
            sigil = stripped[0]
            if sigil == "-":
                old_count += 1
            elif sigil == "+":
                new_count += 1
            elif sigil in (" ", "\\"):
                # Context line ('\\' = "\ No newline at end of file")
                if sigil == " ":
                    old_count += 1
                    new_count += 1
            else:
                # Some other char — assume context
                old_count += 1
                new_count += 1
            j += 1

        new_header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{trailing}\n"
        out_lines.append(new_header)
        out_lines.extend(lines[body_start:j])
        i = j
    return "".join(out_lines)


def _git_apply_check(diff: str, *, repo_dir: Path) -> tuple[bool, str]:
    """Run ``git apply --check`` against the diff in the given repo dir."""
    proc = subprocess.run(
        ["git", "apply", "--check", "-"],
        input=diff,
        text=True,
        cwd=str(repo_dir),
        capture_output=True,
    )
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()


def synthesize_patch(
    *,
    app: str,
    invariant_id: str,
    invariant_statement: str,
    cve_id: str,
    target_rel_path: str,
    model: str = DefaultModels.PATCH_SYNTHESIS,
) -> dict:
    app_dir = _REPO_ROOT / "apps" / app
    if not app_dir.is_dir():
        raise FileNotFoundError(f"app not found: {app_dir}")

    cve = _find_cve(cve_id)
    if not cve:
        raise ValueError(
            f"CVE {cve_id} not found in experimental/android_*_enriched.jsonl"
        )

    target_src, target_path = _read_target(app_dir, target_rel_path)
    canonical_patch = _read_canonical_patch_examples()

    prompt = _build_prompt(
        app=app,
        invariant_id=invariant_id,
        invariant_statement=invariant_statement,
        cve=cve,
        target_rel=target_rel_path,
        target_src=target_src,
        canonical_patch=canonical_patch,
    )
    response = complete(prompt, model=model, max_tokens=6000)
    diff = _extract_diff(response.text)

    # Validate against the codebase submodule
    codebase_dir = app_dir / "codebase"
    if not codebase_dir.is_dir():
        return {
            "model": response.model,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cost_usd": round(response.cost_usd, 6),
            "diff": diff,
            "raw_response_text": response.text,
            "git_apply_check": {
                "applies": False,
                "message": f"codebase dir missing: {codebase_dir}",
            },
            "cve": cve,
            "repair_attempts": [],
        }

    applies, apply_message = _git_apply_check(diff, repo_dir=codebase_dir)

    # One-shot repair: feed the failure back to the LLM with the full file
    repair_attempts: list[dict] = []
    total_input = response.input_tokens
    total_output = response.output_tokens
    total_cost = response.cost_usd

    if not applies:
        repair_prompt = (
            f"The diff you produced did not apply to the file:\n\n"
            f"  git apply --check error: {apply_message}\n\n"
            f"Original target file (full, with line numbers):\n```\n"
            f"{_with_line_numbers(target_src)}\n```\n\n"
            f"Your previous diff:\n```\n{diff}\n```\n\n"
            f"Output a corrected diff (fenced ```diff ... ```) that "
            f"matches the actual file contents and line numbers above. "
            f"Use the exact text from the file as context."
        )
        repair_response = complete(repair_prompt, model=model, max_tokens=6000)
        repaired_diff = _extract_diff(repair_response.text)
        applies2, message2 = _git_apply_check(repaired_diff, repo_dir=codebase_dir)
        repair_attempts.append(
            {
                "diff": repaired_diff,
                "applies": applies2,
                "message": message2,
                "input_tokens": repair_response.input_tokens,
                "output_tokens": repair_response.output_tokens,
                "cost_usd": round(repair_response.cost_usd, 6),
            }
        )
        total_input += repair_response.input_tokens
        total_output += repair_response.output_tokens
        total_cost += repair_response.cost_usd
        if applies2:
            diff = repaired_diff
            apply_message = message2
            applies = True

    return {
        "model": response.model,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cost_usd": round(total_cost, 6),
        "diff": diff,
        "raw_response_text": response.text,
        "git_apply_check": {
            "applies": applies,
            "message": apply_message,
        },
        "cve": cve,
        "repair_attempts": repair_attempts,
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--app", required=True)
    p.add_argument("--invariant-id", required=True)
    p.add_argument("--invariant-statement", required=True)
    p.add_argument("--cve", required=True, help="CVE id, e.g. CVE-2025-27916")
    p.add_argument(
        "--target-file",
        required=True,
        help="Path under apps/<app>/codebase/ (e.g. src/main/java/.../MessageParser.java)",
    )
    p.add_argument(
        "--model",
        default=DefaultModels.PATCH_SYNTHESIS,
        help=f"LLM (default: {DefaultModels.PATCH_SYNTHESIS}).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output dir (default: probe_gen/runs/synthesize_patch_<app>_<cve>_<ts>).",
    )
    args = p.parse_args(argv)

    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        cve_safe = args.cve.replace("-", "_")
        out_dir = (
            _REPO_ROOT
            / "probe_gen"
            / "runs"
            / f"synthesize_patch_{args.app}_{cve_safe}_{ts}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[patch] app={args.app} invariant={args.invariant_id} cve={args.cve}",
        file=sys.stderr,
    )

    try:
        result = synthesize_patch(
            app=args.app,
            invariant_id=args.invariant_id,
            invariant_statement=args.invariant_statement,
            cve_id=args.cve,
            target_rel_path=args.target_file,
            model=args.model,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"[patch] {exc}", file=sys.stderr)
        return 2

    # Patches MUST be LF-terminated. Python's write_text uses the
    # platform default newline (CRLF on Windows), which corrupts the
    # patch format and causes ``git apply`` to choke.
    (out_dir / "vulnerability.patch").write_bytes(result["diff"].encode("utf-8"))
    (out_dir / "raw_llm_output.txt").write_text(
        result["raw_response_text"], encoding="utf-8"
    )
    summary = {
        "app": args.app,
        "invariant_id": args.invariant_id,
        "cve": result["cve"],
        "model": result["model"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "cost_usd": result["cost_usd"],
        "git_apply_check": result["git_apply_check"],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    applies = result["git_apply_check"]["applies"]
    print(
        f"[patch] tokens {result['input_tokens']}/{result['output_tokens']} "
        f"cost=${result['cost_usd']:.4f}",
        file=sys.stderr,
    )
    if applies:
        print("[patch] git apply --check: OK", file=sys.stderr)
    else:
        print(
            f"[patch] git apply --check FAILED: {result['git_apply_check']['message']}",
            file=sys.stderr,
        )
    print(f"[patch] out={out_dir}/vulnerability.patch", file=sys.stderr)

    return 0 if applies else 1


if __name__ == "__main__":
    raise SystemExit(main())
