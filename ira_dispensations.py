"""
ira_dispensations.py
====================
A DEDICATED, self-contained pipeline for the

    "<Category> Portfolio with Active or Expired Dispensation"

tables (label 1f in every category).  These tables always live in
OtherTables.xlsx and follow the simple shape:

    <title row>
    Country | #
    Bangladesh | 1
    Australia  | 3
    ...

This module owns the whole journey for them - detect -> read -> process ->
intermediate -> final - independently of the generic reference-table machinery,
so they are guaranteed to be found and surfaced.

Public API
----------
detect(sheets)                 -> report list (what was found, per table)
parse(sheets)                  -> ({category: {country: value}}, report)
value_for(data, category, country) -> (value, reason)      # final-output pickup
intermediate_frames(data)      -> {sheet_title: DataFrame}  # for the intermediate file
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple
import re
import pandas as pd

try:
    from . import ira_engine as E
except ImportError:
    import ira_engine as E


CATEGORIES = ["Secured", "Unsecured", "SME Banking", "Wealth Lending"]

# exact, case-insensitive alias words that identify each category
_ALIASES: Dict[str, set] = {
    "Unsecured": {"unsecured", "unsec"},
    "Secured": {"secured", "sec"},
    "SME Banking": {"sme", "smb", "business"},
    "Wealth Lending": {"wl", "wm", "wealth"},
}
# a row is a dispensation TITLE if its text contains any of these markers
_TITLE_MARKERS = ("dispensation", "active or expired")
# the label id shown for the dispensation metric in each category's output
LABEL_ID = {"Secured": "1f", "Unsecured": "1f", "SME Banking": "1h", "Wealth Lending": "1g"}


# --------------------------------------------------------------------------- #
#  small helpers
# --------------------------------------------------------------------------- #
def _blank(x) -> bool:
    return E._blank(x)


def _words(s: Any) -> set:
    return set(re.sub(r"[^a-z0-9 ]", " ", str(s).lower()).split())


def _category_of(title: str) -> Optional[str]:
    """Exact, case-insensitive word match - unsecured checked before secured."""
    w = _words(title)
    if w & _ALIASES["Unsecured"]:
        return "Unsecured"
    if w & _ALIASES["Secured"]:
        return "Secured"
    if w & _ALIASES["SME Banking"]:
        return "SME Banking"
    if w & _ALIASES["Wealth Lending"]:
        return "Wealth Lending"
    return None


def _trim_left(rows: List[List[Any]]) -> List[List[Any]]:
    """Drop leading columns blank in every row (handles the col-A gap)."""
    if not rows:
        return rows
    width = max((len(r) for r in rows), default=0)
    first = 0
    for c in range(width):
        if any(c < len(r) and not _blank(r[c]) for r in rows):
            first = c
            break
    return [[(r[c] if c < len(r) else None) for c in range(first, width)] for r in rows]


def _title_in_row(row: List[Any]) -> Optional[str]:
    """Return the cell text if this row is a dispensation title row, else None.
    Robust: the marker can be in any cell, alongside blanks."""
    for v in row:
        if isinstance(v, str) and v.strip():
            low = v.lower()
            if any(m in low for m in _TITLE_MARKERS):
                return v.strip()
    return None


def _collect_block(rows: List[List[Any]], start: int) -> Tuple[List[List[Any]], int]:
    """Consecutive non-blank rows from `start` until a blank row or a new title."""
    out = []
    i = start
    while i < len(rows):
        r = rows[i]
        if all(_blank(c) for c in r):
            break
        if _title_in_row(r):          # next table starts
            break
        out.append(r)
        i += 1
    return out, i


def _parse_country_hash(block: List[List[Any]]) -> Dict[str, Any]:
    """Parse a  Country | #  block into {country: value}."""
    out: Dict[str, Any] = {}
    if not block:
        return out
    start = 0
    # skip a header row if the first row looks like  Country | #
    first_txt = " ".join(str(c).lower() for c in block[0] if not _blank(c))
    if "country" in first_txt or first_txt.strip() in ("#", "count", "number"):
        start = 1
    for r in block[start:]:
        # country = first non-blank cell; value = next numeric cell
        cells = [c for c in r]
        country = None
        for c in cells:
            if isinstance(c, str) and c.strip():
                country = c.strip()
                break
        if not country or country.lower() in ("country", "total", "grand total"):
            continue
        val = None
        for c in cells:
            n = E._num(c)
            if n is not None:
                val = n
                break
        if val is not None:
            out[country] = int(val) if float(val).is_integer() else val
    return out


# --------------------------------------------------------------------------- #
#  detect + parse  (from the very beginning)
# --------------------------------------------------------------------------- #
def parse(sheets: Dict[str, List[List[Any]]]) -> Tuple[Dict[str, Dict[str, Any]], List[dict]]:
    """Scan every sheet, find every dispensation table, return
    ({category: {country: value}}, report)."""
    data: Dict[str, Dict[str, Any]] = {}
    report: List[dict] = []
    for sheet_name, raw in (sheets or {}).items():
        rows = _trim_left(raw)
        i = 0
        while i < len(rows):
            title = _title_in_row(rows[i])
            if title:
                block, nxt = _collect_block(rows, i + 1)
                parsed = _parse_country_hash(block)
                cat = _category_of(title)
                rec = {"sheet": sheet_name, "title": title, "category": cat,
                       "n_countries": len(parsed), "countries": list(parsed.keys()),
                       "values": parsed, "detected": bool(parsed and cat)}
                if cat and parsed:
                    data[cat] = parsed                      # last wins if duplicated
                    rec["note"] = "OK"
                elif not cat:
                    rec["note"] = "category not recognized from title"
                else:
                    rec["note"] = "no Country/# rows parsed"
                report.append(rec)
                i = max(nxt, i + 1)
            else:
                i += 1
    return data, report


def detect(sheets: Dict[str, List[List[Any]]]) -> List[dict]:
    """Detection-only view (no values), for a checks/preview panel."""
    _data, report = parse(sheets)
    return [{k: r[k] for k in ("sheet", "title", "category", "n_countries",
                               "detected", "note")} for r in report]


# --------------------------------------------------------------------------- #
#  final-output pickup
# --------------------------------------------------------------------------- #
def value_for(data: Dict[str, Dict[str, Any]], category: str,
              country: str) -> Tuple[Optional[Any], str]:
    """The value that goes into the final output for (category, country)."""
    tbl = (data or {}).get(category)
    if not tbl:
        return None, f"no dispensation table found for {category}"
    if country in tbl:
        return tbl[country], ""
    ck = E.country_key(country)
    for k, v in tbl.items():
        if E.country_key(k) == ck:
            return v, ""
    avail = ", ".join(sorted(str(k) for k in tbl.keys()))
    return None, f"{country} not in {category} dispensation table (have: {avail})"


# --------------------------------------------------------------------------- #
#  intermediate output  (see the processed 1f tables explicitly)
# --------------------------------------------------------------------------- #
def intermediate_frames(data: Dict[str, Dict[str, Any]]) -> Dict[str, pd.DataFrame]:
    """One tidy sheet per category: the processed dispensation table."""
    frames: Dict[str, pd.DataFrame] = {}
    for cat in CATEGORIES:
        tbl = (data or {}).get(cat)
        title = f"{LABEL_ID.get(cat, '1f')} Dispensations {cat}"
        if tbl:
            df = pd.DataFrame(
                [{"Country": c, "Dispensations (#)": v} for c, v in tbl.items()])
        else:
            df = pd.DataFrame([{"Country": "(no table found)", "Dispensations (#)": None}])
        frames[title[:31]] = df
    return frames
