"""
ira_countries.py
================
Per-category country selection, driven by an editable input list.

The pipeline decides which countries each category (Secured / Unsecured /
SME Banking / Wealth Lending) is run for from ONE editable source:

    countries_config.csv   with columns:  Category, Country, Include

    Category   one of: Secured, Unsecured, SME Banking, Wealth Lending
    Country    a country name (must match the input tables, e.g. Bahrain)
    Include    Yes / No  (also accepts Y/N, TRUE/FALSE, 1/0)

`load(path)` -> {category: [countries with Include=Yes]}.
If the file is missing, the pipeline falls back to auto-detection.

`write_template(path, tables)` seeds the file from whatever countries the
current workbook contains, so you get a ready-to-edit list.
"""

from __future__ import annotations
from typing import Dict, List, Any
import csv
import os

try:
    from . import ira_engine as E
    from . import ira_build as B
except ImportError:
    import ira_engine as E
    import ira_build as B


_TRUE = {"yes", "y", "true", "1", "t", "include", "x"}
_NON_COUNTRY = {"total", "group", "global", "grand total", "country",
                "country and product", ""}


def universe(tables: Dict[str, Any]) -> List[str]:
    """Every real country seen anywhere in the workbook (for the template)."""
    seen: List[str] = []

    def add(c):
        if isinstance(c, str) and c.strip().lower() not in _NON_COUNTRY \
                and not c.strip().lower().startswith("total") and c not in seen:
            seen.append(c.strip())

    # country+product block tables
    for key in ("ENR", "30+%", "30+$", "90+%", "90+$", "RWA"):
        t = tables.get(key)
        if t:
            for c in t.country_data:
                add(c)
            for (c, _p) in t.product_data:
                add(c)
    # stacked / country-only tables (GCO, ME, PvB, LTV)
    for key in ("ME_EA_AWC", "PvB_EA_AWC", "gco"):
        grp = tables.get(key)
        if isinstance(grp, dict):
            for sub in grp.values():
                for c in getattr(sub, "country_data", {}):
                    add(c)
    for key in ("LTV80",):
        t = tables.get(key)
        if t:
            for c in t.country_data:
                add(c)
    return seen


def load(path: str) -> Dict[str, List[str]]:
    """Read the include-list CSV -> {category: [countries]}.  {} if missing/empty."""
    if not path or not os.path.exists(path):
        return {}
    out: Dict[str, List[str]] = {c: [] for c in E.CATEGORIES}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            cat = (row.get("Category") or "").strip()
            country = (row.get("Country") or "").strip()
            inc = (row.get("Include") or "").strip().lower()
            if cat in out and country and inc in _TRUE:
                if country not in out[cat]:
                    out[cat].append(country)
    # drop categories left empty so caller can fall back for those
    return {k: v for k, v in out.items() if v}


def write_template(path: str, tables: Dict[str, Any]) -> Dict[str, List[str]]:
    """Seed an editable CSV: every (category, country), Include=Yes where the
    category actually has data for that country in its core tables, else No."""
    all_countries = universe(tables)
    available = {cat: set(B.countries_for_category(tables, cat)) for cat in E.CATEGORIES}
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Category", "Country", "Include"])
        for cat in E.CATEGORIES:
            for country in all_countries:
                inc = "Yes" if country in available[cat] else "No"
                w.writerow([cat, country, inc])
    return load(path)


def sync_template(path: str, tables: Dict[str, Any]) -> Dict[str, Any]:
    """Reconcile an existing config with the current workbook.

    * Preserves any Include choices already in the file.
    * ADDS rows for countries in this workbook that the file doesn't mention
      (default Yes if the category has data for it, else No).
    * Reports what changed.  If the file doesn't exist, it is created.

    Returns {"created": bool, "added": [(cat, country, inc), ...],
             "config": {category: [countries]}}.
    """
    if not path or not os.path.exists(path):
        write_template(path, tables)
        return {"created": True, "added": [], "config": load(path)}

    # read existing rows, keep order + choices
    existing = {}
    order = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            cat = (row.get("Category") or "").strip()
            country = (row.get("Country") or "").strip()
            inc = (row.get("Include") or "").strip() or "No"
            if cat and country:
                existing[(cat, country)] = inc
                order.append((cat, country))

    all_countries = universe(tables)
    available = {cat: set(B.countries_for_category(tables, cat)) for cat in E.CATEGORIES}
    added = []
    for cat in E.CATEGORIES:
        for country in all_countries:
            if (cat, country) not in existing:
                inc = "Yes" if country in available[cat] else "No"
                existing[(cat, country)] = inc
                order.append((cat, country))
                added.append((cat, country, inc))

    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Category", "Country", "Include"])
        for key in order:
            w.writerow([key[0], key[1], existing[key]])
    return {"created": False, "added": added, "config": load(path)}
