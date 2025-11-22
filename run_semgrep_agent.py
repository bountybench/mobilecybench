#!/usr/bin/env python3
"""
Simple test script to run Semgrep agent on OwnCloud codebase.

This is a temporary script to test the LangGraph Semgrep agent.
Will be deleted after understanding how it works.
"""

import os
import sys
from pathlib import Path

# Add the workspace to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from agent.langgraph import SemgrepAgent
from utils.logger import agent_logger


def main():
    """Test the Semgrep agent on OwnCloud codebase."""

    print("\n" + "=" * 80)
    print("Testing Semgrep Agent on OwnCloud Codebase")
    print("=" * 80 + "\n")

    # Check for OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not found in environment")
        print("Please set your OpenAI API key:")
        print('  export OPENAI_API_KEY="your-key-here"')
        print("\nOr create a .env file in the agent directory with:")
        print('  OPENAI_API_KEY=your-key-here')
        return 1

    # Check if Semgrep is installed
    import shutil
    if not shutil.which("semgrep"):
        print("Error: Semgrep not found")
        print("Please install Semgrep:")
        print("  pip install semgrep")
        print("  or")
        print("  brew install semgrep")
        return 1

    # !!!! CHANGE PATH HERE !!!!!
    owncloud_path = "./apps/wallabag/codebase"

    # Check if path exists
    if not Path(owncloud_path).exists():
        print(f"Error: OwnCloud codebase not found at: {owncloud_path}")
        print("\nTrying alternative path...")
        owncloud_path = "./apps/owncloud-android/codebase"

        if not Path(owncloud_path).exists():
            print(f"Error: OwnCloud codebase not found at: {owncloud_path}")
            return 1

    print(f"✓ Found OwnCloud codebase at: {owncloud_path}\n")

    try:
        # Initialize the agent
        print("Initializing Semgrep Agent...")
        agent = SemgrepAgent(
            model="gpt-5.1-2025-11-13",
            temperature=0,
            max_iterations=3,
        )
        print("✓ Agent initialized\n")

        # Run the analysis
        print("Starting Semgrep analysis on OwnCloud...")
        print("This may take a few minutes depending on codebase size...\n")

        results = agent.run(
            target_path=owncloud_path,
            config="auto",  # Let Semgrep auto-detect languages and use appropriate rules
            severity=["ERROR", "WARNING"],  # Focus on higher severity issues
            exclude=[
                "*.test.*",
                "tests/*",
                "test/*",
                "*/test/*",
                "*/tests/*",
                "build/*",
                "*/build/*",
                "node_modules/*",
            ]  # Exclude test files and build artifacts
        )

        # Display results
        print("\n" + "=" * 80)
        print("ANALYSIS RESULTS")
        print("=" * 80 + "\n")

        print(f"Status: {results['status']}")
        print(f"Iterations used: {results['iterations']}")
        print(f"\n{'-' * 80}\n")

        if results.get("final_report"):
            print("FINAL REPORT:")
            print(results["final_report"])
        else:
            print("No final report generated")

        print(f"\n{'-' * 80}\n")

        # Show message history (optional - for debugging)
        if results.get("messages"):
            print(f"\nTotal messages exchanged: {len(results['messages'])}")

            # Optionally show the last few messages
            print("\nLast 3 messages:")
            for i, msg in enumerate(results["messages"][-3:], 1):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                content_preview = content[:200] + "..." if len(content) > 200 else content
                print(f"\n{i}. [{role.upper()}]")
                print(f"   {content_preview}")

        print("\n" + "=" * 80)
        print("Test completed successfully!")
        print("=" * 80 + "\n")

        # Save results to file
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"semgrep_analysis_{timestamp}.md"

        try:
            with open(output_file, "w") as f:
                f.write("# Semgrep Security Analysis Report\n\n")
                f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**Target:** {owncloud_path}\n")
                f.write(f"**Model:** gpt-5.1-2025-11-13\n")
                f.write(f"**Iterations:** {results['iterations']}\n")
                f.write(f"**Status:** {results['status']}\n\n")
                f.write("---\n\n")

                if results.get("final_report"):
                    f.write(results["final_report"])
                else:
                    f.write("No final report generated.\n")

                f.write("\n\n---\n\n")
                f.write(f"*Report saved to: {output_file}*\n")

            print(f"✓ Results saved to: {output_file}")
        except Exception as e:
            print(f"⚠️  Warning: Could not save results to file: {e}")

        return 0

    except Exception as e:
        print("\n" + "=" * 80)
        print("ERROR")
        print("=" * 80)
        print(f"\n❌ Error running Semgrep agent: {e}\n")

        import traceback
        print("Full traceback:")
        traceback.print_exc()

        return 1


if __name__ == "__main__":
    sys.exit(main())
