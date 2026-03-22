"""Runtime setup utilities for app installation and backend configuration."""

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from utils.logger import logger


def setup_container_emulator_port_forwards(
    app_dir: Path, emulator_backend: str
) -> None:
    """Set up socat port forwards inside the emulator container for container mode.

    In container emulator mode, Android's 10.0.2.2 maps to the emulator container's
    loopback — not the Docker host where backend containers listen. This function
    reads the app's metadata.json to find the server port, discovers which backend
    container on shared_net listens on that port, and sets up socat forwarding inside
    the emulator container.

    Only runs when emulator_backend is "container". In native mode, 10.0.2.2 already
    routes to the host where backend containers listen, so no forwarding is needed.
    """
    if emulator_backend != "container":
        return

    from utils.emulator_manager import EMULATOR_CONTAINER_NAME

    # Read emulator_server from metadata.json
    metadata_path = app_dir / "metadata.json"
    if not metadata_path.exists():
        logger.debug("No metadata.json found — skipping port forwards")
        return

    metadata = json.loads(metadata_path.read_text())
    emulator_server = metadata.get("emulator_server", "")
    if not emulator_server:
        logger.debug("No emulator_server in metadata — skipping port forwards")
        return

    # Parse port from emulator_server (handles "http://10.0.2.2:8080", "10.0.2.2:5222", etc.)
    port = None
    if "://" in emulator_server:
        parsed = urlparse(emulator_server)
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
    else:
        match = re.search(r":(\d+)", emulator_server)
        if match:
            port = int(match.group(1))

    if port is None:
        logger.warning(f"Could not parse port from emulator_server: {emulator_server}")
        return

    # Find backend containers on shared_net (exclude emulator container)
    result = subprocess.run(
        ["docker", "network", "inspect", "shared_net", "--format",
         "{{range .Containers}}{{.Name}} {{end}}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        logger.warning("Could not inspect shared_net network")
        return

    containers = result.stdout.strip().split()
    backend_containers = [c for c in containers if c != EMULATOR_CONTAINER_NAME]

    if not backend_containers:
        logger.debug("No backend containers on shared_net")
        return

    # Find which container listens on the target port
    target_container = None
    for container_name in backend_containers:
        # Check if this container has the port exposed or is listening on it
        check = subprocess.run(
            ["docker", "exec", container_name, "sh", "-c",
             f"ss -tlnp 2>/dev/null | grep -q ':{port}' || "
             f"netstat -tlnp 2>/dev/null | grep -q ':{port}'"],
            capture_output=True,
            timeout=10,
        )
        if check.returncode == 0:
            target_container = container_name
            break

    if target_container is None:
        # Fall back: use the first backend container (common case: single backend)
        target_container = backend_containers[0]
        logger.info(
            f"Could not detect which container listens on port {port}, "
            f"using first backend container: {target_container}"
        )

    # Kill any existing socat on this port
    subprocess.run(
        ["docker", "exec", EMULATOR_CONTAINER_NAME,
         "pkill", "-f", f"socat.*{port}"],
        capture_output=True,
        timeout=10,
    )

    # Set up socat: emulator-container:port → backend-container:port
    result = subprocess.run(
        ["docker", "exec", "-d", EMULATOR_CONTAINER_NAME,
         "socat", f"TCP-LISTEN:{port},fork,reuseaddr",
         f"TCP:{target_container}:{port}"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode == 0:
        logger.info(
            f"Port forward established: emulator-container:{port} → "
            f"{target_container}:{port}"
        )
    else:
        logger.warning(
            f"Failed to set up port forward on port {port}: {result.stderr}"
        )


def install_app_and_setup_backend(
    app_dir: Path,
    emulator,
    project_root: Path,
    *,
    build_command_timeout: int,
    start_ssrf: bool = False,
    apk_path: Optional[Path] = None,
    inject_flags: bool = True,
    emulator_backend: str = "native",
) -> None:
    """
    Install the app and set up backend services.
    Expects the emulator to be booted and ready.

    Args:
        app_dir: Application directory
        emulator: EmulatorManager instance
        project_root: Project root directory
        start_ssrf: Whether to start the SSRF listener (discovery mode only)
        apk_path: Optional path to APK file (passed to start_runtime.sh --apk)
        inject_flags: Whether to inject security flags (discovery mode only)
    """
    from utils.command_executor import CommandExecutor
    from utils.utils import get_app_metadata

    cmd = CommandExecutor()

    # Sanity check: emulator should already be booted by the workflow caller
    if not emulator.check_status():
        raise RuntimeError("Emulator status check failed")
    logger.info("Emulator status verified")

    # Prefer start_runtime.sh (new pattern), fall back to setup.sh (legacy)
    runtime_script = app_dir / "start_runtime.sh"
    legacy_script = app_dir / "setup.sh"

    logger.info("Setting up backend and installing APK...")
    if runtime_script.exists():
        runtime_cmd = "bash ./start_runtime.sh"
        if apk_path:
            runtime_cmd += f" --apk {shlex.quote(str(apk_path))}"
        cmd.run_with_progress(
            runtime_cmd,
            timeout=build_command_timeout,
            message="Setting up backend and installing APK",
            cwd=app_dir,
        )
    elif legacy_script.exists():
        logger.info("Using legacy setup.sh")
        cmd.run_with_progress(
            "bash ./setup.sh",
            timeout=build_command_timeout,
            message="Setting up backend and installing APK",
            cwd=app_dir,
        )
    else:
        raise FileNotFoundError(
            f"No runtime script found in {app_dir}. "
            "Expected start_runtime.sh or setup.sh"
        )

    # Set up port forwarding for container emulator mode
    setup_container_emulator_port_forwards(app_dir, emulator_backend)

    # Inject flags (discovery mode only; exploit uses verify_files)
    if inject_flags:
        logger.info("Injecting security flags...")
        inject_flags_path = project_root / "inject_flags.sh"
        cmd.run(
            f"bash {inject_flags_path}",
            cwd=app_dir,
            timeout=30,
        )
        logger.info("Flags injected successfully")

    # Start SSRF listener if requested (discovery mode only)
    if start_ssrf:
        app_name = app_dir.name
        metadata = get_app_metadata(app_name)
        container_names = metadata.get("container_names", [])

        if container_names:
            from utils.ssrf_utils import start_ssrf_listener

            logger.info("Starting SSRF listener...")
            ssrf_compose_dir = project_root / "evaluation" / "ssrf_listener"
            if start_ssrf_listener(ssrf_compose_dir):
                logger.info("SSRF listener started successfully")
            else:
                logger.warning("Failed to start SSRF listener")
        else:
            logger.info("No backend containers - skipping SSRF listener")


def check_connectivity(container, app_server: Optional[str] = None) -> None:
    """Verify the kali container can reach the app server and emulator.

    Raises RuntimeError if any check fails.

    Args:
        container: Docker container to run checks from.
        app_server: App server URL to check (e.g. "server:8080"). Skipped if None.
    """
    checks = []

    # Kali → app server (if configured)
    # Use nc for a raw TCP check — works for any protocol (HTTP, XMPP, etc.)
    if app_server:
        # Strip scheme (e.g. "http://server:8080" → "server:8080")
        server = app_server.split("://", 1)[-1]
        host, port = server.rsplit(":", 1)
        nc_cmd = f"nc -z -w 10 {host} {port}"
        result = container.exec_run(f"bash -c '{nc_cmd}'")
        checks.append(("kali → app_server", result.exit_code == 0, nc_cmd))

    # Kali → emulator (via ADB)
    result = container.exec_run(
        "bash -c 'export ADB_SERVER_SOCKET=tcp:host.docker.internal:5037 && adb devices'",
        demux=True,
    )
    stdout = result.output[0].decode() if result.output[0] else ""
    checks.append(("kali → emulator (adb)", "emulator" in stdout, stdout.strip()))

    # Host → emulator (for verify scripts that run on host)
    try:
        host_result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        checks.append(
            (
                "host → emulator (adb)",
                "emulator" in host_result.stdout,
                host_result.stdout.strip(),
            )
        )
    except Exception as e:
        checks.append(("host → emulator (adb)", False, str(e)))

    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        logger.info(f"  Connectivity [{status}]: {name} — {detail}")

    failed = [name for name, passed, _ in checks if not passed]
    if failed:
        raise RuntimeError(f"Connectivity check failed: {', '.join(failed)}")
