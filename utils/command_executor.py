#!/usr/bin/env python3
"""
Command Executor

A utility class for running shell commands with proper logging,
error handling, and live output streaming.
"""

import shlex
import sys
import subprocess
import time
from pathlib import Path
from selectors import EVENT_READ, DefaultSelector
from typing import Dict, List, Optional

from utils.logger import logger

# Module-level constants for command timeouts
DEFAULT_COMMAND_TIMEOUT = 120  # 2 minutes


class CommandExecutor:
    def __init__(self):
        pass

    def run(
        self,
        command: str,
        cwd: Optional[Path] = None,
        check: bool = True,
        capture_output: bool = True,
        live_output: bool = False,
        env: Optional[Dict[str, str]] = None,
    ) -> subprocess.CompletedProcess:
        """
        Runs a shell command securely.

        Args:
            command: The command string to execute.
            cwd: The working directory for the command.
            check: If True, raises an exception on non-zero exit codes.
            capture_output: If True, captures stdout and stderr.
            live_output: If True, streams command output to the logger in real-time.
            env: Optional environment variables for the subprocess.

        Returns:
            A CompletedProcess object.
        """
        args = shlex.split(command)
        logger.info(f"Preparing command: `{' '.join(args)}` in `{cwd or '.'}`")

        try:
            if live_output:
                return self._run_with_live_output(args, cwd, check, env)

            result = subprocess.run(
                args,
                cwd=cwd,
                capture_output=capture_output,
                text=True,
                check=False,  # We handle the check manually
                env=env,
            )

            if result.stdout:
                logger.debug(f"STDOUT:\n{result.stdout.strip()}")
            if result.stderr:
                logger.warning(f"STDERR:\n{result.stderr.strip()}")

            if check and result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode, args, result.stdout, result.stderr
                )

            return result

        except FileNotFoundError:
            logger.error(f"Command not found: {args[0]}")
            raise
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed with exit code {e.returncode}: `{command}`")
            logger.error(f"STDERR: {e.stderr.strip() if e.stderr else 'N/A'}")
            raise
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while running command `{command}`: {e}"
            )
            raise

    def start_background_process(
        self,
        command: str,
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> subprocess.Popen:
        """
        Starts a background process without waiting for it to complete.

        Args:
            command: The command string to execute.
            cwd: The working directory for the command.
            env: Optional environment variables for the subprocess.

        Returns:
            A Popen object for the background process.
        """
        args = shlex.split(command)
        logger.info(
            f"Starting background process: `{' '.join(args)}` in `{cwd or '.'}`"
        )

        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            logger.info(f"Background process started with PID: {process.pid}")
            return process
        except FileNotFoundError:
            logger.error(f"Command not found: {args[0]}")
            raise
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while starting background process `{command}`: {e}"
            )
            raise

    def run_with_progress(
        self,
        command: str,
        timeout: int,
        message: str = "Running command with progress",
        cwd: Optional[Path] = None,
        check: bool = True,
        env: Optional[Dict[str, str]] = None
    ) -> subprocess.CompletedProcess:
        args = shlex.split(command)
        is_interactive = sys.stdout.isatty()
        if is_interactive:
            return self._run_with_spinner(args, message, cwd, check, env, timeout)
        else:
            return self._run_with_dots(args, message, cwd, check, env, timeout)

    def _run_with_dots(
            self,
            args: List[str],
            message: str,
            cwd: Optional[Path],
            check: bool,
            env: Optional[Dict[str, str]],
            timeout: int
    ) -> subprocess.CompletedProcess:
        logger.info(f"{message}. . .")
        start_time = time.time()

        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )
            stdout, stderr = process.communicate(timeout=timeout)
            elapsed = time.time() - start_time
            elapsed_str = f"{int(elapsed):.0f}s" if elapsed < 60 else f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

            if process.returncode != 0:
                logger.error(f"{message}... failed! ({elapsed_str})")
                logger.error(f"Command: {' '.join(args)}")
                logger.error(f"Exit code: {process.returncode}")

                if stdout:
                    logger.error(f"STDOUT:\n{stdout}")
                if stderr:
                    logger.error(f"STDERR:\n{stderr}")
                
                if check:
                    raise subprocess.CalledProcessError(
                        process.returncode, args, stdout, stderr
                    )
            else:
                logger.info(f"{message}... done! ({elapsed_str})")
            
            return subprocess.CompletedProcess(
                args=args,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr
            )
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            elapsed = time.time() - start_time
            logger.error(f"{message}... timeout! ({elapsed:.0f}s / {timeout}s)")
            logger.error(f"Command: {' '.join(args)}")
            if stdout:
                logger.error(f"STDOUT:\n{stdout}")
            if stderr:
                logger.error(f"STDERR:\n{stderr}")
            raise
        except FileNotFoundError:
            logger.error(f"Command not found: {args[0]}")
            raise

    def _run_with_spinner(
        self,
        args: List[str],
        message: str,
        cwd: Optional[Path],
        check: bool,
        env: Optional[Dict[str, str]],
        timeout: int,
    ) -> subprocess.CompletedProcess:
        """
        Run command with animated spinner (for interactive terminals).

        Shows: "Building APK ⠋" (spinner animates)
        """
        logger.info(f"{message}...")

        # Spinner characters (Braille patterns - look smooth!)
        spinner_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        start_time = time.time()

        try:
            # Start the process
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )

            # Animate spinner while process runs
            spinner_idx = 0
            while True:
                # Check if process finished
                if process.poll() is not None:
                    break

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    process.kill()
                    raise subprocess.TimeoutExpired(args, timeout)

                # Update spinner (print to console, not logger!)
                spinner = spinner_chars[spinner_idx % len(spinner_chars)]
                elapsed_str = f"{int(elapsed)}s" if elapsed < 60 else f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
                print(f"\r{message} {spinner} ({elapsed_str})", end='', flush=True)

                spinner_idx += 1
                time.sleep(0.1)  # Update every 100ms

            # Get final output
            stdout, stderr = process.communicate()
            elapsed = time.time() - start_time

            # Clear spinner line
            print("\r" + " " * 80 + "\r", end='', flush=True)

            # Format time
            if elapsed < 60:
                time_str = f"{elapsed:.0f}s"
            else:
                m, s = int(elapsed // 60), int(elapsed % 60)
                time_str = f"{m}m {s}s"

            # Check result
            if process.returncode != 0:
                logger.error(f"{message}... failed! ({time_str})")
                logger.error(f"Command: {' '.join(args)}")
                logger.error(f"Exit code: {process.returncode}")

                if stdout:
                    logger.error(f"STDOUT:\n{stdout}")
                if stderr:
                    logger.error(f"STDERR:\n{stderr}")

                if check:
                    raise subprocess.CalledProcessError(
                        process.returncode, args, stdout, stderr
                    )
            else:
                logger.info(f"{message}... done! ({time_str})")

            return subprocess.CompletedProcess(
                args=args,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
            )

        except subprocess.TimeoutExpired:
            stdout, stderr = process.communicate()
            elapsed = time.time() - start_time

            # Clear spinner
            print("\r" + " " * 80 + "\r", end='', flush=True)

            logger.error(f"{message}... timeout! ({elapsed:.0f}s / {timeout}s)")
            logger.error(f"Command: {' '.join(args)}")

            if stdout:
                logger.error(f"STDOUT:\n{stdout}")
            if stderr:
                logger.error(f"STDERR:\n{stderr}")

            raise
        except FileNotFoundError:
            print("\r" + " " * 80 + "\r", end='', flush=True)
            logger.error(f"Command not found: {args[0]}")
            raise

    def _run_with_live_output(
        self,
        args: List[str],
        cwd: Optional[Path],
        check: bool,
        env: Optional[Dict[str, str]],
    ) -> subprocess.CompletedProcess:
        """Helper to stream output in real-time."""
        stdout_lines = []
        stderr_lines = []

        process = subprocess.Popen(
            args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        selector = DefaultSelector()
        selector.register(process.stdout, EVENT_READ)
        selector.register(process.stderr, EVENT_READ)

        while process.poll() is None and selector.get_map():
            events = selector.select(timeout=0.1)
            for key, _ in events:
                line = key.fileobj.readline()
                if not line:
                    selector.unregister(key.fileobj)
                    continue

                if key.fileobj == process.stdout:
                    logger.info(line.strip())
                    stdout_lines.append(line)
                else:
                    logger.warning(line.strip())
                    stderr_lines.append(line)

        stdout, stderr = process.communicate()
        if stdout:
            for line in stdout.splitlines():
                logger.info(line.strip())
                stdout_lines.append(line + "\n")
        if stderr:
            for line in stderr.splitlines():
                logger.warning(line.strip())
                stderr_lines.append(line + "\n")

        if check and process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode, args, "".join(stdout_lines), "".join(stderr_lines)
            )

        return subprocess.CompletedProcess(
            args=args,
            returncode=process.returncode,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
        )

