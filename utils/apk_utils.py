"""APK building and handling utilities."""

from pathlib import Path

from utils.logger import logger

BUILD_COMMAND_TIMEOUT = 1200  # 20 minutes


def setup_apk(app_dir: Path, build_type: str, project_root: Path) -> None:
    """
    Build or download the APK based on build_type.

    Args:
        app_dir: Application directory
        build_type: One of "source", "download-apk", "skip-apk"
        project_root: Project root directory
    """
    from utils.command_executor import CommandExecutor

    cmd = CommandExecutor()

    if build_type == "skip-apk":
        logger.info("Skipping APK handling step")
        return

    if build_type == "download-apk":
        logger.info("Downloading APK...")
        setup_script = project_root / "setup_app_apklink.py"
        app_name = app_dir.name
        cmd.run_with_progress(
            f"python3 {setup_script} {app_name}",
            timeout=BUILD_COMMAND_TIMEOUT,
            message="Downloading APK",
            cwd=project_root,
        )
    else:  # source
        logger.info("Building APK from source...")
        cmd.run_with_progress(
            "bash ./setup_app_source.sh",
            timeout=BUILD_COMMAND_TIMEOUT,
            message="Building APK from source",
            cwd=app_dir,
        )

    # Repackage with honeypot activity
    logger.info("Repackaging APK with honeypot activity...")
    app_name = app_dir.name
    cmd.run_with_progress(
        f"bash ../../utils/repackage_apk.sh apk/{app_name}.apk",
        timeout=BUILD_COMMAND_TIMEOUT,
        message="Repackaging APK",
        cwd=app_dir,
    )
