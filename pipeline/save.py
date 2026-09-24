"""Atomic, idempotent writes for per-month pipeline outputs.

Each file is written to a temp path in the same directory, then moved into
place with os.replace - atomic on the same filesystem, so a crash mid-write
never leaves a half-written file where a reader expects a complete one.
Rerunning for the same month overwrites its output in place (CLAUDE.md
rule 7): the target path is always the same, so a rerun replaces, not
appends.
"""

import json
import os
from pathlib import Path

from pipeline.metrics import kpi_monthly_csv

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = REPO_ROOT / "outputs"


def atomic_write_text(path: Path, content: str) -> None:
    """Write content to path via a same-directory temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def atomic_write_json(path: Path, data: dict) -> None:
    """Atomically write data as indented JSON."""
    atomic_write_text(path, json.dumps(data, indent=2, default=str))


def save_month_outputs(month_label: str, validation_report: dict, metrics: dict, dashboard_html: str, logger,
                       outputs_dir: Path = OUTPUTS_DIR) -> Path:
    """Write validation_report.json, metrics.json, kpi_monthly.csv, and dashboard.html
    to <outputs_dir>/<month_label>/, all atomically.

    outputs_dir defaults to outputs/; chaos runs pass outputs/_chaos so a test
    run can never overwrite a real KPI pack.
    """
    month_dir = outputs_dir / month_label

    atomic_write_json(month_dir / "validation_report.json", validation_report)
    atomic_write_json(month_dir / "metrics.json", metrics)
    atomic_write_text(month_dir / "kpi_monthly.csv", kpi_monthly_csv(metrics.get("m1_kpi_monthly", [])))
    atomic_write_text(month_dir / "dashboard.html", dashboard_html)

    logger.info("[save] wrote %s/ (validation_report.json, metrics.json, kpi_monthly.csv, dashboard.html)", month_dir)
    return month_dir
