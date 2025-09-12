import datetime
import logging
import sys


def _setup_logger(name: str = "MobileCyBench") -> logging.Logger:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"agent_run_{timestamp}.log"

    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


logger = _setup_logger()
