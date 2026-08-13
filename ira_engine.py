"""
ira_engine.py
=============
Framework-agnostic engine that builds the "Inherent Risk Assessment" (IRA)
output workbook (Secured / Unsecured / SME Banking / Wealth Lending) from a set
of input tables.

Design goals
------------
* **Versatile** - the parsers understand the *shapes* of the input tables
  (country + product sub-rows, country-only, 2x2 quadrant, side-by-side,
  long/tidy) rather than hard-coding cell addresses, so a new month / new
  country / re-ordered rows keep working.
* **Config-driven** - every metric is one entry in ``METRICS`` describing where
  its value comes from, how to bucket it into a risk rating, which aggregation
  group it belongs to and its weight.  Editing thresholds or weights never means
  touching the computation code.
* **Portable** - depends only on ``pandas``/``numpy``.  The Dataiku recipe
  (``dataiku_recipe.py``) is a thin wrapper that feeds this engine
  DataFrames and writes its output back to datasets/folders.

Nothing here imports ``dataiku`` so it can be unit-tested and run locally.

--------------------------------------------------------------------------------
KEY CONVENTIONS / ASSUMPTIONS  (all easy to change - see the marked spots)
--------------------------------------------------------------------------------
* Month columns are whatever datetime-like headers appear on a table; the
  *current* month is the last column, the *prior* month the second-last.
* "YoY"  = current month vs the value 12 columns earlier (same month, prior yr).
* "QoQ"  = a month vs the value 3 columns earlier (one quarter earlier).
* The 4 output products map to these input product sub-row labels:
      Secured        -> "Consumer Secured"
      Unsecured      -> "Consumer Unsecured"
      SME Banking    -> "SME Banking"
      Wealth Lending -> "Wealth Banking"
* The AV:AZ lookup (Very Low..Very High = 1..5) is ``RISK_NUMBER``.
* Weights (BB:BD) and the exact final-aggregation grouping are PLACEHOLDERS -
  supply the real ones in ``WEIGHTS`` / ``GROUPS`` when you have them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------- #
#  0.  Constant lookups
# ----------------------------------------------------------------------------- #

# AV:AZ  --  Very Low..Very High  ->  1..5
RISK_NUMBER: Dict[str, int] = {
    "Very Low": 1,
    "Low": 2,
    "Medium": 3,
    "High": 4,
    "Very High": 5,
}
# textual ratings that should not score (kept out of the weighted sum)
NON_SCORING = {"Not Available", "N/A", "", None}

# The 4 output products and the input product-label they read from.
PRODUCTS: Dict[str, str] = {
    "Secured": "Consumer Secured",
    "Unsecured": "Consumer Unsecured",
    "SME Banking": "SME Banking",
    "Wealth Lending": "Wealth Banking",
}

# Country -> currency code, used to line country tables up with the PPI table
# (which is keyed by currency).  Extend freely.
COUNTRY_CCY: Dict[str, str] = {
    "Bahrain": "BHD",
    "Bangladesh": "BDT",
    "China": "CNY",
    "Falklands": "FKP",
    "Brunei": "BND",
    "Hong Kong": "HKD",
    "UAE": "AED",
    "India": "INR",
    "Vietnam": "VND",
    "United Kingdom": "GBP",
    "United States": "USD",
    "Canada": "CAD",
    "Australia": "AUD",
    "Germany": "EUR",
    "France": "EUR",
    "Saudi Arabia": "SAR",
    "Singapore": "SGD",
}

# Canonical product resolution.  Input tables use "Country followed by 4 or 5
# categories": Consumer Secured, Consumer Unsecured, [Other], SME Banking,
# Wealth Banking/Management.  We map to the 4 output products and IGNORE "Other".
# Any label here is a PRODUCT sub-row, so it is never mistaken for a country.
PRODUCT_CANON = {
    "consumer secured": "Consumer Secured",
    "secured": "Consumer Secured",
    "consumer unsecured": "Consumer Unsecured",
    "unsecured": "Consumer Unsecured",
    "sme banking": "SME Banking",
    "sme": "SME Banking",
    "business banking": "SME Banking",
    "wealth banking": "Wealth Banking",
    "wealth management": "Wealth Banking",
    "wealth lending": "Wealth Banking",
    "wealth": "Wealth Banking",
    "other": "Other",
    "others": "Other",
}
# product sub-rows we ignore entirely (kept out of the 4 output products)
IGNORED_PRODUCTS = {"Other"}

PRODUCT_SUBROWS = set(PRODUCT_CANON.keys())

# canonical input product  ->  the normalised OUTPUT name used everywhere
PRODUCT_OUT_NAME = {
    "Consumer Secured": "Secured",
    "Consumer Unsecured": "Unsecured",
    "SME Banking": "SME Banking",
    "Wealth Banking": "Wealth Lending",
    "Other": "Other",
}
# category (output) -> canonical input product it is built from
CATEGORY_TO_CANON = {
    "Secured": "Consumer Secured",
    "Unsecured": "Consumer Unsecured",
    "SME Banking": "SME Banking",
    "Wealth Lending": "Wealth Banking",
}
CATEGORIES = ["Secured", "Unsecured", "SME Banking", "Wealth Lending"]


def out_product_name(canon_or_label: str) -> str:
    """Map any product label to the normalised output name (Secured, ...)."""
    c = PRODUCT_CANON.get(str(canon_or_label).strip().lower(), canon_or_label)
    return PRODUCT_OUT_NAME.get(c, c)


# --- country-name normalisation (case/space tolerant + aliases) ------------- #
# Handles: "HongKong"=="Hong Kong", "Uae"=="UAE", "Korea SCBK"=="Korea", etc.
_COUNTRY_ALIASES = {
    "southkorea": "korea", "republicofkorea": "korea", "koreasouth": "korea",
    "unitedarabemirates": "uae", "usa": "unitedstates", "us": "unitedstates",
    "uk": "unitedkingdom", "greatbritain": "unitedkingdom",
}
# org suffixes that should be stripped from a country label (e.g. "Korea SCBK")
_COUNTRY_SUFFIXES = ("scbk", "sc", "plc", "ltd", "bank")


def country_key(name: Any) -> str:
    """Canonical key for matching a country name across tables."""
    s = str(name).strip().lower()
    s = re.sub(r"\(.*?\)", "", s)          # drop "(Mainland)", "(SCBK)", etc.
    for suf in (" scbk", " sc", " plc", " ltd", " bank"):
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    s = re.sub(r"[\s\-_.,]", "", s)        # drop spaces and punctuation incl comma
    return _COUNTRY_ALIASES.get(s, s)


import datetime as _dt
_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_month(label: Any) -> str:
    """Format a date-like month header as 'Mon-YY', e.g. 3/31/2026 -> 'Mar-26'.
    Non-date labels are returned unchanged."""
    if label is None:
        return ""
    if isinstance(label, (_dt.datetime, _dt.date, pd.Timestamp)):
        return f"{_MONTHS_ABBR[label.month - 1]}-{str(label.year)[2:]}"
    # Excel serial-date number -> real date (epoch 1899-12-30)
    if isinstance(label, (int, float)):
        try:
            f = float(label)
            if 40000 <= f <= 60000:
                d = _dt.datetime(1899, 12, 30) + _dt.timedelta(days=int(f))
                return f"{_MONTHS_ABBR[d.month - 1]}-{str(d.year)[2:]}"
        except Exception:
            pass
        return str(label)
    s = str(label).strip()
    # already Mon-YY
    if re.match(r"^[A-Za-z]{3}-\d{2}$", s):
        return s
    for fmt in ("%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y",
                "%m-%d-%Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %b %y",
                "%b-%Y", "%b %Y", "%B %Y", "%b-%y", "%Y-%m", "%Y/%m", "%Y%m"):
        try:
            d = _dt.datetime.strptime(s.split(" 00:00")[0], fmt)
            return f"{_MONTHS_ABBR[d.month - 1]}-{str(d.year)[2:]}"
        except Exception:
            continue
    try:
        d = pd.to_datetime(s)
        return f"{_MONTHS_ABBR[d.month - 1]}-{str(d.year)[2:]}"
    except Exception:
        return s


def fmt_months(labels) -> List[str]:
    return [fmt_month(x) for x in labels]


_INVALID_SHEET = re.compile(r"[\[\]:*?/\\]")


def sanitize_sheet_name(name: str, used=None) -> str:
    """Make a string safe as an Excel sheet title: strip / \\ ? * [ ] :, cap at
    31 chars, and de-duplicate against `used` (a set)."""
    s = _INVALID_SHEET.sub("-", str(name)).strip().strip("'")
    s = re.sub(r"\s+", " ", s)[:31] or "Sheet"
    if used is not None:
        base, i = s[:28], 1
        while s in used:
            s = f"{base}_{i}"
            i += 1
        used.add(s)
    return s


def is_product_label(label: str) -> bool:
    return isinstance(label, str) and label.strip().lower() in PRODUCT_CANON


# rows that are country-level totals rather than a real country
TOTAL_ROW_PREFIXES = ("total",)


# ----------------------------------------------------------------------------- #
#  1.  Generic parsers  (understand table *shapes*, not fixed addresses)
# ----------------------------------------------------------------------------- #

def _is_date_like(x: Any) -> bool:
    """True for real date/datetime objects OR strings that look like dates.
    Rejects NaN, None, and bare numbers (data cells must never be dates).

    This must accept datetime.datetime / datetime.date / pandas.Timestamp /
    numpy.datetime64 - when a workbook has genuine Excel date cells, the reader
    returns those types (NOT strings), and missing them means zero date columns
    are found and NO tables are detected."""
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return False
    except Exception:
        pass
    # real temporal types (Timestamp is a subclass of datetime.date, but list
    # them all explicitly so plain datetimes are caught too)
    if isinstance(x, (pd.Timestamp, _dt.datetime, _dt.date)):
        return True
    if 'numpy' in str(type(x)) and 'datetime64' in str(type(x)):
        return True
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return False
        if re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", s):     # 3/31/2025, 31-03-25
            return True
        if re.match(r"^\d{4}[-/]\d{1,2}([-/]\d{1,2})?", s):    # 2025-03, 2025/03/31
            return True
        if re.match(r"^\d{6}$", s):                            # 202503 (YYYYMM)
            return True
        # any string containing a month name + a 2-4 digit year:
        #   'Mar-26', 'Mar 2026', 'March 2026', '31-Mar-2025', '31 Mar 25'
        if re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                     s, re.I) and re.search(r"\d{2,4}", s):
            return True
        return False
    # Excel serial-date numbers (some readers hand back dates as serials).
    # Guard tightly so ordinary data values are never mistaken for dates:
    # 40000..60000 ~ mid-2009 .. late-2064.
    if isinstance(x, (int, float)):
        try:
            return 40000 <= float(x) <= 60000 and float(x) == int(float(x))
        except Exception:
            return False
    return False


def _month_cols(row: List[Any]) -> List[int]:
    """Indices of the date-like columns on a header row."""
    return [i for i, v in enumerate(row) if _is_date_like(v)]


def _blank(x) -> bool:
    """True for None, empty/whitespace string, NaN, NaT, or pd.NA."""
    if x is None:
        return True
    try:
        if pd.isna(x):            # catches float NaN, pandas NaT, pd.NA
            return True
    except (TypeError, ValueError):
        pass                      # arrays / unhashables -> not blank
    if isinstance(x, str):
        return x.strip() == ""
    return False


def _num(x) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        f = float(x)
        return None if pd.isna(f) else f
    except Exception:
        return None


def find_header_row(rows: List[List[Any]], key: str = "country") -> int:
    """
    The header row is the one that carries the month columns (>=2 date-like
    cells).  Among those, prefer one whose first cell mentions ``key``.  This
    skips title rows like 'ENR By country and Product' that merely contain the
    word 'country' but have no dates.
    """
    candidates = [i for i, r in enumerate(rows) if len(_month_cols(r)) >= 2]
    if not candidates:
        # fall back to first row mentioning the key
        for i, r in enumerate(rows):
            if any(isinstance(c, str) and key in c.lower() for c in r):
                return i
        return 0
    for i in candidates:
        first = rows[i][0]
        if isinstance(first, str) and key in first.lower():
            return i
    return candidates[0]


def parse_country_product_block(rows: List[List[Any]],
                                header_key: str = "country") -> "MonthTable":
    """
    Parse the recurring "country header + N product sub-rows" monthly shape.

    Returns a MonthTable exposing:
        .months                 -> list[str] month labels
        .value(country, product, month)
        .series(country, product)  -> dict{month: value}
        .country_total(country)    -> product-less country row (the header row)
        .grand_total()             -> a leading "Total X" row if present
    """
    hdr = find_header_row(rows, header_key)
    mcols = _month_cols(rows[hdr])
    months = [str(rows[hdr][i]) for i in mcols]

    data: Dict[tuple, Dict[str, float]] = {}
    country_rows: Dict[str, Dict[str, float]] = {}
    grand_total: Dict[str, float] = {}
    current_country: Optional[str] = None

    for r in rows[hdr + 1:]:
        label = r[0]
        if not isinstance(label, str) or label.strip() == "":
            continue
        lab = label.strip()
        low = lab.lower()
        series = {m: _num(r[i]) for m, i in zip(months, mcols)}

        if low.startswith(TOTAL_ROW_PREFIXES):
            grand_total = series
            continue
        if is_product_label(lab):
            # a recognised product sub-row (incl. "Other") - NEVER a country
            if current_country is not None:
                data[(current_country, _canon_product(lab))] = series
            continue
        # otherwise it's a new country header
        current_country = lab
        country_rows[lab] = series

    return MonthTable(months, data, country_rows, grand_total)


def _canon_product(label: str) -> str:
    """Normalise a product sub-row label to the canonical input product name.
    Handles the 5-category layout: Consumer Secured / Consumer Unsecured /
    Other / SME Banking / Wealth Banking(=Wealth Management)."""
    return PRODUCT_CANON.get(label.strip().lower(), label.strip())


def parse_country_only(rows: List[List[Any]],
                       header_key: str = "country",
                       start: int = 0, end: Optional[int] = None) -> "MonthTable":
    """Country rows only (no product sub-rows), months as columns."""
    block = rows[start:end] if end else rows[start:]
    hdr = find_header_row(block, header_key)
    mcols = _month_cols(block[hdr])
    months = [str(block[hdr][i]) for i in mcols]
    country_rows: Dict[str, Dict[str, float]] = {}
    for r in block[hdr + 1:]:
        label = r[0]
        if not isinstance(label, str) or label.strip() == "":
            continue
        country_rows[label.strip()] = {m: _num(r[i]) for m, i in zip(months, mcols)}
    return MonthTable(months, {}, country_rows, {})


def parse_stacked_country_only(rows: List[List[Any]]) -> Dict[str, "MonthTable"]:
    """
    Several country-only tables stacked vertically, each introduced by a
    non-'Country' title row (e.g. 'ME AWC in $mn' / 'ME EA (PP & NPP)' / ...).
    Returns {title: MonthTable}.
    """
    out: Dict[str, MonthTable] = {}
    title = None
    buf: List[List[Any]] = []

    def flush():
        nonlocal buf, title
        if title and any(r and r[0] not in (None, "") for r in buf):
            out[title] = parse_country_only(buf)
        buf = []

    for r in rows:
        first = r[0] if r else None
        if isinstance(first, str) and first.strip() and \
                "country" not in first.lower() and not _row_has_data(r):
            # looks like a section title row
            flush()
            title = first.strip()
        buf.append(r)
    flush()
    return out


def _row_has_data(r: List[Any]) -> bool:
    return any(_num(c) is not None for c in r[1:])


def parse_side_by_side(rows: List[List[Any]]) -> Dict[str, "MonthTable"]:
    """
    Two blocks laid out left/right separated by a blank column (policy L2 | L3).
    Returns {'left': MonthTable, 'right': MonthTable} keyed by their titles too.
    """
    # find the blank separator column: the column that is empty on the header row
    hdr = find_header_row(rows, "country")
    header = rows[hdr]
    # locate a gap: a None/'' column with real columns on both sides
    split = None
    for i, v in enumerate(header):
        if _blank(v) and 0 < i < len(header) - 1:
            if any(not _blank(header[j]) for j in range(i)) and \
               any(not _blank(header[j]) for j in range(i + 1, len(header))):
                split = i
                break
    if split is None:  # no gap -> just parse whole thing
        return {"left": parse_country_product_block(rows)}

    left = [r[:split] for r in rows]
    right = [r[split + 1:] for r in rows]
    titles = rows[0]
    lt = str(titles[0]) if titles and not _blank(titles[0]) else "left"
    rt = next((str(titles[i]) for i in range(split + 1, len(titles))
               if i < len(titles) and not _blank(titles[i])), "right")
    return {
        "left": parse_country_product_block(left),
        "right": parse_country_product_block(right),
        "left_title": lt, "right_title": rt,
    }


def parse_gco_quadrants(rows: List[List[Any]]) -> Dict[str, "MonthTable"]:
    """
    GCO % sheet: a 2x2 grid of country-only tables, each titled with the product
    ('... Consumer Unsecured', '... Consumer Secured', '... Business Banking',
    '... Wealth Banking').  Returns {product_canon: MonthTable}.
    """
    # locate the vertical split (blank column) and the horizontal split (blank row)
    ncol = max(len(r) for r in rows)
    grid = [list(r) + [None] * (ncol - len(r)) for r in rows]

    # blank column separating the two horizontal halves
    col_split = None
    for j in range(1, ncol - 1):
        if all(_blank(grid[i][j]) for i in range(len(grid))):
            col_split = j
            break
    # blank row separating the two vertical halves
    row_split = None
    for i in range(1, len(grid) - 1):
        if all(_blank(grid[i][j]) for j in range(ncol)):
            row_split = i
            break

    halves = []
    col_ranges = [(0, col_split)] if col_split else [(0, ncol)]
    if col_split:
        col_ranges.append((col_split + 1, ncol))
    row_ranges = [(0, row_split)] if row_split else [(0, len(grid))]
    if row_split:
        row_ranges.append((row_split + 1, len(grid)))

    out: Dict[str, MonthTable] = {}
    for r0, r1 in row_ranges:
        for c0, c1 in col_ranges:
            sub = [row[c0:c1] for row in grid[r0:r1]]
            # title is the first non-empty cell of the sub-block
            title = None
            for row in sub:
                if row and isinstance(row[0], str) and row[0].strip():
                    title = row[0].strip()
                    break
            if not title:
                continue
            prod = _gco_title_to_product(title)
            out[prod] = parse_country_only(sub)
    return out


def _gco_title_to_product(title: str) -> str:
    t = title.lower()
    if "unsecured" in t:
        return "Consumer Unsecured"
    if "secured" in t:
        return "Consumer Secured"
    if "business" in t or "sme" in t:
        return "SME Banking"
    if "wealth" in t:
        return "Wealth Banking"
    return title


def parse_long(rows: List[List[Any]]) -> pd.DataFrame:
    """ECL/IIP/LI tidy table -> DataFrame (title row skipped)."""
    hdr = 0
    for i, r in enumerate(rows):
        if r and isinstance(r[0], str) and r[0].strip().lower() == "period":
            hdr = i
            break
    cols = [c for c in rows[hdr]]
    body = [r for r in rows[hdr + 1:] if any(c not in (None, "") for c in r)]
    df = pd.DataFrame(body, columns=cols[:len(body[0])] if body else cols)
    return df


def parse_ccpl_volatile(rows: List[List[Any]]) -> Dict[str, float]:
    """Horizontal CCPL Volatile table -> {country_code: pct}."""
    codes_row = vals_row = None
    for r in rows:
        joined = [c for c in r if c not in (None, "")]
        if any(isinstance(c, str) and c in ("Global", "KR", "HK") for c in r):
            codes_row = r
        if any(isinstance(c, str) and c.lower() == "volatile" for c in r):
            vals_row = r
    out: Dict[str, float] = {}
    if codes_row and vals_row:
        for i, code in enumerate(codes_row):
            if isinstance(code, str) and code.strip() and _num(vals_row[i]) is not None:
                out[code.strip()] = _num(vals_row[i])
    return out


def parse_fx(rows: List[List[Any]]) -> Dict[str, float]:
    """Fx Rates -> {ccy_code: rate}."""
    out: Dict[str, float] = {}
    for r in rows:
        if len(r) >= 3 and isinstance(r[1], str) and _num(r[2]) is not None:
            out[r[1].strip()] = _num(r[2])
    return out


# ----------------------------------------------------------------------------- #
#  2.  MonthTable container
# ----------------------------------------------------------------------------- #

@dataclass
class MonthTable:
    months: List[str]
    product_data: Dict[tuple, Dict[str, float]]      # (country, product) -> series
    country_data: Dict[str, Dict[str, float]]        # country -> series
    grand_total: Dict[str, float]

    # --- accessors -------------------------------------------------------- #
    def countries(self) -> List[str]:
        cs = list(self.country_data.keys())
        for (c, _p) in self.product_data:
            if c not in cs:
                cs.append(c)
        return cs

    def series_pp(self, country: str, product: str) -> Optional[Dict[str, float]]:
        rec = self.product_data.get((country, product))
        if rec is not None:
            return rec
        ck = country_key(country)
        for (c, p), s in self.product_data.items():
            if p == product and country_key(c) == ck:
                return s
        return None

    def series_c(self, country: str) -> Optional[Dict[str, float]]:
        rec = self.country_data.get(country)
        if rec is not None:
            return rec
        ck = country_key(country)
        for c, s in self.country_data.items():
            if country_key(c) == ck:
                return s
        return None

    def val(self, series: Optional[Dict[str, float]], month: str) -> Optional[float]:
        return series.get(month) if series else None

    # month helpers
    def current_month(self) -> str:
        return self.months[-1]

    def prior_month(self) -> str:
        return self.months[-2] if len(self.months) > 1 else self.months[-1]

    def month_offset(self, base_idx_from_end: int, back: int) -> Optional[str]:
        idx = len(self.months) - 1 - base_idx_from_end - back
        return self.months[idx] if 0 <= idx < len(self.months) else None


# ----------------------------------------------------------------------------- #
#  3.  Metric maths helpers  (operate on a {month: value} series)
# ----------------------------------------------------------------------------- #

def _get(series, months, idx_from_end):
    if not series:
        return None
    i = len(months) - 1 - idx_from_end
    if i < 0:
        return None
    return series.get(months[i])


def yoy_pct(series, months, base_from_end=0, period=12):
    cur = _get(series, months, base_from_end)
    prev = _get(series, months, base_from_end + period)
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev)


def qoq_pct(series, months, base_from_end=0, period=3):
    cur = _get(series, months, base_from_end)
    prev = _get(series, months, base_from_end + period)
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev)


def latest(series, months, base_from_end=0):
    return _get(series, months, base_from_end)


# ----------------------------------------------------------------------------- #
#  4.  Rating band helpers
# ----------------------------------------------------------------------------- #

def bands_desc(value, thresholds):
    """
    thresholds: list of (lower_bound, rating) in DESCENDING severity, i.e.
    first match where value > bound wins; final entry is the floor rating.
    e.g. [(0.10,'Very High'),(0.05,'High'),(0.03,'Medium'),(0.01,'Low'),
          (None,'Very Low')]
    """
    if value is None:
        return "Not Available"
    for bound, rating in thresholds:
        if bound is None:
            return rating
        if value > bound:
            return rating
    return thresholds[-1][1]


# ----------------------------------------------------------------------------- #
#  End of engine part 1 (parsers + helpers).  Metric config + assembly follow
#  in ira_config.py so thresholds/weights live apart from the machinery.
# ----------------------------------------------------------------------------- #
