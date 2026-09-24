"""Build the static, self-contained outputs/<month>/dashboard.html - no external
resources (fonts/scripts/CSS), so it opens correctly from a fresh clone with
no network access, per README's "runnable from a fresh clone" requirement.

Written for a reader who has never seen this project: the page opens with a
plain-language answer generated from the numbers, every chart says what it
shows and how to read it, jargon is translated (definition ids -> "clock
starts when...", rule ids -> questions), and a glossary and a "what this
can't tell you" section close it out.

The headline is the run's scope month (metrics["scope_month_summary"]); trend
charts stay full-history as context. Any value can be missing - a month with
no published scorecard actual yet, a month not in the warehouse - so every
number goes through a formatter that renders None as "n/a" instead of
crashing or guessing. Text from data/config is html-escaped.
"""

import calendar
from datetime import datetime, timezone
from html import escape
from typing import Optional

from pipeline.metrics import build_scope_month_summary, latest_month

NA = "n/a"

# Plain-language names for source fields and definition parts. Presentation
# only - the KPI logic itself lives in config/kpi_definitions.yaml.
FIELD_NAMES = {
    "received_dttm": "911 call received",
    "entry_dttm": "call entered",
    "dispatch_dttm": "unit dispatched",
    "response_dttm": "unit en route",
    "on_scene_dttm": "unit on scene",
    "transport_dttm": "transport started",
    "hospital_dttm": "arrived at hospital",
    "available_dttm": "back in service",
    "call_type_group": "call category",
}
UNIT_SCOPE_NAMES = {
    "medic_only": "SFFD ambulances only",
    "ambulance": "SFFD + private ambulances",
    "any_unit": "any responder, incl. fire engines",
}

# Reference data-viz palette (light / dark steps of the same hues), chart
# chrome and fixed status colors. Status colors always ship with an icon + label.
STYLE = """
<style>
  :root {
    color-scheme: light;
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
    --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
    --good:#0ca30c; --warning:#fab219; --critical:#d03b3b; --good-text:#006300;
    --wash:rgba(42,120,214,0.08); --warn-wash:rgba(250,178,25,0.14);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
      --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good-text:#0ca30c;
      --wash:rgba(57,135,229,0.12); --warn-wash:rgba(250,178,25,0.12);
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good-text:#0ca30c;
    --wash:rgba(57,135,229,0.12); --warn-wash:rgba(250,178,25,0.12);
  }
  * { box-sizing: border-box; }
  body { background: var(--page); color: var(--ink); margin: 0;
         font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 1000px; margin: 0 auto; padding: 32px 16px 64px; }
  h1 { font-size: 26px; line-height: 1.25; margin: 0 0 6px; }
  h2 { font-size: 19px; margin: 44px 0 4px; }
  h3 { font-size: 15px; margin: 0 0 8px; }
  p { margin: 0 0 10px; }
  .lede { font-size: 17px; color: var(--ink-2); margin-bottom: 10px; }
  .meta { color: var(--muted); font-size: 13px; }
  .explain { color: var(--ink-2); font-size: 14px; max-width: 760px; margin-bottom: 14px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin-bottom: 14px; }
  .note { background: var(--warn-wash); border-radius: 10px; padding: 12px 16px; margin: 12px 0; font-size: 14px; }
  .answer { background: var(--wash); border-radius: 12px; padding: 18px 22px; margin: 20px 0; }
  .answer ol { margin: 6px 0 0; padding-left: 20px; }
  .answer li { margin-bottom: 8px; }
  .howto { font-size: 14px; color: var(--ink-2); }
  .howto ul { margin: 6px 0 0; padding-left: 20px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-top: 8px; }
  .tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }
  .tile-label { font-size: 13px; color: var(--ink-2); font-weight: 600; }
  .tile-value { font-size: 32px; font-weight: 650; margin: 4px 0 2px; }
  .tile-sub { font-size: 13px; color: var(--ink-2); }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--ink-2); margin: 4px 0 12px; }
  .key { display: inline-flex; align-items: center; gap: 6px; }
  .swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
  .linekey { width: 16px; height: 0; border-top: 2px solid; display: inline-block; }
  .clock-row { display: grid; grid-template-columns: minmax(180px, 38%) 1fr 64px; gap: 12px; align-items: center; padding: 8px 0; border-top: 1px solid var(--grid); }
  .clock-row:first-of-type { border-top: 0; }
  .clock-name { font-size: 14px; }
  .clock-name small { display: block; color: var(--muted); font-size: 12px; }
  .track { position: relative; height: 22px; }
  .bar { position: absolute; left: 0; top: 3px; height: 16px; border-radius: 0 4px 4px 0; }
  .ref { position: absolute; top: -4px; bottom: -4px; width: 0; }
  .ref-target { border-left: 1px solid var(--muted); }
  .ref-official { border-left: 2px solid var(--ink); }
  .clock-value { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
  .axis-row { display: grid; grid-template-columns: minmax(180px, 38%) 1fr 64px; gap: 12px; font-size: 12px; color: var(--muted); }
  .axis { position: relative; height: 16px; }
  .axis span { position: absolute; transform: translateX(-50%); }
  .timeline { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
  .step { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
  .step-span { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
  .step-value { font-size: 26px; font-weight: 650; margin: 2px 0; }
  .meter { height: 8px; background: var(--grid); border-radius: 4px; margin: 8px 0; overflow: hidden; }
  .meter > div { height: 100%; background: var(--s1); border-radius: 0 4px 4px 0; }
  svg text { fill: var(--muted); font-size: 12px; font-family: inherit; }
  svg .label-strong { fill: var(--ink-2); }
  .gridline { stroke: var(--grid); stroke-width: 1; }
  .baseline { stroke: var(--axis); stroke-width: 1; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--grid); vertical-align: top; }
  th { color: var(--ink-2); font-weight: 600; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  tr.hl td { background: var(--wash); }
  .table-wrap { overflow-x: auto; }
  .chart-scroll { overflow-x: auto; }
  .chart-scroll svg { min-width: 560px; display: block; }
  details { margin-top: 10px; }
  summary { cursor: pointer; color: var(--ink-2); font-size: 14px; font-weight: 600; }
  .status { display: inline-flex; align-items: center; gap: 5px; font-weight: 650; font-size: 12px; white-space: nowrap; }
  .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .st-PASS .dot { background: var(--good); } .st-WARN .dot { background: var(--warning); } .st-FAIL .dot { background: var(--critical); }
  .gate { display: flex; flex-wrap: wrap; gap: 10px 22px; margin: 8px 0 4px; font-size: 14px; }
  .muted { color: var(--muted); }
  .best-tag { font-size: 11px; font-weight: 700; color: var(--s1); white-space: nowrap; }
  dl.glossary { display: grid; grid-template-columns: minmax(140px, 200px) 1fr; gap: 8px 16px; font-size: 14px; margin: 10px 0 0; }
  dl.glossary dt { font-weight: 600; } dl.glossary dd { margin: 0; color: var(--ink-2); }
  ul.caveats { padding-left: 20px; font-size: 14px; color: var(--ink-2); }
  footer { color: var(--muted); font-size: 12px; margin-top: 48px; border-top: 1px solid var(--grid); padding-top: 14px; }
  code { font-size: 12px; }
  @media (max-width: 640px) {
    .clock-row, .axis-row { grid-template-columns: 1fr 52px; }
    .clock-name { grid-column: 1 / -1; }
    .axis-row > div:first-child { display: none; }
    .timeline { grid-template-columns: 1fr; }
    dl.glossary { grid-template-columns: 1fr; }
  }
</style>
"""


# ---------- small formatters: every number goes through one, None -> "n/a" ----------

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


def _field(row: Optional[dict], key: str) -> Optional[float]:
    """row[key], or None when the whole row is missing."""
    return row.get(key) if row else None


def _month_name(month: Optional[str]) -> str:
    """'2026-06' -> 'June 2026'; anything unparseable is returned escaped as-is."""
    if not month:
        return NA
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    except ValueError:
        return escape(month)


def _short_month(month: str) -> str:
    """'2026-06' -> 'Jun 26' for chart axes."""
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%b %y")
    except ValueError:
        return escape(month)


def _days_in_month(month: Optional[str]) -> Optional[int]:
    """Calendar days in a 'YYYY-MM' month, or None."""
    try:
        year, mon = (int(p) for p in month.split("-"))
        return calendar.monthrange(year, mon)[1]
    except (AttributeError, ValueError):
        return None


def _status(severity: str) -> str:
    """PASS/WARN/FAIL as dot + word - never color alone."""
    word = {"PASS": "Passed", "WARN": "Warning", "FAIL": "Failed"}.get(severity, escape(str(severity)))
    return f'<span class="status st-{escape(str(severity))}"><span class="dot"></span>{word}</span>'


def _target_status(meets_target: Optional[bool], gap_to_target_points: Optional[float]) -> str:
    """'meets' / 'below by 7.7 pts' / 'n/a' against the target."""
    if meets_target is None:
        return NA
    return "meets" if meets_target else f"below by {abs(gap_to_target_points):.1f} pts"


# ---------- translating project jargon into plain language ----------

def _field_name(field: str) -> str:
    """Source column -> reader-facing name (falls back to the column name)."""
    return FIELD_NAMES.get(field, field)


def _plain_definition(definition: dict) -> tuple[str, str]:
    """(plain-language headline, technical detail) for one M1 candidate definition."""
    label = str(definition.get("label", definition.get("id", "")))
    clock = definition.get("clock_start_field")
    if not clock:
        return escape(label), ""
    values = ", ".join(str(v) for v in definition.get("priority_values", []))
    priority = {
        "original_priority": f"priority at call-taking = {values}",
        "final_priority": f"final priority = {values}",
        "call_type_group": f"category = {values}",
    }.get(definition.get("priority_field"), f"{definition.get('priority_field')} = {values}")
    units = UNIT_SCOPE_NAMES.get(definition.get("unit_scope"), definition.get("unit_scope", ""))
    headline = f"Clock starts at <b>{escape(_field_name(clock))}</b> &middot; {escape(units)}"
    return headline, escape(priority)


def _plain_check_name(rule_id: str) -> str:
    """Validation rule id -> the question it answers."""
    if rule_id.startswith("null_rate_"):
        return f"How often is &ldquo;{escape(_field_name(rule_id[len('null_rate_'):]))}&rdquo; missing?"
    if rule_id.startswith("timestamp_order_") and "_before_" in rule_id:
        earlier, later = rule_id[len("timestamp_order_"):].split("_before_", 1)
        return f"Is &ldquo;{escape(_field_name(earlier))}&rdquo; recorded before &ldquo;{escape(_field_name(later))}&rdquo;?"
    if rule_id.startswith("outlier_p999_") and "_to_" in rule_id:
        start, end = rule_id[len("outlier_p999_"):].removesuffix("_minutes").split("_to_", 1)
        return (f"Extreme &ldquo;{escape(_field_name(start))} &rarr; {escape(_field_name(end))}&rdquo; "
                f"times, flagged for review")
    fixed = {
        "manifest_completeness": "Did we receive every row the API says exists?",
        "schema_required_columns": "Are all the columns the pipeline needs present?",
        "rowid_uniqueness": "Is every unit-response row unique?",
        "priority_domain": "Are the priority codes from the known set?",
        "freshness": "Is the data recent enough?",
    }
    return fixed.get(rule_id, escape(rule_id))


# ---------- page sections ----------

def _scope_summary(metrics: dict) -> dict:
    """The scope-month block from metrics; rebuilt from the full history if an older
    metrics.json predates scope_month (falls back to the latest warehouse month)."""
    if metrics.get("scope_month_summary"):
        return metrics["scope_month_summary"]
    scope_month = metrics.get("scope_month") or latest_month(metrics.get("m1_kpi_monthly", []))
    if scope_month is None:
        return {"month": None, "in_warehouse": False, "official_pct": None, "m1_by_definition": []}
    return build_scope_month_summary(metrics, scope_month)


def _notes_html(summary: dict) -> str:
    """Warnings about missing inputs for the headline month, shown before any number."""
    month = summary.get("month")
    if not month:
        return ""
    text = escape(month)
    if not summary.get("in_warehouse"):
        return (f'<div class="note">No call data for {text} is in the warehouse, so every value for that month '
                f'shows n/a. The trend charts below cover the full warehouse history.</div>')
    if summary.get("official_pct") is None:
        return (f'<div class="note">No official scorecard actual is published for {text} yet (the city publishes '
                f'about 3 months late), so the official value and gaps to it show n/a.</div>')
    return ""


def _answer_html(ctx: dict) -> str:
    """The short answer in plain sentences, built only from numbers that exist."""
    items = []
    if ctx["best_pct"] is not None and ctx["official_pct"] is not None:
        items.append(
            f"<b>The published number can be approximately reproduced.</b> The city reported "
            f"<b>{_pct(ctx['official_pct'])}</b> for {ctx['month_name']}. Our closest reconstruction "
            f"(clock starts when the ambulance is <i>dispatched</i>) gives <b>{_pct(ctx['best_pct'])}</b>. "
            f"Both are below the {ctx['target_pct'] * 100:.0f}% target.")
    elif ctx["best_pct"] is not None:
        items.append(
            f"<b>{_pct(ctx['best_pct'])}</b> of life-threatening calls got an ambulance within "
            f"{ctx['target_minutes']} minutes of dispatch in {ctx['month_name']} "
            f"(target {ctx['target_pct'] * 100:.0f}%). No official figure is published for this month yet.")
    if ctx["caller_pct"] is not None and ctx["twin_gap"] is not None:
        items.append(
            f"<b>Callers experience something worse.</b> Counting from the moment the 911 call is "
            f"<i>received</i>, only <b>{_pct(ctx['caller_pct'])}</b> got an ambulance within "
            f"{ctx['target_minutes']} minutes, <b>{ctx['twin_gap']:.1f} points lower</b>. The published "
            f"number doesn't count the time spent answering and triaging the call.")
    if ctx["m4_p50"] is not None:
        hours = ctx["hours_lost"]
        shifts = ""
        if hours is not None and ctx["days"]:
            shifts = f" (about {hours / ctx['days'] / 12:.1f} twelve-hour ambulance shifts a day)"
        items.append(
            f"<b>The biggest delay is at the hospital, not on the road.</b> After arriving at a hospital, "
            f"an ambulance takes a median <b>{_minutes(ctx['m4_p50'])} min</b> to get back in service, "
            f"against a {ctx['turnaround_minutes']}-minute standard. Compare {_minutes(ctx['m3_p50'])} min "
            f"driving to the scene and {_minutes(ctx['m2_p50'])} min from the call to dispatch. "
            + (f"Time past the standard cost <b>{_count(hours)} ambulance-hours</b> this month{shifts}."
               if hours is not None else ""))
    if not items:
        return ('<div class="answer"><h3>The short answer</h3><p>Not enough data for this month to draw '
                'conclusions. See the notes above.</p></div>')
    return ('<div class="answer"><h3>The short answer</h3><ol>'
            + "".join(f"<li>{i}</li>" for i in items) + "</ol></div>")


def _tile(label: str, value: str, sub: str) -> str:
    """One stat tile: label, value, one plain sentence of context."""
    return (f'<div class="tile"><div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div><div class="tile-sub">{sub}</div></div>')


def _vs_target(pct: Optional[float], target_pct: float) -> str:
    """'4.4 pts below the 90% target' / 'meets the 90% target' / ''."""
    if pct is None:
        return ""
    gap = (pct - target_pct) * 100
    return (f"meets the {target_pct * 100:.0f}% target" if gap >= 0
            else f"{abs(gap):.1f} pts below the {target_pct * 100:.0f}% target")


def _tiles_html(ctx: dict) -> str:
    """The four headline numbers, each with what it means."""
    t = ctx["target_pct"]
    hours_sub = f"Time ambulances spent at hospitals beyond the {ctx['turnaround_minutes']}-min standard"
    if ctx["history_hours"]:
        hours_sub += f"; {_count(ctx['history_hours'])} over the last {ctx['history_months']} months"
    return '<div class="tiles">' + "".join([
        _tile("Published by the city", _pct(ctx["official_pct"]),
              f"Official scorecard, {ctx['month_name']}. {_vs_target(ctx['official_pct'], t)}".strip()),
        _tile("Our reconstruction (dispatch clock)", _pct(ctx["best_pct"]),
              f"Calls with an ambulance on scene within {ctx['target_minutes']} min of dispatch. "
              f"{_vs_target(ctx['best_pct'], t)}".strip()),
        _tile("What callers experience", _pct(ctx["caller_pct"]),
              f"Same calls, clock started when the 911 call was received. {_vs_target(ctx['caller_pct'], t)}".strip()),
        _tile("Ambulance-hours lost", _count(ctx["hours_lost"]), hours_sub),
    ]) + "</div>"


def _clock_chart_html(ctx: dict, summary: dict, definitions_by_id: dict) -> str:
    """Horizontal bars: every candidate definition for the month, with target and official lines."""
    rows = summary.get("m1_by_definition", [])
    if not rows:
        return '<div class="card muted">No KPI values for this month.</div>'
    target, official = ctx["target_pct"], ctx["official_pct"]
    parts = []
    for d in rows:
        definition = definitions_by_id.get(d["definition_id"], {"label": d.get("label", d["definition_id"])})
        headline, detail = _plain_definition(definition)
        is_received = definition.get("clock_start_field") == "received_dttm"
        color = "var(--s2)" if is_received else "var(--s1)"
        width = max(0.0, min(100.0, (d["pct"] or 0) * 100))
        tag = ' <span class="best-tag">&#9733; best fit</span>' if d.get("is_best_fit") else ""
        official_line = (f'<div class="ref ref-official" style="left:{official * 100:.1f}%"></div>'
                         if official is not None else "")
        bar = (f'<div class="bar" style="width:{width:.1f}%;background:{color}" '
               f'title="{escape(str(d["label"]))}: {_pct(d["pct"])}"></div>' if d["pct"] is not None else "")
        parts.append(
            f'<div class="clock-row"><div class="clock-name">{headline}{tag}<small>{detail}</small></div>'
            f'<div class="track">{bar}<div class="ref ref-target" style="left:{target * 100:.1f}%"></div>'
            f'{official_line}</div><div class="clock-value">{_pct(d["pct"])}</div></div>')
    axis = "".join(f'<span style="left:{v}%">{v}%</span>' for v in (0, 25, 50, 75, 100))
    legend = (
        '<div class="legend">'
        '<span class="key"><span class="swatch" style="background:var(--s1)"></span>Clock starts at dispatch</span>'
        '<span class="key"><span class="swatch" style="background:var(--s2)"></span>Clock starts at the 911 call</span>'
        f'<span class="key"><span class="linekey" style="border-color:var(--muted);border-top-width:1px"></span>'
        f'{target * 100:.0f}% target</span>'
        + (f'<span class="key"><span class="linekey" style="border-color:var(--ink)"></span>'
           f'Official value ({_pct(official)})</span>' if official is not None else "")
        + '</div>')
    return (f'<div class="card">{legend}{"".join(parts)}'
            f'<div class="axis-row"><div></div><div class="axis">{axis}</div><div></div></div></div>')


def _definition_table_html(ctx: dict, summary: dict, definitions_by_id: dict) -> str:
    """The same numbers as the chart, as a table (with counts) for readers who want them."""
    rows = []
    for d in summary.get("m1_by_definition", []):
        definition = definitions_by_id.get(d["definition_id"], {"label": d.get("label", d["definition_id"])})
        headline, detail = _plain_definition(definition)
        tag = ' <span class="best-tag">&#9733; best fit</span>' if d.get("is_best_fit") else ""
        rows.append(
            f"<tr class=\"{'hl' if d.get('is_best_fit') else ''}\"><td>{headline}{tag}"
            f"<br><span class=\"muted\">{detail or escape(str(d.get('label', '')))}</span></td>"
            f"<td class=\"num\">{_pct(d['pct'])}</td>"
            f"<td>{_target_status(d['meets_target'], d['gap_to_target_points'])}</td>"
            f"<td class=\"num\">{_points(d['gap_to_official_points'], signed=True)}</td>"
            f"<td class=\"num\">{_count(d['numerator'])} / {_count(d['denominator'])}</td></tr>")
    return (
        '<details><summary>Show as a table, with call counts</summary><div class="table-wrap"><table>'
        f'<tr><th>How the KPI is counted</th><th class="num">Result</th><th>vs {ctx["target_pct"] * 100:.0f}% target</th>'
        f'<th class="num">vs official ({_pct(ctx["official_pct"])})</th>'
        '<th class="num">Calls on time / calls counted</th></tr>'
        + "".join(rows) + "</table></div></details>")


def _reconciliation_table_html(metrics: dict, definitions_by_id: dict, best_def_id: Optional[str]) -> str:
    """How far each definition sits from the official number, averaged over every month."""
    recon = metrics.get("m1_reconciliation", {})
    ordered = sorted(recon.items(), key=lambda x: (x[1]["mean_absolute_gap"] is None, x[1]["mean_absolute_gap"] or 0))
    rows = []
    for def_id, r in ordered:
        headline, detail = _plain_definition(definitions_by_id.get(def_id, {"label": def_id}))
        gap = r["mean_absolute_gap"] * 100 if r["mean_absolute_gap"] is not None else None
        tag = ' <span class="best-tag">&#9733; best fit</span>' if def_id == best_def_id else ""
        rows.append(f"<tr class=\"{'hl' if def_id == best_def_id else ''}\"><td>{headline}{tag}"
                    f"<br><span class=\"muted\">{detail}</span></td>"
                    f"<td class=\"num\">{r['months_compared']}</td><td class=\"num\">{_points(gap)}</td></tr>")
    return ('<details><summary>Which definition matches the official number best, over all months?</summary>'
            '<p class="explain" style="margin-top:8px">Each definition was compared with the published value for '
            'every month where both exist. A smaller average gap means a closer match. This is how the '
            '&ldquo;best fit&rdquo; was chosen: by testing against the data, not by assuming.</p>'
            '<div class="table-wrap"><table><tr><th>How the KPI is counted</th><th class="num">Months compared</th>'
            '<th class="num">Average gap to official</th></tr>' + "".join(rows) + "</table></div></details>")


def _trend_series(metrics: dict, best_def_id: Optional[str]) -> tuple[list[str], dict[str, list[Optional[float]]]]:
    """Months plus three aligned series: official, best fit (dispatch clock), its received-clock twin."""
    m1 = metrics.get("m1_kpi_monthly", [])
    months = sorted({r["month"] for r in m1})
    by = {(r["definition_id"], r["month"]): r["pct"] for r in m1}
    twin_id = (metrics.get("m5_best_fit_twin") or {}).get("received_clock")
    official = metrics.get("official_scorecard_by_month", {})
    series = {
        "official": [official.get(m) for m in months],
        "best": [by.get((best_def_id, m)) for m in months],
        "caller": [by.get((twin_id, m)) for m in months] if twin_id else [None] * len(months),
    }
    return months, series


def _trend_chart_html(ctx: dict, metrics: dict, best_def_id: Optional[str]) -> str:
    """Line chart over every month: official vs our dispatch-clock reconstruction vs caller clock."""
    months, series = _trend_series(metrics, best_def_id)
    if len(months) < 2:
        return ('<div class="card muted">The trend needs at least two months in the warehouse. '
                'Run the 12-month backfill (see README) to fill it in.</div>')
    w, h, left, right, top, bottom = 760, 280, 44, 16, 16, 30
    lo, hi = 0.5, 1.0
    values = [v for s in series.values() for v in s if v is not None]
    if values:
        lo = min(lo, (int(min(values) * 10)) / 10)
    x = lambda i: left + i * (w - left - right) / (len(months) - 1)
    y = lambda v: top + (hi - v) * (h - top - bottom) / (hi - lo)
    grid = "".join(
        f'<line class="gridline" x1="{left}" x2="{w - right}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
        f'<text x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{t * 100:.0f}%</text>'
        for t in [lo + i * 0.1 for i in range(int(round((hi - lo) / 0.1)) + 1)])
    step = max(1, len(months) // 12)
    xlabels = "".join(f'<text x="{x(i):.1f}" y="{h - 8}" text-anchor="middle">{_short_month(m)}</text>'
                      for i, m in enumerate(months) if i % step == 0 or i == len(months) - 1)
    target_y = y(ctx["target_pct"])
    target = (f'<line x1="{left}" x2="{w - right}" y1="{target_y:.1f}" y2="{target_y:.1f}" stroke="var(--ink-2)" '
              f'stroke-width="1"/><text class="label-strong" x="{w - right}" y="{target_y - 6:.1f}" '
              f'text-anchor="end">{ctx["target_pct"] * 100:.0f}% target</text>')
    names = {"official": "Published by the city", "best": "Our reconstruction (dispatch clock)",
             "caller": "What callers experience (911-call clock)"}
    colors = {"official": "var(--s3)", "best": "var(--s1)", "caller": "var(--s2)"}
    lines = []
    for key in ("caller", "best", "official"):
        pts = [(x(i), y(v), months[i], v) for i, v in enumerate(series[key]) if v is not None]
        if not pts:
            continue
        path = " ".join(f"{'M' if j == 0 else 'L'}{px:.1f},{py:.1f}" for j, (px, py, _, _) in enumerate(pts))
        lines.append(f'<path d="{path}" fill="none" stroke="{colors[key]}" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
        lines.extend(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{colors[key]}" stroke="var(--surface)" stroke-width="2">'
            f'<title>{names[key]}, {_month_name(m)}: {_pct(v)}</title></circle>'
            for px, py, m, v in pts)
    legend = '<div class="legend">' + "".join(
        f'<span class="key"><span class="swatch" style="background:{colors[k]}"></span>{names[k]}</span>'
        for k in ("official", "best", "caller")) + "</div>"
    rows = "".join(
        f"<tr><td>{_month_name(m)}</td><td class=\"num\">{_pct(series['official'][i])}</td>"
        f"<td class=\"num\">{_pct(series['best'][i])}</td><td class=\"num\">{_pct(series['caller'][i])}</td></tr>"
        for i, m in enumerate(months))
    return (f'<div class="card">{legend}<div class="chart-scroll"><svg viewBox="0 0 {w} {h}" width="100%" role="img" '
            f'aria-label="Monthly 10-minute compliance: published, reconstructed and caller-experienced">'
            f'{grid}{target}{"".join(lines)}{xlabels}</svg></div>'
            '<p class="muted" style="font-size:12px;margin:6px 0 0">Hover a point for its exact value.</p>'
            '<details><summary>Show as a table</summary><div class="table-wrap"><table>'
            f'<tr><th>Month</th><th class="num">{names["official"]}</th><th class="num">{names["best"]}</th>'
            f'<th class="num">{names["caller"]}</th></tr>{rows}</table></div></details></div>')


def _timeline_html(ctx: dict, summary: dict) -> str:
    """The three measured stages of a call, median and slow-case (p90) minutes."""
    m2, m3, m4 = summary.get("m2_call_processing"), summary.get("m3_travel_time"), summary.get("m4_hospital_turnaround")
    stages = [
        ("911 call &rarr; unit dispatched", "Answering &amp; dispatching", m2,
         "Time from the call being received to the first unit being sent. Controlled by the 911 dispatch centre."),
        ("en route &rarr; on scene", "Driving to the patient", m3,
         "Ambulance travel time (SFFD and private ambulances). Depends on where ambulances are when a call comes in."),
        ("at hospital &rarr; back in service", "Handing over at hospital", m4,
         f"Time until the ambulance is free for the next call. Standard: {ctx['turnaround_minutes']} min. "
         f"Includes cleaning and restocking."),
    ]
    longest = max([_field(s[2], "p50_minutes") or 0 for s in stages] + [1])
    cards = []
    for span, title, row, text in stages:
        p50, p90 = _field(row, "p50_minutes"), _field(row, "p90_minutes")
        width = 100 * (p50 or 0) / longest
        cards.append(
            f'<div class="step"><div class="step-span">{span}</div><h3>{title}</h3>'
            f'<div class="step-value">{_minutes(p50)} <span style="font-size:14px;font-weight:400">min median</span></div>'
            f'<div class="meter"><div style="width:{width:.0f}%"></div></div>'
            f'<div class="tile-sub">1 in 10 calls takes longer than <b>{_minutes(p90)} min</b>.</div>'
            f'<p class="muted" style="font-size:13px;margin-top:8px">{text}</p></div>')
    return f'<div class="timeline">{"".join(cards)}</div>'


def _hospital_chart_html(ctx: dict, metrics: dict, scope_month: Optional[str]) -> str:
    """Column chart: ambulance-hours lost beyond the turnaround standard, per month, plus its table."""
    m4 = metrics.get("m4_hospital_turnaround", [])
    if not m4:
        return '<div class="card muted">No hospital turnaround data yet.</div>'
    w, h, left, right, top, bottom = 760, 240, 52, 12, 22, 30
    peak = max((r.get("ambulance_hours_lost") or 0) for r in m4) or 1
    nice = 10 ** len(str(int(peak))) / 10
    ymax = (int(peak / nice) + 1) * nice
    band = (w - left - right) / len(m4)
    bar_w = min(24, band * 0.6)
    y = lambda v: top + (ymax - v) * (h - top - bottom) / ymax
    grid = "".join(
        f'<line class="gridline" x1="{left}" x2="{w - right}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
        f'<text x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{t:,.0f}</text>'
        for t in [ymax * i / 4 for i in range(5)])
    bars = []
    for i, r in enumerate(m4):
        v = r.get("ambulance_hours_lost") or 0
        cx = left + band * (i + 0.5)
        top_y, base = y(v), y(0)
        rad = min(4, (base - top_y) / 2)
        opacity = "1" if (scope_month is None or r["month"] == scope_month) else "0.55"
        x0, x1 = cx - bar_w / 2, cx + bar_w / 2
        path = (f"M{x0:.1f},{base:.1f} L{x0:.1f},{top_y + rad:.1f} Q{x0:.1f},{top_y:.1f} {x0 + rad:.1f},{top_y:.1f} "
                f"L{x1 - rad:.1f},{top_y:.1f} Q{x1:.1f},{top_y:.1f} {x1:.1f},{top_y + rad:.1f} L{x1:.1f},{base:.1f} Z")
        bars.append(
            f'<path d="{path}" fill="var(--s1)" fill-opacity="{opacity}"><title>{_month_name(r["month"])}: '
            f'{_count(v)} ambulance-hours lost; {_pct(r.get("pct_over_standard"))} of transports over the standard; '
            f'median {_minutes(r.get("p50_minutes"))} min</title></path>'
            f'<text x="{cx:.1f}" y="{h - 8}" text-anchor="middle">{_short_month(r["month"])}</text>')
        if r["month"] == scope_month:
            bars.append(f'<text class="label-strong" x="{cx:.1f}" y="{top_y - 6:.1f}" text-anchor="middle">{_count(v)}</text>')
    rows = "".join(
        f"<tr class=\"{'hl' if r['month'] == scope_month else ''}\"><td>{_month_name(r['month'])}</td>"
        f"<td class=\"num\">{_count(r.get('n_transports'))}</td><td class=\"num\">{_pct(r.get('pct_over_standard'))}</td>"
        f"<td class=\"num\">{_minutes(r.get('p50_minutes'))}</td><td class=\"num\">{_minutes(r.get('p90_minutes'))}</td>"
        f"<td class=\"num\">{_count(r.get('ambulance_hours_lost'))}</td></tr>" for r in m4)
    return (f'<div class="card"><div class="chart-scroll"><svg viewBox="0 0 {w} {h}" width="100%" role="img" '
            f'aria-label="Ambulance-hours lost beyond the hospital turnaround standard, per month">'
            f'{grid}<line class="baseline" x1="{left}" x2="{w - right}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>'
            f'{"".join(bars)}</svg></div>'
            '<p class="muted" style="font-size:12px;margin:6px 0 0">Hover a bar for details. '
            'The headline month is shown darker.</p>'
            '<details><summary>Show as a table</summary><div class="table-wrap"><table>'
            f'<tr><th>Month</th><th class="num">Transports</th><th class="num">Over {ctx["turnaround_minutes"]} min</th>'
            '<th class="num">Median min</th><th class="num">Slowest 10% take over (min)</th>'
            f'<th class="num">Ambulance-hours lost</th></tr>{rows}</table></div></details></div>')


def _validation_html(validation_report: dict) -> str:
    """The data-quality gate: plain summary first, every check with what it means and what happens next."""
    checks = validation_report.get("checks", [])
    overall = validation_report.get("overall_status", "UNKNOWN")
    counts = {s: sum(c["severity"] == s for c in checks) for s in ("PASS", "WARN", "FAIL")}
    verdict = {
        "PASS": "Every check passed.",
        "WARN": "No check failed, so the numbers were published. The warnings are known, counted data issues, "
                "documented below. They are not errors in this report.",
        "FAIL": "At least one check failed. The pipeline stops on a failure, so these numbers should not be used.",
    }.get(overall, "")
    rows = "".join(
        f"<tr><td>{_plain_check_name(c['rule_id'])}<br><code class=\"muted\">{escape(str(c['rule_id']))}</code></td>"
        f"<td>{_status(c['severity'])}</td>"
        f"<td>{escape(str(c.get('description', '')))}</td><td>{escape(str(c['action']))}</td></tr>"
        for c in checks)
    return (
        '<div class="card"><p class="explain" style="margin-bottom:6px">Before any number is calculated, the raw '
        'data goes through automatic checks. <b>Failed</b> stops the pipeline and nothing is published. '
        '<b>Warning</b> means a known issue that is counted and documented, and the run continues.</p>'
        f'<div class="gate">{_status("PASS")} {counts["PASS"]} {_status("WARN")} {counts["WARN"]} '
        f'{_status("FAIL")} {counts["FAIL"]}</div><p style="font-size:14px">{verdict}</p>'
        '<details><summary>Show every check</summary><div class="table-wrap"><table>'
        '<tr><th>Check</th><th>Result</th><th>What it checks</th><th>What happens next</th></tr>'
        f'{rows}</table></div></details></div>')


def _caveats_html(metrics: dict) -> str:
    """What this page cannot tell you, stated plainly."""
    m4_standard = metrics.get("m4_standard", {})
    offload = m4_standard.get("offload_minutes")
    items = [
        "The city doesn't publish how it calculates its number. The &ldquo;best fit&rdquo; is our inference from the "
        "data, and no official owner has confirmed it yet.",
        "&ldquo;On scene&rdquo; means the unit reached the address, not the patient's side.",
        "Hospital time includes cleaning and restocking the ambulance, so it overstates the hospital's share.",
        "The data doesn't say which hospital or which private ambulance company was involved.",
        "These figures describe what happened. They don't show why (association, not causation).",
    ]
    if offload:
        items.insert(3, f"The stricter {offload}-minute patient hand-over (offload) standard can't be measured from "
                        f"this data: it needs a hospital timestamp that isn't recorded here.")
    return '<ul class="caveats">' + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _glossary_html(ctx: dict) -> str:
    """Terms a newcomer will meet on this page."""
    terms = [
        ("Life-threatening call", "An emergency coded urgent (&ldquo;Code 3&rdquo;: lights and sirens)."),
        ("10-minute compliance", f"Share of those calls where an ambulance was on scene within "
                                 f"{ctx['target_minutes']} minutes. The city's goal is {ctx['target_pct'] * 100:.0f}%."),
        ("Dispatch clock vs 911-call clock", "When the 10-minute timer starts: when an ambulance is sent, or when the "
                                             "caller's 911 call is received. The difference is the time spent "
                                             "answering and triaging the call."),
        ("Best fit (&#9733;)", "The way of counting that comes closest to the city's published number across all "
                               "months."),
        ("Median", "The middle value: half of cases are faster, half slower."),
        ("1 in 10 takes longer than (p90)", "90% of cases are faster than this. It describes the slow cases."),
        ("pts (percentage points)", "The difference between two percentages: 85% vs 88% is 3 pts."),
        ("SFFD vs private ambulances", "City-run ambulances (MEDIC) vs contracted private ones (PRIVATE)."),
        ("Ambulance-hours lost", f"Minutes each ambulance spent at a hospital beyond the "
                                 f"{ctx['turnaround_minutes']}-minute standard, added up and shown in hours."),
    ]
    return ('<details><summary>Glossary: terms used on this page</summary><dl class="glossary">'
            + "".join(f"<dt>{t}</dt><dd>{d}</dd>" for t, d in terms) + "</dl></details>")


def _context(metrics: dict, summary: dict, best_def_id: Optional[str]) -> dict:
    """Every scalar the narrative sections need, pulled out once."""
    best_row = next((d for d in summary.get("m1_by_definition", []) if d["definition_id"] == best_def_id), None)
    m5 = summary.get("m5_definition_gap")
    m4 = metrics.get("m4_hospital_turnaround", [])
    return {
        "month_name": _month_name(summary.get("month")),
        "target_pct": metrics.get("target_pct", 0.90),
        "target_minutes": metrics.get("target_minutes", 10),
        "turnaround_minutes": metrics.get("m4_standard", {}).get("turnaround_minutes", 30),
        "best_pct": _field(best_row, "pct"),
        "official_pct": summary.get("official_pct"),
        "caller_pct": _field(m5, "best_fit_twin_received_clock_pct"),
        "twin_gap": _field(m5, "best_fit_twin_gap_points"),
        "m2_p50": _field(summary.get("m2_call_processing"), "p50_minutes"),
        "m3_p50": _field(summary.get("m3_travel_time"), "p50_minutes"),
        "m4_p50": _field(summary.get("m4_hospital_turnaround"), "p50_minutes"),
        "hours_lost": _field(summary.get("m4_hospital_turnaround"), "ambulance_hours_lost"),
        "days": _days_in_month(summary.get("month")),
        "history_hours": sum(r["ambulance_hours_lost"] for r in m4 if r.get("ambulance_hours_lost") is not None),
        "history_months": len(m4),
    }


def build_dashboard_html(month_label: str, validation_report: dict, metrics: dict) -> str:
    """Render the self-contained dashboard for one run.

    month_label is the run's scope label (e.g. '2026-06' or 'since_3d'); the
    headline numbers come from the scope month in metrics, trend charts from
    the full history. Never raises on missing values - they render as 'n/a'.
    """
    best_def_id = metrics.get("m1_best_fitting_definition")
    summary = _scope_summary(metrics)
    scope_month = summary.get("month")
    ctx = _context(metrics, summary, best_def_id)
    definitions_by_id = {d["id"]: d for d in metrics.get("m1_definitions", [])}
    title_label = escape(month_label)
    scope_text = escape(scope_month) if scope_month else NA
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    overall = validation_report.get("overall_status", "UNKNOWN")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SF Ambulance Response — {title_label}</title>
{STYLE}
</head>
<body>
<main>
  <h1>San Francisco ambulance response: {ctx['month_name']}</h1>
  <p class="lede">Are ambulances reaching life-threatening emergencies within {ctx['target_minutes']} minutes,
    {ctx['target_pct'] * 100:.0f}% of the time, as city policy requires? And does the number the city
    publishes reflect what callers actually experience?</p>
  <div class="meta">Run {title_label} &middot; headline month {scope_text} &middot; data check {_status(overall)}
    &middot; generated {generated}</div>

  {_notes_html(summary)}

  <div class="card howto" style="margin-top:18px"><b>How to read this page.</b>
    <ul>
      <li>The <b>short answer</b> below sums up the month in plain sentences. Everything after it is the evidence.</li>
      <li>Every number is calculated from San Francisco's public 911 dispatch records (DataSF) and compared with
        the city's own published scorecard.</li>
      <li>Charts show a value when you hover. Each has a <b>Show as a table</b> link with the exact numbers.
        Unfamiliar terms are explained in the glossary at the bottom.</li>
    </ul>
  </div>

  {_answer_html(ctx)}

  {_tiles_html(ctx)}

  <h2>1. It depends on when you start the clock</h2>
  <p class="explain">The city doesn't say exactly how it counts its number, so we calculated it five different
    ways. They differ in when the {ctx['target_minutes']}-minute timer starts, which calls count as
    life-threatening, and which vehicles count as &ldquo;an ambulance&rdquo;. The way of counting that matches
    the published number best is marked with a <span class="best-tag">&#9733;</span> (the &ldquo;best fit&rdquo;). The biggest
    difference comes from one choice: <b>when the clock starts</b>.</p>
  {_clock_chart_html(ctx, summary, definitions_by_id)}
  {_definition_table_html(ctx, summary, definitions_by_id)}
  {_reconciliation_table_html(metrics, definitions_by_id, best_def_id)}

  <h2>2. Month by month</h2>
  <p class="explain">The same three views for every month in the data. The gap between the blue and orange
    lines is time the caller waits before an ambulance is even sent. The published number never shows it.</p>
  {_trend_chart_html(ctx, metrics, best_def_id)}

  <h2>3. Where the time goes</h2>
  <p class="explain">A call moves through several stages. These three are measured separately, as
    {ctx['month_name']} medians. The bars compare the stages with each other.</p>
  {_timeline_html(ctx, summary)}

  <h2>4. Ambulance time lost at hospitals</h2>
  <p class="explain">When handover at a hospital takes longer than the {ctx['turnaround_minutes']}-minute
    standard, that ambulance can't answer the next call. Each bar adds up that extra time across all
    ambulances in a month.</p>
  {_hospital_chart_html(ctx, metrics, scope_month)}

  <h2>5. Can this data be trusted?</h2>
  {_validation_html(validation_report)}

  <h2>6. What this page can't tell you</h2>
  {_caveats_html(metrics)}
  {_glossary_html(ctx)}

  <footer>
    Generated by <code>pipeline/report.py</code> from <code>metrics.json</code> and
    <code>validation_report.json</code> in this folder. Sources: SF Fire Dept &amp; EMS Dispatched Calls for
    Service (DataSF <code>nuek-vuh3</code>), City Performance Scorecard measure
    {escape(str(metrics.get('official_measure_code', '973')))} (<code>kc49-udxn</code>). Full reasoning:
    <code>docs/judgement_call.md</code>, <code>docs/kpi_definitions.md</code>, <code>docs/assumptions.md</code>.
  </footer>
</main>
</body>
</html>
"""
