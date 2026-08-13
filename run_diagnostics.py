"""
run_diagnostics.py
==================
Audits an input workbook against the expected-table registry and writes the
"meta output" report (Summary + Table checks) to Excel.

Usage:
    python run_diagnostics.py INPUT.xlsx  IRA_Input_Diagnostics.xlsx
"""

import os
import sys
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, "IRA")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from IRA import ira_diagnostics as D, ira_io as IO
except ImportError:
    try:
        import ira_diagnostics as D, ira_io as IO
    except ImportError as ex:
        sys.exit(
            "ERROR: could not import the IRA modules (%s).\n"
            "Put an 'IRA' folder (or the loose ira_*.py files) next to this "
            "script.\nThis script is at: %s\nSeen here: %s" % (
                ex, _HERE, ", ".join(sorted(os.listdir(_HERE)))))


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "Dummy.xlsx"
    out = sys.argv[2] if len(sys.argv) > 2 else "IRA_Input_Diagnostics.xlsx"

    sheets = IO.read_workbook(inp)          # forces cached formula values

    records, summary = D.audit(sheets)
    D.print_summary(records, summary)
    D.write_report(records, summary, out)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
