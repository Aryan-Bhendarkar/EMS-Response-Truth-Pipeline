"""Structured console + file logging shared by every pipeline stage."""

import logging
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def get_logger(run_id: str, name: str = "pipeline") -> logging.Logger:
    """Return a logger that writes to both the console and logs/pipeline_<run_id>.log.

    Every message should read "[stage/source] outcome" so a FAIL in the log
    names what broke without needing to cross-reference code (CLAUDE.md rule 8).
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"{name}.{run_id}")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger  # already configured (e.g. re-fetched within the same run)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ"
    )

    file_handler = logging.FileHandler(LOG_DIR / f"pipeline_{run_id}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
