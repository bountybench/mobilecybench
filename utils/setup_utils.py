"""Runtime setup utilities for app installation and backend configuration."""

from pathlib import Path

from utils.logger import logger

BUILD_COMMAND_TIMEOUT = 1200  # 20 minutes
EMULATOR_BOOT_TIMEOUT_SECONDS = 300


def install_app_and_setup_backend(
    app_dir: Path,
    emulator,
    project_root: Path,
    start_ssrf: bool = False,
) -> None:
    """
    Install the app and set up backend services.

    Args:
        app_dir: Application directory
        emulator: EmulatorManager instance
        project_root: Project root directory
        start_ssrf: Whether to start the SSRF listener (discovery mode only)
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

    # Prefer start_runtime.sh (new pattern), fall back to setup.sh (legacy)
    runtime_script = app_dir / "start_runtime.sh"
    legacy_script = app_dir / "setup.sh"

    logger.info("Setting up backend and installing APK...")
    if runtime_script.exists():
        cmd.run_with_progress(
            "bash ./start_runtime.sh",
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

    # Inject flags
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
