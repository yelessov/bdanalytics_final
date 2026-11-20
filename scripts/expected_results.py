#!/usr/bin/env python3
"""
Compute the same results as drill/queries.sql directly from ucr_monthly.csv
with pandas. Used to cross-check what Drill returns from HBase.

    python3 scripts/expected_results.py ucr_data/ucr_monthly.csv
"""
import sys

import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)

d = pd.read_csv(sys.argv[1] if len(sys.argv) > 1 else "ucr_data/ucr_monthly.csv",
                dtype={"month": str, "division": str})
d["mon"] = d.month.astype(int)


def pct(a, b):
    return (100.0 * a / b).round(1)


print("\n== Q1  agency types, 2024")
q = d[(d.year == 2024) & d.agency_type.isin(["City", "University", "County", "State Police"])]
g = q.groupby("agency_type").agg(agencies=("ori", "nunique"), violent=("a_violent_total", "sum"),
                                 property=("a_property_total", "sum"), larceny=("a_larceny", "sum"),
                                 burglary=("a_burglary", "sum"), c_violent=("c_violent_total", "sum"),
                                 c_property=("c_property_total", "sum"))
g["violent_share_pct"] = pct(g.violent, g.violent + g.property)
g["larceny_share_of_property_pct"] = pct(g.larceny, g.property)
g["burglary_share_of_property_pct"] = pct(g.burglary, g.property)
g["violent_cleared_pct"] = pct(g.c_violent, g.violent)
g["property_cleared_pct"] = pct(g.c_property, g.property)
print(g.drop(columns=["larceny", "burglary", "c_violent", "c_property"]).sort_values("violent", ascending=False))

panel = d.groupby("ori").size()
panel = set(panel[panel == 24].index)
p = d[d.ori.isin(panel)]

print(f"\n== Q2  YoY violent by state (panel of {len(panel)} agencies reporting 24/24 months)")
s = p.pivot_table(index="state", columns="year", values="a_violent_total", aggfunc="sum", fill_value=0)
s.columns = ["violent_2023", "violent_2024"]
s = s[s.violent_2023 >= 1000]
s["pct_change"] = pct(s.violent_2024 - s.violent_2023, s.violent_2023)
s = s.sort_values("pct_change")
print(s.head(10)); print("..."); print(s.tail(5))
tot = p.groupby("year").a_violent_total.sum()
print("panel total:", dict(tot), "change %.1f%%" % (100 * (tot[2024] - tot[2023]) / tot[2023]))

print("\n== Q3  top university departments by property crime, 2024")
u = d[(d.year == 2024) & (d.agency_type == "University")]
t = u.groupby(["agency_name", "state"]).agg(property=("a_property_total", "sum"), burglary=("a_burglary", "sum"),
                                            larceny=("a_larceny", "sum"), violent=("a_violent_total", "sum"),
                                            c_property=("c_property_total", "sum"))
t["property_cleared_pct"] = pct(t.c_property, t.property)
print(t.drop(columns="c_property").sort_values("property", ascending=False).head(10))

print("\n== Q4  seasonality (panel)")
m = p.pivot_table(index="mon", columns="year", values=["a_violent_total", "a_murder"], aggfunc="sum")
print(m)

print("\n== Q5  murder clearance, cities 250k+, 2024 (>=100 murders)")
b = d[(d.year == 2024) & (d.pop_bucket == "250k+")]
b = b.groupby(["agency_name", "state"]).agg(murders=("a_murder", "sum"), cleared=("c_murder", "sum"))
b = b[b.murders >= 100]
b["murder_cleared_pct"] = pct(b.cleared, b.murders)
print(b.sort_values("murders", ascending=False).head(15))

print("\n== Q6  TX monthly (row-key prefix 'TX#')")
tx = d[d.state == "TX"].groupby(["year", "mon"]).agg(agencies=("ori", "size"), violent=("a_violent_total", "sum"))
print(tx.head(6)); print(f"... {len(tx)} rows")
