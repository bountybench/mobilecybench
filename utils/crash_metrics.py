#!/usr/bin/env python3

"""Collect post-run Android crash metrics for a specific app package."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LOGCAT_TIMESTAMP_RE = re.compile(r"^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)")
DROPBOX_TIMESTAMP_RE = re.compile(
    r"(?:Timestamp:|time:)\s*([0-9T:\-+.Z ]+)", re.IGNORECASE
)
EXCEPTION_RE = re.compile(
    r"\b([A-Za-z0-9_.$]*(?:Exception|Error))(?::\s*([^\n]+))?"
)
PROCESS_RE = re.compile(r"Process:\s*([A-Za-z0-9_.$]+)")
CMDLINE_RE = re.compile(r"Cmd line:\s*([A-Za-z0-9_.$]+)")
CRASH_TAG_RE = re.compile(r"\b(?:data_app_crash|system_app_crash|app_crash)\b")
ANR_TAG_RE = re.compile(r"\b(?:app_anr|anr)\b", re.IGNORECASE)


@dataclass(frozen=True)
class CrashEvent:
    type: str
    timestamp: str | None
    summary: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "timestamp": self.timestamp,
            "summary": self.summary,
            "source": self.source,
        }


def _run_command(args: list[str], timeout: int = 15) -> tuple[str, str | None]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return "", str(exc)

    if result.returncode != 0 and not result.stdout:
        stderr = (result.stderr or "").strip()
        return "", stderr or f"command failed with exit code {result.returncode}"

    return result.stdout or "", None


def _first_timestamp(lines: list[str]) -> str | None:
    for line in lines:
        match = LOGCAT_TIMESTAMP_RE.search(line)
        if match:
            return match.group(1)
        match = DROPBOX_TIMESTAMP_RE.search(line)
        if match:
            return match.group(1).strip()
    return None


def _exception_summary(text: str) -> str | None:
    for line in text.splitlines():
        match = EXCEPTION_RE.search(line)
        if match:
            exc_type = match.group(1)
            detail = (match.group(2) or "").strip()
            return f"{exc_type}: {detail}" if detail else exc_type
    return None


def _process_name(text: str) -> str | None:
    for regex in (PROCESS_RE, CMDLINE_RE):
        match = regex.search(text)
        if match:
            return match.group(1)
    return None


def _build_summary(
    event_type: str,
    package_name: str,
    text: str,
    default_summary: str,
) -> str:
    process_name = _process_name(text)
    exception = _exception_summary(text)

    summary_parts = []
    if exception:
        summary_parts.append(exception)
    if process_name:
        summary_parts.append(f"in {process_name}")
    elif package_name in text:
        summary_parts.append(f"in {package_name}")

    if not summary_parts:
        return default_summary
    return " ".join(summary_parts)


def parse_logcat_crashes(logcat_text: str, package_name: str) -> list[CrashEvent]:
    events: list[CrashEvent] = []
    lines = logcat_text.splitlines()

    for idx, line in enumerate(lines):
        if "FATAL EXCEPTION" not in line:
            continue

        window = lines[idx : idx + 25]
        window_text = "\n".join(window)
        process_name = _process_name(window_text)
        if package_name not in window_text and process_name != package_name:
            continue

        events.append(
            CrashEvent(
                type="FATAL_EXCEPTION",
                timestamp=_first_timestamp(window),
                summary=_build_summary(
                    "FATAL_EXCEPTION",
                    package_name,
                    window_text,
                    f"FATAL EXCEPTION in {package_name}",
                ),
                source="logcat",
            )
        )

    return events


def parse_dropbox_crashes(dropbox_text: str, package_name: str) -> list[CrashEvent]:
    events: list[CrashEvent] = []
    current_section: list[str] = []

    def flush_section() -> None:
        nonlocal current_section
        if not current_section:
            return
        section_text = "\n".join(current_section)
        lowered = section_text.lower()
        if package_name not in section_text:
            current_section = []
            return

        if ANR_TAG_RE.search(lowered):
            event_type = "ANR"
            default_summary = f"ANR detected for {package_name}"
        elif CRASH_TAG_RE.search(lowered):
            event_type = "DROPBOX_CRASH"
            default_summary = f"Crash report detected for {package_name}"
        else:
            current_section = []
            return

        events.append(
            CrashEvent(
                type=event_type,
                timestamp=_first_timestamp(current_section),
                summary=_build_summary(
                    event_type,
                    package_name,
                    section_text,
                    default_summary,
                ),
                source="dropbox",
            )
        )
        current_section = []

    for line in dropbox_text.splitlines():
        if line.startswith("========================================"):
            flush_section()
            continue
        current_section.append(line)

    flush_section()
    return events


def parse_anr_traces(anr_text: str, package_name: str) -> list[CrashEvent]:
    events: list[CrashEvent] = []
    for block in anr_text.split("----- pid"):
        if package_name not in block:
            continue
        if f"Cmd line: {package_name}" not in block and package_name not in block:
            continue
        lines = block.splitlines()
        events.append(
            CrashEvent(
                type="ANR",
                timestamp=_first_timestamp(lines),
                summary=_build_summary(
                    "ANR",
                    package_name,
                    block,
                    f"ANR trace detected for {package_name}",
                ),
                source="anr_traces",
            )
        )
    return events


def _dedupe_events(events: list[CrashEvent]) -> list[CrashEvent]:
    deduped: list[CrashEvent] = []
    seen: set[tuple[str, str | None, str]] = set()

    for event in events:
        key = (event.type, event.timestamp, event.summary)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)

    return deduped


def _load_package_name(app_path: Path) -> str:
    metadata_path = app_path / "metadata.json"
    with open(metadata_path, "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    package_name = metadata.get("package_name")
    if not package_name:
        raise ValueError(f"package_name missing from {metadata_path}")
    return str(package_name)


def _collect_anr_text() -> tuple[str, str | None]:
    listing, error = _run_command(["adb", "shell", "ls", "/data/anr"], timeout=10)
    if error:
        return "", error

    files = [
        line.strip()
        for line in listing.splitlines()
        if line.strip() and "No such file" not in line and "Permission denied" not in line
    ]
    if not files:
        return "", None

    chunks: list[str] = []
    for entry in files[:10]:
        filename = entry.split()[-1]
        path = f"/data/anr/{filename}"
        content, cat_error = _run_command(["adb", "shell", "cat", path], timeout=10)
        if cat_error:
            continue
        chunks.append(f"===== FILE: {filename} =====\n{content}")

    return "\n".join(chunks), None


def collect_crash_report(app_path: Path) -> dict[str, Any]:
    package_name = _load_package_name(app_path)

    logcat_text, logcat_error = _run_command(["adb", "logcat", "-d"], timeout=15)
    dropbox_text, dropbox_error = _run_command(
        ["adb", "shell", "dumpsys", "dropbox", "--print"], timeout=20
    )
    anr_text, anr_error = _collect_anr_text()

    events = _dedupe_events(
        parse_logcat_crashes(logcat_text, package_name)
        + parse_dropbox_crashes(dropbox_text, package_name)
        + parse_anr_traces(anr_text, package_name)
    )

    report: dict[str, Any] = {
        "package_name": package_name,
        "crashes_detected": len(events),
        "crash_events": [event.to_dict() for event in events],
    }

    probe_errors = {
        key: value
        for key, value in {
            "logcat": logcat_error,
            "dropbox": dropbox_error,
            "anr_traces": anr_error,
        }.items()
        if value
    }
    if probe_errors:
        report["probe_errors"] = probe_errors

    return report


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: crash_metrics.py <app_path>", file=sys.stderr)
        return 1

    app_path = Path(sys.argv[1]).resolve()
    if not app_path.is_dir():
        print(f"ERROR: App path '{app_path}' is not a directory.", file=sys.stderr)
        return 1

    try:
        report = collect_crash_report(app_path)
    except Exception as exc:
        print(f"ERROR: Failed to collect crash metrics: {exc}", file=sys.stderr)
        return 1

    output_path = app_path / "crash_report.json"
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
