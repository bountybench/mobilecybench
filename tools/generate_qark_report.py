#!/usr/bin/env python3
"""
Helper script to run QARK against a built APK and stash the report under apps/<app>/static_vuln_reports/qark/.

Example:
    python tools/generate_qark_report.py joplin
    python tools/generate_qark_report.py joplin --apk apps/joplin/apk/joplin.apk --report-type json
"""

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_TYPE = "json"


def _setup_logger(verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - QARKReport - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("QARKReport")


def _import_qark(logger: logging.Logger):
    try:
        from qark import qark as qark_cli
        from qark import report as qark_report_module
        from qark.report import Report
    except ImportError as exc:
        logger.error("QARK is not installed. pip install qark==4.0.0")
        raise SystemExit(1) from exc

    return qark_cli, qark_report_module, Report


def _prepare_report_dir(report_dir: Path, report_type: str):
    report_dir.mkdir(parents=True, exist_ok=True)
    build_dir = report_dir / ".qark_build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    for report_file in report_dir.glob("report.*"):
        report_file.unlink()

    return build_dir


def _cleanup_artifacts(report_dir: Path):
    build_dir = report_dir / ".qark_build"
    shutil.rmtree(build_dir, ignore_errors=True)

    classes_zip_names = {
        Path.cwd() / "classes-error.zip",
        report_dir / "classes-error.zip",
        report_dir.parent / "classes-error.zip",
    }
    for zip_path in classes_zip_names:
        if zip_path.exists():
            zip_path.unlink()


def run_qark(app_name: str, apk_path: Path, report_dir: Path, report_type: str, logger):
    if not apk_path.exists():
        logger.error("APK not found: %s", apk_path)
        raise SystemExit(1)

    qark_cli, qark_report_module, Report = _import_qark(logger)

    build_dir = _prepare_report_dir(report_dir, report_type)

    # Force QARK to write reports into our target directory
    qark_report_module.DEFAULT_REPORT_PATH = os.path.join(str(report_dir), "")
    if hasattr(Report, "_Report__instance"):
        Report._Report__instance = None

    qark_args = [
        "--apk",
        str(apk_path),
        "--report-type",
        report_type,
        "--build-path",
        str(build_dir),
        "--no-debug",
    ]

    logger.info("Running QARK for %s", app_name)
    logger.debug("qark %s", " ".join(qark_args))

    try:
        qark_cli.cli.main(args=qark_args, prog_name="qark", standalone_mode=False)
    except SystemExit as exc:
        _cleanup_artifacts(report_dir)
        if exc.code not in (0, None):
            logger.error("QARK exited with code %s", exc.code)
            raise
    except Exception:
        _cleanup_artifacts(report_dir)
        raise

    report_file = report_dir / f"report.{report_type}"
    if not report_file.exists():
        _cleanup_artifacts(report_dir)
        logger.error("QARK finished but %s was not generated", report_file)
        raise SystemExit(1)

    _cleanup_artifacts(report_dir)
    logger.info("Report generated at %s", report_file)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run QARK against an app APK and store report.json under apps/<app>/static_vuln_reports/qark/."
    )
    parser.add_argument(
        "app_name",
        help="App directory name under apps/",
    )
    parser.add_argument(
        "--apk",
        help="Path to APK. Defaults to apps/<app>/apk/<app>.apk",
    )
    parser.add_argument(
        "--report-type",
        default=DEFAULT_REPORT_TYPE,
        choices=["json", "html", "xml", "csv"],
        help="Report type to generate (default: json)",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory to store report.* (default: apps/<app>/static_vuln_reports/qark)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logger = _setup_logger(args.verbose)

    app_dir = ROOT_DIR / "apps" / args.app_name
    if not app_dir.exists():
        logger.error("App directory not found: %s", app_dir)
        return 1

    if args.apk:
        apk_path = Path(args.apk)
    else:
        apk_path = app_dir / "apk" / f"{args.app_name}.apk"

    report_dir = (
        Path(args.output_dir)
        if args.output_dir
        else app_dir / "static_vuln_reports" / "qark"
    )
    if report_dir.exists():
        _cleanup_artifacts(
            report_dir
        )  # cleanup old artificats before generating new report

    try:
        run_qark(
            app_name=args.app_name,
            apk_path=apk_path,
            report_dir=report_dir,
            report_type=args.report_type,
            logger=logger,
        )
    except SystemExit as exc:
        return exc.code or 1
    except Exception as exc:
        logger.exception("Unexpected failure while running QARK: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
