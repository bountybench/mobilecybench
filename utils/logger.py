import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Log records use UTC so timestamps line up with run_summary.json's UTC ISO.
logging.Formatter.converter = time.gmtime


_PATH_UNSAFE_RE = re.compile(r"[/\\]")


def _sanitize_path_token(value: str) -> str:
    """Replace path separators with '-' so a token stays a single dir level.

    Handles LiteLLM-style model IDs like ``openai/gpt-5.5`` which would
    otherwise be interpreted as nested directories.
    """
    return _PATH_UNSAFE_RE.sub("-", value)


class ColorConsoleFormatter(logging.Formatter):
    """Formatter that adds ANSI colors for WARNING (yellow) and ERROR (red)."""

    COLORS = {
        logging.WARNING: "\033[93m",  # yellow
        logging.ERROR: "\033[91m",  # red
        logging.CRITICAL: "\033[91m",  # red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        result = super().format(record)
        color = self.COLORS.get(record.levelno)
        if color:
            return f"{color}{result}{self.RESET}"
        return result


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
            return before + '"[truncated]"' + after
        return text


class _BootstrapFilter(logging.Filter):
    """One-shot filter that materializes file handlers on the first log record.

    Installed by ``LoggerManager._configure_minimal`` on both the parent
    logger and the agent logger. Whichever path emits first runs
    ``configure()`` (which creates ``logs/experiment_<run_id>/`` + the
    four file handlers + console handler), then returns ``True`` so the
    record proceeds through ``callHandlers`` over the freshly-installed
    handlers and lands on stderr **and** in the appropriate file.

    Why a filter and not a handler: ``Logger.handle`` runs filters
    *before* iterating handlers, so swapping the handler list mid-flight
    in ``configure()`` does not collide with the iterator that's about
    to run.
    """

    def __init__(self, manager: "LoggerManager") -> None:
        super().__init__()
        self._manager = manager
        self._fired = False

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._fired:
            # Set the flag *before* configure() so any logging configure()
            # itself does (it shouldn't with announce=False, but defensive)
            # cannot recurse.
            self._fired = True
            self._manager.configure(self._manager._default_config(), announce=False)
        return True


class LoggerManager:
    """Manages application-wide logging configuration and handlers.

    Attributes:
        run_id: A unique identifier for the experiment session (UUID).
        logs_dir: The directory where all experiment artifacts are stored.
    """

    def __init__(
        self,
        name: str = "MobileCyBench",
        config: dict = None,
        *,
        app_name: Optional[str] = None,
        announce: bool = True,
    ) -> None:
        self._name = name
        self._app_name = app_name
        # Filesystem setup (creating logs/experiment_<uuid>/ + file handlers)
        # is the heaviest part of init. We trigger it eagerly only when:
        #   1. a real config dict was passed (the runner's explicit
        #      reconfigure call after parsing args), or
        #   2. an env-var hint says the caller pinned a logs location
        #      (tests via tests/conftest.py, GKE via entrypoint-gke.sh).
        # Otherwise we drop into minimal mode, which arms a one-shot
        # bootstrap filter that triggers full configure() on the first
        # log record. Bare imports that never log keep zero filesystem
        # footprint; the moment anything actually logs (including
        # runner.py's pre-reconfigure error path), the experiment
        # directory and file handlers materialize and the record lands
        # on disk just like before this fix.
        env_hint = (
            "MOBILECYBENCH_LOGS_DIR" in os.environ
            or "MOBILECYBENCH_SESSION_ID" in os.environ
        )
        if config is not None or env_hint:
            self.configure(
                config or self._default_config(),
                app_name=app_name,
                announce=announce,
            )
        else:
            self._configure_minimal()

    def _configure_minimal(self) -> None:
        """Lightweight init: no filesystem side-effects, lazy-on-first-log.

        Sets up just enough state that ``logger`` and ``agent_logger`` are
        usable Logger objects, and arms a ``_BootstrapFilter`` on both so
        the first emitted record triggers a full ``configure()`` before
        ``callHandlers`` runs. After that first record the manager looks
        identical to one constructed with a real config — same
        experiment directory, same four file handlers, same console
        handler. Records emitted before bootstrap fires would only land
        on stderr; in practice nothing in this codebase logs at module
        import time, so the only emit-then-bootstrap path is
        ``runner.py:498`` (config-load failure) which we want persisted.
        """
        self._config = self._default_config()
        # _app_name may already be set by __init__; preserve if so. The bare
        # UUID fallback in _compute_dirname() handles the unset case.
        if not hasattr(self, "_app_name"):
            self._app_name = None
        self._log_level = self._get_log_level()
        self._logger = logging.getLogger(self._name)
        self._logger.setLevel(self._log_level)

        # Drop any handlers a previous configure() left behind. Idempotent.
        for h in self._logger.handlers[:]:
            self._logger.removeHandler(h)
            h.close()

        # Sentinel values so accessor methods never NPE before bootstrap fires.
        self.run_id = self._resolve_run_id()
        self._is_gold = False
        self._logs_dir: Optional[Path] = None
        self._log_file = None
        self._agent_log_file = None
        self._error_log_file = None
        self._error_buffer_handler = None

        self._agent_logger = logging.getLogger(f"{self._name}.Agent")
        self._agent_logger.setLevel(self._log_level)
        self._agent_logger.propagate = True
        for h in self._agent_logger.handlers[:]:
            self._agent_logger.removeHandler(h)
            h.close()

        # Drop any bootstrap filter a previous _configure_minimal armed.
        # configure() does not clear filters (only handlers), so without
        # this an explicit reconfigure followed by a re-entry into
        # minimal mode (rare, mostly tests) could double-arm.
        for lg in (self._logger, self._agent_logger):
            for f in list(lg.filters):
                if isinstance(f, _BootstrapFilter):
                    lg.removeFilter(f)

        # Single shared filter so the agent-logger path and parent-logger
        # path can't both fire it; whichever logs first wins.
        bootstrap = _BootstrapFilter(self)
        self._logger.addFilter(bootstrap)
        self._agent_logger.addFilter(bootstrap)

    def configure(
        self,
        config: dict,
        *,
        app_name: Optional[str] = None,
        announce: bool = True,
    ) -> None:
        """(Re)configure the logger manager with new settings."""
        self._config = config
        # Preserve a previously-set app_name across re-configure calls when the
        # caller doesn't pass a new one (e.g. test/agent code paths that
        # reconfigure with just a config dict).
        if app_name is not None:
            self._app_name = app_name

        # Drop any one-shot _BootstrapFilter armed by a prior
        # _configure_minimal(). The filter exists to lazily trigger configure()
        # on the first log emit, but is obsolete once configure() is called
        # explicitly. Leaving it in place means the very first emit *during*
        # this configure() (e.g. the "Logging initialized" announce line)
        # re-enters configure() with _default_config(), wiping workflow/model
        # and causing the experiment dir to be renamed to a partial-format
        # name. Has to run before handlers attach so the filter can't fire.
        for _name in (self._name, f"{self._name}.Agent"):
            _lg = logging.getLogger(_name)
            for _f in list(_lg.filters):
                if isinstance(_f, _BootstrapFilter):
                    _lg.removeFilter(_f)

        logger = logging.getLogger(self._name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()

        prev_logs_dir = getattr(self, "_logs_dir", None)

        self._error_buffer_handler = None
        self._error_log_file = None

        self.run_id = self._resolve_run_id()

        self._log_level = self._get_log_level()
        self._logger = logger
        self._log_file: Optional[str] = None
        self._agent_log_file: Optional[str] = None
        self._agent_logger: Optional[logging.Logger] = None

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

        self._is_gold = bool(self._config.get("gold_run"))
        suffix = "_gold" if self._is_gold else ""
        if self._is_gold:
            logs_base = logs_base / "gold"

        logs_base.mkdir(exist_ok=True, parents=True)
        self._logs_dir = logs_base / f"{self._compute_dirname()}{suffix}"

        # Move (not recreate) on reconfigure so logs written during import-time
        # auto-init migrate to the final path instead of being orphaned.
        if prev_logs_dir and prev_logs_dir != self._logs_dir and prev_logs_dir.exists():
            prev_logs_dir.rename(self._logs_dir)
        else:
            self._logs_dir.mkdir(exist_ok=True, parents=True)

        self._ensure_handlers()
        self._setup_agent_logger()
        self._setup_error_logging()

        # Keep canonical UUID for machines while surfacing a short human-friendly hint.
        if announce:
            self._logger.info(
                "Logging initialized (run_id=%s, short_id=%s, logs_dir=%s)",
                self.run_id,
                self.run_id[:8],
                self._logs_dir,
            )

    def _resolve_run_id(self) -> str:
        """Resolve the run ID from environment or generate a new UUID."""
        env_id = os.environ.get("MOBILECYBENCH_SESSION_ID")
        if env_id:
            return env_id

        new_id = str(uuid.uuid4())
        os.environ["MOBILECYBENCH_SESSION_ID"] = new_id
        return new_id

    def _compute_dirname(self) -> str:
        """Compute the experiment directory name from create-time fields.

        Format: ``<app>_<workflow>_<model>_<YYYYMMDD-HHMMSS>_<short-uuid>``.
        Falls back to ``<app>_<ts>_<short>`` or just the bare ``run_id`` when
        fields aren't available (bootstrap-time call or non-runner caller).
        Consumers identify run dirs by the presence of ``run_summary.json``
        rather than by name prefix, so all three forms coexist safely.
        """
        wf = self._config.get("workflow")
        model = self._config.get("model")
        short = self.run_id[:8]
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        # Sanitize path separators so provider-prefixed model IDs like
        # "openai/gpt-5.5" don't fracture the dir into nested levels.
        app = _sanitize_path_token(self._app_name) if self._app_name else None
        wf = _sanitize_path_token(wf) if wf else None
        model = _sanitize_path_token(model) if model else None
        if app and wf and model:
            return f"{app}_{wf}_{model}_{ts}_{short}"
        if app:
            return f"{app}_{ts}_{short}"
        return self.run_id

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
        datefmt = "%Y-%m-%dT%H:%M:%S+0000"
        if self._should_filter_ui():
            file_formatter = FilteringFormatter(formatter_str, datefmt=datefmt)
        else:
            file_formatter = logging.Formatter(formatter_str, datefmt=datefmt)

        file_handler.setFormatter(file_formatter)
        console_handler.setFormatter(
            ColorConsoleFormatter(formatter_str, datefmt=datefmt)
        )

        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)

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
        self._agent_logger.propagate = True

        for h in self._agent_logger.handlers[:]:
            self._agent_logger.removeHandler(h)

        # Mirror the BYO container's /app/agent_run/agent.log layout so custom
        # and external paths leave artifacts in the same place.
        agent_run_dir = self._logs_dir / "agent_run"
        agent_run_dir.mkdir(parents=True, exist_ok=True)
        self._agent_log_file = str(agent_run_dir / "agent.log")

        agent_handler = logging.FileHandler(self._agent_log_file, encoding="utf-8")
        agent_handler.setLevel(self._log_level)

        formatter_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        datefmt = "%Y-%m-%dT%H:%M:%S+0000"
        if self._should_filter_ui():
            formatter = FilteringFormatter(formatter_str, datefmt=datefmt)
        else:
            formatter = logging.Formatter(formatter_str, datefmt=datefmt)

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

    def get_logs_dir(self) -> Optional[Path]:
        """Return the experiment logs directory, or None if not yet configured.

        The directory is created lazily — only when ``configure()`` is
        called with a real config (typically by ``runner.py:main()``
        after argv parsing) or when the import-time singleton sees a
        ``MOBILECYBENCH_LOGS_DIR``/``MOBILECYBENCH_SESSION_ID`` env hint.
        """
        return self._logs_dir

    def get_run_id(self) -> str:
        """Return the unique run identifier (UUID)."""
        return self.run_id

    def update_latest_symlink(self) -> None:
        """Update the 'latest' symlink. Skipped for gold runs so they don't shadow real-LLM experiments."""
        if self._is_gold:
            return
        if self._logs_dir is None:
            # configure() hasn't been called yet — no experiment dir to symlink to.
            return
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


def get_logger_manager(
    config: dict = None, app_name: Optional[str] = None
) -> LoggerManager:
    """Lazy singleton factory for LoggerManager.

    Ensures only one LoggerManager exists and allows initialization/re-configuration
    with a specific config dictionary. ``app_name`` participates in the
    experiment directory name; see ``LoggerManager._compute_dirname``.
    """
    global _instance
    if _instance is None:
        _instance = LoggerManager(
            config=config, app_name=app_name, announce=config is not None
        )
    elif config is not None:
        _instance.configure(config, app_name=app_name, announce=True)
    return _instance


# Export singletons for backward compatibility where lazy init isn't strictly needed
logger_manager = get_logger_manager()
logger = logger_manager.get_logger()
agent_logger = logger_manager.get_agent_logger()
