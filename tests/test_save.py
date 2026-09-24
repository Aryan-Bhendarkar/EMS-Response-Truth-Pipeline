"""Hermetic tests for pipeline/save.py: one month's KPI pack is written
atomically to a tmp outputs dir, and a rerun replaces it (CLAUDE.md rule 7).
"""

import json

from pipeline.save import save_month_outputs

EXPECTED_FILES = ["dashboard.html", "kpi_monthly.csv", "metrics.json", "validation_report.json"]


def make_metrics(pct: float) -> dict:
    return {"m1_kpi_monthly": [{"month": "2026-06", "definition_id": "a", "numerator": 1,
                                "denominator": 1, "pct": pct, "excluded_no_arrival": 0}]}


class TestSaveMonthOutputs:
    def test_writes_four_files_and_no_tmp_leftovers(self, tmp_path, logger):
        out = save_month_outputs("2026-06", {"overall_status": "PASS"}, make_metrics(1.0), "<html>v1</html>",
                                 logger, outputs_dir=tmp_path)
        assert out == tmp_path / "2026-06"
        assert sorted(p.name for p in out.iterdir()) == EXPECTED_FILES
        assert not list(tmp_path.rglob("*.tmp"))
        assert json.loads((out / "validation_report.json").read_text())["overall_status"] == "PASS"
        assert (out / "kpi_monthly.csv").read_text().splitlines()[1] == "2026-06,a,1,1,1.0,0"

    def test_rerun_overwrites_in_place(self, tmp_path, logger):
        save_month_outputs("2026-06", {"overall_status": "WARN"}, make_metrics(1.0), "<html>v1</html>",
                           logger, outputs_dir=tmp_path)
        out = save_month_outputs("2026-06", {"overall_status": "PASS"}, make_metrics(0.5), "<html>v2</html>",
                                 logger, outputs_dir=tmp_path)
        assert sorted(p.name for p in out.iterdir()) == EXPECTED_FILES
        assert (out / "dashboard.html").read_text() == "<html>v2</html>"
        assert json.loads((out / "metrics.json").read_text())["m1_kpi_monthly"][0]["pct"] == 0.5
        assert json.loads((out / "validation_report.json").read_text())["overall_status"] == "PASS"
