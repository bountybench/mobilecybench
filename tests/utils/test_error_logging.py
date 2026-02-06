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

    def test_log_error_outputs_to_stderr(self):
        """Test that log_error writes to stderr"""
        script = self.get_script_path()
        test_script = f"""
        source {script}
        log_error "Test error message"
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )

        assert "Test error message" in result.stderr
        assert "[ERROR]" in result.stderr
        assert result.stdout == ""  # Nothing should go to stdout

    def test_log_error_increments_error_count(self):
        """Test that ERROR_COUNT increments with each log_error call"""
        script = self.get_script_path()
        test_script = f"""
        source {script}
        log_error "Error 1"
        log_error "Error 2"
        log_error "Error 3"
        echo $ERROR_COUNT
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )

        assert "3" in result.stdout.strip()

    def test_error_summary_displays_on_exit_code_1(self):
        """Test that error summary is displayed when script exits with code 1"""
        script = self.get_script_path()
        test_script = f"""
        source {script}
        log_error "First error"
        log_error "Second error"
        exit 1
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )

        assert "=== Error Summary ===" in result.stderr
        assert "Total errors encountered: 2" in result.stderr
        assert "First error" in result.stderr
        assert "Second error" in result.stderr
        assert result.returncode == 1

    def test_error_summary_not_displayed_on_exit_code_0(self):
        """Test that error summary is NOT displayed when script exits with code 0"""
        script = self.get_script_path()
        test_script = f"""
        source {script}
        log_error "Test error"
        exit 0
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )

        assert "=== Error Summary ===" not in result.stderr
        assert result.returncode == 0

    def test_error_formatting_includes_color_codes(self):
        """Test that errors include ANSI color formatting"""
        script = self.get_script_path()
        test_script = f"""
        source {script}
        log_error "Formatted error"
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )

        # Check for ANSI red color code (\033[91m)
        assert "\033[91m" in result.stderr
        assert "\033[0m" in result.stderr  # Reset code

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
        log_error "Database connection failed"
        log_error "Invalid JSON syntax"
        log_error "File not found"
        exit 1
        """
        result = subprocess.run(
            ["bash", "-c", test_script], capture_output=True, text=True
        )

        assert "Database connection failed" in result.stderr
        assert "Invalid JSON syntax" in result.stderr
        assert "File not found" in result.stderr
        assert "Total errors encountered: 3" in result.stderr
