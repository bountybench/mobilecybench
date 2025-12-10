#!/usr/bin/env python3
"""Execute MobSFScan against an app's source tree and store the JSON output under
apps/<app>/static_vuln_reports/mobsfscan/.

Usage:
    python tools/run_mobsfscan.py joplin
    python tools/run_mobsfscan.py joplin --source-dir apps/joplin/codebase/packages/app-mobile/android
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def _setup_logger(verbose: bool) -> logging.Logger:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - MobSFScan - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("MobSFScan")


def _default_source_dir(app_dir: Path) -> Path:
    codebase_dir = app_dir / "codebase"
    if codebase_dir.exists():
        return codebase_dir
    return app_dir


def run_mobsfscan(
    app_name: str,
    source_dir: Path,
    output_dir: Path,
    extra_args: list[str],
    mobsfscan_bin: str,
    logger: logging.Logger,
) -> Path:
    if not source_dir.exists():
        raise SystemExit(f"Source directory not found: {source_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"
    log_path = output_dir / "scan.log"

    cmd = [
        mobsfscan_bin,
        str(source_dir),
        "--json",
        "--output",
        str(report_path),
    ]
    if extra_args:
        cmd.extend(extra_args)

    logger.info("Running MobSFScan for %s", app_name)
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
            f"MobSFScan failed with exit code {proc.returncode}. See {log_path}"
        )

    if not report_path.exists():
        raise SystemExit(
            f"MobSFScan completed but {report_path} was not created. See {log_path}"
        )

    logger.info("MobSFScan report stored at %s", report_path)
    return report_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run MobSFScan on an app's codebase and stash the JSON report."
    )
    parser.add_argument("app_name", help="App directory name under apps/")
    parser.add_argument(
        "--source-dir",
        help="Path to scan (default: apps/<app>/codebase if it exists, otherwise apps/<app>)",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory for scan artifacts (default: apps/<app>/static_vuln_reports/mobsfscan)",
    )
    parser.add_argument(
        "--mobsfscan-bin",
        default="mobsfscan",
        help="MobSFScan executable or module (default: mobsfscan)",
    )
    parser.add_argument(
        "--extra-args",
        nargs=argparse.REMAINDER,
        help="Additional flags to pass directly to mobsfscan (placed at the end of the command).",
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
        else app_dir / "static_vuln_reports" / "mobsfscan"
    )

    try:
        run_mobsfscan(
            app_name=args.app_name,
            source_dir=source_dir,
            output_dir=output_dir,
            extra_args=args.extra_args or [],
            mobsfscan_bin=args.mobsfscan_bin,
            logger=logger,
        )
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        logger.exception("Failed to run MobSFScan: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
