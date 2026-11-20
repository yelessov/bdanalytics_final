#!/usr/bin/env python3
"""
Register the HBase storage plugin in Drill and run drill/queries.sql through
Drill's REST API. Prints every result as a table and saves it to output/.
Standard library only.

    python3 scripts/run_drill_queries.py [--drill http://localhost:8047]
"""
import argparse
import csv
import re
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def post(url, payload, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def statements(path):
    buf, out = [], []
    for line in open(path):
        if line.strip() == ";":
            sql = "\n".join(l for l in buf if not l.strip().startswith("--")).strip()
            title = next((l.strip("- ").strip() for l in buf if re.match(r"--\s*[QV]\d+\.", l.strip())), "")
            if sql:
                out.append((title, sql))
            buf = []
        else:
            buf.append(line.rstrip("\n"))
    return out


def show(cols, rows, limit=40):
    w = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows[:limit])) if rows else len(c) for c in cols}
    print(" | ".join(c.ljust(w[c]) for c in cols))
    print("-+-".join("-" * w[c] for c in cols))
    for r in rows[:limit]:
        print(" | ".join(str(r.get(c, "")).ljust(w[c]) for c in cols))
    if len(rows) > limit:
        print(f"... {len(rows) - limit} more rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drill", default="http://localhost:8047")
    ap.add_argument("--sql", default=os.path.join(ROOT, "drill", "queries.sql"))
    args = ap.parse_args()
    os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)

    # 1. wait for Drill, then register / update the hbase storage plugin
    for _ in range(60):
        try:
            urllib.request.urlopen(args.drill + "/status", timeout=5)
            break
        except Exception:
            print("waiting for Drill ...")
            time.sleep(5)
    plugin = json.load(open(os.path.join(ROOT, "drill", "storage-hbase.json")))
    print("storage plugin:", post(f"{args.drill}/storage/hbase.json", plugin))
    for opt in ("ALTER SYSTEM SET `planner.width.max_per_node` = 2",):
        print(opt, "->", post(f"{args.drill}/query.json", {"queryType": "SQL", "query": opt}).get("rows"))

    # 2. run each statement
    for i, (title, sql) in enumerate(statements(args.sql)):
        print("\n" + "=" * 100 + f"\n{title}\n" + "=" * 100)
        t0 = time.time()
        try:
            try:
                res = post(f"{args.drill}/query.json", {"queryType": "SQL", "query": sql})
            except (ConnectionError, urllib.error.URLError) as e:
                if isinstance(e, urllib.error.HTTPError):
                    raise
                print(f"Drill dropped the connection ({e}); waiting for it, then retrying once")
                for _ in range(36):
                    time.sleep(5)
                    try:
                        urllib.request.urlopen(args.drill + "/status", timeout=5)
                        break
                    except Exception:
                        pass
                time.sleep(10)
                post(f"{args.drill}/storage/hbase.json", plugin)
                res = post(f"{args.drill}/query.json", {"queryType": "SQL", "query": sql})
        except urllib.error.HTTPError as e:
            print("ERROR:", e.read().decode()[:2000])
            continue
        except Exception as e:   # Drill restarted (usually out of memory)
            print(f"ERROR: Drill dropped the connection ({e}); waiting for it to come back")
            for _ in range(36):
                time.sleep(5)
                try:
                    urllib.request.urlopen(args.drill + "/status", timeout=5)
                    post(f"{args.drill}/storage/hbase.json", plugin)
                    break
                except Exception:
                    pass
            continue
        if res.get("errorMessage") or res.get("queryState") == "FAILED":
            print("DRILL ERROR:", (res.get("errorMessage") or str(res))[:1500])
            continue
        cols, rows = res.get("columns", []), res.get("rows", [])
        show(cols, rows)
        print(f"({len(rows)} rows, {time.time() - t0:.1f}s)")
        name = re.sub(r"[^A-Za-z0-9_-]", "_", title.split(".")[0].strip()) or f"stmt{i}"
        with open(os.path.join(ROOT, "output", f"drill_{name}.csv"), "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=cols)
            wr.writeheader()
            wr.writerows(rows)


if __name__ == "__main__":
    main()
