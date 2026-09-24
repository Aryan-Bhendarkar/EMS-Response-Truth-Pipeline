"""Load raw JSON into a persistent DuckDB warehouse and run the SQL models.

Idempotent by design (CLAUDE.md rule 7): calls are upserted by `rowid`, and an
incoming row only overwrites an existing one if its `data_loaded_at` is at
least as new - so loading the same raw pull twice, or loading two overlapping
pulls in any order, converges to the same warehouse state. The scorecard
table is small and always represents "the latest published values," so it's
fully replaced on every load rather than upserted.
"""

import argparse
from pathlib import Path
from typing import Optional

import duckdb
import yaml

from pipeline.logging_utils import get_logger

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "processed" / "sf_ems.duckdb"
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"
TRANSFORM_DIR = REPO_ROOT / "pipeline" / "transform"
PRIORITY_MAP_PATH = REPO_ROOT / "config" / "priority_map.yaml"


def get_connection(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the DuckDB warehouse at db_path."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()[0] > 0


def upsert_calls(con: duckdb.DuckDBPyConnection, glob_pattern: str, logger) -> int:
    """Upsert every row matching glob_pattern into raw_calls, keyed on rowid.

    If the incoming batch itself repeats a rowid (the API sending a duplicate -
    chaos scenario duplicate_rowid), only the copy with the latest
    data_loaded_at is kept before the upsert. Without this, DuckDB accepts the
    batch but picks one copy arbitrarily (verified: it kept the OLDER copy on
    an empty table). The number of in-batch duplicates dropped is logged, so
    the dedupe is counted, not silent (CLAUDE.md rule 5); validate.py's
    rowid_uniqueness check reports the same count in the validation report.
    Returns the raw_calls row count after the upsert.
    """
    source = f"read_json_auto('{glob_pattern}', union_by_name=true)"
    if not _table_exists(con, "raw_calls"):
        con.execute(f"CREATE TABLE raw_calls AS SELECT * FROM {source} WHERE 1=0")
        con.execute("CREATE UNIQUE INDEX raw_calls_rowid_idx ON raw_calls(rowid)")
        logger.info("[load/calls] created raw_calls table")

    columns = [row[0] for row in con.execute("DESCRIBE raw_calls").fetchall()]
    non_key_cols = [c for c in columns if c != "rowid"]
    col_list = ", ".join(f'"{c}"' for c in columns)
    # Socrata JSON omits null fields, so a pull where an optional column is null
    # on every row simply lacks that column. Select NULL for it rather than
    # crashing LOAD after validation has already passed. (Required columns are
    # guaranteed present by validate.py's schema check.)
    incoming = {row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()}
    select_list = ", ".join(f'"{c}"' if c in incoming else f'NULL AS "{c}"' for c in columns)
    set_clause = ", ".join(f'"{c}" = excluded."{c}"' for c in non_key_cols)

    in_batch_duplicates = con.execute(f"SELECT COUNT(*) - COUNT(DISTINCT rowid) FROM {source}").fetchone()[0]
    if in_batch_duplicates:
        logger.warning("[load/calls] rule=dedupe_in_batch_rowid: %d duplicate rowid row(s) in the incoming batch; "
                       "keeping the latest data_loaded_at per rowid", in_batch_duplicates)

    before = con.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0]
    con.execute(f"""
        INSERT INTO raw_calls ({col_list})
        SELECT {select_list} FROM {source}
        QUALIFY ROW_NUMBER() OVER (PARTITION BY rowid ORDER BY data_loaded_at DESC) = 1
        ON CONFLICT (rowid) DO UPDATE SET {set_clause}
        WHERE excluded.data_loaded_at >= raw_calls.data_loaded_at
    """)
    after = con.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0]
    logger.info("[load/calls] upserted from %s: %d -> %d rows (net +%d)", glob_pattern, before, after, after - before)
    return after


def latest_month_in_pull(con: duckdb.DuckDBPyConnection, glob_pattern: str) -> Optional[str]:
    """Latest received_dttm month (YYYY-MM) in one raw calls pull, or None if it has no rows.

    An incremental (--since) run headlines this month: it is the newest month
    the pull actually contains, rather than a calendar guess.
    """
    return con.execute(
        f"SELECT strftime(MAX(CAST(received_dttm AS TIMESTAMP)), '%Y-%m') "
        f"FROM read_json_auto('{glob_pattern}', union_by_name=true)"
    ).fetchone()[0]


def load_scorecard(con: duckdb.DuckDBPyConnection, glob_pattern: str, logger) -> int:
    """Full-replace the scorecard table - it's small and always reflects the latest published state."""
    con.execute(
        f"CREATE OR REPLACE TABLE scorecard_measures AS "
        f"SELECT * FROM read_json_auto('{glob_pattern}', union_by_name=true)"
    )
    n = con.execute("SELECT COUNT(*) FROM scorecard_measures").fetchone()[0]
    logger.info("[load/scorecard] loaded %d rows from %s", n, glob_pattern)
    return n


def load_priority_map(con: duckdb.DuckDBPyConnection, logger, path: Path = PRIORITY_MAP_PATH) -> int:
    """Full-replace dim_priority_map from config/priority_map.yaml (brief §5).

    The mapping is config, not code: every observed original_priority code with
    its assumed meaning, source, owner and confirmed_by_owner flag. The blank
    code is stored as '' - stg_unit_response turns blank into NULL, so join with
    COALESCE(original_priority, '') = dim_priority_map.code.
    """
    with open(path, "r", encoding="utf-8") as f:
        priority_map = yaml.safe_load(f)
    rows = [
        (str(c["code"]), c["assumed_meaning"], c["source"], bool(c["confirmed_by_owner"]), priority_map["owner"])
        for c in priority_map["codes"]
    ]
    con.execute("""
        CREATE OR REPLACE TABLE dim_priority_map (
            code VARCHAR PRIMARY KEY, assumed_meaning VARCHAR, source VARCHAR,
            confirmed_by_owner BOOLEAN, owner VARCHAR
        )
    """)
    con.executemany("INSERT INTO dim_priority_map VALUES (?, ?, ?, ?, ?)", rows)
    n_confirmed = sum(1 for r in rows if r[3])
    logger.info("[transform/dim_priority_map] %d rows (%d confirmed_by_owner)", len(rows), n_confirmed)
    return len(rows)


def run_transform(con: duckdb.DuckDBPyConnection, logger) -> None:
    """Load dim_priority_map, then run every SQL model in pipeline/transform/ in filename order (010_, 020_, ...)."""
    load_priority_map(con, logger)
    for sql_file in sorted(TRANSFORM_DIR.glob("*.sql")):
        sql = sql_file.read_text(encoding="utf-8")
        con.execute(sql)
        row_count = con.execute(f"SELECT COUNT(*) FROM {sql_file.stem.split('_', 1)[1]}").fetchone()[0]
        logger.info("[transform/%s] %d rows", sql_file.stem, row_count)


def calls_glob_for_run(run_ts: str) -> str:
    """Glob for every raw calls page written by one extract run."""
    return str(RAW_DATA_DIR / "calls" / f"run_ts={run_ts}" / "*" / "page_*.json")


def scorecard_glob_for_run(run_ts: str) -> str:
    """Glob for every raw scorecard page written by one extract run."""
    return str(RAW_DATA_DIR / "scorecard" / f"run_ts={run_ts}" / "page_*.json")


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load raw data into DuckDB and run the SQL models.")
    parser.add_argument("--calls-run-ts", required=True, help="run_ts under data/raw/calls/ to load")
    parser.add_argument("--scorecard-run-ts", required=True, help="run_ts under data/raw/scorecard/ to load")
    return parser.parse_args()


def main() -> None:
    """CLI: load one calls run + one scorecard run into the warehouse and rebuild the models."""
    args = _cli()
    logger = get_logger(f"load_{args.calls_run_ts}")
    con = get_connection()
    upsert_calls(con, calls_glob_for_run(args.calls_run_ts), logger)
    load_scorecard(con, scorecard_glob_for_run(args.scorecard_run_ts), logger)
    run_transform(con, logger)
    con.close()
    logger.info("[load] done. warehouse: %s", DB_PATH)


if __name__ == "__main__":
    main()
