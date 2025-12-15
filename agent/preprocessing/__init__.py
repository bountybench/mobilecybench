"""
Preprocessing pipeline for Android app analysis.

Orchestrates:
1. Code indexing (manifest + tree-sitter)
2. Default Semgrep analysis
3. SharedKnowledgeStore population

All preprocessing runs on HOST (not in container) for performance.
"""

from agent.custom_agent_v2.shared_knowledge import SharedKnowledgeStore
from agent.preprocessing.code_indexer import index_codebase
from agent.preprocessing.semgrep_runner import run_default_semgrep
from utils.logger import logger


def preprocess_app(app_path: str, package_name: str) -> SharedKnowledgeStore:
    """
    Run preprocessing pipeline for an app.

    Steps:
    1. Index codebase (manifest + tree-sitter) - cached
    2. Run default Semgrep - CVE-focused rules
    3. Populate SharedKnowledgeStore

    Args:
        app_path: Path to app codebase on host (e.g., "apps/ankidroid/codebase")
        package_name: App package name (e.g., "com.ichi2.anki")

    Returns:
        SharedKnowledgeStore with CodeIndex and initial vulnerabilities
    """
    logger.info("=" * 80)
    logger.info(f"PREPROCESSING: {package_name}")
    logger.info("=" * 80)

    # Initialize knowledge store
    store = SharedKnowledgeStore(app_package=package_name)

    # Step 1: Code indexing (manifest + tree-sitter)
    logger.info("\n[STEP 1/2] Code Indexing")
    logger.info("-" * 80)

    try:
        code_index = index_codebase(app_path, package_name)
        store.set_code_index(code_index)

        logger.info(f"✓ Indexed {len(code_index.classes)} classes")
        logger.info(
            f"✓ Found {sum(len(v) for v in code_index.methods.values())} methods"
        )
        logger.info(f"✓ Flagged {len(code_index.sensitive_apis)} sensitive APIs")
        logger.info(f"✓ Exported components: {len(code_index.exported_components)}")

    except Exception as e:
        logger.error(f"Code indexing failed: {e}")
        logger.exception("Full traceback:")
        # Continue with empty code index
        logger.warning("Continuing with manifest-only data...")

    # Step 2: Default Semgrep
    logger.info("\n[STEP 2/2] Semgrep Analysis (Default Rules)")
    logger.info("-" * 80)

    try:
        vulnerabilities = run_default_semgrep(app_path)

        for vuln in vulnerabilities:
            store.add_vulnerability(vuln)

        logger.info(f"✓ Found {len(vulnerabilities)} potential vulnerabilities")

        # Show breakdown by severity
        by_severity = {}
        for vuln in vulnerabilities:
            by_severity[vuln.severity] = by_severity.get(vuln.severity, 0) + 1

        for severity in ["critical", "high", "medium", "low"]:
            count = by_severity.get(severity, 0)
            if count > 0:
                logger.info(f"  - {severity.upper()}: {count}")

    except Exception as e:
        logger.error(f"Semgrep analysis failed: {e}")
        logger.exception("Full traceback:")
        logger.warning("Continuing without Semgrep findings...")

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("PREPROCESSING COMPLETE")
    logger.info("=" * 80)

    summary = store.get_summary()
    logger.info(f"\nApp: {summary['app_package']}")
    logger.info(f"Code Index: {'✓' if summary['has_code_index'] else '✗'}")
    logger.info(f"Total Vulnerabilities: {summary['total_vulnerabilities']}")

    if summary['total_vulnerabilities'] > 0:
        logger.info("\nBy Severity:")
        for severity, count in summary['by_severity'].items():
            if count > 0:
                logger.info(f"  {severity.upper()}: {count}")

    logger.info("")

    return store


__all__ = ["preprocess_app", "index_codebase", "run_default_semgrep"]
