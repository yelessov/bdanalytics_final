#!/usr/bin/env python3
"""
Parse the FBI UCR "Return A" annual master file (fixed-width, 7385 chars/record)
into a monthly, HBase-ready CSV whose first column is the composite RowKey

        STATE#ORI#YEAR#MM        e.g.  CA#CA01942#2024#01

Source: FBI Crime Data Explorer -> Documents & Downloads -> Master File Downloads
        -> Return A -> <year>   (file reta-<year>.zip, record layout in reta-help.zip)

One input record = one agency-year with 12 monthly blocks (590 chars each).
We emit one output row per agency-month that contains a normal return
(Card 1 type == '5'), i.e. months the agency actually reported.

Usage:  python3 parse_return_a.py reta-2023.txt reta-2024.txt -o ucr_data/ucr_monthly.csv
"""
import argparse
import csv
import sys

# ---------------------------------------------------------------- record layout
# 1-based inclusive positions from "Ret A Rec Descrip.pdf"
HDR = {
    "state_code": (2, 3), "ori": (4, 10), "group": (11, 12), "division": (13, 13),
    "year2": (14, 15), "core_city": (23, 23), "covered_by": (24, 30),
    "months_reported": (42, 43), "pop1": (45, 53), "county1": (54, 56),
    "pop2": (60, 68), "pop3": (75, 83), "city_name": (121, 144),
    "state_name": (145, 150), "agency_name": (151, 180),
}
MONTH_START = 306          # January block starts here
MONTH_LEN = 590
# offsets (relative to the start of a month block, 0-based) of the 4 "cards"
CARD_OFF = {"unfounded": 323 - 306, "actual": 463 - 306,
            "cleared": 603 - 306, "cleared_u18": 743 - 306}
CARD1_TYPE_OFF = 315 - 306     # '5' = normal return
UPDATE_OFF = 308 - 306         # MMDDYY of last update of this month block

# the 28 five-digit fields inside a card (we keep the ones we need)
FIELDS = {
    "murder": 1, "manslaughter": 2, "rape": 3, "robbery": 6, "robbery_gun": 7,
    "assault_total": 11, "assault_gun": 12, "simple_assault": 16,
    "burglary": 17, "burglary_forcible": 18, "larceny": 21, "mvt": 22,
    "grand_total": 26,
}

STATE_ABBR = {  # numeric state code -> postal abbreviation (layout p. I.1-I.2)
    "50": "AK", "01": "AL", "03": "AR", "54": "AS", "02": "AZ", "04": "CA", "05": "CO",
    "06": "CT", "52": "CZ", "08": "DC", "07": "DE", "09": "FL", "10": "GA", "55": "GM",
    "51": "HI", "14": "IA", "11": "ID", "12": "IL", "13": "IN", "15": "KS", "16": "KY",
    "17": "LA", "20": "MA", "19": "MD", "18": "ME", "21": "MI", "22": "MN", "24": "MO",
    "23": "MS", "25": "MT", "26": "NE", "32": "NC", "33": "ND", "28": "NH", "29": "NJ",
    "30": "NM", "27": "NV", "31": "NY", "34": "OH", "35": "OK", "36": "OR", "37": "PA",
    "53": "PR", "38": "RI", "39": "SC", "40": "SD", "41": "TN", "42": "TX", "43": "UT",
    "62": "VI", "45": "VA", "44": "VT", "46": "WA", "48": "WI", "47": "WV", "49": "WY",
}

# negative "overpunch" encoding in the last digit (reta-help: Ret A negative entries.pdf)
NEG = {"}": 0, "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "O": 6, "P": 7, "Q": 8, "R": 9}
POS = {"{": 0, "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8, "I": 9}


def num(s: str) -> int:
    s = s.strip()
    if not s:
        return 0
    last = s[-1]
    if last in NEG:
        return -int((s[:-1] or "0") + str(NEG[last]))
    if last in POS:
        return int((s[:-1] or "0") + str(POS[last]))
    return int(s)


def hdr(rec, key):
    s, e = HDR[key]
    return rec[s - 1:e]


def agency_type(group: str, ori: str, name: str, city: str, pop: int = 0) -> str:
    """Return A has no explicit agency-type field; derive it from the population
    group (layout p. I.2) plus the agency name. Documented heuristic."""
    text = f"{name} {city}".upper()
    # campus police: university/college keyword AND no resident population
    # (excludes towns such as College Station, University Park, Universal City)
    if pop == 0 and any(w in text for w in ("UNIVERSITY", "UNIV ", "UNIV:", "UNIV.", "COLLEGE", "INSTITUTE OF TECH", "SCHOOL OF MEDICINE")):
        return "University"
    if any(w in text for w in ("TRIBAL", "TRIBE", "PUEBLO", "RESERVATION")):
        return "Tribal"
    if ori.endswith("SP") or group.strip() in ("8E", "9E") or "STATE POLICE" in text or "HIGHWAY PATROL" in text:
        return "State Police"
    g = group.strip()[:1]
    if g in ("8", "9"):
        return "County"
    if g in "1234567" and g:
        return "City"
    if g == "0":
        return "Possession"
    return "Other"


def pop_bucket(group: str) -> str:
    return {"1": "250k+", "2": "100k-250k", "3": "50k-100k", "4": "25k-50k",
            "5": "10k-25k", "6": "2.5k-10k", "7": "<2.5k", "8": "Non-MSA county",
            "9": "MSA county", "0": "Possession"}.get(group.strip()[:1], "Unknown")


OUT_COLS = (["rowkey", "state", "ori", "year", "month", "agency_name", "city_name",
             "agency_type", "pop_group", "pop_bucket", "population", "division",
             "core_city", "last_update"]
            + [f"a_{k}" for k in FIELDS] + ["a_agg_assault", "a_violent_total", "a_property_total"]
            + [f"c_{k}" for k in FIELDS] + ["c_agg_assault", "c_violent_total", "c_property_total"]
            + ["u18_violent_total", "unfounded_total"])


def parse(path, writer, stats):
    seen = {}   # 7-char ORI -> times seen in this file (a few ORIs are shared)
    with open(path, encoding="latin-1") as fh:
        for rec in fh:
            rec = rec.rstrip("\r\n")
            if len(rec) < 7385 or rec[0] != "1":
                stats["bad"] += 1
                continue
            st = STATE_ABBR.get(hdr(rec, "state_code"), "XX")
            ori = hdr(rec, "ori").strip()
            seen[ori] = seen.get(ori, 0) + 1
            if seen[ori] > 1:                       # e.g. AL04901 police dept + AL04901 DA office
                ori = f"{ori}{chr(ord('A') + seen[ori] - 1)}"   # -> AL04901B
                stats["ori_suffixed"] = stats.get("ori_suffixed", 0) + 1
            year = 2000 + int(hdr(rec, "year2"))
            grp = hdr(rec, "group")
            city = hdr(rec, "city_name").strip()
            name = hdr(rec, "agency_name").strip() or city
            pop = num(hdr(rec, "pop1")) + num(hdr(rec, "pop2")) + num(hdr(rec, "pop3"))
            atype = agency_type(grp, ori, name, city, pop)
            for m in range(12):
                b = MONTH_START - 1 + m * MONTH_LEN          # 0-based block start
                blk = rec[b:b + MONTH_LEN]
                if blk[CARD1_TYPE_OFF] != "5":
                    continue
                vals = {}
                for card, off in CARD_OFF.items():
                    for fname, idx in FIELDS.items():
                        p = off + (idx - 1) * 5
                        vals[(card, fname)] = num(blk[p:p + 5])
                # field 11 "Assault Total" INCLUDES simple assault (field 16);
                # aggravated assault (a Part I violent crime) = 11 - 16
                for card in CARD_OFF:
                    vals[(card, "agg_assault")] = vals[(card, "assault_total")] - vals[(card, "simple_assault")]
                a = lambda k: vals[("actual", k)]
                c = lambda k: vals[("cleared", k)]
                u = lambda k: vals[("cleared_u18", k)]
                viol = lambda f: f("murder") + f("rape") + f("robbery") + f("agg_assault")
                prop = lambda f: f("burglary") + f("larceny") + f("mvt")
                mm = f"{m + 1:02d}"
                row = ([f"{st}#{ori}#{year}#{mm}", st, ori, year, mm, name, city, atype,
                        grp.strip(), pop_bucket(grp), pop, hdr(rec, "division"),
                        hdr(rec, "core_city").strip(), blk[UPDATE_OFF:UPDATE_OFF + 6]]
                       + [a(k) for k in FIELDS] + [a("agg_assault"), viol(a), prop(a)]
                       + [c(k) for k in FIELDS] + [c("agg_assault"), viol(c), prop(c)]
                       + [viol(u), vals[("unfounded", "grand_total")]])
                writer.writerow(row)
                stats["rows"] += 1
                stats[atype] = stats.get(atype, 0) + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()
    stats = {"rows": 0, "bad": 0}
    with open(args.out, "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(OUT_COLS)
        for p in args.inputs:
            parse(p, w, stats)
    print(stats, file=sys.stderr)


if __name__ == "__main__":
    main()
