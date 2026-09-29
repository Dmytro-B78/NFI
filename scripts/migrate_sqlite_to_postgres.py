#!/usr/bin/env python3
"""
Migrate a freqtrade SQLite trades database to PostgreSQL.

Usage:
    python migrate_sqlite_to_postgres.py <sqlite_db_url> <postgres_db_url>

Example:
    python migrate_sqlite_to_postgres.py \
        "sqlite:////home/ubuntu/NFI/user_data/tradesv3.sqlite" \
        "postgresql+psycopg://nfi:PASSWORD@localhost:5432/nfi"

What it does:
    1. Creates the schema in the target Postgres DB using freqtrade's own
       init_db() (guarantees identical schema to what the bot expects).
    2. Copies every row from every source table into the matching Postgres
       table, preserving primary keys (trade IDs, order IDs stay the same).
    3. Resets Postgres auto-increment sequences to continue after the
       highest migrated id, so new trades don't collide with old ones.
    4. Verifies row counts match between source and target for every table.

Safe to re-run against an empty target database. Refuses to run if the
target tables already contain rows (use --force to override).
"""

import sys
import argparse

from sqlalchemy import create_engine, text, MetaData


def get_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sqlite_url", help="Source sqlite db_url, e.g. sqlite:////path/tradesv3.sqlite")
    p.add_argument("postgres_url", help="Target postgres db_url, e.g. postgresql+psycopg://user:pass@host/db")
    p.add_argument("--force", action="store_true", help="Proceed even if target tables are non-empty")
    return p.parse_args()


def main():
    args = get_args()

    # Import here so the script fails fast on bad args before pulling in freqtrade.
    from freqtrade.persistence import init_db

    print(f"[1/5] Creating schema in target Postgres DB via freqtrade.init_db() ...")
    init_db(args.postgres_url)

    src_engine = create_engine(args.sqlite_url)
    dst_engine = create_engine(args.postgres_url)

    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)

    dst_meta = MetaData()
    dst_meta.reflect(bind=dst_engine)

    # Copy in FK-dependency order (parents before children), not dict/alpha order.
    ordered_src_tables = [t.name for t in src_meta.sorted_tables]
    table_names = [t for t in ordered_src_tables if t in dst_meta.tables]
    skipped = [t for t in ordered_src_tables if t not in dst_meta.tables]
    if skipped:
        print(f"    NOTE: source tables with no match in target schema, skipped: {skipped}")

    print(f"[2/5] Checking target is empty ...")
    if not args.force:
        with dst_engine.connect() as conn:
            for name in table_names:
                dst_table = dst_meta.tables[name]
                count = conn.execute(dst_table.select().limit(1)).fetchone()
                if count is not None:
                    print(f"    ERROR: target table '{name}' already has rows. "
                          f"Re-run with --force to migrate anyway (will duplicate/conflict).")
                    sys.exit(1)

    print(f"[3/5] Copying {len(table_names)} tables: {table_names}")
    row_counts = {}
    with src_engine.connect() as src_conn, dst_engine.begin() as dst_conn:
        for name in table_names:
            src_table = src_meta.tables[name]
            dst_table = dst_meta.tables[name]
            rows = [dict(row._mapping) for row in src_conn.execute(src_table.select())]
            row_counts[name] = len(rows)
            if rows:
                dst_conn.execute(dst_table.insert(), rows)
            print(f"    {name}: {len(rows)} rows copied")

    print(f"[4/5] Resetting Postgres sequences to continue after migrated ids ...")
    with dst_engine.begin() as conn:
        for name in table_names:
            dst_table = dst_meta.tables[name]
            pk_cols = [c for c in dst_table.primary_key.columns]
            if len(pk_cols) != 1:
                continue
            pk_name = pk_cols[0].name
            seq_name = f"{name}_{pk_name}_seq"
            exists = conn.execute(text("SELECT to_regclass(:seq)"), {"seq": seq_name}).scalar()
            if exists is None:
                continue
            conn.execute(text(
                f"SELECT setval(:seq, COALESCE((SELECT MAX({pk_name}) FROM {name}), 0) + 1, false)"
            ), {"seq": seq_name})

    print(f"[5/5] Verifying row counts ...")
    ok = True
    with dst_engine.connect() as conn:
        for name in table_names:
            dst_table = dst_meta.tables[name]
            dst_count = conn.execute(dst_table.select()).fetchall()
            expected = row_counts[name]
            actual = len(dst_count)
            status = "OK" if actual == expected else "MISMATCH"
            if actual != expected:
                ok = False
            print(f"    {name}: source={expected} target={actual} [{status}]")

    if not ok:
        print("MIGRATION FINISHED WITH MISMATCHES -- do not switch config.json yet.")
        sys.exit(1)
    print("MIGRATION OK -- all row counts match.")


if __name__ == "__main__":
    main()
