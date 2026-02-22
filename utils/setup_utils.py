"""Runtime setup utilities for app installation and backend configuration."""

import shlex
import subprocess
from pathlib import Path
from typing import Optional

from utils.logger import logger

BUILD_COMMAND_TIMEOUT = 1200  # 20 minutes
EMULATOR_BOOT_TIMEOUT_SECONDS = 300
INJECT_CA_TIMEOUT = 30


def inject_system_ca(project_root: Path, device_id: Optional[str] = None) -> None:
    """Add shared CA cert to emulator trust store so apps trust local HTTPS backends."""
    script = project_root / "utils" / "inject_system_ca.sh"
    if not script.exists():
        logger.warning(f"CA injection script not found: {script}")
        return

    cmd = ["bash", str(script)]
    if device_id:
        cmd += ["-s", device_id]

    logger.info("Injecting system CA certificate...")
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=INJECT_CA_TIMEOUT
    )
    if result.returncode != 0:
        logger.error(f"CA injection failed: {result.stderr}")
        raise RuntimeError("System CA injection failed")
    logger.info("System CA injected successfully")


def install_app_and_setup_backend(
    app_dir: Path,
    emulator,
    project_root: Path,
    start_ssrf: bool = False,
    apk_path: Optional[Path] = None,
    inject_flags: bool = True,
) -> None:
    """
    Install the app and set up backend services.

    Args:
        app_dir: Application directory
        emulator: EmulatorManager instance
        project_root: Project root directory
        start_ssrf: Whether to start the SSRF listener (discovery mode only)
        apk_path: Optional path to APK file (passed to start_runtime.sh --apk)
        inject_flags: Whether to inject security flags (discovery mode only)
    """
    from utils.command_executor import CommandExecutor
    from utils.utils import get_app_metadata

    cmd = CommandExecutor()

    # Wait for emulator
    logger.info("Waiting for emulator to be ready...")
    emulator.wait_until_ready(timeout=EMULATOR_BOOT_TIMEOUT_SECONDS)
    logger.info("Emulator booted successfully")

    if not emulator.check_status():
        raise RuntimeError("Emulator status check failed")
    logger.info("Emulator status verified")

    # Inject system CA so apps trust local HTTPS backends
    inject_system_ca(project_root, emulator.device_id)

    # Prefer start_runtime.sh (new pattern), fall back to setup.sh (legacy)
    runtime_script = app_dir / "start_runtime.sh"
    legacy_script = app_dir / "setup.sh"

    logger.info("Setting up backend and installing APK...")
    if runtime_script.exists():
        runtime_cmd = "bash ./start_runtime.sh"
        if apk_path:
            runtime_cmd += f" --apk {shlex.quote(str(apk_path))}"
        cmd.run_with_progress(
            runtime_cmd,
            timeout=BUILD_COMMAND_TIMEOUT,
            message="Setting up backend and installing APK",
            cwd=app_dir,
        )
    elif legacy_script.exists():
        logger.info("Using legacy setup.sh")
        cmd.run_with_progress(
            "bash ./setup.sh",
            timeout=BUILD_COMMAND_TIMEOUT,
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
        inject_flags_path = project_root / "inject_flags.sh"
        cmd.run(
            f"bash {inject_flags_path}",
            cwd=app_dir,
            timeout=30,
        )
        logger.info("Flags injected successfully")

    # Start SSRF listener if requested (discovery mode only)
    if start_ssrf:
        app_name = app_dir.name
        metadata = get_app_metadata(app_name)
        container_names = metadata.get("container_names", [])

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
