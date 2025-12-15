"""
LLM-based Android app structure detection.

Uses LLM to analyze directory structure and identify:
- Main AndroidManifest.xml location
- Primary source directories
- Build variant/flavor
- Multi-module structure

Results cached in metadata.json for future runs.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

from langchain_openai import ChatOpenAI

from utils.logger import logger


def detect_app_structure(app_path: str, package_name: str) -> Dict[str, any]:
    """
    Detect Android app structure using LLM.

    Steps:
    1. Check if metadata.json already has structure info
    2. If not, analyze directory tree with LLM
    3. Cache result in metadata.json

    Args:
        app_path: Path to app directory (e.g., "apps/home-assistant-android")
        package_name: Expected package name

    Returns:
        Dict with structure info:
        {
            "manifest_path": "codebase/app/src/main/AndroidManifest.xml",
            "source_dirs": ["codebase/app/src/main", "codebase/common/src/main"],
            "primary_module": "app",
            "build_variant": "release"
        }
    """
    # Check if already detected and cached
    metadata_path = Path(app_path) / "metadata.json"

    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)

        # If structure already detected, return it
        if "manifest_path" in metadata and "source_dirs" in metadata:
            logger.info(f"Using cached structure from metadata.json")
            return {
                "manifest_path": metadata["manifest_path"],
                "source_dirs": metadata["source_dirs"],
                "primary_module": metadata.get("primary_module", "app"),
                "build_variant": metadata.get("build_variant", "release"),
            }

    # Detect with LLM
    logger.info(f"Detecting app structure with LLM for {package_name}...")

    # Get directory tree
    tree = get_directory_tree(app_path)

    # Detect with LLM
    structure = detect_with_llm(app_path, package_name, tree)

    # Save to metadata.json
    save_structure_to_metadata(app_path, structure)

    logger.info(f"Structure detected and cached:")
    logger.info(f"  Manifest: {structure['manifest_path']}")
    logger.info(f"  Source dirs: {structure['source_dirs']}")

    return structure


def get_directory_tree(app_path: str, max_depth: int = 4) -> str:
    """
    Get directory tree structure for LLM analysis.

    Args:
        app_path: Path to app directory
        max_depth: Maximum depth to traverse

    Returns:
        String representation of directory tree
    """
    app_path = Path(app_path)

    # Focus on codebase subdirectory if it exists
    if (app_path / "codebase").exists():
        root = app_path / "codebase"
    else:
        root = app_path

    lines = []

    def traverse(path: Path, prefix: str = "", depth: int = 0):
        if depth > max_depth:
            return

        try:
            entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        except PermissionError:
            return

        # Filter out common noise
        skip_dirs = {
            "build",
            ".gradle",
            ".idea",
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
        }
        skip_files = {".DS_Store", ".gitignore", "gradlew", "gradlew.bat"}

        entries = [
            e
            for e in entries
            if e.name not in skip_dirs and e.name not in skip_files
        ]

        # Limit entries per directory
        if len(entries) > 20:
            entries = entries[:20]

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            current_prefix = "└── " if is_last else "├── "
            lines.append(f"{prefix}{current_prefix}{entry.name}")

            if entry.is_dir():
                extension = "    " if is_last else "│   "
                traverse(entry, prefix + extension, depth + 1)

    lines.append(root.name + "/")
    traverse(root)

    return "\n".join(lines[:200])  # Limit total lines


def detect_with_llm(app_path: str, package_name: str, tree: str) -> Dict[str, any]:
    """
    Use LLM to detect app structure from directory tree.

    Args:
        app_path: Path to app directory
        package_name: Expected package name
        tree: Directory tree string

    Returns:
        Dict with detected structure
    """
    llm = ChatOpenAI(model="gpt-5.1", temperature=0)
    # llm = ChatOpenAI(model="gpt-5-mini", temperature=0) # should be smart enough

    prompt = f"""You are analyzing an Android app directory structure.

**App Path:** {app_path}
**Package Name:** {package_name}

**Directory Tree:**
```
{tree}
```

**Task:**
Identify the correct paths for analyzing this Android app:

1. **manifest_path**: Path to the MAIN AndroidManifest.xml (relative to app_path)
   - Prefer: src/main/AndroidManifest.xml (not debug/test variants)
   - If multi-module: look for "app" module
   - Avoid: test/, debug/, build/, gradle/

2. **source_dirs**: List of source directories to index (relative to app_path)
   - Main app source: typically app/src/main or src/main
   - Include shared modules: common/, library/, core/ if they exist
   - Avoid: test/, androidTest/, debug/

3. **primary_module**: Name of primary app module (usually "app" or root)

4. **build_variant**: Build variant if multiple exist (release/debug, or flavor name)

**Important:**
- If "codebase" subdirectory exists, paths should include it (e.g., "codebase/app/src/main")
- Focus on PRODUCTION code (src/main), not test code
- For multi-module projects, include all relevant modules

**Return ONLY valid JSON (no markdown, no explanation):**
{{
  "manifest_path": "path/to/main/AndroidManifest.xml",
  "source_dirs": ["path/to/src1", "path/to/src2"],
  "primary_module": "app",
  "build_variant": "release"
}}
"""

    try:
        response = llm.invoke(prompt)
        content = response.content.strip()

        # Remove markdown code blocks if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        # Parse JSON
        structure = json.loads(content)

        # Validate required fields
        if "manifest_path" not in structure or "source_dirs" not in structure:
            raise ValueError("LLM response missing required fields")

        # Validate paths exist
        manifest_full = Path(app_path) / structure["manifest_path"]
        if not manifest_full.exists():
            logger.warning(
                f"LLM suggested manifest doesn't exist: {structure['manifest_path']}"
            )
            # Try fallback
            structure = fallback_detection(app_path)

        return structure

    except Exception as e:
        logger.error(f"LLM structure detection failed: {e}")
        logger.warning("Using fallback heuristics...")
        return fallback_detection(app_path)


def fallback_detection(app_path: str) -> Dict[str, any]:
    """
    Fallback heuristics if LLM fails.

    Args:
        app_path: Path to app directory

    Returns:
        Dict with best-guess structure
    """
    app_path = Path(app_path)

    # Check for codebase subdirectory
    if (app_path / "codebase").exists():
        base = app_path / "codebase"
        prefix = "codebase/"
    else:
        base = app_path
        prefix = ""

    # Try common patterns
    candidates = [
        {
            "manifest_path": f"{prefix}app/src/main/AndroidManifest.xml",
            "source_dirs": [f"{prefix}app/src/main"],
        },
        {
            "manifest_path": f"{prefix}src/main/AndroidManifest.xml",
            "source_dirs": [f"{prefix}src/main"],
        },
    ]

    for candidate in candidates:
        manifest_full = app_path / candidate["manifest_path"]
        if manifest_full.exists():
            logger.info(f"Fallback found manifest at: {candidate['manifest_path']}")

            # Check for common/ module
            common_path = base / "common/src/main"
            if common_path.exists():
                candidate["source_dirs"].append(f"{prefix}common/src/main")

            return {
                **candidate,
                "primary_module": "app",
                "build_variant": "release",
            }

    # Last resort: return empty
    logger.error("Could not detect app structure")
    return {
        "manifest_path": "",
        "source_dirs": [],
        "primary_module": "app",
        "build_variant": "release",
    }


def save_structure_to_metadata(app_path: str, structure: Dict[str, any]) -> None:
    """
    Save detected structure to metadata.json.

    Args:
        app_path: Path to app directory
        structure: Detected structure dict
    """
    metadata_path = Path(app_path) / "metadata.json"

    # Load existing metadata or create new
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)
    else:
        metadata = {}

    # Update with structure info
    metadata["manifest_path"] = structure["manifest_path"]
    metadata["source_dirs"] = structure["source_dirs"]
    metadata["primary_module"] = structure["primary_module"]
    metadata["build_variant"] = structure["build_variant"]

    # Save
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"Structure cached to {metadata_path}")
