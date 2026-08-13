"""
ira_io.py
=========
Robust workbook reading.

Input workbooks are FULL OF FORMULAS (e.g. Total ENR = =B4+B9+B14). Depending on
the pandas / openpyxl version, ``pd.read_excel`` can hand back the *formula
strings* instead of the computed numbers - and then every value parses to None,
every metric shows "Not Available", and it looks like no tables were detected.

``read_workbook`` reads with openpyxl ``data_only=True`` so formula cells return
their last cached result. If the cache is missing (a file written by a library
that never computed the formulas), it falls back to ``pd.read_excel`` and flags
the affected sheets.
"""

from __future__ import annotations
from typing import Dict, List, Any, Tuple
import openpyxl
import pandas as pd


def read_workbook(path: str) -> Dict[str, List[List[Any]]]:
    """Return {sheet_name: rows} using cached formula values."""
    sheets, _warn = read_workbook_checked(path)
    return sheets


def read_workbook_checked(path: str) -> Tuple[Dict[str, List[List[Any]]], List[str]]:
    """Same as read_workbook but also returns a list of warnings (sheets whose
    formulas had no cached value and were back-filled from pandas)."""
    warnings: List[str] = []
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets: Dict[str, List[List[Any]]] = {}
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        sheets[ws.title] = _trim(rows)
    wb.close()

    # detect sheets where formulas had no cache (lots of None where pandas differs)
    empties = [name for name, rows in sheets.items() if _looks_empty(rows)]
    if empties:
        try:
            pd_sheets = pd.read_excel(path, sheet_name=None, header=None)
            for name in empties:
                if name in pd_sheets:
                    filled = _trim(pd_sheets[name].values.tolist())
                    if not _looks_empty(filled):
                        sheets[name] = filled
                        warnings.append(
                            f"{name}: openpyxl cache empty; used pandas values")
        except Exception as ex:                       # pragma: no cover
            warnings.append(f"pandas fallback failed: {ex}")
    return sheets, warnings


def _trim(rows: List[List[Any]]) -> List[List[Any]]:
    """Drop fully-empty trailing rows/columns to keep parsing clean."""
    def empty(v):
        return v is None or (isinstance(v, str) and v.strip() == "")
    # trailing empty rows
    while rows and all(empty(c) for c in rows[-1]):
        rows.pop()
    return rows


def _looks_empty(rows: List[List[Any]]) -> bool:
    """True if there is no numeric data anywhere (only labels / None)."""
    for r in rows:
        for c in r:
            if isinstance(c, (int, float)) and not isinstance(c, bool):
                return False
    return True
