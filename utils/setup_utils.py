"""Runtime setup utilities for app installation and backend configuration."""

import shlex
import subprocess
import time
from pathlib import Path
from typing import Optional

from utils.logger import logger

_ADB_READY_TIMEOUT_SECONDS = 120
_INJECT_FLAGS_TIMEOUT_SECONDS = 180


def _adb_command_ok(args: list[str], timeout: int = 10) -> bool:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _adb_command_stdout(args: list[str], timeout: int = 10) -> str | None:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _wait_for_adb_ready(timeout: int = _ADB_READY_TIMEOUT_SECONDS) -> bool:
    """Wait for adb to accept commands after runtime scripts perturb the emulator."""
    deadline = time.time() + timeout
    restarted_server = False

    while time.time() < deadline:
        state = _adb_command_stdout(["adb", "get-state"], timeout=10)
        if (
            _adb_command_ok(["adb", "wait-for-device"], timeout=10)
            and state is not None
            and state.strip() == "device"
            and _adb_command_ok(["adb", "shell", "true"], timeout=10)
        ):
            return True

        if not restarted_server:
            logger.warning("ADB health check failed; restarting adb server once")
            _adb_command_ok(["adb", "kill-server"], timeout=10)
            _adb_command_ok(["adb", "-a", "start-server"], timeout=10)
            restarted_server = True

        time.sleep(2)

    return False


def install_app_and_setup_backend(
    app_dir: Path,
    emulator,
    project_root: Path,
    *,
    build_command_timeout: int,
    start_ssrf: bool = False,
    container_names: list[str] | None = None,
    apk_path: Optional[Path] = None,
    inject_flags: bool = True,
) -> None:
    """
    Install the app and set up backend services.
    Expects the emulator to be booted and ready.

    Args:
        app_dir: Application directory
        emulator: EmulatorManager instance
        project_root: Project root directory
        start_ssrf: Whether to start the SSRF listener (discovery mode only)
        container_names: Backend container names (required when start_ssrf=True)
        apk_path: Optional path to APK file (passed to start_runtime.sh --apk)
        inject_flags: Whether to inject security flags (discovery mode only)
    """
    from utils.command_executor import CommandExecutor

    cmd = CommandExecutor()

    # Sanity check: emulator should already be booted by the workflow caller
    if not emulator.check_status():
        raise RuntimeError("Emulator status check failed")
    logger.info("Emulator status verified")

    # Prefer start_runtime.sh (new pattern), fall back to setup.sh (legacy)
    runtime_script = app_dir / "start_runtime.sh"
    legacy_script = app_dir / "setup.sh"

    if runtime_script.exists():
        runtime_cmd = "bash ./start_runtime.sh"
        if apk_path:
            runtime_cmd += f" --apk {shlex.quote(str(apk_path))}"
        cmd.run_with_progress(
            runtime_cmd,
            timeout=build_command_timeout,
            message="Setting up backend and installing APK",
            cwd=app_dir,
        )
    elif legacy_script.exists():
        logger.info("Using legacy setup.sh")
        cmd.run_with_progress(
            "bash ./setup.sh",
            timeout=build_command_timeout,
            message="Setting up backend and installing APK",
            cwd=app_dir,
        )
    else:
        raise FileNotFoundError(
            f"No runtime script found in {app_dir}. "
            "Expected start_runtime.sh or setup.sh"
        )

    # Inject flags (discovery mode only; exploit uses verify_files)
    if inject_flags:
        logger.info("Injecting security flags...")
        if not _wait_for_adb_ready():
            raise RuntimeError("ADB did not become ready before flag injection")
        inject_flags_path = project_root / "inject_flags.sh"
        cmd.run(
            f"bash {inject_flags_path}",
            cwd=app_dir,
            timeout=_INJECT_FLAGS_TIMEOUT_SECONDS,
        )
        logger.info("Flags injected successfully")

    # Start SSRF listener if requested (discovery mode only)
    if start_ssrf:
        if container_names:
            from utils.ssrf_utils import start_ssrf_listener

            logger.info("Starting SSRF listener...")
            ssrf_compose_dir = project_root / "evaluation" / "ssrf_listener"
            if start_ssrf_listener(ssrf_compose_dir):
                logger.info("SSRF listener started successfully")
            else:
                logger.warning("Failed to start SSRF listener")
        else:
            logger.info("No backend containers - skipping SSRF listener")


def check_connectivity(container, app_server: Optional[str] = None) -> None:
    """Verify the kali container can reach the app server and emulator.

    Raises RuntimeError if any check fails.

    Args:
        container: Docker container to run checks from.
        app_server: App server URL to check (e.g. "server:8080"). Skipped if None.
    """
    checks = []

    # Kali → app server (if configured)
    # Use nc for a raw TCP check — works for any protocol (HTTP, XMPP, etc.)
    if app_server:
        # Strip scheme (e.g. "http://server:8080" → "server:8080")
        server = app_server.split("://", 1)[-1]
        host, port = server.rsplit(":", 1)
        nc_cmd = f"nc -z -w 10 {host} {port}"
        result = container.exec_run(f"bash -c '{nc_cmd}'")
        checks.append(("kali → app_server", result.exit_code == 0, nc_cmd))

    # Kali → emulator (via ADB). ADB_SERVER_SOCKET is inherited from
    # container env (set by setup_agent_environment to tcp:adb-proxy:5037).
    result = container.exec_run("bash -c 'adb devices'", demux=True)
    stdout = result.output[0].decode() if result.output[0] else ""
    checks.append(("kali → emulator (adb)", "emulator" in stdout, stdout.strip()))

    # Host → emulator (for verify scripts that run on host)
    try:
        host_result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        checks.append(
            (
                "host → emulator (adb)",
                "emulator" in host_result.stdout,
                host_result.stdout.strip(),
            )
        )
    except Exception as e:
        checks.append(("host → emulator (adb)", False, str(e)))

    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        logger.info(f"  Connectivity [{status}]: {name} — {detail}")

    failed = [name for name, passed, _ in checks if not passed]
    if failed:
        raise RuntimeError(f"Connectivity check failed: {', '.join(failed)}")
