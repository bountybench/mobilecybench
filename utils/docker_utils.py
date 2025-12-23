import logging
import threading
import time
from typing import Callable, List, Optional, Tuple

import docker

logger = logging.getLogger(__name__)


def run_command_in_container(
    container_name: str,
    command: List[str],
    timeout: float,
    stdout_callback: Optional[Callable[[str], None]] = None,
    stderr_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[str, str, int]:
    """
    Execute a command in a Docker container with real-time streaming and timeout.

    Args:
        container_name: Name or ID of the container
        command: Command list to execute
        timeout: Timeout in seconds
        stdout_callback: Function to handle each chunk of stdout (usually text)
        stderr_callback: Function to handle each chunk of stderr (usually text)

    Returns:
        Tuple of (combined_stdout, combined_stderr, exit_code)
    """
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
    except Exception as e:
        logger.error(f"Failed to get container {container_name}: {e}")
        raise

    # Environment variables
    env = {"PYTHONUNBUFFERED": "1"}

    try:
        exec_id = client.api.exec_create(
            container.id, cmd=command, environment=env, tty=False
        )["Id"]
    except Exception as e:
        logger.error(f"Failed to create exec: {e}")
        raise

    output_stream = client.api.exec_start(exec_id, stream=True, demux=True)

    stdout_chunks = []
    stderr_chunks = []
    stop_event = threading.Event()

    def stream_output():
        try:
            for stdout, stderr in output_stream:
                if stop_event.is_set():
                    break

                if stdout:
                    text = stdout.decode("utf-8", errors="replace")
                    stdout_chunks.append(text)
                    if stdout_callback:
                        stdout_callback(text)

                if stderr:
                    text = stderr.decode("utf-8", errors="replace")
                    stderr_chunks.append(text)
                    if stderr_callback:
                        stderr_callback(text)

        except Exception as e:
            # Only warn if not stopped (timeout sets stop_event)
            if not stop_event.is_set():
                logger.warning(f"Exec stream closed/error: {e}")

    stream_thread = threading.Thread(target=stream_output, daemon=True)
    stream_thread.start()

    exec_inspect = client.api.exec_inspect
    start_time = time.time()
    exit_code = -1

    while True:
        try:
            exec_info = exec_inspect(exec_id)
            if not exec_info["Running"]:
                exit_code = exec_info.get("ExitCode", 0)
                break
        except Exception as e:
            logger.error(f"Failed to inspect exec: {e}")
            break

        if time.time() - start_time > timeout:
            stop_event.set()
            logger.warning(f"Exec command timed out after {timeout} seconds")
            # Cannot easily kill exec inside container via API
            break
        time.sleep(1)

    # If the process finished naturally, we wait for the stream to close on its own.
    # If we timed out or errored, stop_event is already set.
    stream_thread.join(timeout=5)

    # Ensure thread is stopped if join timed out
    if stream_thread.is_alive():
        stop_event.set()
        stream_thread.join(timeout=1)

    return "".join(stdout_chunks), "".join(stderr_chunks), exit_code
