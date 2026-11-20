#!/usr/bin/env python3
"""
Alternative loader: Python + happybase through the HBase Thrift server
(container `thrift`, port 9090). Unlike ImportTsv this goes through the normal
write path (Put -> WAL -> MemStore), so it is useful as a speed comparison.

Loads into a separate table (ucr_crime_monthly_thrift) so the bulk-loaded table
stays untouched.

    pip install happybase
    python3 load_ucr_data.py                 # all ~304k rows
    python3 load_ucr_data.py --limit 50000   # quicker run
"""
import argparse
import time

import happybase

TSV = "ucr_data/hbase/ucr_crime_monthly.tsv"
COLS = "ucr_data/hbase/importtsv_columns_main.txt"
TABLE = "ucr_crime_monthly_thrift"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=2000)
    args = ap.parse_args()

    cols = open(COLS).read().strip().split(",")[1:]          # drop HBASE_ROW_KEY
    conn = happybase.Connection(args.host, port=9090, timeout=120000)
    if TABLE.encode() in conn.tables():
        conn.delete_table(TABLE, disable=True)
    conn.create_table(TABLE, {"agency": dict(max_versions=1), "violent": dict(max_versions=3),
                              "property": dict(max_versions=3), "clearances": dict(max_versions=3)})
    table = conn.table(TABLE)

    t0, n = time.time(), 0
    with table.batch(batch_size=args.batch) as b, open(TSV) as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            b.put(f[0].encode(), {c.encode(): v.encode() for c, v in zip(cols, f[1:])})
            n += 1
            if n % 50000 == 0:
                print(f"{n:,} rows  {n / (time.time() - t0):,.0f} rows/s")
            if args.limit and n >= args.limit:
                break
    dt = time.time() - t0
    print(f"loaded {n:,} rows into {TABLE} in {dt:.1f}s ({n / dt:,.0f} rows/s)")
    print("sample:", table.row(f[0].encode(), columns=[b"agency:name", b"violent:total"]))
    conn.close()


if __name__ == "__main__":
    main()
