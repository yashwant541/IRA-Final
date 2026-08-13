"""
run_detect.py
=============
Reads an input workbook and writes IRA_Detection_Report.xlsx:
  * "Detection Summary" - one row per detected table (Detected Yes/NO, shape,
    #months, month range, #countries, #products, notes)
  * one sheet per detected table - the simplified, cleaned data (Mar-YY headers,
    normalised product names)

Run this FIRST to confirm every table is being read correctly.

Usage:
    python run_detect.py INPUT.xlsx  IRA_Detection_Report.xlsx
"""

import os
import sys
import pandas as pd

# make imports work from anywhere (package folder or loose modules)
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "IRA")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from IRA import ira_detect as DET
except ImportError:
    try:
        import ira_detect as DET
    except ImportError as ex:
        sys.exit(
            "ERROR: could not import the IRA modules (%s).\n"
            "Put an 'IRA' folder (or the loose ira_*.py files) next to this "
            "script.\nThis script is at: %s\nSeen here: %s" % (
                ex, _HERE, ", ".join(sorted(os.listdir(_HERE)))))


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "Dummy.xlsx"
    out = sys.argv[2] if len(sys.argv) > 2 else "IRA_Detection_Report.xlsx"

    xls = pd.read_excel(inp, sheet_name=None, header=None)
    sheets = {name: df.values.tolist() for name, df in xls.items()}

    records = DET.write_detection_report(sheets, out)

    detected = sum(1 for r in records if r["detected"])
    print(f"Sheets read: {len(sheets)}   Tables detected: {detected}"
          f"   (of {len(records)} candidate tables)")
    print("-" * 70)
    for r in records:
        flag = "OK " if r["detected"] else "NO "
        extra = (f"{r['n_months']}m, {r['n_countries']}c, {r['n_products']}p"
                 if r["detected"] else r["notes"][:50])
        print(f"  [{flag}] {r['shape']:22} {r['title'][:34]:34} {extra}")
    print("-" * 70)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
