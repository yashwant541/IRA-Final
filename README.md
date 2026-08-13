# Inherent Risk Assessment (IRA) pipeline

Builds the four IRA output tables — **Secured / Unsecured / SME Banking /
Wealth Lending** — from the monthly input tables (`Dummy.xlsx` shape), exactly
as laid out in *Formulas to be built.xlsx*.

Runs identically **locally** and **inside Dataiku** — the same engine powers
both; only the read/write layer differs.

## Layout

```
IRA/                     <-- upload this whole folder to Dataiku: lib/python/IRA/
  __init__.py            package init (exposes the modules)
  ira_engine.py          shape-aware parsers + maths + 1-5 risk-number lookup
  ira_config.py          metric definitions, thresholds, groups, weights
  ira_intermediate.py    CALCULATED layer: YoY/QoQ/%-of-total/... (+ reasons)
  ira_build.py           value -> rating -> risk number -> final + mapping
  ira_loaders.py         raw sheets -> parsed tables (+ dummy fill)
  ira_registry.py        SINGLE SOURCE OF TRUTH: every expected input table
  ira_diagnostics.py     audits a workbook vs the registry -> meta report
dataiku_recipe.py              the BUILD recipe   (imports `from IRA import ...`)
dataiku_diagnostics_recipe.py  the CHECKS recipe  (emits the meta report)
run_local.py             local build -> IRA_Output.xlsx + _Intermediate.xlsx
run_diagnostics.py       local audit -> IRA_Input_Diagnostics.xlsx
IRA_Output.xlsx              final four IRA tables (with NA reasons)
IRA_Output_Intermediate.xlsx calculated tables + Label Mapping
IRA_Input_Diagnostics.xlsx   meta report (Summary + Table checks)
README.md
```

## Input diagnostics (the "meta output") — run this first

Audits the workbook against the expected-table registry and reports, per table,
whether it is present / missing / empty / ambiguous / mis-shaped, plus which
output metric depends on it.

```bash
python run_diagnostics.py Dummy.xlsx IRA_Input_Diagnostics.xlsx
```

Two sheets: **Summary** (verdict + counts + missing / fabricated / unknown
lists) and **Table checks** (one colour-coded row per table: status, matched
sheet, detected shape, month range, #countries, #products, the metrics it feeds,
and any issues). Statuses: `OK · EMPTY · MISSING · COLLISION · SHAPE_ISSUE ·
FABRICATED · UNKNOWN`. Add a new expected input by adding **one row** to
`ira_registry.py`.

## Start here — Detection Report (simplified processed input)

Before anything else, confirm every table is being read correctly:

```bash
python run_detect.py Dummy.xlsx IRA_Detection_Report.xlsx
```

`IRA_Detection_Report.xlsx` contains a **Detection Summary** (one row per table:
Detected Yes/NO, detected shape, month range like `Mar-25 - Mar-26`, # countries,
# products, notes) plus **one sheet per detected table** holding the cleaned data
(`Country · Product · Mar-25 … Mar-26`, normalised product names). It is
standalone and never crashes — an unreadable sheet is reported as `NO` with the
reason, so you can see exactly what was and wasn't picked up.

## Outputs (produced in this order — intermediates before finals)

| File | Contents |
|---|---|
| `IRA_Normalized_Inputs.xlsx` | Each country+product source reshaped to **long form** — `Country · Product · Mar-25 … Mar-26` — with a `Total` row per country and **output product names**. One sheet per source. |
| `IRA_ByCategory.xlsx` | For each core source, **four per-category tables** (e.g. `ENR-Secured`, `30+%-Wealth Lending`): one product per sheet, `Mar-26` headers. |
| `IRA_Intermediate.xlsx` | `Mapping` (per category: label → source table → calculation) + every **calculated** metric table (YoY/QoQ/%-of-total/…) with the components used and a **Reason** per cell. |
| `IRA_Output.xlsx` | The four final IRA tables; missing cells show `Not Available - <reason>`. |
| `IRA_Input_Diagnostics.xlsx` | The input audit (Summary + Table checks). |

### Product names — normalised everywhere
`Consumer Secured → Secured`, `Consumer Unsecured → Unsecured`, `SME Banking`,
`Wealth Banking / Wealth Management → Wealth Lending`, `Other → ignored`. The
four categories are **Secured / Unsecured / SME Banking / Wealth Lending**
throughout inputs, intermediates, mapping and finals.

### Dates — `Mar-26` format
All intermediate/normalized headers use `Mon-YY` (e.g. `3/31/2026 → Mar-26`). The
**rightmost** month column is the current month; the column to its left is the
prior month.

### Countries per category — editable input list
Coverage is driven by **`countries_config.csv`** (columns `Category, Country,
Include`). Set `Include` to `Yes`/`No` per row to choose which countries each
category runs for, then re-run. The file is **auto-seeded** on first run from
the countries found in the workbook (core-available countries pre-set to `Yes`,
others listed as `No` so you can switch them on). If the file is absent the
pipeline auto-detects. In Dataiku, point `COUNTRIES_DATASET` at an editable
dataset with the same three columns.

### Fixed — "Invalid character / found in sheet title"
Intermediate names like *EA / ENR* and *LTV>80* contain characters Excel forbids
in sheet titles. All sheet names are now sanitised (`/ \ : * ? [ ]` removed,
capped at 31 chars, de-duplicated), so the writer no longer crashes.

## Fixed — input files are full of formulas (this is why "no tables were detected")

The input sheets contain Excel **formulas** (e.g. `Total ENR = =B4+B9+B14`, 52 in
the ENR sheet alone). Depending on the pandas/openpyxl version, `pd.read_excel`
can return the **formula text** instead of the computed number — then every
value parses to blank, every metric shows Not Available, and it looks like *no
tables were detected at all*. All reading now goes through `IRA/ira_io.py`, which
opens the workbook with openpyxl `data_only=True` to get each formula's **cached
result** (with a pandas fallback if a sheet has no cache). This is the fix for
the "not able to detect any tables" symptom.

## Detection Preview — run this first

`IRA_Detection_Preview.xlsx` proves each sheet was understood. It has a
**Detection Summary** (per sheet: detected shape, status, header row, key column,
# date columns, month range, # data rows) plus a **cleaned tidy table** per sheet
(key column + `Mar-26` month columns with the real values). On the sample, 14/18
sheets are detected as monthly tables; the other 4 are correctly flagged as
non-monthly (ECL = long/tidy, Interest Rates = empty, Fx & CCPL = reference).
The detector uses the simple, general rule the data follows: the header row is
the one carrying the date columns, column 1 is the text key, every date-like
column is a month.

## Fixed — 5-category layout ("Other" / "Wealth Management") broke parsing

Real input tables list **Country followed by 4 or 5 categories**:
`Consumer Secured · Consumer Unsecured · Other · SME Banking · Wealth
Banking/Management`. The old parser only knew 4 labels, so **"Other" and
"Wealth Management" were mistaken for country headers** — which polluted the
country list and meant "Wealth Banking" was never found, collapsing **all Wealth
metrics (and anything after an "Other" row) to Not Available**. The parser now
recognises the full set, maps

```
Consumer Secured   -> Secured
Consumer Unsecured -> Unsecured
SME Banking        -> SME Banking
Wealth Banking / Wealth Management -> Wealth Lending
Other              -> ignored
```

and never treats a product row as a country. This is the main reason so many
labels showed Not Available.

## Intermediate (calculated) layer + label mapping

The pipeline now runs **raw → intermediate → final** (bronze → silver → gold):

* `IRA/ira_intermediate.py` computes one calculated table per metric family —
  ENR YoY, DPD QoQ (current/prior), DPD YoY, DPD %-of-group-total, policy-
  exception rate, EA/AWC proportions, LTV, volatile, PPI YoY, interest-rate
  increase, plus the reference lookups — each keyed by (country, product), with
  the **input components used** and a plain-English **Reason** whenever a value
  can't be produced.
* `run_local.py` writes these as **`IRA_Output_Intermediate.xlsx`** (one sheet
  per intermediate table, Reason cells highlighted) plus a **`Label Mapping`**
  sheet: for every label 1a…2d, which **source table** it reads and **what
  calculation** it performs. The metric extractors read from these
  intermediates, so the finals and the intermediate tables always agree.

## Why a cell is "Not Available"

Every metric now carries a reason. When a value is missing, the finals show it
in the last column (`Not Available - <reason>`), e.g. *"no PPI row for currency
CNY (China)"* or *"Falklands not in EA table"*. On the sample only 6 cells
remain Not Available — all genuine missing source rows, each explained — versus
whole columns before.

## Fixed — `%` vs `$` sheet-name collision

The earlier name matcher stripped punctuation, so `30+%`/`30+$` (and
`90+%`/`90+$`) both collapsed to `30`/`90`, and the **percent tables silently
received the dollar tables' data**. The matcher now preserves `%` and `$`, and
the diagnostics flags any two tables resolving to the same sheet (`COLLISION`).
The sample's four DPD sheets happen to hold identical dummy numbers, so the demo
output values are unchanged — but on real data this was corrupting Secured 1d
and the delinquency metrics.

## Files

| File | Role |
|---|---|
| `IRA/ira_engine.py` | Shape-aware **parsers** (country+product blocks, country-only, 2×2 quadrant, side-by-side L2/L3, stacked, long, horizontal) + maths helpers + the 1–5 risk-number lookup. No Dataiku, no config. |
| `IRA/ira_config.py` | The **metric definitions**: per product, each metric's value extractor, its risk-rating threshold ladder (transcribed from the IF-formulas), its aggregation group, and its weight. **This is the only file you edit** to change thresholds/weights/metrics. |
| `IRA/ira_build.py` | Orchestration: value → rating → risk-number → weighted final assessment → output DataFrames. |
| `IRA/ira_loaders.py` | Maps raw sheets to parsed tables and **fabricates the missing tables** with clearly-marked dummy data. |
| `IRA/ira_registry.py` | The list of every expected input table: accepted sheet names, shape, required/optional, which metrics use it, whether it is dummy-filled. |
| `IRA/ira_diagnostics.py` | Runs the audit → `records + summary`; renders the Excel report and a console summary. |
| `dataiku_recipe.py` | The Dataiku **build** recipe — reads the Excel, writes 4 output datasets (+ optional xlsx). |
| `dataiku_diagnostics_recipe.py` | The Dataiku **checks** recipe — writes the per-table checks dataset (+ optional xlsx report). |
| `run_local.py` / `run_diagnostics.py` | Local runners for the build and the audit. |

## How the output is produced (per country, per product)

1. **Value** (column C) — computed straight from the input tables per the
   *"What to do in Value Column"* instructions.
2. **Risk Rating** (column D) — the value bucketed through that metric's
   IF-threshold ladder → Very Low … Very High (or *Not Available* when the input
   is missing).
3. **Risk Number** (column E) — `Very Low=1 … Very High=5` (the AV:AZ table).
4. **Calculated Inherent Credit Risk Assessment** — for each aggregation group,
   take the group's risk number (a single metric, or the **worst** in a
   `MAX(...)` group), multiply by the group weight, sum, then band:
   `≥4.5 Very High · ≥3.5 High · ≥2.5 Medium · ≥1.5 Low · else Very Low`.

## What you need to supply (marked TODO in `ira_config.py`)

* **Weights (BB:BD table).** Placeholders that sum to 100% per product are in
  `GROUPS`. Drop in your real weights (e.g. *1a = 10.25%*, …) — nothing else
  changes. The grouping mirrors the `MAX(...)` blocks in the template's
  final-row formula; confirm it matches your intended formula.

## Tables fabricated as dummy (not present in `Dummy.xlsx`)

`ira_loaders.py` generates these so the pipeline runs end-to-end. Replace each
generator with a real parser once the data exists — expected schema:

| Table | Shape expected |
|---|---|
| **Country Sovereign Rating & Outlook** | one row per country: `Outlook` ∈ {Positive, Stable, Negative}; `FCY CRG` ∈ grades like `1A, 5B, 11A, 13` |
| **Active Dispensations** (Secured/Unsecured/SME/Wealth) | per country: count of *Active* (and *Expired*) dispensations |
| **Credit Risk Appetite Breaches** | per country (optionally per product): # breaches in last 12 months |
| **Interest Rates** | the `Interest Rates` sheet is empty; supply country × month rates. Metric 2a = last month − trailing average |

## Key conventions (all easy to change in `ira_config.py` / `ira_engine.py`)

* Current month = last date column; prior month = second-last.
* **YoY** = current vs 12 columns back. **QoQ** = a month vs 3 columns back.
* Product map: Secured→`Consumer Secured`, Unsecured→`Consumer Unsecured`,
  SME Banking→`SME Banking`, Wealth Lending→`Wealth Banking`.
* Countries are discovered from the core product-block tables (ENR/DPD).

## Notes on the demo numbers

The dummy tables are random 0–1 values while some thresholds/units assume real
percentages or `$mn` (e.g. EA/AWC ÷ ENR). With real same-unit data these
ratios become sensible fractions; the *logic* is unaffected.

## Run locally

```bash
python run_local.py Dummy.xlsx IRA_Output.xlsx
```

## Run in Dataiku

1. Upload the whole **`IRA/`** folder to the project library so it lands at
   `lib/python/IRA/` (Project → Libraries → Python). It then imports as
   `from IRA import ira_loaders, ira_build`.
2. Create a Python recipe and paste **`dataiku_recipe.py`** into it (this file
   stays out of the library).
3. Input: a managed **Folder** holding the Excel (set `INPUT_FOLDER` /
   `INPUT_EXCEL_NAME`). Outputs: 4 datasets (+ optional output folder for xlsx).
