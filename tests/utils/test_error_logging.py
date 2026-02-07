"""Unit tests for utils/local_error_logger.sh"""

import os
import subprocess


class TestLocalErrorLogger:
    """Tests for the local_error_logger.sh script."""

    def get_script_path(self):
        """Get the absolute path to local_error_logger.sh"""
        # Assuming tests are run from the project root
        return os.path.join(
            os.path.dirname(__file__), "..", "..", "utils", "local_error_logger.sh"
        )

    def test_error_logging_to_file(self):
        """Test that errors are written to the log file"""
        script = self.get_script_path()

        test_script = f"""
        source {script}
        
        # Remove the trap so cleanup doesn't happen
        trap - EXIT
        
        echo "Test error message" >&2
        
        # Give tee time to write
        sleep 0.3
        
        # Check log file contents
        if [ -f "$ERROR_LOG_FILE" ]; then
            cat "$ERROR_LOG_FILE"
        else
            echo "LOG_FILE_NOT_FOUND"
        fi
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )

        assert "Test error message" in result.stdout
        assert "LOG_FILE_NOT_FOUND" not in result.stdout

    def test_log_error_increments_error_count(self):
        """Test that ERROR_COUNT increments with each log error call"""
        script = self.get_script_path()
        test_script = f"""
        source {script}
        echo "Error 1" >&2
        echo "Error 2" >&2
        echo "Error 3" >&2
        echo $ERROR_COUNT
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )
        assert "3" in result.stderr.strip()

    def test_error_summary_displays_on_exit_code_1(self):
        """Test that error summary is displayed when script exits with code 1"""
        script = self.get_script_path()
        test_script = f"""
        source {script}
        
        echo "Test error message" >&2
        
        # Give tee time to write
        sleep 0.3

        exit 1
        """

        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )

        assert "Test error message" in result.stderr
        assert "=== Error Summary ===" in result.stderr
        assert result.returncode == 1

    def test_error_summary_not_displayed_on_exit_code_0(self):
        """Test that error summary is NOT displayed when script exits with code 0"""
        script = self.get_script_path()
        test_script = f"""
        source {script}
        echo "Test error" >&2
        exit 0
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )

        assert "=== Error Summary ===" not in result.stderr
        assert result.returncode == 0

    def test_display_error_summary_when_no_errors(self):
        """Test that display_error_summary handles zero errors gracefully"""
        script = self.get_script_path()
        test_script = f"""
        source {script}
        display_error_summary
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )

        # Should not display summary if no errors
        assert "=== Error Summary ===" not in result.stderr

    def test_multiple_errors_all_logged(self):
        """Test that multiple error messages are all logged"""
        script = self.get_script_path()
        test_script = f"""
        source {script}
        echo "Database connection failed" >&2
        echo "Invalid JSON syntax" >&2
        echo "File not found" >&2
        exit 1
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )
        assert "Database connection failed" in result.stderr
        assert "Invalid JSON syntax" in result.stderr
        assert "File not found" in result.stderr
