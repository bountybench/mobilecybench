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
            
        logger.info(f"Running: {command}")
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False
            )
            
            logger.info(f"Command completed (exit code: {result.returncode})")
            # Only log STDERR as warning if it's an actual error (non-zero exit code)
            if result.stderr and result.returncode != 0:
                logger.warning(f"STDERR: {result.stderr}")
                
            if check and result.returncode != 0:
                logger.error(f"Command failed: {command}")
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
            
        logger.info(f"Running with live output: {command}")
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
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    output = output.strip()
                    print(f"  {output}")  # Show to user with indentation
            
            # Wait for process to complete
            return_code = process.poll()
            
            print(f"[COMPLETED] Exit code: {return_code}")
            logger.info(f"Command completed with exit code: {return_code}")
            
            if check and return_code != 0:
                logger.error(f"Command failed: {command}")
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
        """Configure agent environment and start services"""
        print("\n" + "=" * 60)
        print("SETTING UP AGENT ENVIRONMENT")
        print("=" * 60)
        logger.info("Setting up agent environment...")
        
        self._setup_env_file()
        self._start_containers()
        self._copy_codebase_to_kali()
        
        logger.info("Agent environment setup completed")
        print("✓ Agent environment setup completed")

    def _setup_env_file(self):
        """Handle .env file creation/update for OpenAI API key"""
        print("\nSetting up environment file...")
        
        env_file = self.agent_dir / ".env"
        start_dir = f"/tmp/{self.app_name}_app"
        api_key = None
        
        # Load existing .env file if it exists
        if env_file.exists():
            print(f"Found existing .env file at: {env_file}")
            logger.info(f"Loading existing .env file: {env_file}")
            
            try:
                with open(env_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("OPENAI_API_KEY="):
                            api_key = line.split("=", 1)[1]
                            break
                            
                if api_key:
                    print(f"✓ Found existing OpenAI API key")
                    logger.info("Existing OpenAI API key found")
                    
            except Exception as e:
                logger.warning(f"Error reading existing .env file: {e}")
                print(f"Warning: Could not read existing .env file: {e}")
        
        # Prompt for OpenAI API key if not found
        if not api_key:
            api_key = input("Enter your OpenAI API key: ").strip()
            if not api_key:
                self._exit_with_error("OpenAI API key is required")
        
        # Create/update .env file
        print(f"Creating/updating .env file at: {env_file}")
        with open(env_file, "w") as f:
            f.write(f"OPENAI_API_KEY={api_key}\n")
            f.write(f"START_DIR={start_dir}\n")
            
        logger.info(f"Created/updated .env file: {env_file}")
        logger.info(f"START_DIR set to: {start_dir}")
        print(f"✓ Environment configured with START_DIR: {start_dir}")

    def _start_containers(self):
        """Start MCP server and Kali container"""
        print("\nStarting containers...")
        logger.info("Starting MCP server and Kali container...")
        
        # Set environment variable for docker-compose
        env = os.environ.copy()
        start_dir = f"/tmp/{self.app_name}_app"
        env["START_DIR"] = start_dir
        
        print(f"Setting START_DIR environment variable: {start_dir}")
        logger.info(f"Environment variable START_DIR set to: {start_dir}")
        
        # Start services using docker-compose
        print("Starting containers with docker-compose...")
        
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=self.agent_dir,
            env=env,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"Docker-compose failed: {result.stderr}")
            print(f"ERROR: Docker-compose failed")
            print(f"STDERR: {result.stderr}")
            self._exit_with_error("Failed to start containers")
            
        print("✓ Containers started successfully")
        logger.info("Containers started successfully")
        
        print("Waiting for containers to initialize...")
        logger.info("Waiting for containers to initialize...")
        time.sleep(5)
        
        # Check container status
        print("Checking container status...")
        result = subprocess.run(
            ["docker", "compose", "ps"],
            cwd=self.agent_dir,
            capture_output=True,
            text=True
        )
        
        print("Container Status:")
        print(result.stdout)
        logger.info(f"Container status:\n{result.stdout}")
        
        # Verify specific containers are running
        if "mcp-server" in result.stdout and "kali-container" in result.stdout:
            print("✓ Both MCP server and Kali container are running")
            logger.info("Both MCP server and Kali container confirmed running")
        else:
            logger.warning("Some containers may not be running properly")
            print("⚠ Warning: Some containers may not be running properly")

    def _copy_codebase_to_kali(self):
        """Copy app codebase to Kali container"""
        print("\nCopying app codebase to Kali container...")
        logger.info("Copying app codebase to Kali container...")
        
        source_path = self.app_dir / "codebase"
        container_name = "kali-container"
        target_path = f"/tmp/{self.app_name}_app"
        
        # Check if source codebase exists
        if not source_path.exists():
            print(f"⚠ Warning: Codebase directory not found at {source_path}")
            logger.warning(f"Codebase directory not found: {source_path}")
            return
        
        print(f"Source: {source_path}")
        print(f"Target: {container_name}:{target_path}")
        logger.info(f"Copying from {source_path} to {container_name}:{target_path}")
        
        try:
            # Create target directory in container
            result = subprocess.run(
                ["docker", "exec", container_name, "mkdir", "-p", target_path],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.warning(f"Could not create directory in container: {result.stderr}")
                print(f"⚠ Warning: Could not create directory in container")
                return
            
            # Copy files to container
            result = subprocess.run(
                ["docker", "cp", f"{source_path}/.", f"{container_name}:{target_path}/"],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to copy codebase: {result.stderr}")
                print(f"ERROR: Failed to copy codebase to container")
                print(f"STDERR: {result.stderr}")
            else:
                print(f"✓ Codebase copied successfully to {target_path}")
                logger.info(f"Codebase copied successfully to {target_path}")
                
        except Exception as e:
            logger.warning(f"Exception during codebase copy: {e}")
            print(f"⚠ Warning: Exception during codebase copy: {e}")

    def run_agent(self):
        """Run the custom agent - custom_agent.py"""
        print("\n" + "=" * 60)
        print("RUNNING CUSTOM AGENT")
        print("=" * 60)
        logger.info("Starting custom agent execution...")
        
        try:
            # Import the CustomAgent class
            from agent.custom_agent import CustomAgent
            
            # Create agent instance with dry_run mode for infrastructure testing
            # Set dry_run=False for actual AI execution
            print("Initializing custom agent...")
            logger.info("Creating CustomAgent instance")
            
            agent = CustomAgent(
                model="gpt-5-2025-08-07",
                max_iterations=1,
                max_output_tokens=8192,
                screenshot_enabled=True,
                app_name=self.app_name,
                dry_run=True,  # Set to False for actual AI execution
            )
            
            print("Running agent...")
            logger.info("Executing agent.run()")
            
            # This can take a while for actual LLM calls
            result = agent.run()
            
            # Log and display results
            logger.info("Agent execution completed")
            logger.info(f"Agent result: {result}")
            
            print("\n" + "=" * 60)
            print("AGENT EXECUTION RESULTS")
            print("=" * 60)
            print(f"Status: {result.get('status', 'Unknown')}")
            print(f"Turns: {result.get('turns', 0)}")
            print(f"Log file: {result.get('log_file', 'None')}")
            
            if result.get('final_message'):
                print("Final Message:")
                print(f"  {result['final_message']}")
            
            print("=" * 60)
            
            return result
            
        except Exception as e:
            logger.error(f"Error running custom agent: {e}")
            print(f"ERROR: Failed to run custom agent: {e}")
            return {
                "status": f"error: {str(e)}",
                "turns": 0,
                "final_message": None,
                "log_file": None,
            }

    def run_probes_checks(self):
        """Run the evaluation checks"""
        print("\n" + "=" * 60)
        print("RUNNING PROBE CHECKS")
        print("=" * 60)
        logger.info("Running probe checks...")
        
        # Run the checks
        result = self.run_command("./run_checks.sh", cwd=self.app_dir, check=False)
        
        # Show results (for this script, STDERR contains progress info, not errors)
        if result.stdout.strip():
            print(result.stdout)
        if result.stderr.strip():
            print(result.stderr)  # Don't label as STDERR since it's just progress info
        
        print(f"✓ Probe checks completed (exit code: {result.returncode})")
        
        # Check for scores.json file
        scores_file = self.app_dir / "scores.json"
        if scores_file.exists():
            try:
                with open(scores_file, 'r') as f:
                    scores_content = f.read()
                logger.info(f"Scores found: {scores_content}")

            except Exception as e:
                print(f"Error reading scores.json: {e}")
                logger.error(f"Error reading scores.json: {e}")
        else:
            print("No scores.json file was created")
            logger.info("No scores.json file found")
        
        logger.info(f"Probe checks completed with exit code: {result.returncode}")
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

            self.setup_agent()
            self.run_agent()

            self.run_probes_checks()
            
            print("\n" + "=" * 60)
            print("PIPELINE COMPLETED SUCCESSFULLY")
            print("=" * 60)
            print(f"App: {self.app_name}")
            print(f"Log file: {self.log_file}")
            
            logger.info("Pipeline completed successfully")
            return 0
            
        except KeyboardInterrupt:
            print("\n⚠ Runner interrupted by user")
            logger.info("Runner interrupted by user")
            return 1
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
            print(f"Full log available at: {self.log_file}")
            logger.error(f"Unexpected error: {e}")
            return 1
        finally:
            pass
            # self.cleanup()


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