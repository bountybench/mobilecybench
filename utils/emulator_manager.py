"""
Emulator Lifecycle Manager
"""

import os
import subprocess
import time
from enum import Enum
from pathlib import Path
from typing import Optional

from utils.logger import logger


class EmulatorState(Enum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"


class EmulatorManager:
    def __init__(
        self,
        docker_mode: bool,
        project_root: Path,
        sdk_version: Optional[str] = None,
        app_name: Optional[str] = None,
    ):
        self.docker_mode = docker_mode
        self.project_root = project_root
        self.sdk_version = sdk_version
        self.app_name = app_name
        self.state = EmulatorState.NOT_STARTED
        self.process: Optional[subprocess.Popen] = None
        self.device_id: Optional[str] = None  # Track our specific emulator device
        self.emulator_config = self._build_emulator_config()

        logger.info(
            f"EmulatorManager initialized in {'docker' if docker_mode else 'host'} mode"
        )

    def _build_emulator_config(self) -> dict:
        android_home = os.getenv("ANDROID_HOME")
        if android_home is None:
            raise EnvironmentError("ANDROID_HOME environment variable is not set")
        emulator_bin = Path(android_home) / "emulator" / "emulator"

        if self.docker_mode:
            if not self.sdk_version:
                raise ValueError("SDK version required for docker mode")

            emulator_name = f"MobileCybenchEmulatorAPI{self.sdk_version}"
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
            emulator_name = "MobileCybenchEmu"
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
            "mode": f"{'docker' if self.docker_mode else 'host'}",
            "emulator_name": emulator_name,
            "emulator_args": emulator_args,
            "android_home": android_home,
        }

    def _verify_avd_exists(self):
        android_home = self.emulator_config["android_home"]
        emulator_bin = Path(android_home) / "emulator" / "emulator"
        emulator_name = self.emulator_config["emulator_name"]
        # find avd image on device
        try:
            result = subprocess.run(
                [str(emulator_bin), "-list-avds"],
                capture_output=True,
                text=True,
                timeout=10
            )
            available_avds = result.stdout.strip().split("\n")
            available_avds = [avd.strip() for avd in available_avds if avd.strip()]

            if emulator_name not in available_avds:
                logger.error(f"AVD '{emulator_name}' not found")
                logger.error(f"Available AVDs: {available_avds}")
                raise RuntimeError(
                    f"AVD '{emulator_name}' not found. Available AVDs: {available_avds}"
                )
            logger.info(f"AVD '{emulator_name}' found.")

        except FileNotFoundError:
            raise RuntimeError(f"Emulator binary not found at {emulator_bin}.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Timeout while listing available AVDs")
        except Exception as e:
            raise RuntimeError(f"Failed to verify AVD existence: {e}")


    def start_in_background(self):
        """
        Start the Android emulator in background (non-blocking).

        The emulator process will continue booting while this method returns.
        Use wait_until_ready() to block until boot is complete.

        Raises:
            RuntimeError: If emulator is already running
            subprocess.SubprocessError: If emulator fails to start
        """
        if self.state != EmulatorState.NOT_STARTED:
            raise RuntimeError(
                f"Cannot start emulator in state {self.state.value}. Must be NOT_STARTED."
            )
        self._verify_avd_exists()

        logger.info("=" * 60)
        logger.info(f"STARTING EMULATOR ({self.emulator_config['mode']} mode)")
        logger.info("=" * 60)

        self.state = EmulatorState.STARTING

        # Capture existing devices before starting (to detect our new one later)
        self._devices_before_start = self._get_connected_devices()
        if self._devices_before_start:
            logger.info(f"Existing devices before start: {self._devices_before_start}")

        if self.emulator_config["mode"] == "host" and self.app_name:
            logger.info(f"Running setup.sh for {self.app_name} in host mode...")
            try:
                subprocess.run(
                    ["./setup.sh", self.app_name],
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

        # Boot emulator in background
        emulator_args = self.emulator_config["emulator_args"]
        emulator_name = self.emulator_config["emulator_name"]

        logger.info(f"Starting emulator: {emulator_name}")
        logger.info(f"Command: {' '.join(emulator_args)}")
        logger.info("Emulator will boot in background...")

        env = os.environ.copy()
        env["ANDROID_HOME"] = self.emulator_config["android_home"]
        try:
            self.process = subprocess.Popen(
                emulator_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
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

            # Check if emulator process is still alive
            if self.process and self.process.poll() is not None:
                logger.error("Emulator process terminated unexpectedly")
                self.state = EmulatorState.STOPPED
                raise RuntimeError("Emulator process died during boot")

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
                    subprocess.run(
                        ["adb", "-s", self.device_id, "wait-for-device"],
                        capture_output=True,
                        timeout=5,
                    )

                    # Check boot completion property
                    boot_result = subprocess.run(
                        [
                            "adb",
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
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=10,
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
            test_result = subprocess.run(
                ["adb", "-s", device_id, "shell", "echo", "test"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if test_result.returncode != 0:
                logger.error("Device connectivity test failed")
                return False

            logger.info("Device is ready!")

            boot_completed = subprocess.run(
                ["adb", "-s", device_id, "shell", "getprop", "sys.boot_completed"],
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
        Check if emulator process is still running.
        """
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
            logger.info("Emulator stopped")

    def _get_connected_devices(self) -> set:
        """
        Get set of currently connected ADB device IDs.
        Helper to keep track of our specific emulator device.

        Returns:
            Set of device IDs (e.g., {'emulator-5554', 'emulator-5556'})
        """
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=5,
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

        # Don't suppress exceptions
        return False
