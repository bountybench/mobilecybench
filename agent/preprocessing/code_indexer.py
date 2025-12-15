"""
Code indexer using tree-sitter for structural analysis.

Builds CodeIndex from app source code with:
- Manifest data (components, permissions)
- Code structure (classes, methods, fields)
- Sensitive API calls
- Disk caching for performance
"""

import os
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from agent.custom_agent_v2.shared_knowledge import CodeIndex, Symbol
from agent.preprocessing.manifest_parser import parse_manifest
from agent.preprocessing.structure_detector import detect_app_structure
from tools.tree_sitter_indexer import CodebaseIndexer
from utils.logger import logger


def index_codebase(app_path: str, package_name: str) -> CodeIndex:
    """
    Index app codebase using tree-sitter.

    Steps:
    1. Check cache (cache/{package_name}_index.json)
    2. If cache exists and fresh, load from cache
    3. Otherwise:
       - Parse manifest
       - Run tree-sitter on source code
       - Flag sensitive APIs
       - Build CodeIndex
       - Save to cache

    Args:
        app_path: Path to app codebase on host (e.g., "apps/ankidroid/codebase")
        package_name: App package name (e.g., "com.ichi2.anki")

    Returns:
        CodeIndex with manifest + code-level data
    """
    cache_file = f"cache/{package_name}_index.json"

    # Check cache
    if os.path.exists(cache_file):
        if is_cache_fresh(cache_file, app_path):
            logger.info(f"Loading CodeIndex from cache: {cache_file}")
            return CodeIndex.from_json(cache_file)
        else:
            logger.info(f"Cache expired, re-indexing: {package_name}")

    logger.info(f"Indexing codebase: {app_path}")

    # Step 0: Detect app structure with LLM (cached in metadata.json)
    logger.info("[0/3] Detecting app structure...")
    structure = detect_app_structure(app_path, package_name)

    # Step 1: Parse manifest
    logger.info("[1/3] Parsing AndroidManifest.xml...")
    manifest_data = parse_manifest(app_path, structure, package_name)

    # Step 2: Tree-sitter indexing
    logger.info("[2/3] Indexing code with tree-sitter...")
    indexer = CodebaseIndexer()

    # Use LLM-detected source directories
    source_dirs = structure.get("source_dirs", [])
    if not source_dirs:
        logger.warning("No source directories detected, using fallback")
        src_dir = find_source_directory(app_path)
        if src_dir:
            source_dirs = [str(src_dir)]

    # Index all source directories
    total_stats = {"total_files": 0, "total_symbols": 0}
    for src_dir in source_dirs:
        full_path = Path(app_path) / src_dir
        if full_path.exists():
            logger.info(f"  Indexing {src_dir}...")
            stats = indexer.index_directory(str(full_path), extensions=[".java", ".kt"])
            total_stats["total_files"] += stats["total_files"]
            total_stats["total_symbols"] += stats["total_symbols"]
        else:
            logger.warning(f"  Source directory not found: {src_dir}")

    stats = total_stats

    logger.info(
        f"  Indexed {stats['total_files']} files, {stats['total_symbols']} symbols"
    )

    # Step 3: Flag sensitive APIs
    logger.info("[3/3] Flagging sensitive APIs...")
    sensitive_apis = flag_sensitive_apis(indexer)
    logger.info(f"  Found {len(sensitive_apis)} sensitive API calls")

    # Build CodeIndex
    code_index = CodeIndex(
        package_name=manifest_data["package_name"],
        # Manifest-level
        activities=manifest_data["activities"],
        services=manifest_data["services"],
        receivers=manifest_data["receivers"],
        providers=manifest_data["providers"],
        permissions=manifest_data["permissions"],
        exported_components=manifest_data["exported_components"],
        # Code-level (convert Symbol objects to dicts)
        classes={name: asdict(symbol) for name, symbol in indexer.classes.items()},
        methods={
            name: [asdict(s) for s in symbols]
            for name, symbols in indexer.methods.items()
        },
        fields={
            name: [asdict(s) for s in symbols]
            for name, symbols in indexer.fields.items()
        },
        sensitive_apis=sensitive_apis,
        # Metadata
        indexed_at=datetime.now().isoformat(),
        cache_file=cache_file,
    )

    # Save cache
    logger.info(f"Saving CodeIndex to cache: {cache_file}")
    code_index.to_json(cache_file)

    return code_index


def find_source_directory(app_path: str) -> Optional[Path]:
    """Find main source directory in app."""
    app_path = Path(app_path)

    # Common patterns
    candidates = [
        app_path / "src/main/java",
        app_path / "app/src/main/java",
        app_path / "*/src/main/java",
    ]

    for pattern in candidates:
        if "*" in str(pattern):
            matches = list(app_path.glob(str(pattern).replace(str(app_path) + "/", "")))
            if matches:
                return matches[0].parent  # Return src/main, not just java
        elif pattern.exists():
            return pattern.parent  # Return src/main, not just java

    # Fallback: search for any src/main
    src_mains = list(app_path.rglob("src/main"))
    if src_mains:
        # Prefer one not in test/build directories
        for sm in src_mains:
            if "test" not in str(sm) and "build" not in str(sm):
                return sm
        return src_mains[0]

    return None


def flag_sensitive_apis(indexer: CodebaseIndexer) -> List[Dict]:
    """
    Flag sensitive API calls in indexed code.

    Searches for patterns like:
    - WebView: loadUrl, evaluateJavascript, addJavascriptInterface
    - Runtime: exec, ProcessBuilder
    - SQL: rawQuery, execSQL
    - Crypto: Cipher, MessageDigest, SecretKey
    - Network: HttpURLConnection, OkHttpClient
    - File: FileInputStream, FileOutputStream, openFileOutput

    Returns:
        List of {class, method, api_call, line, file}
    """
    sensitive_patterns = {
        "webview": [
            "loadUrl",
            "evaluateJavascript",
            "addJavascriptInterface",
            "setWebViewClient",
            "setWebChromeClient",
        ],
        "runtime": ["Runtime.exec", "ProcessBuilder", "Runtime.getRuntime"],
        "sql": [
            "rawQuery",
            "execSQL",
            "SQLiteDatabase.query",
            "compileStatement",
        ],
        "crypto": [
            "Cipher.getInstance",
            "MessageDigest.getInstance",
            "SecretKey",
            "KeyGenerator",
        ],
        "network": [
            "HttpURLConnection",
            "OkHttpClient",
            "HttpClient",
            "URLConnection.openConnection",
        ],
        "file": [
            "FileInputStream",
            "FileOutputStream",
            "openFileOutput",
            "openFileInput",
            "File(",
        ],
        "intent": ["startActivity", "sendBroadcast", "startService"],
        "reflection": ["Class.forName", "Method.invoke", "getDeclaredMethod"],
    }

    sensitive_apis = []

    # Search through all methods
    for method_name, symbols in indexer.methods.items():
        for symbol in symbols:
            # Check if method name matches sensitive patterns
            for category, patterns in sensitive_patterns.items():
                for pattern in patterns:
                    if pattern.lower() in symbol.name.lower():
                        sensitive_apis.append(
                            {
                                "class": symbol.parent or "unknown",
                                "method": symbol.name,
                                "api_call": pattern,
                                "category": category,
                                "line": symbol.line_start,
                                "file": symbol.file_path,
                            }
                        )

    return sensitive_apis


def is_cache_fresh(cache_file: str, app_path: str, max_age_hours: int = 24) -> bool:
    """
    Check if cache is fresh based on modification time.

    Args:
        cache_file: Path to cache file
        app_path: Path to app codebase
        max_age_hours: Maximum age in hours (default: 24)

    Returns:
        True if cache is fresh, False otherwise
    """
    if not os.path.exists(cache_file):
        return False

    cache_mtime = os.path.getmtime(cache_file)
    current_time = datetime.now().timestamp()

    # Check age
    age_hours = (current_time - cache_mtime) / 3600
    if age_hours > max_age_hours:
        logger.debug(f"Cache expired: {age_hours:.1f} hours old (max: {max_age_hours})")
        return False

    # Check if any source files modified after cache
    app_path = Path(app_path)
    for src_file in app_path.rglob("*.java"):
        if src_file.stat().st_mtime > cache_mtime:
            logger.debug(f"Source file modified: {src_file}")
            return False

    for src_file in app_path.rglob("*.kt"):
        if src_file.stat().st_mtime > cache_mtime:
            logger.debug(f"Source file modified: {src_file}")
            return False

    return True


def clear_cache(package_name: Optional[str] = None) -> None:
    """
    Clear cached indexes.

    Args:
        package_name: Clear specific package cache, or all if None
    """
    if package_name:
        cache_file = f"cache/{package_name}_index.json"
        if os.path.exists(cache_file):
            os.remove(cache_file)
            logger.info(f"Cleared cache: {cache_file}")
    else:
        # Clear all index caches
        cache_dir = Path("cache")
        if cache_dir.exists():
            for cache_file in cache_dir.glob("*_index.json"):
                os.remove(cache_file)
                logger.info(f"Cleared cache: {cache_file}")
