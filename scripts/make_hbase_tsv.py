#!/usr/bin/env python3
"""
Turn ucr_monthly.csv (output of parse_return_a.py) into the two TSV files that
HBase's ImportTsv bulk loader reads (no header, RowKey in column 1):

  ucr_data/hbase/ucr_crime_monthly.tsv   main table   key = STATE#ORI#YEAR#MM
  ucr_data/hbase/ucr_idx_type_year.tsv   index table  key = TYPE#YEAR#STATE#ORI#MM

All counts are written as ZERO-PADDED 6-character strings (e.g. 14 -> "000014").
HBase stores bytes and SingleColumnValueFilter compares bytes lexicographically,
so without padding "9" > "100".  Padding makes byte order == numeric order.

It also prints balanced pre-split points for the main table (by state prefix).
"""
import csv
import os
import sys

W = 6           # width for counts
WPOP = 9        # width for population

# HBase column  <-  CSV column        (family:qualifier)
MAIN_COLS = [
    ("agency:name", "agency_name"), ("agency:city", "city_name"), ("agency:type", "agency_type"),
    ("agency:state", "state"), ("agency:ori", "ori"), ("agency:year", "year"), ("agency:month", "month"),
    ("agency:pop_group", "pop_group"), ("agency:pop_bucket", "pop_bucket"),
    ("agency:population", "population"), ("agency:division", "division"),
    ("agency:core_city", "core_city"), ("agency:last_update", "last_update"),
    ("violent:murder", "a_murder"), ("violent:manslaughter", "a_manslaughter"),
    ("violent:rape", "a_rape"), ("violent:robbery", "a_robbery"), ("violent:robbery_gun", "a_robbery_gun"),
    ("violent:agg_assault", "a_agg_assault"), ("violent:assault_gun", "a_assault_gun"),
    ("violent:simple_assault", "a_simple_assault"), ("violent:total", "a_violent_total"),
    ("property:burglary", "a_burglary"), ("property:burglary_forcible", "a_burglary_forcible"),
    ("property:larceny", "a_larceny"), ("property:mvt", "a_mvt"), ("property:total", "a_property_total"),
    ("clearances:murder", "c_murder"), ("clearances:rape", "c_rape"), ("clearances:robbery", "c_robbery"),
    ("clearances:agg_assault", "c_agg_assault"), ("clearances:burglary", "c_burglary"),
    ("clearances:larceny", "c_larceny"), ("clearances:mvt", "c_mvt"),
    ("clearances:violent_total", "c_violent_total"), ("clearances:property_total", "c_property_total"),
    ("clearances:u18_violent_total", "u18_violent_total"),
]
IDX_COLS = [
    ("ref:main_key", "rowkey"), ("ref:name", "agency_name"), ("ref:violent_total", "a_violent_total"),
    ("ref:property_total", "a_property_total"), ("ref:burglary", "a_burglary"),
]
TEXT = {"agency_name", "city_name", "agency_type", "state", "ori", "year", "month", "pop_group",
        "pop_bucket", "division", "core_city", "last_update", "rowkey"}


def fmt(col, v):
    if col in TEXT:
        return v.replace("\t", " ")
    n = int(v)
    width = WPOP if col == "population" else W
    return f"{n:0{width}d}"          # negatives (rare adjustments) become e.g. -00003


def main(src, outdir):
    os.makedirs(outdir, exist_ok=True)
    main_path = os.path.join(outdir, "ucr_crime_monthly.tsv")
    idx_path = os.path.join(outdir, "ucr_idx_type_year.tsv")
    keys = []
    with open(src, newline="") as fh, open(main_path, "w") as m, open(idx_path, "w") as ix:
        for r in csv.DictReader(fh):
            keys.append(r["rowkey"])
            m.write("\t".join([r["rowkey"]] + [fmt(c, r[c]) for _, c in MAIN_COLS]) + "\n")
            ikey = f'{r["agency_type"].replace(" ", "_")}#{r["year"]}#{r["state"]}#{r["ori"]}#{r["month"]}'
            ix.write("\t".join([ikey] + [fmt(c, r[c]) for _, c in IDX_COLS]) + "\n")
    # ImportTsv column spec strings
    with open(os.path.join(outdir, "importtsv_columns_main.txt"), "w") as f:
        f.write(",".join(["HBASE_ROW_KEY"] + [h for h, _ in MAIN_COLS]))
    with open(os.path.join(outdir, "importtsv_columns_idx.txt"), "w") as f:
        f.write(",".join(["HBASE_ROW_KEY"] + [h for h, _ in IDX_COLS]))
    # balanced split points on the state prefix (8 regions)
    keys.sort()
    n, parts = len(keys), 8
    splits = []
    for i in range(1, parts):
        st = keys[i * n // parts].split("#")[0]
        if st not in splits:
            splits.append(st)
    print(f"rows={n}  main={main_path}  idx={idx_path}")
    print("SPLITS =>", splits)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "ucr_data/ucr_monthly.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "ucr_data/hbase"
    main(src, out)
