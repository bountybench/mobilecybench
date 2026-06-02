import json
import subprocess
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
            project_root=Path("/mock/project"),
            sdk_version="35",
            app_name="test_app",
            emulator_display="headed",
            emulator_backend="native",
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
    reset_calls = [
        call
        for call in mock_run.call_args_list
        if call.args
        and call.args[0] in (["adb", "kill-server"], ["adb", "-a", "start-server"])
    ]
    assert len(reset_calls) == 2
    assert all(call.kwargs.get("check") is True for call in reset_calls)


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
def test_stop_raises_on_reset_nonzero(mock_logger, mock_run, emulator_manager):
    """Test that emulator cleanup completes before surfacing ADB reset failure"""
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
            raise subprocess.CalledProcessError(
                1,
                args[0],
                stderr="ADB server error",
            )
        return MagicMock(returncode=0)

    mock_run.side_effect = run_side_effect

    # Execute
    with pytest.raises(RuntimeError, match="Failed to reset ADB server"):
        emulator_manager.stop()

    # Verify emulator stopped before ADB reset failure was surfaced
    assert emulator_manager.state == EmulatorState.STOPPED
    assert emulator_manager.process is None

    error_calls = [c for c in mock_logger.error.call_args_list]
    assert any("Failed to reset ADB" in str(c) for c in error_calls)


@patch("utils.emulator_manager.subprocess.run")
def test_stop_raises_on_reset_timeout(mock_run, emulator_manager):
    """Test that ADB reset timeouts are surfaced as stop failures."""
    emulator_manager.state = EmulatorState.RUNNING
    emulator_manager.device_id = "emulator-5554"

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    emulator_manager.process = mock_process

    call_count = 0

    def run_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock(returncode=0)
        if "kill-server" in str(args[0]):
            raise subprocess.TimeoutExpired(args[0], timeout=10)
        return MagicMock(returncode=0)

    mock_run.side_effect = run_side_effect

    with pytest.raises(RuntimeError, match="timed out after 10s"):
        emulator_manager.stop()

    assert emulator_manager.state == EmulatorState.STOPPED
    assert emulator_manager.process is None


@patch("utils.emulator_manager.logger")
def test_context_exit_logs_stop_failure(mock_logger, emulator_manager):
    """Context cleanup should not mask an exception from inside the with block."""
    emulator_manager.state = EmulatorState.RUNNING

    with patch.object(
        emulator_manager, "stop", side_effect=RuntimeError("ADB reset failed")
    ):
        result = emulator_manager.__exit__(ValueError, ValueError("boom"), None)

    assert result is False
    error_calls = [c for c in mock_logger.error.call_args_list]
    assert any(
        "Emulator cleanup failed during context exit" in str(c) for c in error_calls
    )


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
                return MagicMock(
                    returncode=0,
                    stdout="MobileCybenchEmulatorAPI35_google_apis\n",
                    stderr="",
                )

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
            project_root=Path("/mock/project"),
            sdk_version="35",
            app_name="test_app",
            emulator_display="headed",
            emulator_backend="native",
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
            project_root=Path("/mock/project"),
            sdk_version="35",
            app_name="test_app",
            emulator_display="headed",
            emulator_backend="native",
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
@patch("utils.emulator_manager.time.sleep")
def test_wait_until_ready_retries_container_boot_once(mock_sleep, mock_run, mock_env):
    """Container-mode boot should retry once after a death during startup."""
    with patch("utils.emulator_manager.Path.exists", return_value=True):
        manager = EmulatorManager(
            project_root=Path("/mock/project"),
            sdk_version="35",
            app_name="test_app",
            emulator_display="headed",
            emulator_backend="container",
        )

    fake_container = MagicMock()
    fake_container.status = "running"
    fake_container.logs.return_value = b"emulator died while booting"
    manager.emulator_container = fake_container
    manager.state = EmulatorState.RUNNING
    manager._devices_before_start = set()

    wait_once = MagicMock(
        side_effect=[
            RuntimeError("Emulator container died during boot"),
            None,
        ]
    )
    stop_container = MagicMock()
    start_container = MagicMock(
        side_effect=lambda: setattr(manager, "state", EmulatorState.RUNNING)
    )

    manager._wait_until_ready_once = wait_once  # type: ignore[method-assign]
    manager._stop_container_emulator = stop_container  # type: ignore[method-assign]
    manager._start_container_emulator = start_container  # type: ignore[method-assign]

    manager.wait_until_ready(timeout=30)

    assert wait_once.call_count == 2
    stop_container.assert_called_once()
    start_container.assert_called_once()
    fake_container.logs.assert_called_once_with(tail=200)
    assert manager.state == EmulatorState.RUNNING


@patch("utils.emulator_manager.subprocess.run")
@patch("utils.emulator_manager.time.sleep")
def test_wait_until_ready_retries_container_boot_timeout(
    mock_sleep, mock_run, mock_env
):
    """Container-mode boot timeouts are treated as retryable emulator flakes."""
    with patch("utils.emulator_manager.Path.exists", return_value=True):
        manager = EmulatorManager(
            project_root=Path("/mock/project"),
            sdk_version="35",
            app_name="test_app",
            emulator_display="headed",
            emulator_backend="container",
        )

    fake_container = MagicMock()
    fake_container.status = "running"
    fake_container.logs.return_value = b"boot timeout diagnostics"
    manager.emulator_container = fake_container
    manager.state = EmulatorState.RUNNING
    manager._devices_before_start = set()

    wait_once = MagicMock(
        side_effect=[
            RuntimeError("Emulator boot timeout after 30s"),
            None,
        ]
    )
    manager._wait_until_ready_once = wait_once  # type: ignore[method-assign]
    manager._stop_container_emulator = MagicMock()  # type: ignore[method-assign]
    manager._start_container_emulator = MagicMock(
        side_effect=lambda: setattr(manager, "state", EmulatorState.RUNNING)
    )  # type: ignore[method-assign]
    mock_run.return_value = MagicMock(
        returncode=0, stdout="List of devices attached\n", stderr=""
    )

    manager.wait_until_ready(timeout=30)

    assert wait_once.call_count == 2
    manager._stop_container_emulator.assert_called_once()
    manager._start_container_emulator.assert_called_once()


@patch("utils.emulator_manager.subprocess.run")
@patch("utils.emulator_manager.time.sleep")
def test_wait_until_ready_honors_container_boot_attempt_env(
    mock_sleep, mock_run, mock_env
):
    """MCB_EMULATOR_BOOT_ATTEMPTS controls how many container boot tries run."""
    with patch("utils.emulator_manager.Path.exists", return_value=True):
        manager = EmulatorManager(
            project_root=Path("/mock/project"),
            sdk_version="35",
            app_name="test_app",
            emulator_display="headed",
            emulator_backend="container",
        )

    manager.emulator_container = MagicMock(status="running")
    manager.emulator_container.logs.return_value = b"dead"
    manager.state = EmulatorState.RUNNING
    manager._devices_before_start = set()
    manager._wait_until_ready_once = MagicMock(
        side_effect=RuntimeError("Emulator container died during boot")
    )  # type: ignore[method-assign]
    manager._stop_container_emulator = MagicMock()  # type: ignore[method-assign]
    manager._start_container_emulator = MagicMock(
        side_effect=lambda: setattr(manager, "state", EmulatorState.RUNNING)
    )  # type: ignore[method-assign]
    mock_run.return_value = MagicMock(
        returncode=0, stdout="List of devices attached\n", stderr=""
    )

    with patch.dict("os.environ", {"MCB_EMULATOR_BOOT_ATTEMPTS": "2"}):
        with pytest.raises(RuntimeError, match="container died"):
            manager.wait_until_ready(timeout=30)

    assert manager._wait_until_ready_once.call_count == 2
    assert manager._stop_container_emulator.call_count == 1
    assert manager._start_container_emulator.call_count == 1


@patch("utils.emulator_manager.subprocess.run")
def test_device_id_cleanup_between_runs(mock_run, mock_env):
    """Test that device_id is properly reset between EmulatorManager instances"""

    with patch("utils.emulator_manager.Path.exists", return_value=True):
        # First instance
        manager1 = EmulatorManager(
            project_root=Path("/mock/project"),
            sdk_version="35",
            app_name="test_app",
            emulator_display="headed",
            emulator_backend="native",
        )
        manager1.device_id = "emulator-5554"
        manager1.state = EmulatorState.RUNNING

        # Stop it
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        manager1.stop()

        # Second instance should start fresh
        manager2 = EmulatorManager(
            project_root=Path("/mock/project"),
            sdk_version="35",
            app_name="test_app",
            emulator_display="headed",
            emulator_backend="native",
        )

        # Verify device_id is None (fresh state)
        assert manager2.device_id is None
        assert manager2.state == EmulatorState.NOT_STARTED


##########################################
#  Pre-existing Emulator Guard Tests     #
##########################################


@patch("utils.emulator_manager.subprocess.run")
def test_start_fails_if_emulator_already_running(mock_run, emulator_manager):
    """start_in_background() refuses to start when an emulator is already connected."""
    # Mock _verify_avd_exists to pass
    emulator_manager._verify_avd_exists = MagicMock()

    # Mock adb devices showing an existing emulator
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="List of devices attached\nemulator-5554\tdevice\n",
        stderr="",
    )

    with pytest.raises(RuntimeError, match="Running emulator.*detected"):
        emulator_manager.start_in_background()

    # State should be reset to NOT_STARTED so the manager is reusable
    assert emulator_manager.state == EmulatorState.NOT_STARTED


@patch("utils.emulator_manager.subprocess.run")
@patch("utils.emulator_manager.subprocess.Popen")
def test_start_allows_non_emulator_adb_devices(mock_popen, mock_run, emulator_manager):
    """start_in_background() proceeds when only physical devices are connected."""
    emulator_manager._verify_avd_exists = MagicMock()

    # adb devices shows a physical device (not emulator-*)
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="List of devices attached\nR5CR1234567\tdevice\n",
        stderr="",
    )
    mock_popen.return_value = MagicMock(pid=12345)

    emulator_manager.start_in_background()

    # Should have started successfully
    assert emulator_manager.state == EmulatorState.RUNNING


@patch("utils.emulator_manager.subprocess.run")
def test_home_assistant_metadata_forwards_ssrf_listener(mock_run, tmp_path, mock_env):
    repo_root = Path(__file__).resolve().parents[1]
    source_metadata = (
        repo_root / "apps/home-assistant-android/metadata.json"
    ).read_text()
    metadata = json.loads(source_metadata)

    assert "14378:ha-ssrf-listener:14378" in metadata["extra_forwards"]

    app_dir = tmp_path / "apps" / "home-assistant-android"
    app_dir.mkdir(parents=True)
    (app_dir / "metadata.json").write_text(json.dumps(metadata))

    with patch("utils.emulator_manager.Path.exists", return_value=True):
        manager = EmulatorManager(
            project_root=tmp_path,
            sdk_version="35",
            app_name="home-assistant-android",
            emulator_display="headless",
            emulator_backend="container",
        )

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    manager.setup_port_forwards(app_dir)

    docker_commands = [" ".join(call.args[0]) for call in mock_run.call_args_list]
    assert any(
        "TCP-LISTEN:8123,fork,reuseaddr" in command
        and "TCP:home-assistant_tls_proxy:443" in command
        for command in docker_commands
    )
    assert any(
        "TCP-LISTEN:14378,fork,reuseaddr" in command
        and "TCP:ha-ssrf-listener:14378" in command
        for command in docker_commands
    )
