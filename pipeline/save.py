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

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = REPO_ROOT / "outputs"


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def atomic_write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, default=str))


def save_month_outputs(month_label: str, validation_report: dict, metrics: dict, dashboard_html: str, logger) -> Path:
    """Write validation_report.json, metrics.json, kpi_monthly.csv, and dashboard.html
    to outputs/<month_label>/, all atomically."""
    month_dir = OUTPUTS_DIR / month_label

    atomic_write_json(month_dir / "validation_report.json", validation_report)
    atomic_write_json(month_dir / "metrics.json", metrics)

    csv_lines = ["month,definition_id,numerator,denominator,pct,excluded_no_arrival"]
    for row in metrics.get("m1_kpi_monthly", []):
        csv_lines.append(
            f"{row['month']},{row['definition_id']},{row['numerator']},{row['denominator']},"
            f"{row['pct'] if row['pct'] is not None else ''},{row['excluded_no_arrival']}"
        )
    atomic_write_text(month_dir / "kpi_monthly.csv", "\n".join(csv_lines) + "\n")

    atomic_write_text(month_dir / "dashboard.html", dashboard_html)

    logger.info("[save] wrote outputs/%s/ (validation_report.json, metrics.json, kpi_monthly.csv, dashboard.html)", month_label)
    return month_dir
