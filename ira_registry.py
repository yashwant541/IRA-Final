"""
ira_registry.py
===============
The single source of truth for **what input tables the pipeline expects**.

Every entry describes one logical input table: the sheet name(s) it may appear
under, the shape it should have, whether it is required, which output metrics
consume it, and whether the pipeline currently fabricates it as dummy data.

`ira_diagnostics.py` audits a real workbook against this registry and reports,
per table, exactly what is present / missing / mis-read.

Adding a new input table = add one row here (and, if it feeds a metric, wire an
extractor in ira_config.py).  Nothing else needs to know about it.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


# shape identifiers understood by the diagnostics validators
SHAPE_PRODUCT_BLOCK   = "country_product_block"   # country header + product sub-rows
SHAPE_COUNTRY_ONLY    = "country_only"            # country rows, months as cols
SHAPE_SIDE_BY_SIDE    = "side_by_side"            # two blocks L | R
SHAPE_QUADRANT        = "gco_quadrants"           # 2x2 product quadrants
SHAPE_STACKED         = "stacked_country_only"    # several country-only tables stacked
SHAPE_CCPL_HORIZONTAL = "ccpl_horizontal"         # codes across a row
SHAPE_FX              = "fx_reference"             # currency -> rate
SHAPE_LONG            = "long"                     # tidy / one-row-per-record
SHAPE_FABRICATED      = "fabricated"              # not read from the file at all


@dataclass
class Expected:
    key: str                          # internal table key used across the code
    display: str                      # human name for the report
    aliases: List[str]                # accepted sheet names (matched tolerantly)
    shape: str
    required: bool = True             # ERROR if a required table is absent
    reference: bool = False           # a lookup/reference table (fx, ccpl)
    fabricated: bool = False          # pipeline currently generates dummy data
    used_by: List[str] = field(default_factory=list)   # metric ids / products
    expects_products: bool = False    # product sub-rows expected under countries
    note: str = ""


# --------------------------------------------------------------------------- #
#  The registry
# --------------------------------------------------------------------------- #
REGISTRY: List[Expected] = [
    # ---- core product-block monthly tables ------------------------------- #
    Expected("ENR", "ENR by Country & Product", ["ENR"],
             SHAPE_PRODUCT_BLOCK, used_by=["1a Asset Growth", "EA/AWC denominator"],
             expects_products=True, note="Carries a leading 'Total ENR' row."),
    Expected("90+%", "90+ DPD % by Country & Product", ["90+%"],
             SHAPE_PRODUCT_BLOCK, used_by=["Secured 1bi/1bii/1c"],
             expects_products=True),
    Expected("90+$", "90+ DPD $ by Country & Product", ["90+$"],
             SHAPE_PRODUCT_BLOCK, used_by=["Secured 1d %-of-total"],
             expects_products=True),
    Expected("30+%", "30+ DPD % by Country & Product", ["30+%"],
             SHAPE_PRODUCT_BLOCK, used_by=["Unsec/SME/Wealth 1bi/1bii/1c"],
             expects_products=True),
    Expected("30+$", "30+ DPD $ by Country & Product", ["30+$"],
             SHAPE_PRODUCT_BLOCK, used_by=["Unsec/SME/Wealth 1d %-of-total"],
             expects_products=True),
    Expected("RWA", "RWA by Country & Product", ["RWA"],
             SHAPE_PRODUCT_BLOCK, required=False, used_by=["(available; not yet in a metric)"],
             expects_products=True, note="Carries a leading 'Total RWA' row."),
    Expected("app_rate", "Country/Product Approval Rate",
             ["Country prod level app rate"],
             SHAPE_PRODUCT_BLOCK, required=False,
             used_by=["(available; not yet in a metric)"], expects_products=True),
    Expected("new_approved", "# Monthly New Approved",
             ["#monthly new approved", "monthly new approved"],
             SHAPE_PRODUCT_BLOCK, required=False,
             used_by=["(available; not yet in a metric)"], expects_products=True),

    # ---- side-by-side ---------------------------------------------------- #
    Expected("policy_exception", "Policy Exceptions L2 | L3",
             ["# policy exception L2 and L3", "policy exception L2 and L3"],
             SHAPE_SIDE_BY_SIDE, used_by=["1e Policy Exceptions"],
             expects_products=True,
             note="Two blocks side by side (L2 left, L3 right); summed."),

    # ---- quadrant -------------------------------------------------------- #
    Expected("gco", "GCO % (2x2 product quadrants)", ["GCO %", "GCO"],
             SHAPE_QUADRANT, required=False,
             used_by=["(available; not yet in a metric)"],
             note="Unsecured / Secured / Business / Wealth quadrants."),

    # ---- long ------------------------------------------------------------ #
    Expected("ecl", "ECL / IIP / LI (long)", ["ECL IIP LI"],
             SHAPE_LONG, required=False, used_by=["(available; not yet in a metric)"]),

    # ---- stacked country-only ------------------------------------------- #
    Expected("ME_EA_AWC", "ME EA / AWC (stacked)", ["ME EA AWC"],
             SHAPE_STACKED, used_by=["SME/Wealth 1e EA, 1f AWC"],
             note="3 sub-tables: AWC, EA (PP&NPP), EA NPP."),
    Expected("PvB_EA_AWC", "PvB EA / AWC (stacked)", ["PvB EA AWC"],
             SHAPE_STACKED, required=False,
             used_by=["(available; Wealth private-bank EA/AWC)"]),

    # ---- country-only / reference --------------------------------------- #
    Expected("PPI", "Property Price Index (by currency)", ["PPI"],
             SHAPE_COUNTRY_ONLY, used_by=["2b PPI YoY"],
             note="Rows keyed by currency code (AED, BDT, ...)."),
    Expected("ccpl_volatile", "CCPL Volatile by Country",
             ["CCPL Volatile by Country"],
             SHAPE_CCPL_HORIZONTAL, reference=True,
             used_by=["Unsecured 1g Volatile Concentration"],
             note="Country codes across a row (Global, KR, HK, ...)."),
    Expected("LTV80", "LTV > 80% (excl MIP)", ["LTV > 80 Excl MIP", "LTV>80 Excl MIP"],
             SHAPE_COUNTRY_ONLY, used_by=["Secured 1g LTV Concentration"]),
    Expected("fx", "FX Rates used", ["Fx Rates used"],
             SHAPE_FX, reference=True, used_by=["currency conversion (reference)"]),
    Expected("interest_rates", "Interest Rates", ["Interest Rates"],
             SHAPE_COUNTRY_ONLY, used_by=["Secured 2a Rate Increase"],
             note="Sheet is present but EMPTY in the sample -> dummy filled."),

    # ---- tables NOT in the workbook (fabricated) ------------------------- #
    Expected("sovereign", "Country Sovereign Rating & Outlook", ["Sovereign", "Country Rating"],
             SHAPE_FABRICATED, fabricated=True,
             used_by=["2c Outlook", "2d Grading"],
             note="Not in the file. Supply Outlook + FCY CRG per country."),
    Expected("dispensations", "Active Dispensations", ["Dispensations"],
             SHAPE_FABRICATED, fabricated=True,
             used_by=["1f/1h Active Dispensations"],
             note="Not in the file. Supply active/expired counts per country."),
    Expected("cra_breaches", "Credit Risk Appetite Breaches", ["CRA Breaches", "Breaches"],
             SHAPE_FABRICATED, fabricated=True,
             used_by=["1h/1i CRA Breaches"],
             note="Not in the file. Supply # breaches (last 12m) per country."),
]


def by_key(key: str) -> Optional[Expected]:
    for e in REGISTRY:
        if e.key == key:
            return e
    return None
