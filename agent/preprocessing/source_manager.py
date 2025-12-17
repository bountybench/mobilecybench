
import os
from pathlib import Path
from typing import Dict, List

from utils.logger import logger


def get_source_files(app_path: str, source_dirs: List[str] = None) -> Dict[str, List[str]]:
    """
    Deterministically discover source and resource files.

    Logic:
    1. Scan codebase for standard source roots (src/main/java, src/main/kotlin).
    2. Collect Polyglot files (JS, TS, Vue, CPP) from codebase (excluding build).
    3. Collect Critical Resources (strings.xml, network_security_config).
    
    Args:
        app_path: Root of apps/<app-name>
        source_dirs: Optional overrides (unused in deterministic mode, kept for compat)

    Returns:
        Dict: {
            "java_kotlin_files": ["/abs/path/to/A.java", ...],
            "polyglot_files": ["/abs/path/to/script.js", ...],
            "resource_files": ["/abs/path/to/strings.xml", ...]
        }
    """
    app_path = Path(app_path)
    codebase_path = app_path / "codebase"
    
    # 1. Define Standard Source Extensions
    src_extensions = {".java", ".kt"}
    polyglot_extensions = {".js", ".jsx", ".ts", ".tsx", ".vue", ".html", ".cpp", ".h", ".c"}
    resource_names = {"strings.xml", "network_security_config.xml"} # Targeted resources
    
    # Files to ignore strictly
    skip_dirs = {
        "build", "bin", "generated", ".gradle", ".git", "test", "androidTest", 
        "node_modules", ".idea", "__pycache__"
    }

    java_kotlin_files = []
    polyglot_files = []
    resource_files = []

    if not codebase_path.exists():
        logger.error(f"Codebase path not found: {codebase_path}")
        return {
            "java_kotlin_files": [],
            "polyglot_files": [],
            "resource_files": []
        }

    # 2. Recursive Walk
    logger.info(f"Scanning codebase: {codebase_path}")
    count = 0
    
    for root, dirs, files in os.walk(codebase_path):
        # Prune excluded directories IN-PLACE
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        for file in files:
            file_path = Path(root) / file
            suffix = file_path.suffix
            name = file_path.name
            
            # Category 1: Java/Kotlin (for Tree-sitter + RAG)
            if suffix in src_extensions:
                # Extra check: ensure we are locally in a 'src/main' or 'src' context?
                # Actually, the user requirement was just "codebase/**" excluding tests.
                # Just excluding 'test' dir above handles most.
                # We can be stricter if needed, but let's trust the skip_dirs for now.
                java_kotlin_files.append(str(file_path))
                
            # Category 2: Polyglot (for RAG only)
            elif suffix in polyglot_extensions:
                polyglot_files.append(str(file_path))
                
            # Category 3: Resources (Targeted)
            elif name in resource_names:
                # Verify it's in a res/ structure to avoid random files
                # e.g. .../res/values/strings.xml
                if "res/" in str(file_path):
                    resource_files.append(str(file_path))
                    
            count += 1

    logger.info("Source Discovery Stat:")
    logger.info(f"  Java/Kotlin: {len(java_kotlin_files)}")
    logger.info(f"  Polyglot: {len(polyglot_files)}")
    logger.info(f"  Resources: {len(resource_files)}")

    return {
        "java_kotlin_files": java_kotlin_files,
        "polyglot_files": polyglot_files,
        "resource_files": resource_files
    }
