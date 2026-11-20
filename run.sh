#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-command pipeline for the UCR / HBase project (run from the project root)
#
#   ./run.sh prepare    parse FBI master files -> CSV -> HBase TSVs   (Python 3, no deps)
#   ./run.sh up         build image + start HDFS, ZooKeeper, HBase, Drill
#   ./run.sh create     create the pre-split HBase tables
#   ./run.sh load       ImportTsv bulk load (HFiles) + completebulkload
#   ./run.sh demo       HBase shell demos  -> output/hbase_demo.txt
#   ./run.sh versions   multi-version demo -> output/hbase_versions.txt
#   ./run.sh drill      Drill SQL queries  -> output/drill_*.csv
#   ./run.sh expected   pandas cross-check of the Drill results
#   ./run.sh all        everything above in order
#   ./run.sh down       stop the cluster (data kept in Docker volumes)
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p output
PY=${PY:-python3}

prepare() {
  $PY scripts/parse_return_a.py ucr_data/raw/reta-2023.txt ucr_data/raw/reta-2024.txt \
      -o ucr_data/ucr_monthly.csv
  $PY scripts/make_hbase_tsv.py ucr_data/ucr_monthly.csv ucr_data/hbase
}
up() {
  docker compose build
  docker compose up -d
  echo "waiting for HBase master + regionserver ..."
  until docker exec ucr-hmaster bash -c "echo status | hbase shell -n 2>/dev/null | grep -q '1 active master.*1 servers'"; do
    sleep 5; printf "."
  done
  echo; docker compose ps
}
create()   { docker exec ucr-hmaster hbase shell -n /hbase-scripts/01_create_tables.hbase; }
load()     { docker exec ucr-hmaster bash /hbase-scripts/02_bulk_load.sh 2>&1 | tee output/bulk_load.log; }
demo()     { docker exec ucr-hmaster hbase shell /hbase-scripts/03_demo_queries.hbase 2>&1 | tee output/hbase_demo.txt; }
versions() { docker exec ucr-hmaster hbase shell /hbase-scripts/04_versions_demo.hbase 2>&1 | tee output/hbase_versions.txt; }
drill()    { $PY scripts/run_drill_queries.py 2>&1 | tee output/drill_results.txt; }
expected() { $PY scripts/expected_results.py ucr_data/ucr_monthly.csv | tee output/expected_results.txt; }
down()     { docker compose down; }

case "${1:-}" in
  prepare|up|create|load|demo|versions|drill|expected|down) "$1" ;;
  all) prepare; up; create; load; demo; versions; drill; expected ;;
  *) sed -n '2,17p' "$0"; exit 1 ;;
esac
