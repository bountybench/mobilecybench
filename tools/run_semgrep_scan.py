#!/usr/bin/env python3
"""
Run Semgrep against an app codebase and stash the JSON report under
apps/<app>/static_vuln_reports/semgrep/report.json.

Usage:
    python tools/run_semgrep_scan.py joplin
    python tools/run_semgrep_scan.py joplin --source-dir apps/joplin/codebase --config p/security-audit
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def _setup_logger(verbose: bool) -> logging.Logger:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - Semgrep - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("SemgrepScan")


def _default_source_dir(app_dir: Path) -> Path:
    codebase_dir = app_dir / "codebase"
    return codebase_dir if codebase_dir.exists() else app_dir


def run_semgrep_scan(
    app_name: str,
    source_dir: Path,
    output_dir: Path,
    config: str,
    severities: list[str],
    extra_args: list[str],
    logger: logging.Logger,
) -> Path:
    if not source_dir.exists():
        raise SystemExit(f"Source directory not found: {source_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"
    log_path = output_dir / "scan.log"

    cmd = [
        "semgrep",
        "scan",
        str(source_dir),
        "--config",
        config,
        "--json",
        "--output",
        str(report_path),
    ]
    for sev in severities:
        cmd.extend(["--severity", sev])
    if extra_args:
        cmd.extend(extra_args)

    logger.info("Running Semgrep for %s", app_name)
    logger.debug("Command: %s", " ".join(cmd))

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=ROOT_DIR,
    )

    log_path.write_text(f"STDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}\n")

    if proc.returncode != 0:
        raise SystemExit(
            f"Semgrep failed with exit code {proc.returncode}. See {log_path}"
        )

    if not report_path.exists():
        raise SystemExit(
            f"Semgrep completed but {report_path} was not created. See {log_path}"
        )

    # Validate JSON early to avoid surprises later
    try:
        json.loads(report_path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Semgrep produced invalid JSON: {exc}") from exc

    logger.info("Semgrep report stored at %s", report_path)
    return report_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run Semgrep on an app's codebase and stash the JSON report."
    )
    parser.add_argument("app_name", help="App directory name under apps/")
    parser.add_argument(
        "--source-dir",
        help="Path to scan (default: apps/<app>/codebase if it exists, otherwise apps/<app>)",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory for scan artifacts (default: apps/<app>/static_vuln_reports/semgrep)",
    )
    parser.add_argument(
        "--config",
        default="auto",
        help="Semgrep config (default: auto). Examples: p/security-audit, p/owasp-top-ten",
    )
    parser.add_argument(
        "--severity",
        action="append",
        default=["ERROR", "WARNING"],
        help="Severity filter (repeatable). Defaults to ERROR and WARNING.",
    )
    parser.add_argument(
        "--extra-args",
        nargs=argparse.REMAINDER,
        help="Additional flags to pass directly to semgrep (placed at the end of the command).",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logger = _setup_logger(args.verbose)

    app_dir = ROOT_DIR / "apps" / args.app_name
    if not app_dir.exists():
        logger.error("App directory not found: %s", app_dir)
        return 1

    source_dir = (
        Path(args.source_dir) if args.source_dir else _default_source_dir(app_dir)
    )
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else app_dir / "static_vuln_reports" / "semgrep"
    )

    try:
        run_semgrep_scan(
            app_name=args.app_name,
            source_dir=source_dir,
            output_dir=output_dir,
            config=args.config,
            severities=args.severity,
            extra_args=args.extra_args or [],
            logger=logger,
        )
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        logger.exception("Failed to run Semgrep: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
