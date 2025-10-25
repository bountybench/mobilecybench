#!/usr/bin/env python3

import shlex
import subprocess
from pathlib import Path
from selectors import EVENT_READ, DefaultSelector
from typing import Dict, List, Optional

from utils.logger import logger

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

