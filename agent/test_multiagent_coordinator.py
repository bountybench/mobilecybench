"""
Test the multi-agent coordinator on actual ownCloud semgrep results.
This tests parsing, categorization, and task creation WITHOUT requiring:
- MCP server
- Docker containers
"""

import json
import logging
import os
import sys
from pathlib import Path
from collections import Counter
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(Path(__file__).parent / '.env')

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

from multiagent_system import CoordinatorAgent, VulnerabilityType

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def analyze_semgrep_results(semgrep_path: str):
    """Analyze semgrep results and show what the coordinator would do"""

    logger.info("=" * 80)
    logger.info("MULTI-AGENT COORDINATOR TEST - ownCloud Android")
    logger.info("=" * 80)

    # Load semgrep results
    logger.info(f"\n[1/4] Loading semgrep results: {semgrep_path}")
    with open(semgrep_path, 'r') as f:
        semgrep_data = json.load(f)

    total_findings = len(semgrep_data.get("results", []))
    logger.info(f"  Total findings: {total_findings}")

    # Create coordinator
    logger.info("\n[2/4] Creating coordinator agent...")
    coordinator = CoordinatorAgent(model="gpt-5.1")

    # Parse findings
    logger.info("\n[3/4] Parsing and categorizing findings...")
    findings = coordinator.parse_semgrep_output(semgrep_data)
    logger.info(f"  Parsed: {len(findings)} findings")

    # Show severity breakdown
    severity_counts = Counter(f.severity for f in findings)
    logger.info(f"\n  Severity breakdown:")
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "WARNING", "INFO"]:
        count = severity_counts.get(severity, 0)
        if count > 0:
            logger.info(f"    {severity:12s}: {count:4d}")

    # Show vulnerability type breakdown
    vuln_counts = Counter(f.vulnerability_type for f in findings)
    logger.info(f"\n  Vulnerability types:")
    for vuln_type, count in vuln_counts.most_common():
        logger.info(f"    {vuln_type.value:25s}: {count:4d}")

    # Filter to HIGH/CRITICAL (what we'd actually investigate)
    high_priority = [f for f in findings if f.severity in ["HIGH", "CRITICAL"]]
    logger.info(f"\n  Filtered to HIGH/CRITICAL: {len(high_priority)} findings")

    if len(high_priority) == 0:
        logger.warning("  ⚠️  No HIGH/CRITICAL findings!")
        logger.info("  For testing, will use WARNING level findings instead...")
        # Use WARNING level for testing
        high_priority = [f for f in findings if f.severity == "WARNING"][:20]  # Limit to 20 for testing
        logger.info(f"  Using {len(high_priority)} WARNING findings for test")

    # Show sample HIGH/CRITICAL findings
    logger.info(f"\n  Sample HIGH/CRITICAL findings:")
    for f in high_priority[:5]:
        logger.info(f"    [{f.severity}] {f.vulnerability_type.value}")
        logger.info(f"      {f.path}:{f.line}")
        logger.info(f"      {f.message[:80]}...")

    if len(high_priority) > 5:
        logger.info(f"    ... and {len(high_priority) - 5} more")

    # Create investigation tasks
    logger.info("\n[4/4] Creating investigation tasks...")
    context = {
        "package_name": "com.owncloud.android",
        "server_url": "owncloud_server:8080",
        "app_dir": "/app/codebase",
        "exported_components": []  # Would be extracted from AndroidManifest
    }

    tasks = coordinator.create_investigation_tasks(high_priority, context)
    logger.info(f"  Created: {len(tasks)} tasks")

    # Show tasks
    logger.info(f"\n  Investigation Tasks (Priority Order):")
    for task in tasks:
        logger.info(f"\n    Task {task.task_id}: {task.vulnerability_type.value}")
        logger.info(f"      Priority: {task.priority} (1=highest)")
        logger.info(f"      Findings: {len(task.findings)}")

        # Show severity breakdown for this task
        task_severities = Counter(f.severity for f in task.findings)
        sev_str = ", ".join(f"{sev}:{count}" for sev, count in task_severities.items())
        logger.info(f"      Severities: {sev_str}")

        # Show first 2 findings
        logger.info(f"      Sample findings:")
        for f in task.findings[:2]:
            logger.info(f"        - {f.path}:{f.line}")

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("COORDINATOR TEST COMPLETE")
    logger.info("=" * 80)
    logger.info(f"\nSummary:")
    logger.info(f"  Total semgrep findings: {total_findings}")
    logger.info(f"  HIGH/CRITICAL findings: {len(high_priority)}")
    logger.info(f"  Investigation tasks: {len(tasks)}")
    logger.info(f"  Vulnerability types: {len(vuln_counts)}")

    priority_1 = sum(1 for t in tasks if t.priority == 1)
    priority_2 = sum(1 for t in tasks if t.priority == 2)
    priority_3 = sum(1 for t in tasks if t.priority == 3)

    logger.info(f"\nTask priorities:")
    logger.info(f"  Priority 1 (CRITICAL): {priority_1} tasks")
    logger.info(f"  Priority 2 (HIGH):     {priority_2} tasks")
    logger.info(f"  Priority 3 (MEDIUM):   {priority_3} tasks")

    logger.info(f"\nNext steps to run full multi-agent system:")
    logger.info(f"  1. Start MCP server with ngrok")
    logger.info(f"  2. Set OPENAI_API_KEY environment variable")
    logger.info(f"  3. Run: python agent/multiagent_runner.py \\")
    logger.info(f"       --semgrep-results {semgrep_path} \\")
    logger.info(f"       --app-dir /app/codebase \\")
    logger.info(f"       --output owncloud_multiagent_report.json")

    return tasks


def main():
    """Main entry point"""
    semgrep_path = Path(__file__).parent / "semgrep_results_owncloud.json"

    if not semgrep_path.exists():
        logger.error(f"Semgrep results not found: {semgrep_path}")
        logger.error("Run: docker cp kali-container:/app/codebase/semgrep_results.json agent/semgrep_results_owncloud.json")
        return 1

    try:
        tasks = analyze_semgrep_results(str(semgrep_path))
        return 0
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
