#!/usr/bin/env python3

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

from utils.logger import logger


class CommandExecutor:
    @staticmethod
    def _fix_bash_command(args):
        """
        Replace 'bash' with Git Bash on Windows and convert Windows paths to Unix format.
        Does nothing on non-NT systems.
        """
        if args and args[0] == "bash" and os.name == "nt":
            # On Windows, prefer Git Bash over WSL bash
            git_bash = r"C:\Program Files\Git\usr\bin\bash.exe"
            if os.path.exists(git_bash):
                args[0] = git_bash
                # Convert Windows paths to Git Bash format for arguments
                for i in range(1, len(args)):
                    # Check if argument looks like a Windows path (e.g., C:\... or D:\...)
                    if len(args[i]) > 2 and args[i][1:3] == ':\\':
                        # Convert Windows path to Git Bash format: C:\path -> /c/path
                        drive = args[i][0].lower()
                        path = args[i][3:].replace('\\', '/')
                        args[i] = f"/{drive}/{path}"
        return args

    def run(
        self,
        command: str,
        cwd: Optional[Path] = None,
        check: bool = True,
        capture_output: bool = True,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> subprocess.CompletedProcess:
        # Use posix=False on Windows to preserve backslashes
        args = shlex.split(command, posix=(os.name != "nt"))
        args = self._fix_bash_command(args)
        logger.info(f"Preparing command: `{' '.join(args)}` in `{cwd or '.'}`")

        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                capture_output=capture_output,
                text=True,
                check=False,
                env=env,
                timeout=timeout,
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
            if e.stdout:
                logger.error(f"STDOUT:\n{e.stdout.strip()}")
            if e.stderr:
                logger.error(f"STDERR:\n{e.stderr.strip()}")
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
        # Use posix=False on Windows to preserve backslashes
        args = shlex.split(command, posix=(os.name != "nt"))
        args = self._fix_bash_command(args)
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
        env: Optional[Dict[str, str]] = None,
    ) -> subprocess.CompletedProcess:
        # Use posix=False on Windows to preserve backslashes
        args = shlex.split(command, posix=(os.name != "nt"))
        args = self._fix_bash_command(args)
        logger.info(f"{message}...")
        spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        start_time = time.time()

        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            # animation while running
            spinner_idx = 0
            while True:
                if process.poll() is not None:  # process finished
                    break

                elapsed = time.time() - start_time
                if elapsed > timeout:
                    process.kill()
                    raise subprocess.TimeoutExpired(args, timeout)

                spinner = spinner_chars[spinner_idx % len(spinner_chars)]
                time_str = self._format_elapsed_time(elapsed)
                print(f"\r{message} {spinner} ({time_str})", end="", flush=True)
                spinner_idx += 1
                time.sleep(0.1)

            stdout, stderr = process.communicate()
            elapsed = time.time() - start_time
            print("\r" + " " * 80 + "\r", end="", flush=True)  # clear spinner
            time_str = self._format_elapsed_time(elapsed)

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
            print("\r" + " " * 80 + "\r", end="", flush=True)  # clear spinner
            logger.error(f"{message}... timeout! ({elapsed:.0f}s / {timeout}s)")
            logger.error(f"Command: {' '.join(args)}")
            if stdout:
                logger.error(f"STDOUT:\n{stdout}")
            if stderr:
                logger.error(f"STDERR:\n{stderr}")
            raise
        except FileNotFoundError:
            print("\r" + " " * 80 + "\r", end="", flush=True)
            logger.error(f"Command not found: {args[0]}")
            raise

    def _format_elapsed_time(self, seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        else:
            m, s = int(seconds // 60), int(seconds % 60)
            return f"{m}m {s}s"
