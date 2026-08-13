"""
ira_preview.py
=============
Produces the "yes, this was detected, and here is the table" output.

For EVERY sheet it applies the simple, general rule the data follows:
    * the header row is the row carrying the date columns,
    * the first column is the text/key column,
    * every date-like column is a month (shown as Mar-26),
and returns:
    1) a one-row-per-sheet DETECTION SUMMARY (shape, header row, key column,
       # date columns, month range, # data rows, status), and
    2) a cleaned tidy table per sheet (key column + Mar-26 month columns),
       so you can eyeball that detection worked.

This is deliberately independent of the metric logic - it just proves the
columns were understood.
"""

from __future__ import annotations
from typing import Dict, List, Any, Tuple
import pandas as pd

try:
    from . import ira_engine as E
except ImportError:
    import ira_engine as E


def detect_sheet(rows: List[List[Any]]) -> Dict[str, Any]:
    """Detect the header row, key column and month columns of one sheet."""
    info = dict(header_row=None, key_column=None, n_date_cols=0,
                month_range="", n_data_rows=0, months=[], date_col_idx=[],
                status="", note="")
    if not rows:
        info["status"] = "EMPTY"
        info["note"] = "sheet has no rows"
        return info

    # header row = the row with the most date-like cells (>= 2)
    best_i, best_n = None, 1
    for i, r in enumerate(rows[:8]):          # header is near the top
        n = len(E._month_cols(r))
        if n > best_n:
            best_i, best_n = i, n
    if best_i is None:
        info["status"] = "NO DATE COLUMNS"
        info["note"] = ("no row had 2+ date-like headers - is this a reference "
                        "table rather than a monthly table?")
        return info

    hdr = rows[best_i]
    date_idx = E._month_cols(hdr)
    months = [E.fmt_month(hdr[i]) for i in date_idx]
    data_rows = [r for r in rows[best_i + 1:]
                 if r and not _blank(r[0])]
    info.update(header_row=best_i + 1,            # 1-based for humans
                key_column=str(hdr[0]) if hdr and hdr[0] is not None else "(col 1)",
                n_date_cols=len(date_idx), date_col_idx=date_idx,
                months=months,
                month_range=(f"{months[0]} .. {months[-1]}" if months else ""),
                n_data_rows=len(data_rows), status="OK")
    return info


def clean_table(rows: List[List[Any]], info: Dict[str, Any]) -> pd.DataFrame:
    """Cleaned tidy table: key column + Mar-26 month columns."""
    if info["status"] != "OK":
        return pd.DataFrame()
    hdr_i = info["header_row"] - 1
    hdr = rows[hdr_i]
    key_name = info["key_column"] or "Key"
    cols = [key_name] + info["months"]
    out = []
    for r in rows[hdr_i + 1:]:
        if not r or _blank(r[0]):
            continue
        row = {key_name: r[0]}
        for idx, m in zip(info["date_col_idx"], info["months"]):
            row[m] = r[idx] if idx < len(r) else None
        out.append(row)
    return pd.DataFrame(out, columns=cols)


def _blank(x):
    return x is None or (isinstance(x, str) and x.strip() == "")


# recognise which structural shape each sheet is (for the summary)
def _shape_hint(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("30+", "90+", "enr", "rwa", "app rate",
                            "monthly new")):
        return "country + product block"
    if "policy exception" in n:
        return "side-by-side (L2 | L3)"
    if "gco" in n:
        return "2x2 product quadrants"
    if " me ea" in n or "pvb ea" in n:
        return "stacked country-only"
    if "ppi" in n or "ltv" in n or "interest" in n:
        return "country-only monthly"
    if "ccpl" in n:
        return "horizontal (codes across a row)"
    if "fx" in n:
        return "reference (currency -> rate)"
    if "ecl" in n:
        return "long / tidy"
    return "generic (key + dates)"


def build_preview(sheets: Dict[str, List[List[Any]]]
                  ) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """Return (summary_df, {sheet: cleaned_df})."""
    summary_rows = []
    cleaned: Dict[str, pd.DataFrame] = {}
    for name, rows in sheets.items():
        info = detect_sheet(rows)
        summary_rows.append({
            "Sheet": name,
            "Detected shape": _shape_hint(name),
            "Status": info["status"],
            "Header row": info["header_row"] if info["header_row"] else "",
            "Key column": info["key_column"] or "",
            "# Date columns": info["n_date_cols"],
            "Month range": info["month_range"],
            "# Data rows": info["n_data_rows"],
            "Note": info["note"],
        })
        df = clean_table(rows, info)
        if not df.empty:
            cleaned[name] = df
    summary = pd.DataFrame(summary_rows, columns=[
        "Sheet", "Detected shape", "Status", "Header row", "Key column",
        "# Date columns", "Month range", "# Data rows", "Note"])
    return summary, cleaned
