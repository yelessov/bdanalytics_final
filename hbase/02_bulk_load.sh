#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 02_bulk_load.sh  - real bulk load: ImportTsv writes HFiles, completebulkload
# hands them to the RegionServer (no Put/WAL path).  Runs inside `hmaster`:
#     docker exec ucr-hmaster bash /hbase-scripts/02_bulk_load.sh
# ---------------------------------------------------------------------------
set -euo pipefail
SRC=/data/ucr/hbase
# all cells get this timestamp (2025-01-01T00:00:00Z) so that the "revision"
# puts in 04_versions_demo.hbase are clearly newer versions
TS=1735689600000

echo "== 1. copy TSVs into HDFS"
hdfs dfs -mkdir -p /ucr/input/main /ucr/input/idx
hdfs dfs -put -f $SRC/ucr_crime_monthly.tsv /ucr/input/main/
hdfs dfs -put -f $SRC/ucr_idx_type_year.tsv /ucr/input/idx/
hdfs dfs -ls -h /ucr/input/main /ucr/input/idx
hdfs dfs -rm -r -f -skipTrash /ucr/hfiles

bulk() {   # table  input_dir  columns_file
  local table=$1 input=$2 cols
  cols=$(cat "$3")
  echo "== 2. ImportTsv -> HFiles for $table"
  local t0=$(date +%s)
  hbase org.apache.hadoop.hbase.mapreduce.ImportTsv \
      -Dimporttsv.columns="$cols" \
      -Dimporttsv.timestamp=$TS \
      -Dimporttsv.bulk.output=/ucr/hfiles/$table \
      "$table" "$input"
  echo "== 3. completebulkload $table"
  hbase completebulkload /ucr/hfiles/$table "$table"
  echo "== $table loaded in $(( $(date +%s) - t0 ))s"
}

bulk ucr_crime_monthly /ucr/input/main $SRC/importtsv_columns_main.txt
bulk ucr_idx_type_year /ucr/input/idx  $SRC/importtsv_columns_idx.txt

echo "== 4. row counts"
echo "count 'ucr_crime_monthly', INTERVAL => 100000, CACHE => 10000" | hbase shell -n
echo "count 'ucr_idx_type_year', INTERVAL => 100000, CACHE => 10000" | hbase shell -n
hdfs dfs -du -h /hbase/data/default
