# IRA Credit Risk — Dataiku web app (light, workflow edition)

Guided flow: **Details & files → Data checks → Results & approval**, with
managed-folder saves, a Tableau scenario trigger, per Product+Country override,
and run history. The IRA engine in `lib/python/IRA` is **not modified**.

## 1. Project library
Put the `IRA/` package in **Libraries ▸ Python** → `lib/python/IRA/` (unchanged).

## 2. One managed folder for storage
Create a **managed folder** (Flow ▸ +Dataset ▸ Folder). Note its name/ID and set
it at the top of `backend.py`:
```python
STORE_FOLDER    = "IRA_STORE"            # <-- your managed folder name or id
TABLEAU_SCENARIO= "UPLOAD_TO_TABLEAU"    # <-- your scenario id for the Tableau push
PROJECT_KEY     = None                    # None = current project
```
The app writes, inside that folder:
```
outputs/<run_id>.xlsx      formatted workbook (with override rows once approved)
overrides/<run_id>.csv     per Product+Country override table  (point 6)
runs/<run_id>.json         run metadata for the history panel
```

## 3. Tableau scenario
Create a **scenario** that publishes/refreshes your Tableau data (e.g. a
“Sync to Tableau” step or an exporter). Put its id in `TABLEAU_SCENARIO`.
The **Trigger Tableau upload** button calls `project.get_scenario(id).run()`.

## 4. Create the web app
**Web apps ▸ +New ▸ Standard**, name **IRA Credit Risk**, paste:

| Tab   | File         |
|-------|--------------|
| HTML  | `app.html`   |
| CSS   | `style.css`  |
| JS    | `script.js`  |
| Python| `backend.py` |

Enable the **Python backend**, Save, Start backend. Grant the backend
**write access** to the managed folder and **run** permission for the scenario
(web app runs as its owner; ensure that user can write the folder / run the scenario).

## Using it
1. **Details & files** — enter name, quarter, year; drop MI file (req), Other
   tables (opt), Countries config (req); click **Run checks & process**.
2. **Data checks** — see `Table | Available (Y/N)` and every Not-Available value
   (product, country, label, reason).
3. **Results & approval** — pick **Product** + **Country** to see
   `Label | Value | Risk Rating | Risk Number`, including *Calculated* and
   *Final Inherent Credit Risk Assessment (with Override)*. Set an override
   rating + justification per Product+Country. Then:
   - **Send output to Dataiku folder** → writes `outputs/<run_id>.xlsx`
   - **Trigger Tableau upload** → runs the scenario
   - **Approve & finalize** → writes `overrides/<run_id>.csv` + finalized run
   - **Download Excel** → downloads the workbook

**Recent runs** on step 1 lists prior runs (user, quarter, year, time, status)
from `runs/`.

## Preview without Dataiku
Open `../IRA_CreditRisk_UI_preview.html` in a browser — the full light UI runs
against an embedded sample (backend mocked).

## Local test of the data layer
`run_analysis(mi, other, config, user, quarter, year)` in `backend.py` is pure
and testable; folder writes fall back to `./ira_store` when Dataiku isn’t present
(set `IRA_STORE_DIR` to change the path).
