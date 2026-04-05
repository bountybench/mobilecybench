import json
import time
from unittest.mock import Mock, patch

import pytest

from utils.time_tracker import ExperimentTiming, LLMCallTiming, TimeTracker

##########################################
#              Fixtures                  #
##########################################


@pytest.fixture
def tracker():
    """Create a fresh TimeTracker instance for each test."""
    return TimeTracker()


@pytest.fixture
def tracker_with_experiment(tracker):
    """Create a tracker with an active experiment."""
    tracker.start_experiment("test-app")
    return tracker


@pytest.fixture
def tracker_with_calls(tracker_with_experiment):
    """Create a tracker with some LLM calls."""
    tracker = tracker_with_experiment

    # Add successful calls
    with tracker.llm_timing("gpt-4", "conv-1", turn=1):
        time.sleep(0.01)

    with tracker.llm_timing("gpt-3.5-turbo", "conv-2", turn=2):
        time.sleep(0.02)

    # Add failed call
    with pytest.raises(ValueError):
        with tracker.llm_timing("gpt-4", "conv-1", turn=3):
            time.sleep(0.01)
            raise ValueError("API error")

    tracker.end_experiment()
    return tracker


##########################################
#         Core Functionality Tests       #
##########################################


@pytest.mark.time_tracker
def test_initialization_and_lifecycle(tracker):
    """Test complete experiment lifecycle."""
    # Initial state
    assert tracker.experiment_start_time is None
    assert tracker.experiment_end_time is None
    assert tracker.llm_calls == []
    assert tracker._current_call_number == 0

    # Start experiment
    tracker.start_experiment("test-app")
    assert tracker.experiment_start_time is not None
    assert tracker._experiment_id.startswith("exp_")
    assert tracker._app_name == "test-app"

    # End experiment
    tracker.end_experiment()
    assert tracker.experiment_end_time is not None
    assert tracker.experiment_end_time > tracker.experiment_start_time

    # Duration calculation
    duration = tracker.get_experiment_duration()
    assert duration is not None
    assert duration >= 0


@pytest.mark.time_tracker
def test_context_manager_basic_usage(tracker_with_experiment):
    """Test context manager for successful LLM calls."""
    tracker = tracker_with_experiment

    with tracker.llm_timing("gpt-4", "conv-1", turn=1):
        time.sleep(0.01)

    # Verify call was recorded correctly
    assert len(tracker.llm_calls) == 1
    call = tracker.llm_calls[0]

    assert call.call_id.startswith("call_1_")
    assert call.model == "gpt-4"
    assert call.conversation_id == "conv-1"
    assert call.turn == 1
    assert call.success is True
    assert call.error is None
    assert call.duration > 0


@pytest.mark.time_tracker
def test_context_manager_exception_handling(tracker_with_experiment):
    """Test context manager handles exceptions correctly."""
    tracker = tracker_with_experiment

    with pytest.raises(RuntimeError, match="Test error"):
        with tracker.llm_timing("gpt-4", turn=1):
            time.sleep(0.01)
            raise RuntimeError("Test error")

    # Verify call was still recorded with error
    assert len(tracker.llm_calls) == 1
    call = tracker.llm_calls[0]
    assert call.success is False
    assert call.error == "Test error"
    assert call.duration > 0  # Should still have timing data


@pytest.mark.time_tracker
def test_multiple_calls_and_statistics(tracker_with_calls):
    """Test multiple calls and comprehensive statistics."""
    tracker = tracker_with_calls

    # Basic counts
    assert tracker.get_llm_call_count() == 3
    assert tracker.get_total_llm_time() > 0

    # Verify call sequence
    for i, call in enumerate(tracker.llm_calls, 1):
        assert call.call_number == i

    # Check models and outcomes
    assert tracker.llm_calls[0].model == "gpt-4"
    assert tracker.llm_calls[1].model == "gpt-3.5-turbo"
    assert tracker.llm_calls[2].model == "gpt-4"

    assert tracker.llm_calls[0].success is True
    assert tracker.llm_calls[1].success is True
    assert tracker.llm_calls[2].success is False

    # Test statistics computation
    stats = tracker._compute_stats()
    assert stats["overall"]["count"] == 3
    assert "model_gpt-4" in stats
    assert "model_gpt-3.5-turbo" in stats

    # Verify per-model stats
    gpt4_stats = stats["model_gpt-4"]
    assert gpt4_stats["count"] == 2  # 2 calls to gpt-4

    turbo_stats = stats["model_gpt-3.5-turbo"]
    assert turbo_stats["count"] == 1  # 1 call to gpt-3.5-turbo


##########################################
#         Edge Cases and Accuracy        #
##########################################


@pytest.mark.time_tracker
def test_empty_experiment(tracker):
    """Test experiment with no LLM calls."""
    tracker.start_experiment("test-app")
    tracker.end_experiment()

    assert tracker.get_experiment_duration() > 0
    assert tracker.get_total_llm_time() == 0.0
    assert tracker.get_llm_call_count() == 0

    json_data = tracker.to_json()
    assert json_data["llm_call_count"] == 0
    assert json_data["total_llm_time"] == 0.0
    assert json_data["llm_calls"] == []


@pytest.mark.time_tracker
@pytest.mark.slow
def test_timing_accuracy():
    """Test timing accuracy with known delays."""
    tracker = TimeTracker()
    tracker.start_experiment("test-app")

    # Test with known delays
    expected_delays = [0.1, 0.2, 0.05]

    for delay in expected_delays:
        with tracker.llm_timing("gpt-4", turn=1):
            time.sleep(delay)

    tracker.end_experiment()

    # Check individual call durations (within 20% tolerance)
    for expected, call in zip(expected_delays, tracker.llm_calls):
        assert call.duration == pytest.approx(expected, rel=0.2)

    # Check total experiment time
    total_duration = tracker.get_experiment_duration()
    expected_total = sum(expected_delays)
    assert total_duration == pytest.approx(expected_total, rel=0.2)


@pytest.mark.time_tracker
def test_monotonic_clock_usage():
    """Test that monotonic clock is used (immune to system clock changes)."""
    tracker = TimeTracker()

    # Mock time.time to simulate clock drift
    with patch("time.time") as mock_time:
        mock_time.side_effect = [1000, 1005, 1010]  # Simulate clock drift

        tracker.start_experiment("test-app")

        with tracker.llm_timing("gpt-4", turn=1):
            time.sleep(0.01)

        tracker.end_experiment()

        # Durations should be realistic despite clock drift
        call_duration = tracker.llm_calls[0].duration
        experiment_duration = tracker.get_experiment_duration()

        assert 0.005 < call_duration < 0.1
        assert 0.005 < experiment_duration < 0.1


@pytest.mark.time_tracker
def test_call_id_uniqueness():
    """Test that call IDs are unique across experiments."""
    tracker1 = TimeTracker()
    tracker2 = TimeTracker()

    tracker1.start_experiment("app1")
    tracker2.start_experiment("app2")

    # Test that call numbers are sequential within each tracker
    with tracker1.llm_timing("gpt-4", turn=1):
        time.sleep(0.001)

    with tracker2.llm_timing("gpt-4", turn=1):
        time.sleep(0.001)

    call1_id = tracker1.llm_calls[0].call_id
    call2_id = tracker2.llm_calls[0].call_id

    # Both should start with call_1_ but have different counters/timestamps
    assert call1_id.startswith("call_1_")
    assert call2_id.startswith("call_1_")

    # Test multiple calls in same experiment
    with tracker1.llm_timing("gpt-4", turn=2):
        time.sleep(0.001)

    call3_id = tracker1.llm_calls[1].call_id
    assert call3_id != call1_id
    assert call3_id.startswith("call_2_")

    # Verify call numbers are correct
    assert tracker1.llm_calls[0].call_number == 1
    assert tracker1.llm_calls[1].call_number == 2
    assert tracker2.llm_calls[0].call_number == 1


##########################################
#         JSON Export and I/O           #
##########################################


@pytest.mark.time_tracker
def test_json_export_and_file_io(tracker_with_calls, tmp_path):
    """Test JSON export and file I/O functionality."""
    tracker = tracker_with_calls

    # Test JSON export
    json_data = tracker.to_json()

    # Verify structure
    assert json_data["experiment_id"] is not None
    assert json_data["app_name"] == "test-app"
    assert json_data["start_time"] > 0
    assert json_data["end_time"] > json_data["start_time"]
    assert json_data["total_duration"] > 0
    assert json_data["total_llm_time"] > 0
    assert json_data["llm_call_count"] == 3

    # Verify LLM calls structure
    assert len(json_data["llm_calls"]) == 3
    for call in json_data["llm_calls"]:
        assert all(
            key in call
            for key in [
                "call_id",
                "call_number",
                "duration",
                "model",
                "success",
                "turn",
            ]
        )

    # Verify stats structure
    assert "stats" in json_data
    assert "overall" in json_data["stats"]

    # Test file I/O using pytest tmp_path
    temp_file = tmp_path / "test_timings.json"
    tracker.save_json(temp_file)
    assert temp_file.exists()

    with open(temp_file) as f:
        saved_data = json.load(f)

    assert saved_data["app_name"] == "test-app"
    assert len(saved_data["llm_calls"]) == 3


##########################################
#         Integration Tests              #
##########################################


@pytest.mark.time_tracker
def test_logging_integration(tracker_with_calls):
    """Test logging summary functionality."""
    tracker = tracker_with_calls

    # Mock logger to capture log calls
    mock_logger = Mock()
    tracker.log_summary(mock_logger)

    # Verify logger was called with expected messages
    log_calls = mock_logger.info.call_args_list
    log_messages = [call[0][0] for call in log_calls]

    # Check for key log messages
    assert any("EXPERIMENT TIMING SUMMARY" in msg for msg in log_messages)
    assert any("total_experiment_clock_time:" in msg for msg in log_messages)
    assert any("total_llm_time:" in msg for msg in log_messages)
    assert any("llm_call_count:" in msg for msg in log_messages)
    assert any("model_provider_call_1:" in msg for msg in log_messages)
    assert any("model_provider_call_2:" in msg for msg in log_messages)
    assert any("model_provider_call_3:" in msg for msg in log_messages)

    # Should have success and failure indicators
    success_calls = [
        msg for msg in log_messages if "model_provider_call_" in msg and "✓" in msg
    ]
    error_calls = [
        msg for msg in log_messages if "model_provider_call_" in msg and "✗" in msg
    ]

    assert len(success_calls) == 2  # 2 successful calls
    assert len(error_calls) == 1  # 1 failed call


##########################################
#         Data Structure Validation      #
##########################################


@pytest.mark.time_tracker
def test_dataclass_validation():
    """Test dataclass structure and validation."""
    # Test LLMCallTiming
    call = LLMCallTiming(
        call_id="test_call_1",
        call_number=1,
        start_time=1000.0,
        end_time=1001.0,
        duration=1.0,
        model="gpt-4",
        conversation_id="conv-1",
        turn=1,
        success=True,
        error=None,
    )

    assert call.call_id == "test_call_1"
    assert call.call_number == 1
    assert call.duration == 1.0
    assert call.model == "gpt-4"
    assert call.success is True
    assert call.error is None

    # Test ExperimentTiming
    calls = [call]
    experiment = ExperimentTiming(
        experiment_id="exp_123",
        app_name="test-app",
        start_time=1000.0,
        end_time=1002.0,
        total_duration=2.0,
        llm_calls=calls,
        total_llm_time=1.0,
        llm_call_count=1,
        stats={"overall": {"count": 1}},
    )

    assert experiment.experiment_id == "exp_123"
    assert experiment.app_name == "test-app"
    assert experiment.total_duration == 2.0
    assert len(experiment.llm_calls) == 1
    assert experiment.total_llm_time == 1.0
    assert experiment.llm_call_count == 1


##########################################
#         Error Handling Tests           #
##########################################


@pytest.mark.time_tracker
def test_invalid_input_handling(tracker):
    """Test handling of invalid inputs."""
    # Test with None app name (becomes "unknown" due to or operator)
    tracker.start_experiment(None)
    assert tracker._app_name == "unknown"

    # Test with empty string (also becomes "unknown" due to or operator)
    tracker.start_experiment("")
    assert tracker._app_name == "unknown"

    # Test with valid string
    tracker.start_experiment("test")
    assert tracker._app_name == "test"

    # Test context manager with None values
    with tracker.llm_timing("gpt-4", None, None):
        time.sleep(0.001)

    call = tracker.llm_calls[0]
    assert call.conversation_id is None
    assert call.turn is None

    # Test that timing still works with invalid inputs
    assert call.duration > 0
    assert call.success is True


@pytest.mark.time_tracker
def test_statistics_edge_cases():
    """Test statistics computation with edge cases."""
    tracker = TimeTracker()
    tracker.start_experiment("test-app")

    # Single call
    with tracker.llm_timing("gpt-4", turn=1):
        time.sleep(0.01)

    stats = tracker._compute_stats()
    overall = stats["overall"]
    assert overall["count"] == 1
    assert overall["min"] == overall["max"] == overall["p50"] == overall["p95"]

    # No calls
    empty_tracker = TimeTracker()
    empty_stats = empty_tracker._compute_stats()
    assert empty_stats == {}
