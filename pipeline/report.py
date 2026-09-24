"""Build the static, self-contained outputs/<month>/dashboard.html - no external
resources (fonts/scripts/CSS), so it opens correctly from a fresh clone with
no network access, per README's "runnable from a fresh clone" requirement.

The headline is the run's scope month (metrics["scope_month_summary"]); the
trend and reconciliation tables stay full-history as context. Any value can be
missing - a month with no published scorecard actual yet, a month not in the
warehouse - so every number goes through a formatter that renders None as
"n/a" instead of crashing or guessing. Text from data/config is html-escaped.
"""

from datetime import datetime, timezone
from html import escape
from typing import Optional

from pipeline.metrics import build_scope_month_summary, latest_month

NA = "n/a"

STYLE = """
<style>
  :root { --bg:#0b0d12; --panel:#151922; --border:#262b36; --text:#e7ebf3; --muted:#9aa4b5;
          --pass:#3ecf8e; --warn:#f5b849; --fail:#f0556b; --accent:#5b9bff; }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         margin: 0; padding: 32px 24px 64px; max-width: 980px; margin-inline: auto; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  h2 { font-size: 16px; color: var(--muted); font-weight: 600; margin-top: 40px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
  .subtitle { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; overflow-x: auto; }
  .note { background: rgba(245,184,73,.10); border: 1px solid rgba(245,184,73,.35); color: var(--warn);
          border-radius: 10px; padding: 12px 16px; margin-bottom: 16px; font-size: 13px; }
  .kpi-row { display: flex; gap: 16px; flex-wrap: wrap; }
  .kpi-card { flex: 1; min-width: 190px; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; }
  .kpi-value { font-size: 28px; font-weight: 700; }
  .kpi-label { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .badge { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: .04em; }
  .badge-pass { background: rgba(62,207,142,.15); color: var(--pass); }
  .badge-warn { background: rgba(245,184,73,.15); color: var(--warn); }
  .badge-fail { background: rgba(240,85,107,.15); color: var(--fail); }
  .muted { color: var(--muted); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
  tr.best { background: rgba(91,155,255,.08); }
  .bar-row { display: flex; align-items: center; gap: 10px; margin: 8px 0; font-size: 13px; }
  .bar-label { width: 160px; color: var(--muted); flex-shrink: 0; }
  .bar-track { flex: 1; background: #1d2230; border-radius: 4px; height: 18px; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--accent); border-radius: 4px; }
  .bar-value { width: 70px; text-align: right; flex-shrink: 0; }
  .footer { color: var(--muted); font-size: 11px; margin-top: 40px; border-top: 1px solid var(--border); padding-top: 12px; }
</style>
"""


def _pct(value: Optional[float]) -> str:
    """0-1 fraction -> '82.3%', or 'n/a'."""
    return f"{value * 100:.1f}%" if value is not None else NA


def _points(value: Optional[float], signed: bool = False) -> str:
    """Percentage points -> '17.1 pts' (or '+17.1 pts' when signed), or 'n/a'."""
    if value is None:
        return NA
    return f"{value:+.1f} pts" if signed else f"{value:.1f} pts"


def _minutes(value: Optional[float]) -> str:
    """Minutes -> '7.4', or 'n/a'."""
    return f"{value:.1f}" if value is not None else NA


def _count(value: Optional[float], decimals: int = 0) -> str:
    """Count -> '21,896', or 'n/a'."""
    return f"{value:,.{decimals}f}" if value is not None else NA


def _badge(severity: str) -> str:
    """Colored PASS/WARN/FAIL pill."""
    cls = {"PASS": "badge-pass", "WARN": "badge-warn", "FAIL": "badge-fail"}.get(severity, "badge-warn")
    return f'<span class="badge {cls}">{escape(str(severity))}</span>'


def _bar(label: str, minutes: Optional[float], max_minutes: float) -> str:
    """One horizontal bar; a missing value renders as an empty bar labelled n/a."""
    width = min(100, round(100 * minutes / max_minutes)) if minutes is not None and max_minutes else 0
    value = f"{minutes:.1f} min" if minutes is not None else NA
    return (
        f'<div class="bar-row"><div class="bar-label">{escape(label)}</div>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{width}%"></div></div>'
        f'<div class="bar-value">{value}</div></div>'
    )


def _field(row: Optional[dict], key: str) -> Optional[float]:
    """row[key], or None when the whole row is missing."""
    return row.get(key) if row else None


def _target_status(meets_target: Optional[bool], gap_to_target_points: Optional[float]) -> str:
    """'meets' / 'below by 7.7 pts' / 'n/a' against the target."""
    if meets_target is None:
        return NA
    return "meets" if meets_target else f"below by {abs(gap_to_target_points):.1f} pts"


def _scope_summary(metrics: dict) -> dict:
    """The scope-month block from metrics; rebuilt from the full history if an older
    metrics.json predates scope_month (falls back to the latest warehouse month)."""
    if metrics.get("scope_month_summary"):
        return metrics["scope_month_summary"]
    scope_month = metrics.get("scope_month") or latest_month(metrics.get("m1_kpi_monthly", []))
    if scope_month is None:
        return {"month": None, "in_warehouse": False, "official_pct": None, "m1_by_definition": []}
    return build_scope_month_summary(metrics, scope_month)


def build_dashboard_html(month_label: str, validation_report: dict, metrics: dict) -> str:
    """Render the self-contained dashboard for one run.

    month_label is the run's scope label (e.g. '2026-06' or 'since_3d'); the
    headline numbers come from the scope month in metrics, trend tables from
    the full history. Never raises on missing values - they render as 'n/a'.
    """
    target_pct = metrics.get("target_pct", 0.90)
    target_minutes = metrics.get("target_minutes", 10)
    best_def_id = metrics.get("m1_best_fitting_definition")
    summary = _scope_summary(metrics)
    scope_month = summary.get("month")
    scope_text = escape(scope_month) if scope_month else NA

    definitions_by_id = {d["id"]: d for d in metrics.get("m1_definitions", [])}
    best_row = next((d for d in summary.get("m1_by_definition", []) if d["definition_id"] == best_def_id), None)
    best_pct = _field(best_row, "pct")
    official_pct = summary.get("official_pct")

    m2_scope = summary.get("m2_call_processing")
    m3_scope = summary.get("m3_travel_time")
    m4_scope = summary.get("m4_hospital_turnaround")
    m2_p50, m3_p50, m4_p50 = _field(m2_scope, "p50_minutes"), _field(m3_scope, "p50_minutes"), _field(m4_scope, "p50_minutes")
    max_bar = max([v for v in (m2_p50, m3_p50, m4_p50) if v] + [1])

    m4 = metrics.get("m4_hospital_turnaround", [])
    history_hours_lost = sum(r["ambulance_hours_lost"] for r in m4 if r.get("ambulance_hours_lost") is not None)
    history_span = f"{len(m4)} mo., {escape(m4[0]['month'])}&ndash;{escape(m4[-1]['month'])}" if m4 else "0 mo."
    turnaround_minutes = metrics.get("m4_standard", {}).get("turnaround_minutes", 30)

    notes = []
    if scope_month and not summary.get("in_warehouse"):
        notes.append(f"No call data for {scope_text} is in the warehouse, so every value for that month shows n/a. "
                     f"Trend tables below are the full warehouse history.")
    if scope_month and summary.get("in_warehouse") and official_pct is None:
        notes.append(f"No official scorecard actual is published for {scope_text} yet, so the official value "
                     f"and gaps to it show n/a.")
    notes_html = "".join(f'<div class="note">{n}</div>' for n in notes)

    per_def_rows_html = "".join(
        f"<tr class=\"{'best' if d['is_best_fit'] else ''}\">"
        f"<td>{escape(str(d['label']))}</td>"
        f"<td>{_pct(d['pct'])}</td>"
        f"<td>{_target_status(d['meets_target'], d['gap_to_target_points'])}</td>"
        f"<td>{_pct(official_pct)}</td>"
        f"<td>{_points(d['gap_to_official_points'], signed=True)}</td>"
        f"<td class=\"muted\">{_count(d['numerator'])} / {_count(d['denominator'])}</td>"
        f"<td>{'&#9733; best fit' if d['is_best_fit'] else ''}</td></tr>"
        for d in summary.get("m1_by_definition", [])
    )

    recon = metrics.get("m1_reconciliation", {})
    recon_rows_html = "".join(
        f"<tr class=\"{'best' if def_id == best_def_id else ''}\">"
        f"<td>{escape(str(definitions_by_id.get(def_id, {}).get('label', def_id)))}</td>"
        f"<td>{r['months_compared']}</td>"
        f"<td>{_points(r['mean_absolute_gap'] * 100 if r['mean_absolute_gap'] is not None else None)}</td>"
        f"<td>{'&#9733; best fit' if def_id == best_def_id else ''}</td></tr>"
        for def_id, r in sorted(recon.items(), key=lambda x: (x[1]["mean_absolute_gap"] is None, x[1]["mean_absolute_gap"] or 0))
    )

    m4_rows_html = "".join(
        f"<tr class=\"{'best' if r['month'] == scope_month else ''}\"><td>{escape(r['month'])}</td>"
        f"<td>{_count(r.get('n_transports'))}</td><td>{_pct(r.get('pct_over_standard'))}</td>"
        f"<td>{_minutes(r.get('p50_minutes'))}</td><td>{_minutes(r.get('p90_minutes'))}</td>"
        f"<td>{_count(r.get('ambulance_hours_lost'))}</td></tr>"
        for r in m4
    )

    checks = validation_report.get("checks", [])
    overall = validation_report.get("overall_status", "UNKNOWN")
    checks_rows_html = "".join(
        f"<tr><td>{escape(str(c['rule_id']))}</td><td>{_badge(c['severity'])}</td><td>{escape(str(c['action']))}</td></tr>"
        for c in checks
    )

    title_label = escape(month_label)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SF EMS Response — {title_label}</title>
{STYLE}
</head>
<body>
  <h1>EMS Response Truth Pipeline</h1>
  <div class="subtitle">Run for {title_label} &middot; headline month {scope_text} &middot; generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} &middot; gate status {_badge(overall)}</div>

  {notes_html}
  <div class="kpi-row">
    <div class="kpi-card">
      <div class="kpi-value">{_pct(best_pct)}</div>
      <div class="kpi-label">M1 — best-fit definition, {scope_text} (target {target_pct*100:.0f}%, {target_minutes} min)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-value">{_pct(official_pct)}</div>
      <div class="kpi-label">Official scorecard, {scope_text}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-value">{_count(_field(m4_scope, 'ambulance_hours_lost'))}</div>
      <div class="kpi-label">Ambulance-hours lost to hospital turnaround &gt; {turnaround_minutes} min, {scope_text}
        ({_count(history_hours_lost)} over {history_span})</div>
    </div>
  </div>

  <h2>M1 — every candidate definition, {scope_text}, vs the {target_pct*100:.0f}% target and the official value</h2>
  <div class="panel">
    <table>
      <tr><th>Definition</th><th>Value</th><th>vs {target_pct*100:.0f}% target</th><th>Official</th><th>Gap to official</th><th>Calls within / scored</th><th></th></tr>
      {per_def_rows_html}
    </table>
  </div>

  <h2>M1 — which definition reproduces the official number? (full history)</h2>
  <div class="panel">
    <table>
      <tr><th>Definition</th><th>Months compared</th><th>Mean gap to official</th><th></th></tr>
      {recon_rows_html}
    </table>
  </div>

  <h2>Where time is lost ({scope_text}, per-step median)</h2>
  <div class="panel">
    {_bar('Call processing (M2)', m2_p50, max_bar)}
    {_bar('Ambulance travel (M3)', m3_p50, max_bar)}
    {_bar('Hospital turnaround (M4)', m4_p50, max_bar)}
  </div>

  <h2>M4 — hospital turnaround trend ({turnaround_minutes}-min standard, full history)</h2>
  <div class="panel">
    <table>
      <tr><th>Month</th><th>Transports</th><th>% over standard</th><th>p50 min</th><th>p90 min</th><th>Ambulance-hrs lost</th></tr>
      {m4_rows_html}
    </table>
  </div>

  <h2>Validation gate — {_badge(overall)}</h2>
  <div class="panel">
    <table>
      <tr><th>Rule</th><th>Severity</th><th>Action</th></tr>
      {checks_rows_html}
    </table>
  </div>

  <div class="footer">
    Generated by pipeline/report.py. Every number above comes from metrics.json and
    validation_report.json for this run - see docs/judgement_call.md, docs/decision_log.md
    and docs/assumptions.md for the reasoning behind each definition and exclusion.
  </div>
</body>
</html>
"""
