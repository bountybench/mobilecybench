"""Utilities for synthetic vulnerability handling."""

import subprocess
from pathlib import Path

from utils.logger import logger


def find_synthetic_patches(app_dir: Path) -> list[Path]:
    """
    Find all synthetic vulnerability patch files.

    Args:
        app_dir: Application directory

    Returns:
        List of patch file paths
    """
    synth_root = app_dir / "synthetic_vulnerabilities"
    if not synth_root.exists():
        return []

    vuln_dirs = sorted(
        p for p in synth_root.glob("*") if p.is_dir() and not p.name.startswith(".")
    )
    patch_paths = [p / "vulnerability.patch" for p in vuln_dirs]
    return [p for p in patch_paths if p.exists()]


def apply_synthetic_patch(app_dir: Path, patch_paths: list[Path]) -> None:
    """
    Apply synthetic vulnerability patches to the codebase.

    Args:
        app_dir: Application directory
        patch_paths: List of patch file paths to apply
    """
    if not patch_paths:
        return

    codebase_dir = app_dir / "codebase"
    if not codebase_dir.exists():
        codebase_dir = app_dir

    for patch_path in patch_paths:
        logger.info(f"Applying synthetic patch: {patch_path}")
        result = subprocess.run(
            ["git", "apply", str(patch_path)],
            cwd=codebase_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.info(f"Patch did not apply: {result.stderr.strip()}")
            logger.info("This is fine if patch is already applied or codebase is dirty")
        else:
            logger.info("Patch applied successfully")
