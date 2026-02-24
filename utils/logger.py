import datetime
import logging
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


class FilteringFormatter(logging.Formatter):
    """Formatter that truncates large UI element arrays in log messages.

    Thread-safe by copying the log record before modification.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Create a copy to avoid mutating the original record for other handlers
        record_copy = logging.makeLogRecord(record.__dict__)
        original_msg = record_copy.msg

        if isinstance(original_msg, str) and '"ui_elements":' in original_msg:
            record_copy.msg = self._truncate_ui_elements(original_msg)

        result = super().format(record_copy)
        return result

    def _truncate_ui_elements(self, text: str) -> str:
        pattern = r'"ui_elements"\s*:\s*'
        match = re.search(pattern, text)
        if not match:
            return text

        start_pos = match.end()
        if start_pos >= len(text) or text[start_pos] != "[":
            return text

        bracket_count = 1
        pos = start_pos + 1
        while pos < len(text) and bracket_count > 0:
            if text[pos] == "[":
                bracket_count += 1
            elif text[pos] == "]":
                bracket_count -= 1
            pos += 1

        if bracket_count == 0:
            before = text[:start_pos]
            after = text[pos:]
            return before + '"[truncated - see debug log]"' + after
        return text


class LoggerManager:
    """Manages application-wide logging configuration and handlers.

    Attributes:
        run_id: A unique identifier for the experiment session (UUID).
        logs_dir: The directory where all experiment artifacts are stored.
    """

    def __init__(self, name: str = "MobileCyBench", config: dict = None) -> None:
        self._name = name
        self.configure(config or self._default_config())

    def configure(self, config: dict) -> None:
        """(Re)configure the logger manager with new settings."""
        self._config = config
        
        # Reset handlers if reconfiguring
        logger = logging.getLogger(self._name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()

        self._error_buffer_handler = None
        self._error_log_file = None

        # Resolve or generate the unique run ID
        self.run_id = self._resolve_run_id()

        self._log_level = self._get_log_level()
        self._logger = logger
        self._log_file: Optional[str] = None
        self._agent_log_file: Optional[str] = None
        self._agent_logger: Optional[logging.Logger] = None
        self._ui_debug_log_file: Optional[str] = None

        # Setup logs directory
        if "MOBILECYBENCH_LOGS_DIR" in os.environ:
            logs_base = Path(os.environ["MOBILECYBENCH_LOGS_DIR"])
        else:
            # Fallback to current working directory if project root is elusive
            try:
                self._project_root = Path(__file__).resolve().parent.parent
            except Exception:
                self._project_root = Path.cwd()
            logs_base = self._project_root / "logs"

        logs_base.mkdir(exist_ok=True, parents=True)
        self._logs_dir = logs_base / f"experiment_{self.run_id}"
        self._logs_dir.mkdir(exist_ok=True, parents=True)

        self._ensure_handlers()
        self._setup_agent_logger()
        self._setup_error_logging()

        if self._should_filter_ui():
            self._setup_ui_debug_logger()

    def _resolve_run_id(self) -> str:
        """Resolve the run ID from environment or generate a new UUID."""
        env_id = os.environ.get("MOBILECYBENCH_SESSION_ID")
        if env_id:
            return env_id

        # Use UUID for machine-readability and uniqueness
        new_id = str(uuid.uuid4())
        os.environ["MOBILECYBENCH_SESSION_ID"] = new_id
        return new_id

    def _default_config(self) -> dict:
        return {"log_level": "info", "filter_ui_elements": True}

    def _get_log_level(self) -> int:
        lvl = self._config.get("log_level", "info").upper()
        return getattr(logging, lvl, logging.INFO)

    def _should_filter_ui(self) -> bool:
        return self._config.get("filter_ui_elements", True)

    def _ensure_handlers(self) -> None:
        self._log_file = str(self._logs_dir / "experiment.log")
        self._logger.setLevel(self._log_level)

        file_handler = logging.FileHandler(self._log_file)
        file_handler.setLevel(self._log_level)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self._log_level)

        formatter_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        if self._should_filter_ui():
            formatter = FilteringFormatter(formatter_str)
        else:
            formatter = logging.Formatter(formatter_str)

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)

    def _setup_ui_debug_logger(self) -> None:
        self._ui_debug_log_file = str(self._logs_dir / "ui_debug.log")

        debug_handler = logging.FileHandler(self._ui_debug_log_file, encoding="utf-8")
        debug_handler.setLevel(self._log_level)

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        debug_handler.setFormatter(formatter)

        if self._agent_logger:
            self._agent_logger.addHandler(debug_handler)

    def _setup_error_logging(self) -> None:
        self._error_log_file = str(self._logs_dir / "errors.log")

        # Use standard formatter for buffering; color is applied at print-time
        summary_formatter = logging.Formatter("%(levelname)s - %(name)s - %(message)s")
        self._error_buffer_handler = ErrorBufferHandler(formatter=summary_formatter)

        error_file_handler = logging.FileHandler(self._error_log_file, encoding="utf-8")
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

        self._logger.addHandler(error_file_handler)
        self._logger.addHandler(self._error_buffer_handler)

    def _setup_agent_logger(self) -> None:
        """Setup a separate logger for agent-specific logs."""
        name = f"{self._name}.Agent"
        self._agent_logger = logging.getLogger(name)
        self._agent_logger.setLevel(self._log_level)
        self._agent_logger.propagate = True # Allow propagation to main logger handlers
        
        # Clear existing handlers
        for h in self._agent_logger.handlers[:]:
            self._agent_logger.removeHandler(h)

        self._agent_log_file = str(self._logs_dir / "agent.log")

        agent_handler = logging.FileHandler(self._agent_log_file, encoding="utf-8")
        agent_handler.setLevel(self._log_level)

        formatter_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        if self._should_filter_ui():
            formatter = FilteringFormatter(formatter_str)
        else:
            formatter = logging.Formatter(formatter_str)

        agent_handler.setFormatter(formatter)
        self._agent_logger.addHandler(agent_handler)

    def get_logger(self) -> logging.Logger:
        return self._logger

    def get_agent_logger(self) -> logging.Logger:
        if self._agent_logger is None:
             self._agent_logger = logging.getLogger(f"{self._name}.Agent")
        return self._agent_logger

    def get_log_file_name(self) -> str:
        return self._log_file or ""

    def get_agent_log_file_name(self) -> str:
        return self._agent_log_file or ""

    def get_ui_debug_log_file_name(self) -> str:
        return self._ui_debug_log_file or ""

    def get_logs_dir(self) -> Path:
        return self._logs_dir

    def get_run_id(self) -> str:
        """Return the unique run identifier (UUID)."""
        return self.run_id

    def update_latest_symlink(self) -> None:
        """Update the 'latest' symlink in the logs directory."""
        try:
            latest_link = self._logs_dir.parent / "latest"
            if latest_link.exists() or latest_link.is_symlink():
                latest_link.unlink()
            
            # Use relative path for the symlink to keep it portable
            latest_link.symlink_to(self._logs_dir.name, target_is_directory=True)
        except Exception as e:
            # Don't fail the run just because symlinking failed (e.g. on Windows)
            self._logger.debug(f"Failed to update 'latest' symlink: {e}")

    def get_session_id(self) -> str:
        """Alias for get_run_id for backward compatibility."""
        return self.get_run_id()

    def get_error_count(self) -> int:
        if not self._error_buffer_handler:
            return 0
        return len(self._error_buffer_handler.errors)

    def get_tool_logger(self) -> logging.Logger:
        """Return a child logger for tool interactions."""
        # Use standard agent logger to consolidate logs
        return self.get_agent_logger()

    def print_error_summary(self) -> None:
        """Print and log a summary of all captured errors."""
        if not self._error_buffer_handler or not self._error_buffer_handler.errors:
            return

        error_count = len(self._error_buffer_handler.errors)
        capped = error_count >= ErrorBufferHandler.MAX_ERRORS

        # Use INFO level for the summary to avoid triggering the ErrorBufferHandler
        # which listens for ERROR level.
        self._logger.info("=" * 80)
        self._logger.info(
            "ERROR SUMMARY: %d error(s)%s",
            error_count,
            " (capped)" if capped else "",
        )
        for line in self._error_buffer_handler.errors:
            self._logger.info("  %s", line)
        self._logger.info("=" * 80)

        # Print to console (with ANSI color)
        print("\n" + "=" * 80)
        print("\033[91mERROR SUMMARY\033[0m")
        print("=" * 80)

        for line in self._error_buffer_handler.errors:
            print(f"\033[91m{line}\033[0m")

        if capped:
            print(
                f"\033[91m... capped at {ErrorBufferHandler.MAX_ERRORS} errors\033[0m"
            )

        print("=" * 80 + "\n")


class ErrorBufferHandler(logging.Handler):
    """Handler that buffers errors in memory for later summary printing."""

    MAX_ERRORS = 100

    def __init__(self, formatter: logging.Formatter):
        super().__init__(level=logging.ERROR)
        self.formatter = formatter
        self.errors = []

    def emit(self, record):
        if len(self.errors) < self.MAX_ERRORS:
            self.errors.append(self.format(record))


_instance: Optional[LoggerManager] = None


def get_logger_manager(config: dict = None) -> LoggerManager:
    """Lazy singleton factory for LoggerManager.

    Ensures only one LoggerManager exists and allows initialization/re-configuration
    with a specific config dictionary.
    """
    global _instance
    if _instance is None:
        _instance = LoggerManager(config=config)
    elif config is not None:
        # Re-configure existing instance if new config provided
        _instance.configure(config)
    return _instance


# Export singletons for backward compatibility where lazy init isn't strictly needed
logger_manager = get_logger_manager()
logger = logger_manager.get_logger()
agent_logger = logger_manager.get_agent_logger()

