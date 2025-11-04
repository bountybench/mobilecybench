import datetime
import logging
import re
import sys
from typing import Optional


class FilteringFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        original_msg = record.msg
        if isinstance(record.msg, str) and '"ui_elements":' in record.msg:
            record.msg = self._truncate_ui_elements(record.msg)
        result = super().format(record)
        record.msg = (
            original_msg  # restore for other handlers (especially debug handler)
        )
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
        while pos < len(text) and bracket_count > 0:  # O(n)
            if text[pos] == "[":
                bracket_count += 1
            elif text[pos] == "]":
                bracket_count -= 1
            pos += 1

        # replace the ui_elements array with truncation marker
        if bracket_count == 0:  # found end of ui_elements array
            before = text[:start_pos]
            after = text[pos:]
            return before + '"[truncated - see debug log]"' + after
        return text


class LoggerManager:
    """Simple logger manager that owns the log file path.

    Keeps a single named logger with file + console handlers and exposes
    the active log file name for callers that need it.
    """

    def __init__(self, name: str = "MobileCyBench", config: dict = None) -> None:
        self._name = name
        self._config = config or self._default_config()
        self._timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_level = self._get_log_level()
        self._logger = logging.getLogger(name)
        self._log_file: Optional[str] = None
        self._agent_log_file: Optional[str] = None
        self._agent_logger: Optional[logging.Logger] = None
        self._ui_debug_log_file: Optional[str] = None
        self._ensure_handlers()
        self._setup_agent_logger()
        if self._should_filter_ui():
            self._setup_ui_debug_logger()

    def _default_config(self) -> dict:
        return {"log_level": "info", "filter_ui_elements": True}

    def _get_log_level(self) -> int:
        lvl = self._config.get("log_level", "info").upper()
        return getattr(logging, lvl, logging.INFO)

    def _should_filter_ui(self) -> bool:
        return self._config.get("filter_ui_elements", True)

    def _ensure_handlers(self) -> None:
        if self._logger.handlers:
            # Attempt to discover existing file handler path if already configured
            for h in self._logger.handlers:
                if isinstance(h, logging.FileHandler):
                    self._log_file = getattr(h, "baseFilename", None)
            return

        self._log_file = f"agent_run_{self._timestamp}.log"
        self._logger.setLevel(self._log_level)

        file_handler = logging.FileHandler(self._log_file)
        file_handler.setLevel(self._log_level)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self._log_level)

        # Use FilteringFormatter for console if filtering is enabled
        if self._should_filter_ui():
            formatter = FilteringFormatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)

    def _setup_ui_debug_logger(self) -> None:
        self._ui_debug_log_file = f"ui_debug_{self._timestamp}.log"

        debug_handler = logging.FileHandler(self._ui_debug_log_file, encoding="utf-8")
        debug_handler.setLevel(self._log_level)

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        debug_handler.setFormatter(formatter)

        self._agent_logger.addHandler(debug_handler)  # Attach to agent_logger

    def _setup_agent_logger(self) -> None:
        """Setup a separate logger for agent-specific logs.

        This creates a child logger that:
        - Writes to its own agent-only log file
        - Also propagates to the main logger (so logs appear in both files)
        """
        # Create child logger
        self._agent_logger = logging.getLogger(f"{self._name}.Agent")
        self._agent_logger.setLevel(self._log_level)

        # Create agent-specific log file
        self._agent_log_file = f"agent_only_{self._timestamp}.log"

        # Add file handler to agent logger
        agent_handler = logging.FileHandler(self._agent_log_file, encoding="utf-8")
        agent_handler.setLevel(self._log_level)

        if self._should_filter_ui():
            formatter = FilteringFormatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        agent_handler.setFormatter(formatter)

        self._agent_logger.addHandler(agent_handler)

    def get_logger(self) -> logging.Logger:
        return self._logger

    def get_agent_logger(self) -> logging.Logger:
        return self._agent_logger

    def get_log_file_name(self) -> str:
        return self._log_file or ""

    def get_agent_log_file_name(self) -> str:
        return self._agent_log_file or ""

    def get_ui_debug_log_file_name(self) -> str:
        return self._ui_debug_log_file or ""


# TODO: integrate with runner_config or have separate config file
# for integrating with runner_config, may need to refactor logger.py
config = {"log_level": "info", "filter_ui_elements": True}

logger_manager = LoggerManager(config=config)
logger = logger_manager.get_logger()
agent_logger = logger_manager.get_agent_logger()
