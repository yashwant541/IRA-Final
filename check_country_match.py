"""
Show which config countries match each reference table (sovereign, dispensations,
CRA breaches, PPI, interest) - and for the ones that DON'T, the closest name in
the table so you can align the spelling.

Usage:  python check_country_match.py [INPUT.xlsx]
"""
import os, sys, glob, difflib, pandas as pd
_HERE=os.path.dirname(os.path.abspath(__file__))
for p in (_HERE, os.path.join(_HERE,"IRA")):
    if os.path.isdir(p) and p not in sys.path: sys.path.insert(0,p)
try:
    from IRA import ira_loaders as L, ira_engine as E, ira_countries as CC
except ImportError:
    import ira_loaders as L, ira_engine as E, ira_countries as CC

inp = sys.argv[1] if len(sys.argv)>1 else "Dummy.xlsx"
sheets = {n:d.values.tolist() for n,d in pd.read_excel(inp,sheet_name=None,header=None).items()}
_dir = os.path.dirname(os.path.abspath(inp)) or "."
for f in glob.glob(os.path.join(_dir,"Other_Tables.xlsx"))+glob.glob(os.path.join(_dir,"*Other*.xlsx")):
    if os.path.abspath(f)!=os.path.abspath(inp):
        for n,d in pd.read_excel(f,sheet_name=None,header=None).items():
            sheets[f"{os.path.basename(f)}::{n}"]=d.values.tolist()

t = L.load_tables(sheets)
cfg = CC.load("countries_config.csv") if os.path.exists("countries_config.csv") else {}
config_countries = sorted({c for lst in cfg.values() for c in lst}) or \
                   sorted({c for k in ("ENR",) if t.get(k) for c in t[k].countries()})

def keys_of(obj):
    if obj is None: return []
    if isinstance(obj, dict):
        # per-category dict (dispensations/breaches) -> union of inner keys
        if obj and all(isinstance(v,dict) for v in obj.values()) and \
           any(k in ("Secured","Unsecured","SME Banking","Wealth Lending") for k in obj):
            out=set()
            for v in obj.values(): out|=set(v.keys())
            return sorted(out)
        return sorted(obj.keys())
    if hasattr(obj,"country_data"): return sorted(obj.country_data.keys())
    return []

ref = {"Sovereign": t.get("sovereign"), "Dispensations": t.get("dispensations"),
       "CRA breaches": t.get("cra_breaches"), "PPI": t.get("PPI"),
       "Interest rates": t.get("interest_rates")}

print(f"Config countries: {config_countries}\n")
for name, obj in ref.items():
    ks = keys_of(obj)
    if not ks:
        print(f"[{name}] table not found / empty"); print(); continue
    normmap = {E.country_key(k): k for k in ks}
    print(f"[{name}]  (table has: {', '.join(map(str,ks))})")
    for c in config_countries:
        if E.country_key(c) in normmap:
            print(f"    OK    {c:16} -> {normmap[E.country_key(c)]}")
        else:
            hint = difflib.get_close_matches(E.country_key(c), list(normmap.keys()), n=1, cutoff=0.6)
            sug = f"  (closest: '{normmap[hint[0]]}')" if hint else ""
            print(f"    MISS  {c:16}{sug}")
    print()
