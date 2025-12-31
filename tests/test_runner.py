from unittest.mock import MagicMock, patch

import pytest

from runner import MobileCybenchRunner


@pytest.fixture
def mock_config():
    """Mock configuration for MobileCybenchRunner"""
    from models.config import CustomAgentConfig, EnvironmentConfig, RunnerConfig

    env = EnvironmentConfig(
        build_type="source",
        server_access=True,
        adb_access="full",
        screenshot_mode=False,
        headless_mode=True,
        dry_run=True,
        docker_mode=False,
    )

    agents = {
        "custom": CustomAgentConfig(
            max_iterations=10,
            max_kali_message_tokens=1000,
            max_model_response_tokens=1000,
            max_context_length=10000,
            model="gpt-4",
            agent_image="test-image",
        )
    }

    return RunnerConfig(environment=env, agents=agents)


@pytest.fixture
def runner(mock_config):
    """Create a MobileCybenchRunner instance for testing"""
    with patch("runner.Path.exists", return_value=True), patch(
        "runner.get_app_metadata"
    ) as mock_metadata:
        mock_metadata.return_value = {"app_name": "test_app"}
        runner_instance = MobileCybenchRunner(app_name="test_app", config=mock_config)
        return runner_instance


##########################################
#     Exploit Workflow Tests            #
##########################################


@patch("runner.subprocess.run")
def test_check_and_save_agent_exploit_exists(mock_run, runner):
    """Test _check_and_save_agent_exploit when exploit.sh exists"""
    # Mock docker exec test -f to succeed (file exists)
    test_result = MagicMock(returncode=0)
    # Mock docker exec cat to return exploit contents
    cat_result = MagicMock(returncode=0, stdout="#!/bin/bash\necho 'exploit'\n")
    # Mock docker cp to succeed
    cp_result = MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = [test_result, cat_result, cp_result]

    result = runner._check_and_save_agent_exploit()

    assert result is True
    # Verify docker commands were called
    assert mock_run.call_count == 3
    assert "test" in str(mock_run.call_args_list[0])
    assert "cat" in str(mock_run.call_args_list[1])
    assert "cp" in str(mock_run.call_args_list[2])


@patch("runner.subprocess.run")
def test_check_and_save_agent_exploit_not_exists(mock_run, runner):
    """Test _check_and_save_agent_exploit when exploit.sh does not exist"""
    # Mock docker exec test -f to fail (file does not exist)
    test_result = MagicMock(returncode=1)
    mock_run.return_value = test_result

    result = runner._check_and_save_agent_exploit()

    assert result is False
    # Should only call test, not cat
    assert mock_run.call_count == 1


@patch("runner.subprocess.run")
@patch("runner.Path")
def test_run_agent_exploit_success(mock_path, mock_run, runner):
    """Test _run_agent_exploit successfully executes and logs exploit"""
    # Mock file operations
    mock_file = MagicMock()
    mock_path.return_value.__truediv__.return_value = mock_file

    # Mock docker exec cat (read exploit)
    cat_result = MagicMock(returncode=0, stdout="#!/bin/bash\necho 'running exploit'\n")
    # Mock docker exec bash (run exploit)
    exec_result = MagicMock(returncode=0, stdout="exploit output\n", stderr="")

    mock_run.side_effect = [cat_result, exec_result]

    # Mock open for writing log file
    with patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value = mock_file

        runner._run_agent_exploit()

        # Verify log file was written
        assert mock_open.call_count >= 2  # At least 2 writes (script contents + output)
        assert mock_file.write.called


@patch("runner.subprocess.run")
def test_run_agent_exploit_timeout(mock_run, runner):
    """Test _run_agent_exploit handles timeout gracefully"""
    # Mock docker exec cat to succeed
    cat_result = MagicMock(returncode=0, stdout="#!/bin/bash\nsleep 1000\n")

    # Mock docker exec bash to timeout
    from subprocess import TimeoutExpired

    mock_run.side_effect = [cat_result, TimeoutExpired(cmd="bash", timeout=300)]

    # Mock file operations
    with patch("builtins.open", create=True) as mock_open:
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file

        result = runner._run_agent_exploit()

        # Should still return a log path
        assert result is not None
        # Should have written timeout error - check the actual write call args
        write_calls = mock_file.write.call_args_list
        all_writes = "".join([str(call[0][0]) for call in write_calls])
        assert "timeout" in all_writes.lower() or "timed out" in all_writes.lower()


@patch("runner.subprocess.run")
@patch("runner.Path.exists", return_value=True)
def test_run_cleanup(mock_exists, mock_run, runner):
    """Test _run_cleanup executes cleanup.sh"""
    mock_run.return_value = MagicMock(returncode=0)

    with patch.object(runner.cmd, "run_with_progress") as mock_progress:
        runner._run_cleanup()

        # Verify cleanup.sh was called
        mock_progress.assert_called_once()
        assert "cleanup.sh" in str(mock_progress.call_args)


def test_probe_results_structure(runner):
    """Test that probe_results dictionary is initialized properly"""
    assert hasattr(runner, "probe_results")
    assert isinstance(runner.probe_results, dict)


@patch("runner.EmulatorManager")
@patch.object(MobileCybenchRunner, "_validate_input")
@patch.object(MobileCybenchRunner, "_setup_app_apk")
@patch.object(MobileCybenchRunner, "_install_app_and_setup_backend")
@patch.object(MobileCybenchRunner, "_setup_agent_environment")
@patch.object(MobileCybenchRunner, "_run_agent")
@patch.object(MobileCybenchRunner, "run_probes_checks")
@patch.object(MobileCybenchRunner, "_check_and_save_agent_exploit")
@patch.object(MobileCybenchRunner, "_run_cleanup")
@patch.object(MobileCybenchRunner, "_run_agent_exploit")
@patch("runner.logger_manager")
@patch("runner.Path.exists", return_value=True)
def test_run_two_emulator_workflow_with_exploit(
    mock_path_exists,
    mock_logger_manager,
    mock_run_exploit,
    mock_cleanup,
    mock_check_exploit,
    mock_probes,
    mock_run_agent,
    mock_setup_agent,
    mock_install_app,
    mock_setup_apk,
    mock_validate,
    mock_emulator_class,
    runner,
):
    """Test the full workflow with two EmulatorManager contexts when exploit exists"""
    # Mock EmulatorManager context manager
    mock_emulator1 = MagicMock()
    mock_emulator2 = MagicMock()
    mock_emulator_class.return_value.__enter__.side_effect = [
        mock_emulator1,
        mock_emulator2,
    ]

    # Mock exploit exists
    mock_check_exploit.return_value = True

    # Mock probe results
    mock_probes.return_value = {"probe1": "result1"}

    # Mock logger
    mock_logger_manager.get_agent_log_file_name.return_value = "test_agent.log"

    # Mock exploit log path
    from pathlib import Path

    mock_run_exploit.return_value = Path("exploit_log_test.log")

    # Execute
    runner.run()

    # Verify two emulators were created
    assert mock_emulator_class.call_count == 2

    # Verify probe_results has all four stages
    assert "pre_agent_run" in runner.probe_results
    assert "post_agent_run" in runner.probe_results
    assert "pre_agent_exploit" in runner.probe_results
    assert "post_agent_exploit" in runner.probe_results

    # Verify cleanup was called before second emulator
    mock_cleanup.assert_called_once()

    # Verify exploit was executed
    mock_run_exploit.assert_called_once()


@patch("runner.EmulatorManager")
@patch.object(MobileCybenchRunner, "_validate_input")
@patch.object(MobileCybenchRunner, "_setup_app_apk")
@patch.object(MobileCybenchRunner, "_install_app_and_setup_backend")
@patch.object(MobileCybenchRunner, "_setup_agent_environment")
@patch.object(MobileCybenchRunner, "_run_agent")
@patch.object(MobileCybenchRunner, "run_probes_checks")
@patch.object(MobileCybenchRunner, "_check_and_save_agent_exploit")
@patch.object(MobileCybenchRunner, "_run_cleanup")
@patch.object(MobileCybenchRunner, "_run_agent_exploit")
@patch("runner.logger_manager")
@patch("runner.Path.exists", return_value=True)
def test_run_skips_exploit_pipeline_when_no_exploit(
    mock_path_exists,
    mock_logger_manager,
    mock_run_exploit,
    mock_cleanup,
    mock_check_exploit,
    mock_probes,
    mock_run_agent,
    mock_setup_agent,
    mock_install_app,
    mock_setup_apk,
    mock_validate,
    mock_emulator_class,
    runner,
):
    """Test that exploit pipeline is skipped when no exploit exists"""
    # Mock EmulatorManager context manager
    mock_emulator1 = MagicMock()
    mock_emulator_class.return_value.__enter__.return_value = mock_emulator1

    # Mock exploit does NOT exist
    mock_check_exploit.return_value = False

    # Mock probe results
    mock_probes.return_value = {"probe1": "result1"}

    # Mock logger
    mock_logger_manager.get_agent_log_file_name.return_value = "test_agent.log"

    # Execute
    runner.run()

    # Verify only ONE emulator was created (not two)
    assert mock_emulator_class.call_count == 1

    # Verify probe_results has only first two stages (not exploit stages)
    assert "pre_agent_run" in runner.probe_results
    assert "post_agent_run" in runner.probe_results
    assert "pre_agent_exploit" not in runner.probe_results
    assert "post_agent_exploit" not in runner.probe_results

    # Verify cleanup was NOT called (since no second emulator)
    mock_cleanup.assert_not_called()

    # Verify exploit was NOT executed
    mock_run_exploit.assert_not_called()


@patch("agent.hierarchical_agent.create_and_run_supervisor_system")
def test_run_agent_supervisor_mode_passes_metadata(mock_create_run, runner):
    """Test that _run_agent passes metadata to supervisor system."""
    runner.mode = "supervisor"
    runner.config.dry_run = False
    runner.metadata = {"key": "value"}

    runner._run_agent()

    mock_create_run.assert_called_once()
    call_kwargs = mock_create_run.call_args.kwargs
    assert "metadata" in call_kwargs
    assert call_kwargs["metadata"] == {"key": "value"}
