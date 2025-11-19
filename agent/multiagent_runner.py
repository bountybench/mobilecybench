"""
Integration script to run the multi-agent security testing system
with the existing MobileCyBench infrastructure.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from agent.multiagent_system import MultiAgentSecuritySystem, VulnerabilityType
from agent.mcp_adapter import create_langchain_tools_from_mcp
from utils.mcp_utils import get_mcp_server_config

logger = logging.getLogger(__name__)


def create_mcp_tools(mcp_config: Dict[str, Any] = None) -> List:
    """
    Create LangChain tools from MCP server using the adapter.

    Args:
        mcp_config: MCP configuration dict. If None, auto-discovers.

    Returns:
        List of LangChain tools
    """
    return create_langchain_tools_from_mcp(mcp_config)


def load_application_context(app_dir: Path) -> Dict[str, Any]:
    """
    Load context about the application being tested.
    This provides specialist agents with necessary background information.
    """
    context = {
        "app_dir": str(app_dir),
        "package_name": None,
        "exported_components": [],
        "server_endpoints": [],
        "target_flags": [
            "/data/data/{package_name}/files/flag.txt",
            "/root/flag.txt",
            "/tmp/pwned"
        ]
    }

    # Try to extract package name from AndroidManifest.xml
    manifest_paths = list(app_dir.glob("**/AndroidManifest.xml"))
    if manifest_paths:
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(manifest_paths[0])
            root = tree.getroot()
            context["package_name"] = root.attrib.get("package")

            # Extract exported components
            for elem in root.iter():
                if "android:exported" in elem.attrib:
                    if elem.attrib["android:exported"] == "true":
                        component_name = elem.attrib.get("{http://schemas.android.com/apk/res/android}name", "")
                        context["exported_components"].append({
                            "type": elem.tag,
                            "name": component_name
                        })
        except Exception as e:
            logger.warning(f"Failed to parse AndroidManifest: {e}")

    return context


def run_multiagent_assessment(
    semgrep_results_path: str,
    app_dir: str,
    output_path: str,
    coordinator_model: str = "gpt-5.1",
    specialist_model: str = "gpt-5.1",
    mcp_config: Dict[str, Any] = None,
    max_workers: int = 1
) -> Dict[str, Any]:
    """
    Run a complete multi-agent security assessment.

    Args:
        semgrep_results_path: Path to semgrep JSON results
        app_dir: Path to application codebase directory
        output_path: Where to write the final report
        coordinator_model: Model for coordinator agent
        specialist_model: Model for specialist agents
        mcp_config: MCP configuration dict (auto-discovers if None)
        max_workers: Number of parallel workers for specialist agents (default: 1 for sequential)

    Returns:
        Final assessment report dictionary
    """
    logger.info("=" * 80)
    logger.info("MULTI-AGENT SECURITY ASSESSMENT")
    logger.info("=" * 80)

    # Load application context
    logger.info(f"Loading application context from: {app_dir}")
    context = load_application_context(Path(app_dir))
    logger.info(f"Package: {context.get('package_name')}")
    logger.info(f"Exported components: {len(context.get('exported_components', []))}")

    # Get or discover MCP config
    if mcp_config is None:
        logger.info("Discovering MCP server configuration...")
        mcp_config = get_mcp_server_config(check_reachability=True)

    logger.info(f"MCP Server: {mcp_config['server_url']}")

    # Create MCP tools for specialist agents
    logger.info("Creating LangChain tools from MCP server...")
    mcp_tools = create_mcp_tools(mcp_config)

    # Initialize multi-agent system
    logger.info(f"Initializing multi-agent system")
    logger.info(f"  Coordinator model: {coordinator_model}")
    logger.info(f"  Specialist model: {specialist_model}")
    logger.info(f"  Max parallel workers: {max_workers}")
    system = MultiAgentSecuritySystem(
        coordinator_model=coordinator_model,
        specialist_model=specialist_model,
        mcp_tools=mcp_tools,
        max_workers=max_workers
    )

    # Run assessment
    logger.info(f"Running assessment on semgrep results: {semgrep_results_path}")
    report = system.run_security_assessment(semgrep_results_path, context)

    # Save report
    logger.info(f"Writing report to: {output_path}")
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    # Print summary
    logger.info("=" * 80)
    logger.info("ASSESSMENT COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Overall Risk: {report['overall_risk']}")
    logger.info(f"Verified Vulnerabilities: {report['total_verified_vulnerabilities']}")
    logger.info(f"  - CRITICAL: {report['critical_vulnerabilities']}")
    logger.info(f"  - HIGH: {report['high_vulnerabilities']}")
    logger.info(f"False Positives Filtered: {report['false_positives_count']}")
    logger.info("=" * 80)

    return report


def main():
    """Command-line interface for multi-agent assessment"""
    parser = argparse.ArgumentParser(
        description="Multi-Agent Security Testing System for Android Apps"
    )
    parser.add_argument(
        "--semgrep-results",
        required=True,
        help="Path to semgrep JSON results file"
    )
    parser.add_argument(
        "--app-dir",
        required=True,
        help="Path to application codebase directory"
    )
    parser.add_argument(
        "--mcp-server",
        default=None,
        help="URL of MCP server (default: auto-discover from ngrok)"
    )
    parser.add_argument(
        "--output",
        default="multiagent_report.json",
        help="Output path for final report (default: multiagent_report.json)"
    )
    parser.add_argument(
        "--coordinator-model",
        default="gpt-5.1",
        help="Model for coordinator agent (default: gpt-5.1)"
    )
    parser.add_argument(
        "--specialist-model",
        default="gpt-5.1",
        help="Model for specialist agents (default: gpt-5.1)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Number of parallel workers for specialist agents (default: 1 for sequential)"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Validate inputs
    if not os.path.exists(args.semgrep_results):
        logger.error(f"Semgrep results file not found: {args.semgrep_results}")
        sys.exit(1)

    if not os.path.exists(args.app_dir):
        logger.error(f"Application directory not found: {args.app_dir}")
        sys.exit(1)

    # Get MCP config if URL provided
    mcp_config = None
    if args.mcp_server:
        logger.info(f"Using provided MCP server: {args.mcp_server}")
        mcp_config = {
            "type": "mcp",
            "server_label": "mobile_server_mcp",
            "server_url": args.mcp_server,
            "require_approval": "never"
        }

    # Run assessment
    try:
        report = run_multiagent_assessment(
            semgrep_results_path=args.semgrep_results,
            app_dir=args.app_dir,
            output_path=args.output,
            coordinator_model=args.coordinator_model,
            specialist_model=args.specialist_model,
            mcp_config=mcp_config,
            max_workers=args.max_workers
        )

        # Exit with appropriate code
        if report["overall_risk"] in ["CRITICAL", "HIGH"]:
            sys.exit(1)  # Indicate vulnerabilities found
        else:
            sys.exit(0)  # Success

    except Exception as e:
        logger.error(f"Assessment failed: {e}", exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
