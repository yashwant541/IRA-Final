"""
ira_normalize.py
================
Turns the raw "country header + product sub-rows" sheets into clean, tidy
intermediate tables - the shapes described in the requirements:

1) LONG form (one sheet per source):
       Country | Product | Mar-25 | ... | Mar-26
   with a `Total` row per country and OUTPUT product names
   (Consumer Secured -> Secured, Wealth Banking -> Wealth Lending, Other dropped).

2) PER-CATEGORY form (four tables per source):
       Country | Product | Mar-25 | ... | Mar-26
   filtered to a single category, e.g. every row = "Secured".

Date headers are formatted Mar-26 (last column = current month, the one to its
left = prior month).
"""

from __future__ import annotations
from typing import Dict, Any, List
import pandas as pd

try:
    from . import ira_engine as E
except ImportError:
    import ira_engine as E


# order products appear in each country block
CANON_ORDER = ["Consumer Secured", "Consumer Unsecured", "SME Banking", "Wealth Banking"]


def block_to_long(tbl: "E.MonthTable", include_total=True) -> pd.DataFrame:
    """MonthTable (country+product block) -> tidy long DataFrame with Mar-26 headers."""
    if tbl is None:
        return pd.DataFrame()
    months = tbl.months
    hdrs = E.fmt_months(months)
    rows = []
    # preserve country order as first seen
    countries = []
    for c in tbl.country_data:
        if not str(c).lower().startswith("total") and c not in countries:
            countries.append(c)
    for (c, _p) in tbl.product_data:
        if c not in countries:
            countries.append(c)

    for country in countries:
        if include_total and country in tbl.country_data:
            tot = tbl.country_data[country]
            rows.append(_row(country, "Total", tot, months, hdrs))
        for canon in CANON_ORDER:
            s = tbl.product_data.get((country, canon))
            if s is not None:
                rows.append(_row(country, E.PRODUCT_OUT_NAME[canon], s, months, hdrs))
    return pd.DataFrame(rows)


def block_to_category(tbl: "E.MonthTable", category: str) -> pd.DataFrame:
    """Per-category table (one product), Mar-26 headers, output product name."""
    if tbl is None:
        return pd.DataFrame()
    canon = E.CATEGORY_TO_CANON[category]
    months = tbl.months
    hdrs = E.fmt_months(months)
    out_name = E.PRODUCT_OUT_NAME[canon]
    rows = []
    countries = []
    for c in tbl.country_data:
        if not str(c).lower().startswith("total") and c not in countries:
            countries.append(c)
    for (c, _p) in tbl.product_data:
        if c not in countries:
            countries.append(c)
    for country in countries:
        s = tbl.product_data.get((country, canon))
        if s is not None:
            rows.append(_row(country, out_name, s, months, hdrs))
    return pd.DataFrame(rows)


def _row(country, product, series, months, hdrs):
    row = {"Country": country, "Product": product}
    for m, h in zip(months, hdrs):
        row[h] = series.get(m)
    return row


# which raw tables are country+product blocks worth normalising
BLOCK_SOURCES = {
    "ENR": "ENR", "30+%": "30+%", "30+$": "30+$", "90+%": "90+%", "90+$": "90+$",
    "RWA": "RWA", "app_rate": "AppRate", "new_approved": "NewApproved",
}


def normalized_long(tables: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """One tidy long DataFrame per block source present."""
    out = {}
    for key, short in BLOCK_SOURCES.items():
        tbl = tables.get(key)
        if tbl is not None:
            out[short] = block_to_long(tbl)
    # policy exception: combine L2 + L3 sides into long too
    pe = tables.get("policy_exception")
    if pe and pe.get("left"):
        out["PolicyExc-L2"] = block_to_long(pe["left"])
    if pe and pe.get("right"):
        out["PolicyExc-L3"] = block_to_long(pe["right"])
    return out


def normalized_by_category(tables: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """For each core block source, four per-category tables. Keyed 'SRC-Category'."""
    out = {}
    core = {"ENR": "ENR", "30+%": "30+%", "30+$": "30+$",
            "90+%": "90+%", "90+$": "90+$"}
    pe = tables.get("policy_exception")
    for key, short in core.items():
        tbl = tables.get(key)
        if tbl is None:
            continue
        for cat in E.CATEGORIES:
            out[f"{short}-{cat}"] = block_to_category(tbl, cat)
    if pe and pe.get("left"):
        for cat in E.CATEGORIES:
            out[f"PolExcL2-{cat}"] = block_to_category(pe["left"], cat)
    if pe and pe.get("right"):
        for cat in E.CATEGORIES:
            out[f"PolExcL3-{cat}"] = block_to_category(pe["right"], cat)
    return out
