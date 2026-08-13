# -*- coding: utf-8 -*-
"""
dataiku_diagnostics_recipe.py  -  Dataiku Python recipe
=======================================================
Audits the input workbook against the expected-table registry and emits the
"meta output": a per-table checks dataset (+ optional formatted Excel report).

Run this BEFORE the main build recipe to see, up front, exactly what data is
present / missing / mis-read.

WIRING
    INPUT : managed Folder holding the Excel (INPUT_FOLDER / INPUT_EXCEL_NAME)
    OUTPUT: dataset  ira_input_checks         (one row per expected table)
            (optional) Folder for the .xlsx report

The IRA library folder must be at  lib/python/IRA/.
"""

import io
import pandas as pd
import dataiku

try:
    from IRA import ira_diagnostics as D
except ImportError:
    import ira_diagnostics as D

# ------------------------------------------------------------------ CONFIG -- #
INPUT_FOLDER = "ira_inputs"
INPUT_EXCEL_NAME = "Dummy.xlsx"
OUTPUT_DATASET = "ira_input_checks"        # per-table checks
OUTPUT_FOLDER = None                        # e.g. "ira_outputs" to also drop xlsx
REPORT_NAME = "IRA_Input_Diagnostics.xlsx"


def read_sheets():
    folder = dataiku.Folder(INPUT_FOLDER)
    with folder.get_download_stream(INPUT_EXCEL_NAME) as stream:
        data = stream.read()
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    sheets = {ws.title: [list(r) for r in ws.iter_rows(values_only=True)]
              for ws in wb.worksheets}
    wb.close()
    return sheets


def main():
    sheets = read_sheets()
    records, summary = D.audit(sheets)

    # flatten records to a tidy dataset
    rows = [{
        "status": r["status"], "severity": r["severity"], "table": r["display"],
        "matched_sheet": r["matched_sheet"], "shape": r["shape"],
        "n_months": r["n_months"], "month_range": r["month_range"],
        "n_countries": r["n_countries"], "countries": r["countries"],
        "n_products": r["n_products"], "products": r["products"],
        "used_by": r["used_by"], "issues": " | ".join(r["issues"]),
        "note": r["note"],
    } for r in records]
    checks_df = pd.DataFrame(rows)
    dataiku.Dataset(OUTPUT_DATASET).write_with_schema(checks_df)

    print("Verdict:", summary["verdict"],
          "| OK:", summary["ok"],
          "| Errors:", summary["errors"],
          "| Warnings:", summary["warnings"])

    if OUTPUT_FOLDER:
        import tempfile, os
        tmp = os.path.join(tempfile.gettempdir(), REPORT_NAME)
        D.write_report(records, summary, tmp)
        with open(tmp, "rb") as fh:
            dataiku.Folder(OUTPUT_FOLDER).upload_stream(REPORT_NAME, fh)


if __name__ == "__main__":
    main()
