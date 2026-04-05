"""Host-based malicious APK replay: build, install, run, collect evidence.

No Docker container needed — the host builds the APK and deploys via ADB.
The APK runs in the Android sandbox on the emulator.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from utils.logger import logger

PACKAGE = "com.mobilecybench.exploit"
RUNNER = f"{PACKAGE}/.ExploitRunner"
APK_FILENAME = f"{PACKAGE}.apk"
EVIDENCE_DEVICE_DIR = f"/sdcard/Android/data/{PACKAGE}/files"


@dataclass
class EvidenceBundle:
    """Evidence collected from the emulator after an exploit runs."""

    instrument_stdout: str = ""
    logcat: str = ""
    evidence_dir: Path | None = None  # local dir with pulled files (may not exist)


@dataclass
class ReplayResult:
    """Result of a single malicious APK replay."""

    exit_code: int
    evidence: EvidenceBundle
    evidence_log_path: Path | None = None
    build_stdout: str = ""
    # TODO: permissions: PermissionProfile — classify and log declared permissions


def build_apk(project_dir: Path) -> Path:
    """Run build_exploit_apk.sh and return the path to the built APK.

    Raises RuntimeError if the build fails or APK not found.
    """
    build_script = project_dir / "build_exploit_apk.sh"
    if not build_script.exists():
        raise RuntimeError(f"Build script not found: {build_script}")

    logger.info("Building exploit APK...")
    proc = subprocess.run(
        ["bash", str(build_script)],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        logger.error(f"APK build failed (exit {proc.returncode})")
        if proc.stderr:
            logger.error(f"stderr: {proc.stderr}")
        raise RuntimeError(
            f"APK build failed (exit {proc.returncode}): {proc.stderr or proc.stdout}"
        )

    apk_path = project_dir / "dist" / APK_FILENAME
    if not apk_path.exists():
        raise RuntimeError(f"Build succeeded but APK not found at {apk_path}")

    logger.info(f"Built {apk_path}")
    return apk_path


def uninstall(package: str = PACKAGE) -> None:
    """Uninstall the attacker APK. Ignores errors (may not be installed)."""
    subprocess.run(
        ["adb", "uninstall", package],
        capture_output=True,
        text=True,
    )


def install_apk(apk_path: Path, package: str = PACKAGE) -> None:
    """Install APK on emulator. Uninstalls first for clean state."""
    uninstall(package)
    logger.info(f"Installing {apk_path}...")
    proc = subprocess.run(
        ["adb", "install", "-r", str(apk_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"adb install failed: {proc.stderr or proc.stdout}")

    # TODO: grant runtime permissions via `adb shell pm grant`
    # For now, install-time permissions are auto-granted by Android.
    # Runtime (dangerous) permissions will be added in a future step.


def run_instrument(
    package: str = PACKAGE,
    runner: str = RUNNER,
    timeout: int = 60,
) -> tuple[int, str]:
    """Run am instrument -w and return (exit_code, stdout).

    exit_code: 0 = exploit succeeded, non-zero = failed.
    On timeout, returns (1, stdout_so_far).
    """
    cmd = ["adb", "shell", "am", "instrument", "-w", runner]
    logger.info(f"Running exploit via am instrument (timeout={timeout}s)...")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout
    except subprocess.TimeoutExpired as e:
        logger.warning(f"am instrument timed out after {timeout}s")
        stdout = e.stdout.decode() if e.stdout else ""
        return 1, stdout

    # Parse INSTRUMENTATION_CODE from output
    import re

    match = re.search(r"INSTRUMENTATION_CODE:\s*(-?\d+)", stdout)
    if match:
        code = int(match.group(1))
    else:
        logger.warning("Could not parse INSTRUMENTATION_CODE from output")
        code = 1

    return code, stdout


def collect_evidence(phase_dir: Path, instrument_stdout: str) -> EvidenceBundle:
    """Collect all evidence sources from the emulator into phase_dir.

    Sources:
    1. am instrument stdout (already captured)
    2. Logcat entries tagged MOBILECYBENCH
    3. Files written by APK to its external files dir
    """
    # 1. Save instrument stdout
    (phase_dir / "instrument_stdout.txt").write_text(instrument_stdout)

    # 2. Logcat
    proc = subprocess.run(
        ["adb", "logcat", "-d", "-s", "MOBILECYBENCH:*"],
        capture_output=True,
        text=True,
    )
    logcat = proc.stdout or ""
    (phase_dir / "logcat.txt").write_text(logcat)

    # 3. APK evidence files
    evidence_dir = phase_dir / "apk_evidence"
    proc = subprocess.run(
        ["adb", "pull", EVIDENCE_DEVICE_DIR, str(evidence_dir)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # No files written by APK — that's fine
        evidence_dir = None

    return EvidenceBundle(
        instrument_stdout=instrument_stdout,
        logcat=logcat,
        evidence_dir=evidence_dir if evidence_dir and evidence_dir.is_dir() else None,
    )


def assemble_evidence_log(evidence: EvidenceBundle, phase_dir: Path) -> Path:
    """Combine all evidence sources into replay_evidence.log.

    This is the file that probes read to detect leaked secrets/flags.
    Same format as the existing replay_evidence.log from exploit.sh replays.
    """
    parts = []

    if evidence.instrument_stdout:
        parts.append(f"=== am instrument stdout ===\n{evidence.instrument_stdout}")

    if evidence.logcat:
        parts.append(f"=== logcat (MOBILECYBENCH) ===\n{evidence.logcat}")

    if evidence.evidence_dir and evidence.evidence_dir.is_dir():
        for fpath in sorted(evidence.evidence_dir.rglob("*")):
            if fpath.is_file():
                try:
                    text = fpath.read_text(encoding="utf-8", errors="strict")
                    rel = fpath.relative_to(evidence.evidence_dir)
                    parts.append(f"=== apk_evidence/{rel} ===\n{text}")
                except (UnicodeDecodeError, OSError):
                    pass  # skip binary files

    log_path = phase_dir / "replay_evidence.log"
    log_path.write_text("\n".join(parts))
    return log_path


def replay_malicious_apk(
    apk_project_dir: Path,
    phase_dir: Path,
    timeout: int = 60,
) -> ReplayResult:
    """Full replay: build → install → run → collect evidence → uninstall.

    Args:
        apk_project_dir: Path to the APK project (contains build_exploit_apk.sh)
        phase_dir: Where to save replay artifacts
        timeout: Seconds before am instrument is killed

    Returns:
        ReplayResult with exit_code, evidence, and paths to artifacts
    """
    phase_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Build
    logger.info("[replay] Step 1/5: Building exploit APK...")
    apk_path = build_apk(apk_project_dir)
    build_stdout = (
        (apk_project_dir / "dist" / "build.log").read_text()
        if (apk_project_dir / "dist" / "build.log").exists()
        else ""
    )
    (phase_dir / "build_stdout.txt").write_text(build_stdout)
    logger.info(f"[replay] Step 1/5: Build OK → {apk_path.name}")

    # Step 2: Install (uninstalls first for clean state)
    logger.info("[replay] Step 2/5: Installing exploit APK...")
    install_apk(apk_path)
    logger.info("[replay] Step 2/5: Install OK")

    # Step 3: Run instrumentation
    logger.info(f"[replay] Step 3/5: Running am instrument (timeout={timeout}s)...")
    exit_code, instrument_stdout = run_instrument(timeout=timeout)
    status_str = "SUCCEEDED" if exit_code == 0 else "FAILED"
    logger.info(
        f"[replay] Step 3/5: am instrument {status_str} (exit_code={exit_code})"
    )
    if instrument_stdout:
        for line in instrument_stdout.strip().splitlines():
            logger.info(f"[replay]   {line}")

    # Step 4: Collect evidence
    logger.info("[replay] Step 4/5: Collecting evidence (logcat, files)...")
    evidence = collect_evidence(phase_dir, instrument_stdout)
    evidence_log = assemble_evidence_log(evidence, phase_dir)
    logger.info(f"[replay] Step 4/5: Evidence saved to {evidence_log}")

    # Step 5: Uninstall (clean state for next phase)
    logger.info("[replay] Step 5/5: Uninstalling exploit APK...")
    uninstall()
    logger.info("[replay] Step 5/5: Uninstall OK")

    return ReplayResult(
        exit_code=exit_code,
        evidence=evidence,
        evidence_log_path=evidence_log,
        build_stdout=build_stdout,
    )
