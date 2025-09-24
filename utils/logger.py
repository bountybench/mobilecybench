import datetime
import logging
import sys
from typing import Optional


class LoggerManager:
    """Simple logger manager that owns the log file path.

    Keeps a single named logger with file + console handlers and exposes
    the active log file name for callers that need it.
    """

    def __init__(self, name: str = "MobileCyBench") -> None:
        self._name = name
        self._logger = logging.getLogger(name)
        self._log_file: Optional[str] = None
        self._ensure_handlers()

    def _ensure_handlers(self) -> None:
        if self._logger.handlers:
            # Attempt to discover existing file handler path if already configured
            for h in self._logger.handlers:
                if isinstance(h, logging.FileHandler):
                    self._log_file = getattr(h, "baseFilename", None)
            return

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_file = f"agent_run_{timestamp}.log"
        self._logger.setLevel(logging.INFO)

        file_handler = logging.FileHandler(self._log_file)
        file_handler.setLevel(logging.INFO)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        return self._logger

    def get_log_file_name(self) -> str:
        return self._log_file or ""


logger_manager = LoggerManager()
logger = logger_manager.get_logger()
