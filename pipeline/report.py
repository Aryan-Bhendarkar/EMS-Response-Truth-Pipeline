"""Build the static, self-contained outputs/<month>/dashboard.html - no external
resources (fonts/scripts/CSS), so it opens correctly from a fresh clone with
no network access, per README's "runnable from a fresh clone" requirement.
"""

from datetime import datetime, timezone

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
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; }
  .kpi-row { display: flex; gap: 16px; flex-wrap: wrap; }
  .kpi-card { flex: 1; min-width: 190px; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; }
  .kpi-value { font-size: 28px; font-weight: 700; }
  .kpi-label { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .badge { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: .04em; }
  .badge-pass { background: rgba(62,207,142,.15); color: var(--pass); }
  .badge-warn { background: rgba(245,184,73,.15); color: var(--warn); }
  .badge-fail { background: rgba(240,85,107,.15); color: var(--fail); }
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


def _badge(severity: str) -> str:
    cls = {"PASS": "badge-pass", "WARN": "badge-warn", "FAIL": "badge-fail"}.get(severity, "badge-warn")
    return f'<span class="badge {cls}">{severity}</span>'


def _bar(label: str, minutes: float, max_minutes: float) -> str:
    pct = min(100, round(100 * minutes / max_minutes)) if max_minutes else 0
    return (
        f'<div class="bar-row"><div class="bar-label">{label}</div>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>'
        f'<div class="bar-value">{minutes:.1f} min</div></div>'
    )


def build_dashboard_html(month_label: str, validation_report: dict, metrics: dict) -> str:
    target_pct = metrics.get("target_pct", 0.90)
    target_minutes = metrics.get("target_minutes", 10)
    best_def_id = metrics.get("m1_best_fitting_definition")

    latest_month = None
    best_pct = None
    official_pct = None
    for row in metrics.get("m1_kpi_monthly", []):
        if row["definition_id"] == best_def_id and row["pct"] is not None:
            if latest_month is None or row["month"] > latest_month:
                latest_month = row["month"]
                best_pct = row["pct"]
    if latest_month:
        official_pct = metrics.get("official_scorecard_by_month", {}).get(latest_month)

    m2 = metrics.get("m2_call_processing_p50_p90", [])
    m3 = metrics.get("m3_travel_time_p50_p90", [])
    m4 = metrics.get("m4_hospital_turnaround", [])
    m2_p50 = m2[-1]["p50_minutes"] if m2 else None
    m3_p50 = m3[-1]["p50_minutes"] if m3 else None
    m4_p50 = m4[-1]["p50_minutes"] if m4 else None
    max_bar = max([v for v in (m2_p50, m3_p50, m4_p50) if v] + [1])

    definitions_by_id = {d["id"]: d for d in metrics.get("m1_definitions", [])}
    recon = metrics.get("m1_reconciliation", {})

    checks = validation_report.get("checks", [])
    overall = validation_report.get("overall_status", "UNKNOWN")

    m4_rows_html = "".join(
        f"<tr><td>{r['month']}</td><td>{r['n_transports']}</td>"
        f"<td>{r['pct_over_standard']*100:.1f}%</td><td>{r['p50_minutes']:.1f}</td>"
        f"<td>{r['p90_minutes']:.1f}</td><td>{r['ambulance_hours_lost']:.0f}</td></tr>"
        for r in m4
    )

    recon_rows_html = "".join(
        (
            f"<tr class=\"{'best' if def_id == best_def_id else ''}\">"
            f"<td>{definitions_by_id.get(def_id, {}).get('label', def_id)}</td>"
            f"<td>{r['months_compared']}</td>"
            f"<td>{r['mean_absolute_gap']*100:.1f} pts</td>"
            f"<td>{'&#9733; best fit' if def_id == best_def_id else ''}</td></tr>"
        )
        for def_id, r in sorted(recon.items(), key=lambda x: (x[1]["mean_absolute_gap"] is None, x[1]["mean_absolute_gap"] or 9))
    )

    checks_rows_html = "".join(
        f"<tr><td>{c['rule_id']}</td><td>{_badge(c['severity'])}</td><td>{c['action']}</td></tr>"
        for c in checks
    )

    total_hours_lost = sum(r["ambulance_hours_lost"] for r in m4)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SF EMS Response — {month_label}</title>
{STYLE}
</head>
<body>
  <h1>EMS Response Truth Pipeline</h1>
  <div class="subtitle">Run for {month_label} &middot; generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} &middot; gate status {_badge(overall)}</div>

  <div class="kpi-row">
    <div class="kpi-card">
      <div class="kpi-value">{best_pct*100:.1f}%</div>
      <div class="kpi-label">M1 — best-fit definition, {latest_month or 'n/a'} (target {target_pct*100:.0f}%, {target_minutes} min)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-value">{official_pct*100:.1f}%</div>
      <div class="kpi-label">Official scorecard, same month</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-value">{total_hours_lost:,.0f}</div>
      <div class="kpi-label">Ambulance-hours lost to hospital turnaround &gt; 30 min (12 mo.)</div>
    </div>
  </div>

  <h2>M1 — which definition reproduces the official number?</h2>
  <div class="panel">
    <table>
      <tr><th>Definition</th><th>Months compared</th><th>Mean gap to official</th><th></th></tr>
      {recon_rows_html}
    </table>
  </div>

  <h2>Where time is lost (most recent month, per-step median)</h2>
  <div class="panel">
    {_bar('Call processing (M2)', m2_p50 or 0, max_bar)}
    {_bar('Ambulance travel (M3)', m3_p50 or 0, max_bar)}
    {_bar('Hospital turnaround (M4)', m4_p50 or 0, max_bar)}
  </div>

  <h2>M4 — hospital turnaround trend (30-min standard)</h2>
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
    Generated by pipeline/report.py. Every number above comes from outputs/metrics.json and
    outputs/validation_report.json for this run - see docs/judgement_call.md, docs/decision_log.md
    and docs/assumptions.md for the reasoning behind each definition and exclusion.
  </div>
</body>
</html>
"""
