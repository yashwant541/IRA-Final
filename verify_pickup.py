"""Prove the final output values match the intermediate tables, cell by cell."""
import os, sys, pandas as pd
_HERE=os.path.dirname(os.path.abspath(__file__))
for p in (_HERE, os.path.join(_HERE,"IRA")):
    if os.path.isdir(p) and p not in sys.path: sys.path.insert(0,p)
try:
    from IRA import ira_loaders as L, ira_build as B, ira_config as C, ira_intermediate as I
except ImportError:
    import ira_loaders as L, ira_build as B, ira_config as C, ira_intermediate as I

inp = sys.argv[1] if len(sys.argv)>1 else "Dummy.xlsx"
xls = pd.read_excel(inp, sheet_name=None, header=None)
sheets = {n: d.values.tolist() for n,d in xls.items()}
# merge reference tables sitting alongside (same rule run_local uses)
import glob
for f in glob.glob(os.path.join(os.path.dirname(os.path.abspath(inp)) or ".","Other_Tables.xlsx")):
    for n,d in pd.read_excel(f,sheet_name=None,header=None).items():
        sheets[f"{os.path.basename(f)}::{n}"]=d.values.tolist()

cfg = "countries_config.csv"
per_cat = None
if os.path.exists(cfg):
    from IRA import ira_countries as CC  # noqa
    per_cat = CC.load(cfg)

tables = L.load_tables(sheets)
resolved = B.resolve_countries(tables, None, per_cat)   # what run_local uses
tables["intermediates"] = I.build(tables, resolved)      # the single source of truth
INT = tables["intermediates"]

# Now, for each category+country+metric, confirm the extractor returns the
# SAME value that sits in the intermediate dict.
mismatches = 0
checked = 0
for cat, defs in C.METRICS.items():
    for country in resolved.get(cat, []):
        for m in defs():
            key = m["value"].int_key
            rec = m["value"](tables, country, cat)          # what the FINAL uses
            direct = INT.get(key,{}).get((country,cat)) or INT.get(key,{}).get((country,None))
            got = rec.get("value")
            exp = (direct or {}).get("value")
            checked += 1
            if got != exp:
                mismatches += 1
                print(f"MISMATCH {cat}/{country}/{m['id']} ({key}): picked={got} intermediate={exp}")

print(f"\nChecked {checked} metric cells. Mismatches: {mismatches}")
print("PASS - finals pick up exactly the intermediate values." if mismatches==0
      else "FAIL - see mismatches above.")
