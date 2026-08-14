"""
ira_reftables.py
================
Parses the reference tables that arrive with a DIFFERENT schema (and possibly a
different sheet/file name) than the main product-block sheets:

  * Dispensations         "<Category> Portfolio with Active or Expired ..."
                          Country | #                       -> {category: {country: count}}
  * CRA breaches          "Credit Risk Appetite Breaches - <Category>"
                          Country | <months Y/blank> | L12M -> {category: {country: count_last_12m}}
  * Sovereign rating      "Country Sovereign Rating & Outlook"
                          Country | LCY CRG | FCY CRG | Outlook | Approved Date
                                                          -> {country: {outlook, fcy_crg, lcy_crg}}
  * Property Price Index  "Property Price Index"   (dates in ROWS, countries in COLUMNS)
                                                          -> MonthTable keyed by country
  * Interest Rates        "Interest Rates"          (dates in ROWS, countries in COLUMNS)
                                                          -> MonthTable keyed by country

These tables are located by their TITLE text, so they work whether they sit in
their own sheet, are stacked several-to-a-sheet, or come in a separate file.
A leading blank column (data starting in column B) is handled.
"""

from __future__ import annotations
from typing import Dict, List, Any, Tuple, Optional
import pandas as pd

try:
    from . import ira_engine as E
except ImportError:
    import ira_engine as E


CATEGORY_WORDS = {
    "secured": "Secured", "unsecured": "Unsecured",
    "sme": "SME Banking", "business": "SME Banking",
    "wealth": "Wealth Lending",
}
FOOTER_WORDS = ("yoy change", "last 3 yr", "last 3 yrs", "rate increase",
                "average", "3 yr", "l12m total")


def _blank(x):
    return E._blank(x)


def _trim_left(rows: List[List[Any]]) -> List[List[Any]]:
    """Drop leading columns that are blank in every row (handles the col-A gap)."""
    if not rows:
        return rows
    width = max(len(r) for r in rows)
    first = 0
    for c in range(width):
        if any(c < len(r) and not _blank(r[c]) for r in rows):
            first = c
            break
    return [[(r[c] if c < len(r) else None) for c in range(first, width)] for r in rows]


def _title_of(row: List[Any]) -> Optional[str]:
    """A title row has exactly one non-blank cell that is a non-date string."""
    nb = [(i, v) for i, v in enumerate(row) if not _blank(v)]
    if len(nb) == 1 and isinstance(nb[0][1], str) and not E._is_date_like(nb[0][1]):
        return nb[0][1].strip()
    return None


def _category_from(title: str) -> Optional[str]:
    """Map a table title to a category by EXACT, case-insensitive word match.
    The title is lowercased and de-punctuated, then split into words; a category
    wins if any of its alias words is present.  'unsecured' is checked before
    'secured' so the shared substring never collides.  No fuzzy matching."""
    import re
    words = set(re.sub(r"[^a-z0-9 ]", " ", str(title).lower()).split())

    if words & {"unsecured", "unsec"}:
        return "Unsecured"
    if words & {"secured", "sec"}:
        return "Secured"
    if words & {"sme", "smb", "business"}:
        return "SME Banking"
    if words & {"wl", "wm", "wealth"}:
        return "Wealth Lending"
    return None


def _block(rows: List[List[Any]], start: int) -> Tuple[List[List[Any]], int]:
    """Consecutive non-blank rows from `start` until a fully-blank row/new title."""
    out = []
    i = start
    while i < len(rows):
        r = rows[i]
        if all(_blank(c) for c in r):
            break
        if out and _title_of(r):     # a new title starts the next block
            break
        out.append(r)
        i += 1
    return out, i


# --------------------------------------------------------------------------- #
#  per-schema parsers
# --------------------------------------------------------------------------- #
def _parse_dispensation(block: List[List[Any]]) -> Dict[str, float]:
    """Country | #  ->  {country: count}."""
    out = {}
    if not block:
        return out
    # header is first row (Country | #); data follows
    for r in block[1:]:
        if len(r) >= 2 and isinstance(r[0], str) and not _blank(r[0]):
            if r[0].strip().lower() in ("country", "total"):
                continue
            val = E._num(r[1])
            if val is not None:
                out[r[0].strip()] = int(val) if float(val).is_integer() else val
    return out


def _parse_breaches(block: List[List[Any]]) -> Dict[str, int]:
    """Country | <months Y/blank> | L12M  ->  {country: count of Y in last 12 months}."""
    out = {}
    if not block:
        return out
    header = block[0]
    # month columns are the date-like headers
    mcols = [i for i, v in enumerate(header) if E._is_date_like(v)]
    last12 = mcols[-12:] if len(mcols) >= 12 else mcols
    for r in block[1:]:
        if not r or _blank(r[0]) or not isinstance(r[0], str):
            continue
        country = r[0].strip()
        if country.lower() in ("country", "total"):
            continue
        cnt = sum(1 for i in last12
                  if i < len(r) and isinstance(r[i], str) and r[i].strip().lower() == "y")
        out[country] = cnt
    return out


def _parse_sovereign(block: List[List[Any]]) -> Dict[str, Dict[str, str]]:
    """Country | LCY CRG | FCY CRG | Outlook | ...  ->  {country: {...}}."""
    out = {}
    if not block:
        return out
    header = [str(c).strip().lower() if c is not None else "" for c in block[0]]

    def col(*names):
        for nm in names:
            for i, h in enumerate(header):
                if nm in h:
                    return i
        return None

    ci = 0
    fcy = col("fcy crg", "fcy rating", "fcy", "foreign currency")
    lcy = col("lcy crg", "lcy rating", "lcy", "local currency")
    out_c = col("outlook")
    for r in block[1:]:
        if not r or _blank(r[ci]) or not isinstance(r[ci], str):
            continue
        country = r[ci].strip()
        if country.lower() in ("country", "total"):
            continue
        rec = {}
        if fcy is not None and fcy < len(r):
            rec["fcy_crg"] = (str(r[fcy]).strip() if not _blank(r[fcy]) else None)
        if lcy is not None and lcy < len(r):
            rec["lcy_crg"] = (str(r[lcy]).strip() if not _blank(r[lcy]) else None)
        if out_c is not None and out_c < len(r):
            rec["outlook"] = (str(r[out_c]).strip() if not _blank(r[out_c]) else None)
        out[country] = rec
    return out


def _parse_matrix(block: List[List[Any]]) -> "E.MonthTable":
    """Dates in the first column (rows), entities across the header (columns).
    Returns a MonthTable keyed by entity (country)."""
    if not block:
        return E.MonthTable([], {}, {}, {})
    header = block[0]
    # entity columns = every non-blank header cell after the first column
    ent_cols = [(i, str(header[i]).strip()) for i in range(1, len(header))
                if not _blank(header[i]) and not E._is_date_like(header[i])]
    months = []
    data: Dict[str, Dict[str, float]] = {name: {} for _i, name in ent_cols}
    for r in block[1:]:
        if not r or _blank(r[0]):
            continue
        # stop at footer rows (YoY / averages / rate increase)
        if isinstance(r[0], str) and any(w in r[0].lower() for w in FOOTER_WORDS):
            continue
        if not E._is_date_like(r[0]):
            continue
        mlabel = str(r[0])
        months.append(mlabel)
        for i, name in ent_cols:
            data[name][mlabel] = E._num(r[i]) if i < len(r) else None
    return E.MonthTable(months, {}, data, {})


# --------------------------------------------------------------------------- #
#  top-level: scan all sheets, extract every reference table by title
# --------------------------------------------------------------------------- #
def parse_reference_tables(sheets: Dict[str, List[List[Any]]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"dispensations": {}, "cra_breaches": {},
                           "sovereign": {}, "ppi": None, "interest_rates": None}
    for name, raw in sheets.items():
        rows = _trim_left(raw)
        i = 0
        while i < len(rows):
            title = _title_of(rows[i])
            if not title:
                i += 1
                continue
            low = title.lower()
            block, nxt = _block(rows, i + 1)

            if "active or expired" in low or "active/expired" in low or \
               ("dispensation" in low):
                cat = _category_from(low)
                if cat:
                    out["dispensations"][cat] = _parse_dispensation(block)
            elif "credit risk appetite breaches" in low or \
                    ("appetite" in low and "breach" in low):
                cat = _category_from(low)
                if cat:
                    out["cra_breaches"][cat] = _parse_breaches(block)
            elif "sovereign" in low or ("outlook" in low and
                                        ("crg" in low or "rating" in low)):
                out["sovereign"] = _parse_sovereign(block)
            elif "property price index" in low or low.strip() == "ppi":
                out["ppi"] = _parse_matrix(block)
            elif low.strip() == "interest rates" or "interest rate" in low:
                out["interest_rates"] = _parse_matrix(block)
            i = max(nxt, i + 1)
    # drop empties
    return {k: v for k, v in out.items()
            if v not in (None, {}, [])}
