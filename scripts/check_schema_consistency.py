"""Verify that ``db/schema.sql`` and the SQLAlchemy models in ``backend/db.py`` agree.

The DDL is the source of truth for deployments while the ORM is what the API
writes through, so the two drifting apart is a classic source of production
breakage ("column does not exist" at 2am). This script fails loudly instead.

    python scripts/check_schema_consistency.py

Exit code 0 means every ORM column exists in the reviewed DDL. DDL-only columns
are reported as notes: they are intentional (generated columns, database
defaults, audit fields, and the server-managed ``created_at``/``updated_at``).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.db import Base  # noqa: E402

SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
REQUIRED_VIEWS = (
    "v_latest_credit_assessment",
    "v_portfolio_risk_monitor",
    "v_reason_code_frequency",
    "v_underwriting_file",
)
REQUIRED_ENUMS = (
    "applicant_category",
    "region_tier",
    "shop_ownership",
    "crop_type",
    "risk_tier",
    "underwriting_decision",
)

#: Second token of a column definition must be one of these for the line to be
#: treated as a column (as opposed to a constraint or a comment).
_TYPE_PATTERN = (
    r"(?:BIGINT|SMALLINT|INTEGER|NUMERIC|VARCHAR|TEXT|DATE|TIMESTAMPTZ|BOOLEAN|JSONB"
    r"|applicant_category|region_tier|shop_ownership|crop_type|risk_tier|underwriting_decision)"
)


def ddl_columns(raw_sql: str, table: str) -> set[str]:
    """Column names of ``table`` as written in the DDL."""
    block = re.search(rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);", raw_sql, re.S)
    if not block:
        return set()
    columns = set()
    for line in block.group(1).split("\n"):
        match = re.match(rf"\s*([a-z_][a-z0-9_]*)\s+{_TYPE_PATTERN}\b", line)
        if match:
            columns.add(match.group(1))
    return columns


def main() -> int:
    if not SCHEMA_PATH.exists():
        print(f"[FAIL] {SCHEMA_PATH} not found", file=sys.stderr)
        return 1

    raw_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    problems: list[str] = []
    notes: list[str] = []

    for mapper in Base.registry.mappers:
        table = mapper.local_table.name
        ddl = ddl_columns(raw_sql, table)
        if not ddl:
            problems.append(f"{table}: no CREATE TABLE IF NOT EXISTS block in schema.sql")
            continue
        orm = {column.name for column in mapper.local_table.columns}
        if orm - ddl:
            problems.append(f"{table}: ORM column(s) absent from the DDL -> {sorted(orm - ddl)}")
        if ddl - orm:
            notes.append(f"{table}: DDL-only column(s) -> {sorted(ddl - orm)}")
        print(f"  {table:24} DDL={len(ddl):2d} column(s)  ORM={len(orm):2d} column(s)")

    problems += [f"view {view} is missing" for view in REQUIRED_VIEWS
                 if f"CREATE OR REPLACE VIEW {view}" not in raw_sql]
    problems += [f"enum type {enum} is not declared" for enum in REQUIRED_ENUMS
                 if f"typname = '{enum}'" not in raw_sql]
    if "BEGIN;" not in raw_sql or "COMMIT;" not in raw_sql:
        problems.append("schema.sql is not wrapped in a transaction")

    if notes:
        print("\nIntentional DDL-only columns:")
        for note in notes:
            print(f"  - {note}")

    if problems:
        print("\n[FAIL] schema drift detected:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"\n[OK] {len(Base.registry.mappers)} tables, {len(REQUIRED_VIEWS)} views and "
          f"{len(REQUIRED_ENUMS)} enum types agree between db/schema.sql and backend/db.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
