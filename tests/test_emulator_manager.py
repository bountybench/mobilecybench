from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from utils.emulator_manager import EmulatorManager, EmulatorState


@pytest.fixture
def mock_env():
    """Mock environment with ANDROID_HOME set"""
    with patch.dict("os.environ", {"ANDROID_HOME": "/mock/android/sdk"}):
        yield


@pytest.fixture
def emulator_manager(mock_env):
    """Create an EmulatorManager instance for testing"""
    with patch("utils.emulator_manager.Path.exists", return_value=True):
        manager = EmulatorManager(
            docker_mode=False,
            project_root=Path("/mock/project"),
            sdk_version="30",
            app_name="test_app",
        )
        return manager


##########################################
#        ADB Reset Tests                 #
##########################################


@patch("utils.emulator_manager.subprocess.run")
def test_stop_calls_adb_reset(mock_run, emulator_manager):
    """Test that stop() calls adb kill-server and start-server"""
    # Setup: set emulator to RUNNING state
    emulator_manager.state = EmulatorState.RUNNING
    emulator_manager.device_id = "emulator-5554"

    # Mock the process
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.wait.return_value = None
    emulator_manager.process = mock_process

    # Mock subprocess.run to succeed
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    # Execute
    emulator_manager.stop()

    # Verify ADB reset calls were made
    adb_calls = [c for c in mock_run.call_args_list if "adb" in str(c)]

    # Should have: adb -s device emu kill, adb kill-server, adb start-server
    assert any(
        "kill-server" in str(c) for c in adb_calls
    ), "Should call adb kill-server"
    assert any(
        "start-server" in str(c) for c in adb_calls
    ), "Should call adb start-server"


@patch("utils.emulator_manager.subprocess.run")
def test_stop_handles_missing_adb(mock_run, emulator_manager):
    """Test that stop() handles missing ADB gracefully"""
    # Setup
    emulator_manager.state = EmulatorState.RUNNING
    emulator_manager.device_id = "emulator-5554"

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    emulator_manager.process = mock_process

    # Mock ADB commands to raise FileNotFoundError
    def run_side_effect(*args, **kwargs):
        if "adb" in args[0]:
            raise FileNotFoundError("adb not found")
        return MagicMock(returncode=0)

    mock_run.side_effect = run_side_effect

    # Should not raise exception
    emulator_manager.stop()

    # Verify state is STOPPED even though ADB failed
    assert emulator_manager.state == EmulatorState.STOPPED


@patch("utils.emulator_manager.subprocess.run")
@patch("utils.emulator_manager.logger")
def test_stop_continues_on_reset_failure(mock_logger, mock_run, emulator_manager):
    """Test that emulator stops even if ADB reset fails"""
    # Setup
    emulator_manager.state = EmulatorState.RUNNING
    emulator_manager.device_id = "emulator-5554"

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    emulator_manager.process = mock_process

    call_count = 0

    def run_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # First call (emu kill) succeeds
        if call_count == 1:
            return MagicMock(returncode=0)
        # kill-server fails
        elif "kill-server" in str(args[0]):
            raise Exception("ADB server error")
        return MagicMock(returncode=0)

    mock_run.side_effect = run_side_effect

    # Execute
    emulator_manager.stop()

    # Verify emulator still stopped despite ADB reset failure
    assert emulator_manager.state == EmulatorState.STOPPED
    assert emulator_manager.process is None

    # Should log warning about reset failure
    warning_calls = [c for c in mock_logger.warning.call_args_list]
    assert any("Failed to reset ADB" in str(c) for c in warning_calls)


##########################################
#      Device Detection Tests            #
##########################################


@patch("utils.emulator_manager.subprocess.run")
@patch("utils.emulator_manager.subprocess.Popen")
@patch("utils.emulator_manager.time.sleep")
def test_wait_detects_new_device(mock_sleep, mock_popen, mock_run, emulator_manager):
    """Test that wait_until_ready() detects a new device"""
    # Setup
    emulator_manager.state = EmulatorState.RUNNING
    emulator_manager._devices_before_start = set()

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    emulator_manager.process = mock_process

    # Mock adb devices output - device appears after a few calls
    call_count = 0

    def run_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1

        # First few calls: no devices
        if call_count < 3:
            return MagicMock(
                returncode=0, stdout="List of devices attached\n", stderr=""
            )
        # Then device appears
        elif "adb devices" in str(args[0]) or (
            "adb" in str(args[0]) and len(args[0]) == 2
        ):
            return MagicMock(
                returncode=0,
                stdout="List of devices attached\nemulator-5554\tdevice\n",
                stderr="",
            )
        # Boot completed check
        elif "boot_completed" in str(args[0]):
            return MagicMock(returncode=0, stdout="1\n", stderr="")
        # Other ADB commands succeed
        else:
            return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = run_side_effect

    # Execute
    emulator_manager.wait_until_ready(timeout=30)

    # Verify device was detected
    assert emulator_manager.device_id == "emulator-5554"


@patch("utils.emulator_manager.subprocess.run")
@patch("utils.emulator_manager.time.sleep")
def test_wait_detects_reused_device_after_reset(mock_sleep, mock_run, emulator_manager):
    """Test that wait_until_ready() detects device even when ID is reused after ADB reset"""
    # Setup: simulate second emulator run where device ID is reused
    # After ADB reset, the device list should be empty initially
    emulator_manager.state = EmulatorState.RUNNING
    emulator_manager._devices_before_start = set()  # Empty after ADB reset

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    emulator_manager.process = mock_process

    # Mock: device appears with same ID as before (emulator-5554)
    call_count = 0

    def run_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1

        if call_count < 2:
            return MagicMock(
                returncode=0, stdout="List of devices attached\n", stderr=""
            )
        elif "adb devices" in str(args[0]) or (
            "adb" in str(args[0]) and len(args[0]) == 2
        ):
            # Device appears (reused ID)
            return MagicMock(
                returncode=0,
                stdout="List of devices attached\nemulator-5554\tdevice\n",
                stderr="",
            )
        elif "boot_completed" in str(args[0]):
            return MagicMock(returncode=0, stdout="1\n", stderr="")
        else:
            return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = run_side_effect

    # Execute
    emulator_manager.wait_until_ready(timeout=30)

    # Verify device was detected (as a new device since _devices_before_start was empty)
    assert emulator_manager.device_id == "emulator-5554"


##########################################
#      Integration Tests                 #
##########################################


@patch("utils.emulator_manager.subprocess.run")
@patch("utils.emulator_manager.subprocess.Popen")
@patch("utils.emulator_manager.time.sleep")
def test_successive_emulator_runs(mock_sleep, mock_popen, mock_run, mock_env):
    """Test two successive EmulatorManager contexts (simulating the actual bug scenario)"""

    def create_run_side_effect(run_num):
        """Create a side effect function for a specific run number"""

        def run_side_effect(*args, **kwargs):
            # Handle list-avds
            if "-list-avds" in args[0]:
                return MagicMock(returncode=0, stdout="MobileCybenchEmu\n", stderr="")

            # Handle adb devices - return empty initially, then device appears
            if (
                "adb" in str(args[0])
                and "devices" in str(args[0])
                and len(args[0]) == 2
            ):
                # First call: no devices (just after ADB reset)
                # Later calls: device appears
                if hasattr(run_side_effect, "device_call_count"):
                    run_side_effect.device_call_count += 1
                else:
                    run_side_effect.device_call_count = 0

                if run_side_effect.device_call_count < 2:
                    return MagicMock(
                        returncode=0, stdout="List of devices attached\n", stderr=""
                    )
                else:
                    return MagicMock(
                        returncode=0,
                        stdout="List of devices attached\nemulator-5554\tdevice\n",
                        stderr="",
                    )

            # Handle boot_completed check
            if "boot_completed" in str(args[0]):
                return MagicMock(returncode=0, stdout="1\n", stderr="")

            # Handle ADB reset commands
            if "kill-server" in str(args[0]) or "start-server" in str(args[0]):
                return MagicMock(returncode=0, stdout="", stderr="")

            # Other commands succeed
            return MagicMock(returncode=0, stdout="", stderr="")

        return run_side_effect

    # First emulator run
    with patch("utils.emulator_manager.Path.exists", return_value=True):
        manager1 = EmulatorManager(
            docker_mode=False,
            project_root=Path("/mock/project"),
            sdk_version="30",
            app_name="test_app",
        )

        mock_run.side_effect = create_run_side_effect(1)
        mock_popen.return_value = MagicMock(
            pid=12345, poll=MagicMock(return_value=None)
        )

        manager1.start_in_background()
        manager1.wait_until_ready(timeout=30)

        # Verify first device detected
        assert manager1.device_id == "emulator-5554"

        # Stop first emulator (triggers ADB reset)
        manager1.stop()
        assert manager1.state == EmulatorState.STOPPED

    # Second emulator run (the bug scenario)
    with patch("utils.emulator_manager.Path.exists", return_value=True):
        manager2 = EmulatorManager(
            docker_mode=False,
            project_root=Path("/mock/project"),
            sdk_version="30",
            app_name="test_app",
        )

        mock_run.side_effect = create_run_side_effect(2)
        mock_popen.return_value = MagicMock(
            pid=67890, poll=MagicMock(return_value=None)
        )

        manager2.start_in_background()
        manager2.wait_until_ready(timeout=30)

        # Verify second device detected (should work after ADB reset)
        assert manager2.device_id == "emulator-5554"

        manager2.stop()
        assert manager2.state == EmulatorState.STOPPED


@patch("utils.emulator_manager.subprocess.run")
def test_device_id_cleanup_between_runs(mock_run, mock_env):
    """Test that device_id is properly reset between EmulatorManager instances"""

    with patch("utils.emulator_manager.Path.exists", return_value=True):
        # First instance
        manager1 = EmulatorManager(
            docker_mode=False,
            project_root=Path("/mock/project"),
            sdk_version="30",
            app_name="test_app",
        )
        manager1.device_id = "emulator-5554"
        manager1.state = EmulatorState.RUNNING

        # Stop it
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        manager1.stop()

        # Second instance should start fresh
        manager2 = EmulatorManager(
            docker_mode=False,
            project_root=Path("/mock/project"),
            sdk_version="30",
            app_name="test_app",
        )

        # Verify device_id is None (fresh state)
        assert manager2.device_id is None
        assert manager2.state == EmulatorState.NOT_STARTED
