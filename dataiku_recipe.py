# -*- coding: utf-8 -*-
"""
dataiku_recipe.py  -  Dataiku Python recipe
===========================================
Reads the input tables from a Dataiku **managed folder** (a single multi-sheet
Excel such as Dummy.xlsx) OR from individual input datasets, runs the IRA engine,
and writes the four product outputs.

------------------------------------------------------------------------------
HOW TO WIRE IT UP IN DATAIKU
------------------------------------------------------------------------------
Option A - single Excel in a folder (matches how you work today)
    * Recipe INPUT  : a managed Folder (e.g. "ira_inputs") holding Dummy.xlsx
    * Recipe OUTPUTS: 4 datasets  -> ira_secured, ira_unsecured,
                                     ira_sme_banking, ira_wealth_lending
      (optional) 1 output Folder  -> to also drop a formatted .xlsx
    * Set INPUT_FOLDER / INPUT_EXCEL_NAME / the OUTPUT_DATASETS below.

Option B - one dataset per input table
    * Point INPUT_DATASETS at the dataset names; each is read with headers off
      (first row kept) so the shape-parsers still work.

The engine lives in the **IRA** package.  Upload the whole `IRA/` folder to the
project library at  lib/python/IRA/  and it imports as `from IRA import ...`
(done below).  This file itself is the *recipe* code - it does NOT go in the
library; paste it into a Dataiku Python recipe.
"""

import io
import pandas as pd
import dataiku

# The IRA library folder must be uploaded to the project library at
# lib/python/IRA/  (see IRA/__init__.py).  Import it as a package:
try:
    from IRA import ira_loaders as L
    from IRA import ira_build as B
    from IRA import ira_engine as E
except ImportError:            # fallback if the modules sit flat on the path
    import ira_loaders as L
    import ira_build as B
    import ira_engine as E

# ------------------------------------------------------------------ CONFIG -- #
INPUT_FOLDER = "ira_inputs"          # managed folder holding the Excel
INPUT_EXCEL_NAME = "Dummy.xlsx"      # file name inside that folder

OUTPUT_DATASETS = {
    "IRA - Secured":        "ira_secured",
    "IRA - Unsecured":      "ira_unsecured",
    "IRA - SME Banking":    "ira_sme_banking",
    "IRA - Wealth Lending": "ira_wealth_lending",
}
OUTPUT_FOLDER = None                 # e.g. "ira_outputs" to also write an xlsx
OUTPUT_EXCEL_NAME = "IRA_Output.xlsx"

INTERMEDIATE_DATASET = "ira_intermediate"   # long table of all calculated values (or None)
MAPPING_DATASET = "ira_label_mapping"       # label -> table -> calculation (or None)

# Editable per-category country list. Point this at a dataset with columns
# Category, Country, Include (Yes/No). Leave None to auto-detect.
COUNTRIES_DATASET = "ira_countries_config"

# If you prefer one dataset per input table (Option B), map them here and set
# USE_DATASETS = True.  Keys must match the sheet names ira_loaders expects.
USE_DATASETS = False
INPUT_DATASETS = {
    # "ENR": "enr_dataset",
    # "90+%": "dpd90_pct_dataset",
    # ...
}


# ------------------------------------------------------------------ READ ---- #
def read_sheets_from_folder():
    """Return {sheet_name: list_of_rows} from the Excel in the input folder,
    forcing cached formula values (input files are full of formulas)."""
    import openpyxl
    folder = dataiku.Folder(INPUT_FOLDER)
    with folder.get_download_stream(INPUT_EXCEL_NAME) as stream:
        data = stream.read()
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    sheets = {}
    for ws in wb.worksheets:
        sheets[ws.title] = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return sheets


def read_sheets_from_datasets():
    sheets = {}
    for sheet_name, ds_name in INPUT_DATASETS.items():
        df = dataiku.Dataset(ds_name).get_dataframe(infer_with_pandas=False)
        sheets[sheet_name] = df.values.tolist()
    return sheets


# ------------------------------------------------------------------ MAIN ---- #
def main():
    sheets = read_sheets_from_datasets() if USE_DATASETS \
        else read_sheets_from_folder()

    tables = L.load_tables(sheets)

    # per-category country selection from an editable dataset (Category, Country, Include)
    countries_per_category = None
    if COUNTRIES_DATASET:
        try:
            cdf = dataiku.Dataset(COUNTRIES_DATASET).get_dataframe()
            sel = {}
            for _, r in cdf.iterrows():
                inc = str(r.get("Include", "")).strip().lower() in (
                    "yes", "y", "true", "1", "t")
                cat, ctry = str(r.get("Category", "")).strip(), str(r.get("Country", "")).strip()
                if inc and cat and ctry:
                    sel.setdefault(cat, []).append(ctry)
            countries_per_category = sel or None
        except Exception as ex:
            print("Country config dataset not usable, auto-detecting:", ex)

    frames = B.build_all(tables, countries_per_category=countries_per_category)

    # write the four final datasets
    for sheet_name, ds_name in OUTPUT_DATASETS.items():
        dataiku.Dataset(ds_name).write_with_schema(frames[sheet_name])

    # intermediate (calculated) tables + label mapping
    per_cat = B.resolve_countries(tables, None, countries_per_category)
    all_countries = sorted({c for v in per_cat.values() for c in v})
    per_cat_d = B.resolve_countries(tables, None, countries_per_category)
    inter = B.build_intermediate_frames(tables, per_cat_d)
    mapping = B.build_mapping()

    #   a) one long "intermediate" dataset (all metric families, tagged)
    if INTERMEDIATE_DATASET:
        long = []
        for title, df in inter.items():
            d = df.copy()
            d.insert(0, "Intermediate", title)
            long.append(d)
        if long:
            dataiku.Dataset(INTERMEDIATE_DATASET).write_with_schema(
                pd.concat(long, ignore_index=True))
    #   b) the label -> table -> calculation mapping dataset
    if MAPPING_DATASET:
        dataiku.Dataset(MAPPING_DATASET).write_with_schema(mapping)

    # optionally drop formatted Excels into an output folder
    if OUTPUT_FOLDER:
        folder = dataiku.Folder(OUTPUT_FOLDER)
        buf = io.BytesIO()
        _used=set()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            for sheet_name, df in frames.items():
                df.to_excel(xw, sheet_name=E.sanitize_sheet_name(sheet_name, _used), index=False)
        buf.seek(0)
        folder.upload_stream(OUTPUT_EXCEL_NAME, buf)

        buf2 = io.BytesIO()
        with pd.ExcelWriter(buf2, engine="openpyxl") as xw:
            _used2=set(); mapping.to_excel(xw, sheet_name="Label Mapping", index=False); _used2.add("Label Mapping")
            for title, df in inter.items():
                df.to_excel(xw, sheet_name=E.sanitize_sheet_name(title, _used2), index=False)
        buf2.seek(0)
        folder.upload_stream("IRA_Output_Intermediate.xlsx", buf2)


if __name__ == "__main__":
    main()
