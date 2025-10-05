#!/usr/bin/env python3
"""
Standalone Agent Runner

This script runs just the custom agent without re-running the full pipeline.
It assumes the infrastructure (emulator, containers, app setup) is already running.
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from agent.custom_agent import CustomAgent
from runner import MobileCybenchRunner, load_config
from utils.logger import logger
from utils.utils import get_app_metadata

load_dotenv()

project_root = Path(__file__).parent.parent


def main():
    """Run just the custom agent with CLI-provided app and config file"""

    parser = argparse.ArgumentParser(
        description="Standalone Agent Runner - runs only the custom agent using a config file"
    )
    parser.add_argument(
        "app_name",
        help="Name of the app to set up the MobileCybench Runner (must exist in apps/ directory)",
    )
    parser.add_argument(
        "config_file",
        nargs="?",
        default="runner_config.json",
        help="Path to JSON configuration file (default: runner_config.json)",
    )

    args = parser.parse_args()

    config_file = args.config_file
    if not config_file:
        config_path = project_root / "runner_config.json"
    else:
        config_path = (
            Path(config_file)
            if Path(config_file).is_absolute()
            else project_root / config_file
        )

    # Load and validate config
    config = load_config(config_path)

    app_name = args.app_name

    runner = MobileCybenchRunner(app_name, config)

    runner.setup_agent()

    logger.info("=" * 80)
    logger.info("STANDALONE TEST FOR AGENT RUNNER")
    logger.info(f"App: {app_name}")
    logger.info(f"Model: {config['model']}")
    logger.info(f"Dry Run: {config['dry_run']}")
    logger.info("=" * 80)

    try:
        # Get app metadata
        metadata = get_app_metadata(app_name)
        logger.info(f"Metadata loaded: {metadata}")

        # TODO: modify system prompt for your own use case
        system_prompt = {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": "You are a helpful cybersecurity expert. Help me describe what the current state of the screen looks like.",
                }
            ],
        }

        # Create and run the agent
        agent = CustomAgent(
            model=config["model"],
            max_iterations=config["max_iterations"],
            max_model_response_tokens=config["max_model_response_tokens"],
            max_kali_message_tokens=config["max_kali_message_tokens"],
            max_context_length=config["max_context_length"],
            screenshot_enabled=config.get("screenshot_mode", False),
            app_name=app_name,
            dry_run=config["dry_run"],
            app_server=metadata.get("app_server", None),
            system_prompt=system_prompt,
        )

        logger.info("Starting agent execution...")
        result = agent.run()

        # Display results
        logger.info("=" * 60)
        logger.info("AGENT EXECUTION RESULTS")
        logger.info("=" * 60)
        logger.info(f"Status: {result.get('status', 'Unknown')}")
        logger.info(f"Turns: {result.get('turns', 0)}")
        logger.info(f"Log file: {result.get('log_file', 'None')}")

        if result.get("final_message"):
            logger.info("Final Message:")
            logger.info(f"  {result['final_message']}")

        logger.info("=" * 60)

        return result

    except Exception as e:
        logger.error(f"Error running agent: {e}")
        return {
            "status": f"error: {str(e)}",
            "turns": 0,
            "final_message": None,
            "log_file": None,
        }


if __name__ == "__main__":
    result = main()
    print(f"\nAgent execution completed with status: {result.get('status', 'Unknown')}")
    if result.get("log_file"):
        print(f"Full log available at: {result['log_file']}")
