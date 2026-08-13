"""
ira_intermediate.py
===================
The **calculated (silver) layer**.  From the raw parsed tables it builds one
intermediate result per metric family - YoY, QoQ, %-of-total, proportions,
etc. - keyed by (country, product), each carrying the computed value, the
input components used, and a plain-English REASON when the value can't be
produced (this is what turns "Not Available" into "why").

The metric extractors in ira_config.py read from here, and the same tables are
written out as intermediate outputs so every number is inspectable.

Product mapping (input label -> our 4 outputs), "Other" ignored:
    Consumer Secured   -> Secured
    Consumer Unsecured -> Unsecured
    SME Banking        -> SME Banking
    Wealth Banking /
    Wealth Management  -> Wealth Lending
"""

from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd

try:
    from . import ira_engine as E
except ImportError:
    import ira_engine as E


# output product -> canonical input product label
PROD_IN = {
    "Secured": "Consumer Secured",
    "Unsecured": "Consumer Unsecured",
    "SME Banking": "SME Banking",
    "Wealth Lending": "Wealth Banking",
}
PRODUCTS_OUT = list(PROD_IN.keys())

# Secured looks at 90+ DPD; the other three look at 30+ DPD
def _dpd_pct_key(prod_out):  return "90+%" if prod_out == "Secured" else "30+%"
def _dpd_amt_key(prod_out):  return "90+$" if prod_out == "Secured" else "30+$"


# --------------------------------------------------------------------------- #
#  calculation primitives that return (value, reason)
# --------------------------------------------------------------------------- #
def _series(tbl, country, prod_in):
    if tbl is None:
        return None, "source table missing"
    s = tbl.series_pp(country, prod_in)
    if s is None:
        s = tbl.series_c(country)          # country-only table
    if s is None:
        return None, f"row not found for {country} / {prod_in}"
    return s, ""


def _at(series, months, back):
    i = len(months) - 1 - back
    return series.get(months[i]) if 0 <= i < len(months) else None


def _yoy(tbl, country, prod_in, period=12):
    s, why = _series(tbl, country, prod_in)
    if s is None:
        return None, why, {}
    m = tbl.months
    cur, prev = _at(s, m, 0), _at(s, m, period)
    comp = {"current": cur, f"prior_{period}m": prev,
            "current_month": E.fmt_month(m[-1]) if m else "",
            "prior_month": (E.fmt_month(m[-1-period]) if len(m) > period else "n/a")}
    if cur is None:
        return None, "current-month value missing", comp
    if prev is None:
        return None, f"value {period} months back missing (need >= {period+1} months)", comp
    if prev == 0:
        return None, "base value is zero (cannot compute %)", comp
    return (cur - prev) / abs(prev), "", comp


def _qoq(tbl, country, prod_in, base_back=0, period=3):
    s, why = _series(tbl, country, prod_in)
    if s is None:
        return None, why, {}
    m = tbl.months
    cur, prev = _at(s, m, base_back), _at(s, m, base_back + period)
    comp = {"value": cur, f"minus_{period}m": prev}
    if cur is None:
        return None, "month value missing", comp
    if prev is None:
        return None, f"value {period} months earlier missing", comp
    if prev == 0:
        return None, "base value is zero", comp
    return (cur - prev) / abs(prev), "", comp


def _dpd_delta(tbl, country, prod_in, base_back, period, ref_label):
    """1bi/1bii/1c deterioration = (reference month value) - (period months back).
    The current month is the RIGHTMOST column.  Returns the raw difference; the
    output multiplies it by 100 and shows a %.  `comp` carries the two month
    labels and their values for the intermediate file."""
    s, why = _series(tbl, country, prod_in)
    if s is None:
        return None, why, {}
    m = tbl.months
    if not m:
        return None, "no month columns detected in the DPD% table", {}
    cur_idx = len(m) - 1 - base_back            # rightmost = current month
    if cur_idx < 0:
        return None, "reference month not in the data", {}
    cur_month = m[cur_idx]
    cur_val = s.get(cur_month)
    comp = {"Current Month": E.fmt_month(cur_month),
            "Current Month Value": cur_val}
    ref_idx = cur_idx - period
    if ref_idx < 0:
        comp[f"{ref_label} Month"] = "n/a"
        comp[f"{ref_label} Month Value"] = None
        return None, (f"need {period} months of history before "
                      f"{E.fmt_month(cur_month)}"), comp
    ref_month = m[ref_idx]
    ref_val = s.get(ref_month)
    comp[f"{ref_label} Month"] = E.fmt_month(ref_month)
    comp[f"{ref_label} Month Value"] = ref_val
    if cur_val is None or ref_val is None:
        return None, "value missing at current or reference month", comp
    return (cur_val - ref_val), "", comp


def _pct_of_total(tbl, country, prod_in, scope_countries):
    """1d: this country's product $ (current month) / sum of the SAME product
    across the in-scope countries that month."""
    s, why = _series(tbl, country, prod_in)
    if s is None:
        return None, why, {}
    m = tbl.months
    if not m:
        return None, "no month columns detected in the DPD$ table " \
                     "(check its header row of dates)", {}
    last = m[-1]
    cur = _at(s, m, 0)
    total = 0.0
    found = False
    for c in scope_countries:
        cs = tbl.series_pp(c, prod_in)
        if cs is not None and cs.get(last) is not None:
            total += cs.get(last)
            found = True
    comp = {"product_current": cur,
            "product_total_across_countries": (round(total, 6) if found else None),
            "month": E.fmt_month(last)}
    if cur is None:
        return None, "current-month value missing", comp
    if not found or total == 0:
        return None, "product total across countries is zero/blank", comp
    return cur / total, "", comp


# --------------------------------------------------------------------------- #
#  build all intermediates
# --------------------------------------------------------------------------- #
# output-format class per intermediate key (drives % vs count vs text display)
PCT_KEYS = {"enr_yoy", "dpd_qoq_cur", "dpd_qoq_prior", "dpd_yoy",
            "dpd_pct_total", "policy_exc_rate", "ea_prop", "awc_prop",
            "ltv", "volatile", "ppi_yoy", "interest_inc"}
COUNT_KEYS = {"dispensations", "breaches"}
TEXT_KEYS = {"sovereign_outlook", "sovereign_grade"}


# Metrics whose value is COUNTRY-LEVEL (identical across all four categories).
# These are stored once per country (no category column in the intermediate).
COUNTRY_LEVEL_KEYS = {"sovereign_outlook", "sovereign_grade", "interest_inc",
                      "ppi_yoy", "ltv", "volatile"}


def _lookup(d, country):
    """Dict lookup by country with normalised (case/space/alias) matching."""
    if not d:
        return None
    if country in d:
        return d[country]
    ck = E.country_key(country)
    for k, v in d.items():
        if E.country_key(k) == ck:
            return v
    return None


def _miss_reason(table_name, country, keys):
    """Build a helpful 'not found' reason: closest name in the table, or a list."""
    import difflib
    normmap = {E.country_key(k): k for k in keys}
    hit = difflib.get_close_matches(E.country_key(country),
                                    list(normmap.keys()), n=1, cutoff=0.6)
    if hit:
        return (f"'{country}' not found in {table_name} - closest name there is "
                f"'{normmap[hit[0]]}'; align the spelling in one of the files")
    avail = ", ".join(sorted(str(k) for k in keys)[:12])
    return f"'{country}' not found in {table_name} (available: {avail})"


def build(tables: Dict[str, Any], countries_per_category) -> Dict[str, Dict[Tuple, dict]]:
    # accept either {category: [countries]} or a flat list (same for all)
    if isinstance(countries_per_category, (list, tuple, set)):
        countries_per_category = {cat: list(countries_per_category)
                                  for cat in PRODUCTS_OUT}
    INT: Dict[str, Dict[Tuple, dict]] = {}

    def put(key, country, prod, value, reason, comp):
        rec = dict(value=value, reason=reason)
        for k, v in (comp or {}).items():
            if k not in ("value", "reason"):
                rec[k] = v
        INT.setdefault(key, {})[(country, prod)] = rec

    # union of all in-scope countries (country-level metrics computed once each)
    all_countries: List[str] = []
    for cat in PRODUCTS_OUT:
        for c in countries_per_category.get(cat, []):
            if c not in all_countries:
                all_countries.append(c)

    # ---- country-level metrics (same for every category -> stored once) ---- #
    for country in all_countries:
        v, why, comp = _ltv(tables, country)
        put("ltv", country, None, v, why, comp)
        v, why, comp = _volatile(tables, country)
        put("volatile", country, None, v, why, comp)
        v, why, comp = _ppi_yoy(tables, country)
        put("ppi_yoy", country, None, v, why, comp)
        v, why, comp = _interest_inc(tables, country)
        put("interest_inc", country, None, v, why, comp)
        out, grd = _sovereign(tables, country)
        put("sovereign_outlook", country, None, out[0], out[1], {})
        put("sovereign_grade", country, None, grd[0], grd[1], {})

    # ---- category-level metrics --------------------------------------------- #
    for po in PRODUCTS_OUT:
        pin = PROD_IN[po]
        scope = countries_per_category.get(po, [])
        amt_tbl = tables.get(_dpd_amt_key(po))     # 90+$ / 30+$ for 1d

        for country in scope:
            # 1a  ENR asset growth YoY
            v, why, comp = _yoy(tables.get("ENR"), country, pin)
            put("enr_yoy", country, po, v, why or "", comp)

            # 1bi / 1bii  QoQ deterioration = current - 3 months back.
            # Current month = rightmost column; last quarter = 3 months earlier.
            dpd_pct = tables.get(_dpd_pct_key(po))
            v, why, comp = _dpd_delta(dpd_pct, country, pin, base_back=0,
                                      period=3, ref_label="Last Quarter")
            put("dpd_qoq_cur", country, po, v, why, comp)
            v, why, comp = _dpd_delta(dpd_pct, country, pin, base_back=1,
                                      period=3, ref_label="Last Quarter")
            put("dpd_qoq_prior", country, po, v, why, comp)

            # 1c  YoY deterioration = current - 12 months back.
            v, why, comp = _dpd_delta(dpd_pct, country, pin, base_back=0,
                                      period=12, ref_label="Last Year")
            put("dpd_yoy", country, po, v, why, comp)

            # 1d  DPD $ share of the product total across in-scope countries
            v, why, comp = _pct_of_total(amt_tbl, country, pin, scope)
            put("dpd_pct_total", country, po, v, why, comp)

            # 1e  policy exception rate (L2+L3)/(new approved)
            v, why, comp = _policy_exc(tables, country, pin)
            put("policy_exc_rate", country, po, v, why, comp)

            # EA / AWC proportions
            v, why, comp = _ratio_of_enr(tables, country, pin, kind="EA")
            put("ea_prop", country, po, v, why, comp)
            v, why, comp = _ratio_of_enr(tables, country, pin, kind="AWC")
            put("awc_prop", country, po, v, why, comp)

            # dispensations / breaches (per category)
            v, why = _dispensations(tables, country, po)
            put("dispensations", country, po, v, why, {})
            v, why = _breaches(tables, country, po)
            put("breaches", country, po, v, why, {})

    return INT


# --------------------------------------------------------------------------- #
#  the remaining, table-specific calculations
# --------------------------------------------------------------------------- #
def _policy_exc(tables, country, prod_in):
    """1e/1g/1f: (# approved with policy exception L2+L3) / (# monthly new
    approved), summed over the last 12 months, per the mapping file."""
    pe = tables.get("policy_exception")
    if not pe:
        return None, "policy-exception (L2|L3) table missing", {}
    left, right = pe.get("left"), pe.get("right")
    l2 = left.series_pp(country, prod_in) if left else None
    l3 = right.series_pp(country, prod_in) if right else None
    if l2 is None and l3 is None:
        return None, f"no L2/L3 row for {country}/{prod_in}", {}
    months = (left.months if left else None) or (right.months if right else None) or []
    if not months:
        return None, "no month columns in the policy-exception table", {}
    win = months[-12:]                      # last 12 months

    def _sum(series):
        return sum((series.get(m) or 0) for m in win) if series else 0

    numer = _sum(l2) + _sum(l3)

    na = tables.get("new_approved")
    den_series = na.series_pp(country, prod_in) if na else None
    denom = sum((den_series.get(m) or 0) for m in win) if den_series else None

    comp = {"exceptions_L2+L3_12m": numer, "new_approved_12m": denom,
            "window": f"{E.fmt_month(win[0])}..{E.fmt_month(win[-1])}"}
    if na is None:
        return None, "'# monthly new approved' table missing (denominator)", comp
    if den_series is None:
        return None, f"no 'new approved' row for {country}/{prod_in}", comp
    if not denom:
        return None, "monthly-new-approved total is zero/blank", comp
    return numer / denom, "", comp


def _ratio_of_enr(tables, country, prod_in, kind="EA"):
    me = tables.get("ME_EA_AWC") or {}
    if kind == "EA":
        tbl = me.get("ME EA (PP & NPP) in $mn") or me.get("ME EA NPP in $mn")
    else:
        tbl = me.get("ME AWC in $mn")
    if tbl is None:
        return None, f"{kind} table not found in ME EA AWC", {}
    num = E.latest(tbl.series_c(country), tbl.months)
    enr = tables.get("ENR")
    den = E.latest(enr.series_pp(country, prod_in), enr.months) if enr else None
    comp = {kind: num, "ENR": den}
    if num is None:
        return None, f"{country} not in {kind} table", comp
    if den in (None, 0):
        return None, "ENR denominator missing/zero", comp
    return num / den, "", comp


def _ltv(tables, country):
    tbl = tables.get("LTV80")
    if tbl is None:
        return None, "LTV>80 table missing", {}
    s = tbl.series_c(country) or tbl.series_c("Group")
    v = E.latest(s, tbl.months) if s else None
    if v is None:
        return None, f"{country} not in LTV table (and no Group row)", {}
    return v / 100.0, "", {"ltv_raw": v, "basis": "value/100"}


def _volatile(tables, country):
    vol = tables.get("ccpl_volatile") or {}
    if not vol:
        return None, "CCPL Volatile table missing", {}
    hit = _lookup(vol, country)
    if hit is not None:
        return hit, "", {"matched": country}
    for key in (E.COUNTRY_CCY.get(country, ""), country[:2].upper()):
        if key in vol:
            return vol[key], "", {"matched_code": key}
    if "Global" in vol:
        return vol["Global"], "no country code match; used Global", {}
    return None, f"no CCPL code for {country}", {}


def _ppi_yoy(tables, country):
    ppi = tables.get("PPI")
    if ppi is None:
        return None, "PPI table missing", {}
    # real PPI is keyed by country (matrix); fall back to currency for old format
    s = ppi.series_c(country)
    label = country
    if s is None:
        ccy = E.COUNTRY_CCY.get(country, country)
        s = ppi.series_c(ccy)
        label = ccy
    if s is None:
        return None, f"no PPI column for {country}", {}
    tmp = E.MonthTable(ppi.months, {}, {country: s}, {})
    v, why, comp = _yoy(tmp, country, country)
    comp["ppi_key"] = label
    return v, why, comp


def _interest_inc(tables, country):
    """2a: (current-month rate - last-3-years average) / 100, per the mapping."""
    ir = tables.get("interest_rates")
    if ir is None:
        return None, "Interest Rates table missing/empty", {}
    s = ir.series_c(country)
    if not s:
        return None, f"no interest-rate column for {country}", {}
    months = ir.months
    win = months[-36:] if len(months) >= 36 else months     # last 3 years
    vals = [s.get(m) for m in win if s.get(m) is not None]
    if not vals:
        return None, "interest-rate column has no values", {}
    avg = sum(vals) / len(vals)
    last = E.latest(s, months)
    if last is None:
        return None, "current-month interest rate missing", {"avg_3yr": round(avg, 6)}
    return (last - avg) / 100.0, "", {"current": round(last, 4),
                                      "avg_3yr": round(avg, 4),
                                      "basis": "(current - 3yr avg)/100"}


def _sovereign(tables, country):
    sov = tables.get("sovereign") or {}
    rec = _lookup(sov, country)
    if not rec:
        why = _miss_reason("Sovereign table", country, sov.keys())
        miss = (None, why)
        return miss, miss
    return ((rec.get("outlook"), ""), (rec.get("fcy_crg"), ""))


def _dispensations(tables, country, category):
    d = tables.get("dispensations") or {}
    tbl = d.get(category)
    if not tbl:
        return None, f"no dispensation table for {category}"
    val = _lookup(tbl, country)
    if val is None:
        return None, _miss_reason(f"{category} dispensation table", country, tbl.keys())
    return val, ""


def _breaches(tables, country, category):
    b = tables.get("cra_breaches") or {}
    tbl = b.get(category)
    if not tbl:
        return None, f"no CRA-breaches table for {category}"
    val = _lookup(tbl, country)
    if val is None:
        return None, _miss_reason(f"{category} CRA-breaches table", country, tbl.keys())
    return val, ""


# --------------------------------------------------------------------------- #
#  render intermediates as tidy DataFrames for output
# --------------------------------------------------------------------------- #
INT_TITLES = {
    "enr_yoy": "1a ENR Asset Growth YoY %",
    "dpd_qoq_cur": "1bi DPD% QoQ (current)",
    "dpd_qoq_prior": "1bii DPD% QoQ (prior)",
    "dpd_yoy": "1c DPD% YoY",
    "dpd_pct_total": "1d DPD$ share of group total",
    "policy_exc_rate": "1e Policy exceptions (L2+L3) YoY",
    "ea_prop": "EA to ENR proportion",
    "awc_prop": "AWC to ENR proportion",
    "ltv": "1g LTV over 80 concentration",
    "volatile": "1g Volatile segment concentration",
    "ppi_yoy": "2b PPI YoY",
    "interest_inc": "2a Interest-rate increase vs avg",
    "sovereign_outlook": "2c Country outlook",
    "sovereign_grade": "2d Country grading",
    "dispensations": "Active dispensations",
    "breaches": "CRA breaches (12m)",
}

# For the Label -> Table -> Calculation mapping sheet:
#   int_key -> (source table(s), what is calculated)
INT_SOURCE = {
    "enr_yoy": ("ENR", "product ENR: (Mar26 - Mar25) / |Mar25|"),
    "dpd_qoq_cur": ("90+% (Secured) / 30+% (others)",
                    "current month - 3 months back (x100 as %)"),
    "dpd_qoq_prior": ("90+% / 30+%",
                      "prior month - 3 months back (x100 as %)"),
    "dpd_yoy": ("90+% / 30+%",
                "current month - 12 months back (x100 as %)"),
    "dpd_pct_total": ("90+$ / 30+$", "product current / group total current"),
    "policy_exc_rate": ("# policy exception L2&L3  /  # monthly new approved",
                        "sum(L2+L3, 12m) / sum(new approved, 12m)"),
    "ea_prop": ("ME EA AWC (EA) + ENR", "EA(country) / ENR(product), current month"),
    "awc_prop": ("ME EA AWC (AWC) + ENR", "AWC(country) / ENR(product), current month"),
    "ltv": ("LTV > 80 Excl MIP", "country current value / 100"),
    "volatile": ("CCPL Volatile by Country", "volatile % for the country code"),
    "ppi_yoy": ("Property Price Index (by country)", "YoY of PPI for the country"),
    "interest_inc": ("Interest Rates (3-yr history)", "(current - 3yr avg) / 100"),
    "sovereign_outlook": ("Country Sovereign Rating & Outlook", "Outlook value"),
    "sovereign_grade": ("Country Sovereign Rating & Outlook", "FCY CRG grade"),
    "dispensations": ("<Category> Portfolio Active/Expired Dispensation",
                      "# column for the country"),
    "breaches": ("Credit Risk Appetite Breaches - <Category>",
                 "count of Y in last 12 months"),
}


def to_frames(INT: Dict[str, Dict[Tuple, dict]]) -> Dict[str, pd.DataFrame]:
    frames = {}
    for key, recs in INT.items():
        country_level = key in COUNTRY_LEVEL_KEYS
        rows = []
        for (country, prod), rec in recs.items():
            base = {"Country": country}
            if not country_level:
                base["Product"] = prod        # category column only when relevant
            base["Value"] = rec.get("value")
            base["Reason"] = rec.get("reason", "")
            for k, v in rec.items():
                if k not in ("value", "reason"):
                    base[k] = v
            rows.append(base)
        df = pd.DataFrame(rows)
        if not df.empty:
            sort_cols = ["Country"] if country_level else ["Product", "Country"]
            df = df.sort_values(sort_cols).reset_index(drop=True)
        frames[INT_TITLES.get(key, key)] = df
    return frames
