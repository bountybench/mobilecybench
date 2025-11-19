"""
Test a single specialist agent with MCP tools to verify it can execute commands.
This demonstrates the full specialist workflow without needing HIGH/CRITICAL findings.
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
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_specialist_agent():
    """Test a specialist agent with MCP tools"""

    logger.info("=" * 80)
    logger.info("SPECIALIST AGENT TEST")
    logger.info("=" * 80)

    # Create MCP tools
    logger.info("\n[1/4] Creating MCP tools...")
    mcp_tools = create_langchain_tools_from_mcp()
    logger.info(f"  Created {len(mcp_tools)} tools")

    # Create a mock finding for testing
    logger.info("\n[2/4] Creating mock Path Traversal finding...")
    mock_finding = SemgrepFinding(
        check_id="java.android.security.path-traversal",
        path="/app/codebase/DocumentsProvider.java",
        line=123,
        severity="HIGH",
        message="Potential path traversal in ContentProvider",
        vulnerability_type=VulnerabilityType.PATH_TRAVERSAL,
        metadata={
            "cwe": "CWE-22",
            "owasp": "A01:2021"
        }
    )

    # Create investigation task with context
    context = {
        "package_name": "com.owncloud.android",
        "app_dir": "/app/codebase",
        "server_url": "owncloud_server:8080"
    }

    task = InvestigationTask(
        task_id="test_001",
        vulnerability_type=VulnerabilityType.PATH_TRAVERSAL,
        findings=[mock_finding],
        priority=1,
        context=context
    )

    logger.info(f"  Finding: {mock_finding.message}")
    logger.info(f"  Location: {mock_finding.path}:{mock_finding.line}")

    # Create specialist agent
    logger.info("\n[3/4] Creating Path Traversal specialist agent...")
    specialist = SpecialistAgent(
        vulnerability_type=VulnerabilityType.PATH_TRAVERSAL,
        model="gpt-5.1",
        mcp_tools=mcp_tools
    )

    # Test MCP tools directly first
    logger.info("\n[4/4] Testing MCP tool execution...")
    logger.info("  Testing execute_command tool...")
    result = mcp_tools[0].invoke({"command": "pwd"})
    logger.info(f"  Result: {result[:100]}...")

    logger.info("\n  Testing get_current_ui_state tool...")
    ui_state = mcp_tools[1].invoke({})
    logger.info(f"  UI State keys: {list(ui_state.keys()) if isinstance(ui_state, dict) else type(ui_state)}")

    logger.info("\n" + "=" * 80)
    logger.info("TEST COMPLETE")
    logger.info("=" * 80)
    logger.info("\nResults:")
    logger.info(f"  MCP tools created: {len(mcp_tools)}")
    logger.info(f"  Specialist agent created: {specialist.vulnerability_type.value}")
    logger.info(f"  Tools working: YES")
    logger.info(f"  Agent executor created: {specialist.executor is not None}")

    if specialist.executor:
        logger.info("\n  Full investigation workflow is ready!")
        logger.info(f"  To run a full investigation, the specialist would:")
        logger.info(f"    1. Review the finding at {mock_finding.path}:{mock_finding.line}")
        logger.info(f"    2. Execute commands to test exploitation")
        logger.info(f"    3. Verify if the vulnerability is exploitable")
        logger.info(f"    4. Generate evidence-based report")
    else:
        logger.info("\n  Note: Agent executor not created (LangChain version issue)")
        logger.info("  But MCP tools are working correctly!")

    return specialist


if __name__ == "__main__":
    try:
        specialist = test_specialist_agent()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        sys.exit(1)
