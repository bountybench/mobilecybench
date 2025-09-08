#!/usr/bin/env python3
"""
Mobile Cybench Runner Script

This script orchestrates the complete pipeline for running cybersecurity tests
on Android applications using AI agents.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.logger import logger


class MobileCybenchRunner:
    def __init__(self, app_name: str, log_file: Optional[str] = None):
        self.app_name = app_name
        self.project_root = project_root
        self.app_dir = self.project_root / "apps" / app_name
        self.agent_dir = self.project_root / "agent"
        if not log_file:
            log_file = "runner.log"
        self.log_file = log_file
        
        # Configure logger to also write to our log file
        self._setup_logging()
        
        logger.info("=" * 80)
        logger.info(f"MobileCybench Runner Started")
        logger.info(f"App: {app_name}")
        logger.info(f"Timestamp: {datetime.datetime.now()}")
        logger.info(f"Log file: {log_file}")
        logger.info("=" * 80)

    def _setup_logging(self):
        """Configure logging to write to both console and file"""
        import logging
        
        # Create file handler
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(file_handler)

    def run_command(self, command: str, cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
        """Run a shell command and log the results"""
        if cwd is None:
            cwd = self.project_root
            
        logger.info(f"Running command: {command}")
        logger.info(f"Working directory: {cwd}")
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False
            )
            
            logger.info(f"Exit code: {result.returncode}")
            if result.stdout:
                logger.info(f"STDOUT:\n{result.stdout}")
            if result.stderr:
                logger.info(f"STDERR:\n{result.stderr}")
                
            if check and result.returncode != 0:
                logger.error(f"Command failed with exit code {result.returncode}")
                self._exit_with_error(f"Command failed: {command}")
                
            return result
            
        except Exception as e:
            logger.error(f"Exception running command: {e}")
            if check:
                self._exit_with_error(f"Exception running command: {command}")
            raise

    def run_command_with_live_output(self, command: str, cwd: Optional[Path] = None, check: bool = True) -> int:
        """Run a shell command with real-time output to console and logging"""
        if cwd is None:
            cwd = self.project_root
            
        logger.info(f"Running command with live output: {command}")
        logger.info(f"Working directory: {cwd}")
        print(f"[RUNNING] {command}")
        
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )
            
            # Read output line by line and display in real-time
            output_lines = []
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    output = output.strip()
                    print(f"  {output}")  # Show to user with indentation
                    logger.info(f"OUTPUT: {output}")  # Log it
                    output_lines.append(output)
            
            # Wait for process to complete
            return_code = process.poll()
            
            logger.info(f"Command completed with exit code: {return_code}")
            print(f"[COMPLETED] Exit code: {return_code}")
            
            if check and return_code != 0:
                logger.error(f"Command failed with exit code {return_code}")
                self._exit_with_error(f"Command failed: {command}")
                
            return return_code
            
        except Exception as e:
            logger.error(f"Exception running command: {e}")
            print(f"[ERROR] {e}")
            if check:
                self._exit_with_error(f"Exception running command: {command}")
            raise

    def _exit_with_error(self, message: str):
        """Log error and exit"""
        logger.error(message)
        logger.error("Runner execution failed. Check log for details.")
        print(f"ERROR: {message}")
        print(f"Full log available at: {self.log_file}")
        sys.exit(1)

    def validate_input(self):
        """Validate app name and required files"""
        logger.info("Validating input...")
        
        # Check if app directory exists
        if not self.app_dir.exists():
            self._exit_with_error(f"App directory not found: {self.app_dir}")
            
        # Check for metadata.json
        metadata_file = self.app_dir / "metadata.json"
        if not metadata_file.exists():
            self._exit_with_error(f"metadata.json not found: {metadata_file}")
            
        # Validate metadata.json structure
        try:
            with open(metadata_file) as f:
                metadata = json.load(f)
            logger.info(f"Metadata loaded: {metadata}")
        except Exception as e:
            self._exit_with_error(f"Invalid metadata.json: {e}")
            
        # Check for required scripts
        required_scripts = ["setup_app_source.sh", "setup.sh", "run_checks.sh"]
        for script in required_scripts:
            script_path = self.app_dir / script
            if not script_path.exists():
                self._exit_with_error(f"Required script not found: {script_path}")
                
        logger.info("Input validation passed")

    def setup_emulator(self):
        """Start and check Android emulator"""
        logger.info("Setting up Android emulator...")
        self.run_command(f"./setup.sh {self.app_name}")
        
        # Start emulator (runs in background - continuous output like docker without detached mode)
        logger.info("Starting emulator in background...")
        emulator_process = subprocess.Popen(
            ["bash", "./start_emulator.sh"],
            cwd=self.project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        logger.info(f"Emulator process started with PID: {emulator_process.pid}")
        
        # Wait a moment for emulator to start initializing
        logger.info("Waiting for emulator to initialize...")
        logger.info("Emulator setup started, waiting for it to be ready while building the app...")

    def setup_app(self):
        """Build and install the app"""
        logger.info("Building the app from source")
        print("\n" + "=" * 60)
        print("SETTING UP APP SOURCE")
        print("=" * 60)
        self.run_command_with_live_output("./setup_app_source.sh", cwd=self.app_dir)

        # Check emulator is ready (this will wait until device is ready)
        print("\n" + "=" * 60)
        print("CHECKING EMULATOR STATUS")
        print("=" * 60)
        logger.info("Checking emulator status...")
        self.run_command_with_live_output("./check_device.sh")

        # Setup/build app
        print("\n" + "=" * 60)
        print("BUILDING AND INSTALLING APP")
        print("=" * 60)
        logger.info("Building and installing app...")
        self.run_command_with_live_output("./setup.sh", cwd=self.app_dir)
        
        logger.info("App setup completed")

    def setup_agent(self):
        """Configure agent environment"""
        # TODO
        

    def start_services(self):
        """Start MCP server and Kali container"""
        # TODO
        

    def run_agent(self):
        """Run the custom agent - custom_agent.py"""
        # TODO

    def run_evaluation(self):
        """Run the evaluation checks"""
        logger.info("Running evaluation...")
        
        # Run the checks
        result = self.run_command("./run_checks.sh", cwd=self.app_dir, check=False)
        
        # Output results
        print("\n" + "=" * 80)
        print("EVALUATION RESULTS")
        print("=" * 80)
        print(result.stdout)
        if result.stderr:
            print("STDERR:")
            print(result.stderr)
        print(f"Exit code: {result.returncode}")
        print("=" * 80)
        
        # Log results
        logger.info("Evaluation completed")
        logger.info(f"Exit code: {result.returncode}")
        logger.info(f"Results:\n{result.stdout}")
        
        return result.returncode == 0

    def cleanup(self):
        """Clean up services"""
        logger.info("Cleaning up services...")
        
        try:
            # Stop docker compose services
            subprocess.run(
                ["docker", "compose", "down"],
                cwd=self.agent_dir,
                capture_output=True,
                text=True
            )
            logger.info("Services stopped")
        except Exception as e:
            logger.warning(f"Error during cleanup: {e}")

    def run(self):
        """Run the complete pipeline"""
        try:
            self.validate_input()
            self.setup_emulator()
            self.setup_app()
            
            # Setup agent
            self.setup_agent()
            
            # # Start services
            # # Run agent
            # Run evaluation -> output success
            
            success = True
            # Log completion
            logger.info("=" * 80)
            logger.info(f"Runner execution completed")
            logger.info(f"App: {self.app_name}")
            logger.info(f"Success: {success}")
            logger.info(f"Log file: {self.log_file}")
            logger.info("=" * 80)
            logger.info(f"Runner execution completed!")
            logger.info(f"Success: {success}")
            logger.info(f"Full log available at: {self.log_file}")

            return 0 if success else 1
            
        except KeyboardInterrupt:
            logger.info("Runner interrupted by user")
            print("\nRunner interrupted by user")
            return 1
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            print(f"Unexpected error: {e}")
            return 1
        finally:
            self.cleanup()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="MobileCybench Runner - Orchestrates AI-driven mobile app security testing"
    )
    parser.add_argument(
        "app_name",
        help="Name of the app to test (must exist in apps/ directory)"
    )
    parser.add_argument(
        "--log-file",
        help="Custom log file path"
    )
    
    args = parser.parse_args()
    
    # Create and run the runner
    runner = MobileCybenchRunner(args.app_name, args.log_file)
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())