#!/usr/bin/env python3

import os
import shlex
import subprocess
import time
import queue
import threading
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
                    if len(args[i]) > 2 and args[i][1:3] == ":\\":
                        # Convert Windows path to Git Bash format: C:\path -> /c/path
                        drive = args[i][0].lower()
                        path = args[i][3:].replace("\\", "/")
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
        
        def clear_line() -> None:
            print("\r" + " " * 80 + "\r", end="", flush=True)

        def drain_queue(q: queue.Queue, error=False, accumulator: str="") -> str:
            log = logger.info
            if (error):
                log = logger.error
            while True:
                try:
                    line: str = q.get_nowait()
                except queue.Empty:
                    break
                clear_line()
                log(line.rstrip("\n"))
                accumulator += line
            return accumulator

        def enqueue_output(stream, q: queue.Queue) -> None:
            for line in stream:
                q.put(line)
            stream.close()

        def spinner():
            spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            idx = 0
            timestamp = 0.0

            def update(elapsed: float) -> int:
                nonlocal timestamp, idx

                spinner = spinner_chars[idx % len(spinner_chars)]
                time_str = self._format_elapsed_time(elapsed)
                print(f"\r{message} {spinner} ({time_str})", end="", flush=True)

                if (elapsed - timestamp > 0.1):
                    timestamp = elapsed
                    idx += 1
            
            return update
        

        # Use posix=False on Windows to preserve backslashes
        args = shlex.split(command, posix=(os.name != "nt"))
        args = self._fix_bash_command(args)
        logger.info(f"{message}...")
        start_time = time.time()
        update_spinner = spinner()

        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )

            stdout_q = queue.Queue()
            stderr_q = queue.Queue()
            stdout_t = threading.Thread(target=enqueue_output, args=(process.stdout, stdout_q))
            stderr_t = threading.Thread(target=enqueue_output, args=(process.stderr, stderr_q))
            stdout_t.start()
            stderr_t.start()
            stdout = ""
            stderr = ""

            while process.poll() is None:

                elapsed = time.time() - start_time
                if elapsed > timeout:
                    process.kill()
                    raise subprocess.TimeoutExpired(args, timeout)

                stdout += drain_queue(stdout_q)
                stderr += drain_queue(stderr_q, True)
                update_spinner(elapsed)

            stdout_t.join()
            stderr_t.join()

            stdout += drain_queue(stdout_q)
            stderr += drain_queue(stderr_q)

            elapsed = time.time() - start_time
            clear_line()
            time_str = self._format_elapsed_time(elapsed)

            if process.returncode != 0:
                logger.error(f"{message}... failed! ({time_str})")
                logger.error(f"Command: {' '.join(args)}")
                logger.error(f"Exit code: {process.returncode}")
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
            stdout_t.join()
            stderr_t.join()

            stdout += drain_queue(stdout_q)
            stderr += drain_queue(stderr_q)

            elapsed = time.time() - start_time
            clear_line()

            logger.error(f"{message}... timeout! ({elapsed:.0f}s / {timeout}s)")
            logger.error(f"Command: {' '.join(args)}")
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
