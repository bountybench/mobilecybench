"""
Emulator Lifecycle Manager
"""

import logging
import os
import subprocess
import tempfile
import time
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("MobileCyBench.emulator_manager")

EMULATOR_CONTAINER_NAME = "emulator-container"


class EmulatorState(Enum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"


class SystemImage(Enum):
    GOOGLE_APIS = "google_apis"  # can be rooted with 'adb root'
    GOOGLE_APIS_PLAYSTORE = "google_apis_playstore"  # cannot be rooted


class EmulatorManager:
    """
    AVD naming convention: MobileCybenchEmulatorAPI{sdk_version}_{system_image_type} - this is consistent with our orchestrator docker image.
    Previous name: MobileCybenchEmu for host. This should be deprecated moving forward. Haven't done this yet - breaks local ci / not important for now.
    """

    def __init__(
        self,
        project_root: Path,
        sdk_version: Optional[str] = None,
        app_name: Optional[str] = None,
        rootable: bool = True,
        emulator_backend: str = "native",
        emulator_display: str = "headed",
    ):
        self.emulator_backend = emulator_backend
        self.emulator_display = emulator_display
        self.project_root = project_root
        self.sdk_version = sdk_version
        self.app_name = app_name
        self.rootable = rootable
        self.system_image = (
            SystemImage.GOOGLE_APIS if rootable else SystemImage.GOOGLE_APIS_PLAYSTORE
        )
        self.state = EmulatorState.NOT_STARTED
        self.process: Optional[subprocess.Popen] = None
        self.emulator_container = None  # Docker container (container mode)
        self.device_id: Optional[str] = None  # Track our specific emulator device
        self.emulator_config = self._build_emulator_config()

        emulator_type = "rootable" if rootable else "non-rootable"
        logger.info(
            f"EmulatorManager initialized: backend={emulator_backend}, "
            f"display={emulator_display} ({emulator_type})"
        )

    def _build_emulator_config(self) -> dict:
        android_home = os.getenv("ANDROID_HOME")
        if android_home is None:
            raise EnvironmentError("ANDROID_HOME environment variable is not set")
        emulator_bin = Path(android_home) / "emulator" / "emulator"

        if not self.sdk_version:
            raise ValueError("SDK version is required")

        system_image_suffix = self.system_image.value
        emulator_name = (
            f"MobileCybenchEmulatorAPI{self.sdk_version}_{system_image_suffix}"
        )

        if self.emulator_display == "headless":
            emulator_args = [
                str(emulator_bin),
                "-avd",
                emulator_name,
                "-no-snapshot-save",
                "-wipe-data",
                "-no-window",
                "-gpu",
                "off",
                "-memory",
                "2048",
                "-no-audio",
                "-read-only",
            ]
        else:
            emulator_args = [
                str(emulator_bin),
                "-avd",
                emulator_name,
                "-no-snapshot-save",
                "-wipe-data",
                "-gpu",
                "host",
                "-skin",
                "1080x1920",
                "-memory",
                "2048",
            ]

        return {
            "emulator_display": self.emulator_display,
            "emulator_name": emulator_name,
            "emulator_args": emulator_args,
            "android_home": android_home,
            "system_image": system_image_suffix,
        }

    def _verify_avd_exists(self):
        android_home = self.emulator_config["android_home"]
        emulator_bin = Path(android_home) / "emulator" / "emulator"
        emulator_name = self.emulator_config["emulator_name"]

        try:
            result = subprocess.run(
                [str(emulator_bin), "-list-avds"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            raise RuntimeError(f"Emulator binary not found at {emulator_bin}.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Timeout while listing available AVDs")
        except Exception as e:
            raise RuntimeError(f"Failed to list AVDs: {e}")

        available_avds = result.stdout.strip().split("\n")
        available_avds = [avd.strip() for avd in available_avds if avd.strip()]
        if not available_avds:
            logger.error("No AVDs found on this system")
            raise RuntimeError(
                "No AVDs found. Please create an AVD first using Android SDK tools."
            )
        if emulator_name not in available_avds:
            raise RuntimeError(
                f"AVD '{emulator_name}' not found. Available AVDs: {available_avds}"
            )
        logger.info(f"AVD '{emulator_name}' found.")

    def start_in_background(self):
        """
        Start the Android emulator in background (non-blocking).

        Dispatches to container or native mode based on self.emulator_backend.
        Use wait_until_ready() to block until boot is complete.

        Raises:
            RuntimeError: If emulator is already running
            subprocess.SubprocessError: If emulator fails to start
        """
        if self.state != EmulatorState.NOT_STARTED:
            raise RuntimeError(
                f"Cannot start emulator in state {self.state.value}. Must be NOT_STARTED."
            )

        if self.emulator_backend == "container":
            self._start_container_emulator()
        else:
            self._start_native_emulator()

    def _start_container_emulator(self):
        """Start emulator as a Docker container inside DinD."""
        import docker

        logger.info("=" * 60)
        logger.info("STARTING EMULATOR (container mode)")
        logger.info("=" * 60)

        self.state = EmulatorState.STARTING

        client = docker.from_env()

        # Remove stale container
        try:
            old = client.containers.get(EMULATOR_CONTAINER_NAME)
            old.remove(force=True)
            logger.info("Removed stale emulator-container")
        except docker.errors.NotFound:
            pass

        emulator_name = self.emulator_config["emulator_name"]
        android_home = self.emulator_config["android_home"]
        emulator_bin = f"{android_home}/emulator/emulator"

        # Always headless in container mode
        emulator_cmd = (
            f"{emulator_bin} -avd {emulator_name} "
            f"-no-snapshot-save -wipe-data -no-window -gpu off "
            f"-memory 2048 -no-audio -read-only"
        )

        # Use a minimal emulator image (much smaller than the orchestrator)
        emulator_image = os.environ.get(
            "EMULATOR_IMAGE", "cybench/mobilecybench-emulator:latest"
        )

        logger.info(f"Starting emulator container with image: {emulator_image}")
        logger.info(f"Emulator AVD: {emulator_name}")

        # Kill any existing ADB server on the host so it doesn't conflict
        # with the container's port 5037 mapping. The port mapping is needed
        # because host-side scripts (inject_system_ca.sh, start_runtime.sh)
        # use bare `adb` commands. Once all host-side ADB usage is routed
        # through docker exec, the port mapping and this kill-server can go.
        subprocess.run(["adb", "kill-server"], capture_output=True)
        self._devices_before_start = set()

        # Single ADB server design: the container runs the only ADB server
        # (on 0.0.0.0:5037) and the emulator's adbd connects to it via the
        # local qemud pipe. We publish port 5037 to the host so the
        # orchestrator's `adb` commands transparently reach the container's
        # server. No TCP mode (adb tcpip) needed — same architecture as
        # native mode, just the ADB server lives in the container.
        container_cmd = f"bash -c 'adb -a start-server && {emulator_cmd}'"

        try:
            self.emulator_container = client.containers.run(
                image=emulator_image,
                name=EMULATOR_CONTAINER_NAME,
                command=container_cmd,
                devices=["/dev/kvm:/dev/kvm"],
                network="shared_net",
                ports={"5037/tcp": 5037},
                detach=True,
                environment={"ANDROID_HOME": android_home},
            )
            logger.info(
                f"Emulator container started: {self.emulator_container.short_id}"
            )
        except Exception as e:
            self.state = EmulatorState.STOPPED
            logger.error(f"Failed to start emulator container: {e}")
            raise RuntimeError(f"Failed to start emulator container: {e}")

        self.state = EmulatorState.RUNNING
        logger.info(
            "Emulator container started (boot-wait deferred to wait_until_ready)"
        )

    def _start_native_emulator(self):
        """Start emulator as a native subprocess (original behavior)."""
        self._verify_avd_exists()

        logger.info("=" * 60)
        logger.info(
            f"STARTING EMULATOR (display={self.emulator_config['emulator_display']})"
        )
        logger.info("=" * 60)

        self.state = EmulatorState.STARTING

        # Capture existing devices before starting (to detect our new one later)
        self._devices_before_start = self._get_connected_devices()
        running_emulators = [
            d for d in self._devices_before_start if d.startswith("emulator-")
        ]
        if running_emulators:
            self.state = EmulatorState.NOT_STARTED
            devices = ", ".join(running_emulators)
            raise RuntimeError(
                f"Running emulator(s) detected: {devices}\n"
                f"\n"
                f"The runner manages its own emulator — please stop all emulators first:\n"
                f"\n"
                f"  ./stop_emulator.sh          # or: adb -s <device> emu kill\n"
                f"\n"
                f"Then re-run the command."
            )
        if self._devices_before_start:
            logger.info(
                f"Existing non-emulator devices before start: {self._devices_before_start}"
            )

        if self.emulator_display == "headed" and self.app_name:
            logger.info(f"Installing android dependencies for {self.app_name}...")
            try:
                subprocess.run(
                    ["bash", "./setup.sh", self.app_name],
                    cwd=self.project_root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                logger.info("Setup completed successfully")
            except subprocess.CalledProcessError as e:
                self.state = EmulatorState.STOPPED
                logger.error(f"Setup failed: {e.stderr}")
                raise RuntimeError(f"Failed to run setup.sh: {e}")

        # Restart ADB on all interfaces (-a) so Docker containers can reach
        # it via host.docker.internal:5037.
        #
        # Without -a, ADB binds to 127.0.0.1 only. On Linux, host-gateway
        # maps host.docker.internal to the docker0 bridge IP (172.17.0.1),
        # which can't reach 127.0.0.1. macOS Docker Desktop masks this
        # because its VM proxy forwards to the host loopback.
        # See issue #688
        subprocess.run(["adb", "kill-server"], capture_output=True, timeout=10)
        subprocess.run(["adb", "-a", "start-server"], capture_output=True, timeout=10)

        # Boot emulator in background
        emulator_args = self.emulator_config["emulator_args"]
        emulator_name = self.emulator_config["emulator_name"]

        logger.info(f"Starting emulator: {emulator_name}")
        logger.info(f"Command: {' '.join(emulator_args)}")
        logger.info("Emulator will boot in background...")

        env = os.environ.copy()
        env["ANDROID_HOME"] = self.emulator_config["android_home"]
        try:
            # Use temp file instead of PIPE to avoid deadlock if stderr buffer fills.
            self._stderr_file = tempfile.TemporaryFile()
            self.process = subprocess.Popen(
                emulator_args,
                stdout=subprocess.DEVNULL,
                stderr=self._stderr_file,
                env=env,
            )
            logger.info(f"Emulator process started with PID: {self.process.pid}")
            self.state = EmulatorState.RUNNING
        except FileNotFoundError as e:
            self.state = EmulatorState.STOPPED
            logger.error(f"Emulator binary not found: {emulator_args[0]}")
            logger.error(
                f"Make sure ANDROID_HOME is set correctly: {env.get('ANDROID_HOME')}"
            )
            raise RuntimeError(f"Emulator binary not found: {e}")
        except Exception as e:
            self.state = EmulatorState.STOPPED
            logger.error(f"Failed to start emulator: {e}")
            raise RuntimeError(f"Failed to start emulator: {e}")

    def wait_until_ready(self, timeout: int = 300):
        """
        Block until our specific emulator is fully booted and ready.

        First detects which NEW device appeared (our emulator), then waits
        for that specific device to complete booting.
        """
        if self.state != EmulatorState.RUNNING:
            logger.error(
                f"Emulator is not in RUNNING state. Emulator process running: {self.is_running()}"
            )
            raise RuntimeError(
                f"Cannot wait for emulator in state {self.state.value}. Must be RUNNING."
            )

        logger.info("=" * 60)
        logger.info("WAITING FOR EMULATOR TO BOOT")
        logger.info("=" * 60)
        logger.info(f"Waiting up to {timeout}s for device to boot...")

        start_time = time.time()
        last_dot_time = time.time()
        device_detected = False

        while True:
            elapsed = time.time() - start_time

            if elapsed >= timeout:
                logger.error(f"Timeout waiting for emulator boot after {timeout}s")
                raise RuntimeError(f"Emulator boot timeout after {timeout}s")

            if time.time() - last_dot_time >= 2:
                print(".", end="", flush=True)
                last_dot_time = time.time()

            # Check if emulator process/container is still alive
            if self.emulator_backend == "container" and self.emulator_container:
                self.emulator_container.reload()
                if self.emulator_container.status not in ("running", "created"):
                    logger.error("Emulator container stopped unexpectedly")
                    self.state = EmulatorState.STOPPED
                    raise RuntimeError("Emulator container died during boot")
            elif self.process and self.process.poll() is not None:
                stderr = ""
                if hasattr(self, "_stderr_file") and self._stderr_file:
                    self._stderr_file.seek(0)
                    stderr = self._stderr_file.read().decode(errors="replace")
                logger.error("Emulator process terminated unexpectedly")
                self.state = EmulatorState.STOPPED
                msg = "Emulator process died during boot"
                if stderr.strip():
                    msg += f"\n{stderr.strip()}"
                raise RuntimeError(msg)

            try:
                current_devices = self._get_connected_devices()

                # find the emulator that we just created
                if not device_detected and not self.device_id:
                    new_devices = current_devices - self._devices_before_start
                    if new_devices:
                        self.device_id = list(new_devices)[0]
                        device_detected = True
                        print()
                        logger.info(f"Detected our emulator device: {self.device_id}")
                        logger.info(f"Waiting for {self.device_id} to complete boot...")

                if self.device_id:
                    # Wait for device to be ready
                    self._run_adb(
                        ["-s", self.device_id, "wait-for-device"],
                        capture_output=True,
                        timeout=5,
                    )

                    # Check boot completion property
                    boot_result = self._run_adb(
                        [
                            "-s",
                            self.device_id,
                            "shell",
                            "getprop",
                            "sys.boot_completed",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

                    boot_completed = boot_result.stdout.strip()
                    if boot_completed == "1":
                        print()
                        logger.info(f"Device {self.device_id} boot completed!")
                        logger.info("Emulator is ready")
                        return

            except subprocess.TimeoutExpired:
                logger.debug("ADB command timeout, retrying...")
            except FileNotFoundError:
                logger.warning("ADB not found in PATH, retrying...")
            except Exception as e:
                logger.debug(f"Error checking device status: {e}")

            time.sleep(0.5)

    def check_status(self) -> bool:
        if self.state != EmulatorState.RUNNING:
            logger.error(
                f"Cannot check status in state {self.state.value}. Must be RUNNING."
            )
            return False

        if not self.device_id:
            logger.error("Device ID not set. Call wait_until_ready() first.")
            return False

        logger.info("=" * 60)
        logger.info("CHECKING EMULATOR STATUS")
        logger.info("=" * 60)

        try:
            result = self._run_adb(
                ["devices"], capture_output=True, text=True, timeout=10
            )

            logger.info(f"Connected devices:\n{result.stdout}")

            # Verify our specific device
            current_devices = self._get_connected_devices()
            if self.device_id not in current_devices:
                logger.error(f"Our device {self.device_id} is no longer connected")
                return False

            device_id = self.device_id

            # Test device connectivity
            logger.info("Testing device connectivity...")
            test_result = self._run_adb(
                ["-s", device_id, "shell", "echo", "test"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if test_result.returncode != 0:
                logger.error("Device connectivity test failed")
                return False

            logger.info("Device is ready!")

            boot_completed = self._run_adb(
                ["-s", device_id, "shell", "getprop", "sys.boot_completed"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()

            if boot_completed == "1":
                logger.info("Boot status: Completed")
            else:
                logger.warning("Boot status: Still booting...")
                return False

            logger.info("Emulator status check passed")
            return True

        except FileNotFoundError:
            logger.error("ADB not found in PATH")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Emulator status check timed out")
            return False
        except Exception as e:
            logger.error(f"Error checking emulator status: {e}")
            return False

    def is_running(self) -> bool:
        """
        Check if emulator process/container is still running.
        """
        if self.emulator_backend == "container":
            if self.emulator_container is None:
                return False
            try:
                self.emulator_container.reload()
                return self.emulator_container.status == "running"
            except Exception:
                return False

        if self.process is None:
            return False
        return self.process.poll() is None

    def stop(self):
        if self.state == EmulatorState.STOPPED:
            logger.info("Emulator already stopped")
            return

        if self.state == EmulatorState.NOT_STARTED:
            logger.info("Emulator was never started")
            return

        logger.info("=" * 60)
        logger.info("STOPPING EMULATOR")
        logger.info("=" * 60)

        self.state = EmulatorState.STOPPED

        if self.emulator_backend == "container":
            self._stop_container_emulator()
        else:
            self._stop_native_emulator()

    def _stop_container_emulator(self):
        """Stop and remove the emulator Docker container."""
        try:
            # Disconnect ADB first
            if self.device_id:
                subprocess.run(
                    ["adb", "disconnect", self.device_id],
                    capture_output=True,
                    timeout=5,
                )

            if self.emulator_container:
                logger.info(
                    f"Removing emulator container: {self.emulator_container.short_id}"
                )
                self.emulator_container.remove(force=True)
                logger.info("Emulator container removed")
        except Exception as e:
            logger.error(f"Error stopping emulator container: {e}")
            # Try to force-remove by name as fallback
            try:
                import docker

                client = docker.from_env()
                old = client.containers.get(EMULATOR_CONTAINER_NAME)
                old.remove(force=True)
            except Exception:
                pass
        finally:
            self.emulator_container = None
            logger.info("Emulator stopped")

    def _stop_native_emulator(self):
        """Stop the native emulator process (original behavior)."""
        try:
            if self.device_id:
                logger.info(f"Killing specific device: {self.device_id}")
                result = subprocess.run(
                    ["adb", "-s", self.device_id, "emu", "kill"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            else:
                logger.warning(
                    "Device ID not found. Unexpected error in emulator. Using generic adb emu kill, but does not guarantee stopping our specific emulator."
                )
                result = subprocess.run(
                    ["adb", "emu", "kill"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

            if result.returncode == 0:
                logger.info("Emulator shutdown command sent successfully")
            else:
                logger.warning(f"ADB shutdown returned non-zero: {result.stderr}")

            if self.process:
                try:
                    self.process.wait(timeout=10)
                    logger.info("Emulator process terminated successfully")
                except subprocess.TimeoutExpired:
                    logger.warning("Emulator did not terminate, forcing kill...")
                    self.process.kill()
                    self.process.wait(timeout=5)
                    logger.info("Emulator process killed")

        except FileNotFoundError:
            logger.warning("ADB not found, trying process kill...")
            if self.process:
                self.process.kill()
                self.process.wait(timeout=5)
                logger.info("Emulator process killed")

        except Exception as e:
            logger.error(f"Error stopping emulator: {e}")
            if self.process:
                try:
                    self.process.kill()
                    logger.info("Emulator process force killed")
                except Exception as kill_error:
                    logger.error(f"Failed to force kill emulator: {kill_error}")

        finally:
            self.process = None
            if hasattr(self, "_stderr_file") and self._stderr_file:
                self._stderr_file.close()
                self._stderr_file = None
            logger.info("Emulator stopped")

            # TODO: look into this ADB reset — start already does kill-server + start-server -a.
            logger.info("Resetting ADB server to clear device state...")
            try:
                subprocess.run(
                    ["adb", "kill-server"],
                    capture_output=True,
                    timeout=10,
                )
                time.sleep(1)
                subprocess.run(
                    ["adb", "-a", "start-server"],
                    capture_output=True,
                    timeout=10,
                )
                logger.info("ADB server reset complete")
            except FileNotFoundError:
                logger.warning("ADB not found, skipping server reset")
            except Exception as e:
                logger.warning(f"Failed to reset ADB server: {e}")

    def _run_adb(self, args: list[str], **kwargs) -> subprocess.CompletedProcess:
        """Run an ADB command, routing through docker exec in container mode.

        In container mode this avoids invoking the host `adb` client, which
        would auto-start a local server and race with the container's server
        on port 5037.

        Commands like adb root, adb devices, etc. will spawn the host ADB server if it
        is not running, which can cause conflicts with the container's ADB server.
        """
        if self.emulator_backend == "container" and self.emulator_container:
            cmd = ["docker", "exec", EMULATOR_CONTAINER_NAME, "adb"] + args
        else:
            cmd = ["adb"] + args
        return subprocess.run(cmd, **kwargs)

    def restart(self):
        """Stop the emulator, reset internal state, and start a fresh instance.

        Used during evaluation to get a clean emulator (with -wipe-data) for
        exploit verification without side-effects from the agent's session.
        The caller must still call wait_until_ready() and install_app_and_setup_backend() afterwards
        to wait for boot, install the APK, and set up the backend.
        """
        logger.info("=" * 60)
        logger.info("RESTARTING EMULATOR")
        logger.info("=" * 60)

        self.stop()

        # Reset to initial state so start_in_background() accepts the call
        self.state = EmulatorState.NOT_STARTED
        self.device_id = None
        self._devices_before_start = set()

        self.start_in_background()
        logger.info("Emulator restarted (booting in background)")

    def _get_connected_devices(self) -> set:
        """
        Get set of currently connected ADB device IDs.
        Helper to keep track of our specific emulator device.

        Returns:
            Set of device IDs (e.g., {'emulator-5554', 'emulator-5556'})
        """
        try:
            result = self._run_adb(
                ["devices"], capture_output=True, text=True, timeout=5
            )

            devices = result.stdout.strip().split("\n")[1:]  # Skip header
            device_ids = set()
            for line in devices:
                if line.strip() and "\t" in line:
                    device_id = line.split("\t")[0].strip()
                    if device_id:
                        device_ids.add(device_id)
            return device_ids
        except Exception as e:
            logger.error(f"Error getting connected devices: {e}")
            return set()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.state in [EmulatorState.STARTING, EmulatorState.RUNNING]:
            self.stop()
        return False
