"""Emulator certificate management for local HTTPS backends."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from utils.logger import logger

INJECT_CA_TIMEOUT = 60


def inject_system_ca(project_root: Path, device_id: Optional[str] = None) -> None:
    """Add shared CA cert to emulator trust store so apps trust local HTTPS backends."""
    script = project_root / "utils" / "inject_system_ca.sh"
    if not script.exists():
        logger.warning(f"CA injection script not found: {script}")
        return

    env = os.environ.copy()
    if device_id:
        env["ANDROID_SERIAL"] = device_id

    logger.info("Injecting system CA certificate...")
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True,
        timeout=INJECT_CA_TIMEOUT, env=env,
    )
    if result.returncode != 0:
        logger.error(f"CA injection failed: {result.stderr}")
        raise RuntimeError("System CA injection failed")
    logger.info("System CA injected successfully")
