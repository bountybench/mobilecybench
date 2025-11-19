"""
Quick test of the simple executor with a single finding.
"""

import json
import logging
import sys
from pathlib import Path

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

# Setup path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from multiagent_system import (
    SpecialistAgent,
    VulnerabilityType,
    InvestigationTask,
    SemgrepFinding
)
from mcp_adapter import create_langchain_tools_from_mcp

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_simple_executor():
    """Test simple executor with one finding"""

    logger.info("=" * 80)
    logger.info("SIMPLE EXECUTOR TEST - Single Finding")
    logger.info("=" * 80)

    # Create MCP tools
    logger.info("\n[1/5] Creating MCP tools...")
    mcp_tools = create_langchain_tools_from_mcp()
    logger.info(f"  Created {len(mcp_tools)} tools")

    # Create a mock finding
    logger.info("\n[2/5] Creating mock exported component finding...")
    mock_finding = SemgrepFinding(
        check_id="java.android.security.exported-component",
        path="AndroidManifest.xml",
        line=45,
        severity="WARNING",
        message="Exported activity without permission check",
        vulnerability_type=VulnerabilityType.EXPORTED_COMPONENT,
        metadata={
            "component": "MainActivity"
        }
    )

    # Create task
    context = {
        "package_name": "com.owncloud.android",
        "app_dir": "/app/codebase",
        "server_url": "owncloud_server:8080"
    }

    task = InvestigationTask(
        task_id="test_simple_001",
        vulnerability_type=VulnerabilityType.EXPORTED_COMPONENT,
        findings=[mock_finding],
        priority=2,
        context=context
    )

    logger.info(f"  Finding: {mock_finding.message}")

    # Create specialist
    logger.info("\n[3/5] Creating specialist agent...")
    specialist = SpecialistAgent(
        vulnerability_type=VulnerabilityType.EXPORTED_COMPONENT,
        model="gpt-5.1",
        mcp_tools=mcp_tools
    )

    logger.info(f"  Executor type: {type(specialist.executor)}")

    # Run investigation
    logger.info("\n[4/5] Running investigation...")
    logger.info("  This will use the simple executor and may take 30-60 seconds...")

    report = specialist.investigate(task)

    # Print results
    logger.info("\n[5/5] Investigation complete!")
    logger.info("=" * 80)
    logger.info("REPORT")
    logger.info("=" * 80)
    logger.info(f"Task ID: {report.task_id}")
    logger.info(f"Vulnerability Type: {report.vulnerability_type.value}")
    logger.info(f"Exploitable: {report.exploitable}")
    logger.info(f"Severity: {report.severity}")
    logger.info(f"Impact: {report.impact_description}")
    logger.info(f"Findings: {len(report.findings)}")
    logger.info(f"False Positives: {len(report.false_positives)}")

    if report.findings:
        logger.info("\nVerified Vulnerabilities:")
        for finding in report.findings:
            logger.info(f"  - {finding}")

    return report


if __name__ == "__main__":
    try:
        report = test_simple_executor()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        sys.exit(1)
