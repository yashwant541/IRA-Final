"""
ira_config.py
=============
The *what* of the assessment, kept apart from the *how* in ira_engine.py.

For every product (Secured / Unsecured / SME Banking / Wealth Lending) this file
lists, in output order, each metric:

    id      - short code used by the aggregation groups
    label   - exact text shown in column B of the output
    value   - fn(tables, country, product_input_label) -> float | str | None
              (column C: computed straight from the input tables per the
               "What to do in Value Column" instructions)
    rating  - fn(value, ctx) -> "Very Low".."Very High" | "Not Available"
              (column D: the IF-threshold ladder, transcribed per product)

``ctx`` is the dict of already-computed values for the same country/product, so
compound metrics (e.g. the QoQ current+prior pair) can see each other.

GROUPS + WEIGHTS drive the final "Calculated Inherent Credit Risk Assessment":
    score = SUM over groups of  agg(risk_numbers in group) * weight
    rating = >=4.5 Very High / >=3.5 High / >=2.5 Medium / >=1.5 Low / else Very Low

>>> The WEIGHTS below are PLACEHOLDERS (they sum to 100% per product).  Replace
>>> them with your BB:BD metric/weight table when you have it - just edit the
>>> numbers here, nothing else changes.  The grouping mirrors the MAX(...) blocks
>>> in the template's final-row formulas; confirm it against your real formula.
"""

from __future__ import annotations
from typing import Dict, List, Callable, Any

try:                        # inside the IRA package (Dataiku library)
    from . import ira_engine as E
except ImportError:         # flat import (local / standalone)
    import ira_engine as E


# --------------------------------------------------------------------------- #
#  Value extractors  (column C)  -- now read from the intermediate layer
# --------------------------------------------------------------------------- #
# Every metric value comes from a pre-computed intermediate table (built once in
# ira_intermediate.build and stored at tables["intermediates"]).  Extractors are
# thin lookups keyed by (country, OUTPUT product) - e.g. "Secured".  This keeps
# the finals and the intermediate outputs perfectly consistent and lets us
# surface a REASON for every "Not Available".

def from_int(int_key: str):
    """Return an extractor that pulls value + reason from an intermediate table."""
    def f(t, country, prod_out):
        recs = t.get("intermediates", {}).get(int_key, {})
        rec = recs.get((country, prod_out)) or recs.get((country, None))
        return rec if rec else {"value": None, "reason": "intermediate not built"}
    f.int_key = int_key
    return f


# each extractor returns the intermediate record dict {value, reason, ...}
v_asset_growth_yoy     = from_int("enr_yoy")
v_dpd_qoq_current      = from_int("dpd_qoq_cur")
v_dpd_qoq_prior        = from_int("dpd_qoq_prior")
v_dpd_yoy              = from_int("dpd_yoy")
v_dpd_pct_of_total     = from_int("dpd_pct_total")
v_policy_exception_rate = from_int("policy_exc_rate")
v_ea_proportion        = from_int("ea_prop")
v_awc_proportion       = from_int("awc_prop")
v_ltv_concentration    = from_int("ltv")
v_volatile_concentration = from_int("volatile")
v_ppi_yoy              = from_int("ppi_yoy")
v_interest_rate_increase = from_int("interest_inc")
v_country_outlook      = from_int("sovereign_outlook")
v_country_grading      = from_int("sovereign_grade")
v_active_dispensations = from_int("dispensations")
v_cra_breaches         = from_int("breaches")


# --------------------------------------------------------------------------- #
#  Rating ladders  (column D)   -- transcribed verbatim from the IF-formulas
# --------------------------------------------------------------------------- #

def _pair_rating(ctx, cur_key, prior_key, ladder):
    """QoQ metrics rate on BOTH current & prior exceeding a bound (AND logic)."""
    cur, prior = ctx.get(cur_key), ctx.get(prior_key)
    if cur is None or prior is None:
        return "Not Available"
    for bound, rating in ladder:
        if bound is None:
            return rating
        if cur > bound and prior > bound:
            return rating
    return ladder[-1][1]


# Thresholds for the DPD deterioration DIFFERENCE (current - back), as a
# fraction (x100 = percentage points).  PLACEHOLDER - adjust to your policy.
#   > 5pp Very High / > 3pp High / > 1pp Medium / > 0 Low / <= 0 Very Low
DETERIORATION_LADDER = [(.05, "Very High"), (.03, "High"), (.01, "Medium"),
                        (0, "Low"), (None, "Very Low")]


def r_deterioration(value, ctx=None):
    """Single-value deterioration rating (used for 1c)."""
    return E.bands_desc(value, DETERIORATION_LADDER)


def r_deterioration_pair(ctx):
    """Paired deterioration rating (used for 1bi & 1bii together)."""
    return _pair_rating(ctx, "1bi", "1bii", DETERIORATION_LADDER)


def r_grading(value, ctx=None):
    if value is None or str(value).strip() == "":
        return "Not Available"
    v = str(value).strip()
    if v in ("11A", "11B", "11C", "12A", "12B", "12C", "13"):
        return "Very High"
    if v in ("8B", "9A", "9B", "10A"):
        return "High"
    if v in ("5B", "6A", "6B", "7A", "7B", "8A"):
        return "Medium"
    if v in ("1A", "1B", "2A"):
        return "Very Low"
    return "Low"


def r_outlook(value, ctx=None):
    if value is None or str(value).strip() == "":
        return "Not Available"
    v = str(value).strip()
    if v == "Positive":
        return "Very Low"
    if v == "Stable":
        return "Low"
    return "Very High"


# --------------------------------------------------------------------------- #
#  Per-product metric definitions
# --------------------------------------------------------------------------- #

def _m(id, label, value, rating, group, weight_key):
    return dict(id=id, label=label, value=value, rating=rating,
                group=group, weight_key=weight_key)


# ladders as (bound, rating) descending; None bound = floor
def secured_metrics() -> List[dict]:
    return [
        _m("1a", "1a.Asset Growth Year on Year as %", v_asset_growth_yoy,
           lambda v, c: E.bands_desc(v, [(.10, "Very High"), (.05, "High"),
                                         (.03, "Medium"), (.01, "Low"),
                                         (None, "Very Low")]),
           "G1", "1a"),
        _m("1bi", "1bi.QoQ Deterioration in 90+DPD$% in Current Month",
           v_dpd_qoq_current,
           lambda v, c: r_deterioration_pair(c),
           "G2", "delinquency"),
        _m("1bii", "1bii.QoQ Deterioration in 90+DPD$% in Prior Month",
           v_dpd_qoq_prior,
           lambda v, c: r_deterioration_pair(c),
           "G2", "delinquency"),
        _m("1c", "1c. YoY Deterioration in 90+ DPD$%", v_dpd_yoy,
           lambda v, c: r_deterioration(v), "G2", "delinquency"),
        _m("1d", "1d.Country 90+DPD% Total Group 90+ Delinquency",
           v_dpd_pct_of_total,
           lambda v, c: E.bands_desc(v, [(.25, "Very High"), (.15, "High"),
                                         (.05, "Medium"), (.025, "Low"),
                                         (None, "Very Low")]),
           "G2", "delinquency"),
        _m("1e", "1e. Last 12 Months Policy Exceptions rate",
           v_policy_exception_rate,
           lambda v, c: E.bands_desc(v, [(.15, "Very High"), (.10, "High"),
                                         (.075, "Medium"), (.05, "Low"),
                                         (None, "Very Low")]),
           "G3", "policy_disp"),
        _m("1f", "1f. Active Dispensations on Secured Lending",
           v_active_dispensations,
           lambda v, c: _disp_rating(v), "G3", "policy_disp"),
        _m("1g", "1g.Concentration of Mortgage exposures exceeding LTV 80%",
           v_ltv_concentration,
           lambda v, c: E.bands_desc(v, [(.10, "Very High"), (.05, "High"),
                                         (.025, "Medium"), (.01, "Low"),
                                         (None, "Very Low")]),
           "G4", "ltv"),
        _m("1h", "1h.Credit Risk Appetite breaches in last 12 months",
           v_cra_breaches, lambda v, c: _breach_rating(v), "G5", "breaches"),
        _m("2a", "2a. Interest Rate Increase from Last 3 Years Average",
           v_interest_rate_increase,
           lambda v, c: E.bands_desc(v, [(.03, "Very High"), (.02, "High"),
                                         (.01, "Medium"), (0, "Low"),
                                         (None, "Very Low")]),
           "G6", "macro"),
        _m("2b", "2b. YOY Change in Property Price Index", v_ppi_yoy,
           lambda v, c: _ppi_rating(v), "G6", "macro"),
        _m("2c", "2c.Country Risk - Outlook", v_country_outlook, r_outlook,
           "G6", "macro"),
        _m("2d", "2d.Country Risk - Grading", v_country_grading, r_grading,
           "G6", "macro"),
    ]


def unsecured_metrics() -> List[dict]:
    return [
        _m("1a", "1a.Asset Growth Year on Year as %", v_asset_growth_yoy,
           lambda v, c: E.bands_desc(v, [(.15, "Very High"), (.05, "High"),
                                         (.03, "Medium"), (.01, "Low"),
                                         (None, "Very Low")]), "G1", "1a"),
        _m("1bi", "1bi.QoQ Deterioration in 30+DPD$% in Current Month",
           v_dpd_qoq_current,
           lambda v, c: r_deterioration_pair(c), "G2", "delinquency"),
        _m("1bii", "1bii.QoQ Deterioration in 30+DPD$% in Prior Month",
           v_dpd_qoq_prior,
           lambda v, c: r_deterioration_pair(c), "G2", "delinquency"),
        _m("1c", "1c. YoY Deterioration in 30+ DPD$%", v_dpd_yoy,
           lambda v, c: r_deterioration(v), "G2", "delinquency"),
        _m("1d", "1d.Country 30+DPD% Total Group 30+ Delinquency",
           v_dpd_pct_of_total,
           lambda v, c: E.bands_desc(v, [(.10, "Very High"), (.075, "High"),
                                         (.05, "Medium"), (.025, "Low"),
                                         (None, "Very Low")]), "G2", "delinquency"),
        _m("1e", "1e. Last 12 Months Policy Exceptions rate",
           v_policy_exception_rate,
           lambda v, c: E.bands_desc(v, [(.05, "Very High"), (.01, "High"),
                                         (.005, "Medium"), (.0025, "Low"),
                                         (None, "Very Low")]), "G3", "policy_disp"),
        _m("1f", "1f. Active Dispensations on Unsecured Lending",
           v_active_dispensations, lambda v, c: _disp_rating(v),
           "G3", "policy_disp"),
        _m("1g", "1g.Portfolio Concentration in Volatile Segment",
           v_volatile_concentration,
           lambda v, c: E.bands_desc(v, [(.125, "Very High"), (.10, "High"),
                                         (.075, "Medium"), (.05, "Low"),
                                         (None, "Very Low")]), "G4", "volatile"),
        _m("1h", "1h.Credit Risk Appetite breaches in last 12 months",
           v_cra_breaches, lambda v, c: _breach_rating(v), "G5", "breaches"),
        _m("2a", "2a.Country Risk - Outlook", v_country_outlook, r_outlook,
           "G6", "macro"),
        _m("2b", "2b.Country Risk - Grading", v_country_grading, r_grading,
           "G6", "macro"),
    ]


def sme_metrics() -> List[dict]:
    return [
        _m("1a", "1a.Asset Growth Year on Year as %", v_asset_growth_yoy,
           lambda v, c: E.bands_desc(v, [(.15, "Very High"), (.05, "High"),
                                         (.03, "Medium"), (.01, "Low"),
                                         (None, "Very Low")]), "G1", "1a"),
        _m("1bi", "1bi.QoQ Deterioration in 30+DPD$% in Current Month",
           v_dpd_qoq_current,
           lambda v, c: r_deterioration_pair(c), "G2", "delinquency"),
        _m("1bii", "1bii.QoQ Deterioration in 30+DPD$% in Prior Month",
           v_dpd_qoq_prior,
           lambda v, c: r_deterioration_pair(c), "G2", "delinquency"),
        _m("1c", "1c. YoY Deterioration in 30+ DPD$%", v_dpd_yoy,
           lambda v, c: r_deterioration(v), "G2", "delinquency"),
        _m("1d", "1d.Country 30+DPD% Total Group 30+ Delinquency",
           v_dpd_pct_of_total,
           lambda v, c: E.bands_desc(v, [(.20, "Very High"), (.15, "High"),
                                         (.10, "Medium"), (.05, "Low"),
                                         (None, "Very Low")]), "G2", "delinquency"),
        _m("1e", "1e. Proportion of Exposure in Early Alert (EA)",
           v_ea_proportion,
           lambda v, c: E.bands_desc(v, [(.10, "Very High"), (.075, "High"),
                                         (.05, "Medium"), (.025, "Low"),
                                         (None, "Very Low")]), "G2", "delinquency"),
        _m("1f", "1f. Proportion of Exposure in Collection (AWC)",
           v_awc_proportion,
           lambda v, c: E.bands_desc(v, [(.125, "Very High"), (.10, "High"),
                                         (.075, "Medium"), (.05, "Low"),
                                         (None, "Very Low")]), "G2", "delinquency"),
        _m("1g", "1g.Last 12 Months Policy Exceptions rate",
           v_policy_exception_rate,
           lambda v, c: E.bands_desc(v, [(.075, "Very High"), (.05, "High"),
                                         (.03, "Medium"), (.01, "Low"),
                                         (None, "Very Low")]), "G3", "policy_disp"),
        _m("1h", "1h.Active Dispensations on SME Lending",
           v_active_dispensations, lambda v, c: _disp_rating(v),
           "G3", "policy_disp"),
        _m("1i", "1i.Credit Risk Appetite breaches in last 12 months",
           v_cra_breaches, lambda v, c: _breach_rating(v), "G4", "breaches"),
        _m("2a", "2a.Country Risk - Outlook", v_country_outlook, r_outlook,
           "G5", "macro"),
        _m("2b", "2b.Country Risk - Grading", v_country_grading, r_grading,
           "G5", "macro"),
    ]


def wealth_metrics() -> List[dict]:
    # Per the mapping file, Wealth has NO DPD %-of-group-total; 1d/1e are the
    # EA/AWC proportions, 1f is the policy-exception rate, 1g dispensations,
    # 1h breaches, then Country Risk outlook/grading.
    return [
        _m("1a", "1a.Asset Growth Year on Year as %", v_asset_growth_yoy,
           lambda v, c: E.bands_desc(v, [(.15, "Very High"), (.05, "High"),
                                         (.03, "Medium"), (.01, "Low"),
                                         (None, "Very Low")]), "G1", "1a"),
        _m("1bi", "1bi.QoQ Deterioration in 30+DPD$% in Current Month",
           v_dpd_qoq_current,
           lambda v, c: r_deterioration_pair(c), "G2", "delinquency"),
        _m("1bii", "1bii.QoQ Deterioration in 30+DPD$% in Prior Month",
           v_dpd_qoq_prior, lambda v, c: r_deterioration_pair(c), "G2", "delinquency"),
        _m("1c", "1c. YoY Deterioration in 30+ DPD$%", v_dpd_yoy,
           lambda v, c: r_deterioration(v), "G2", "delinquency"),
        _m("1d", "1d. Proportion of Exposure in Early Alert (EA)",
           v_ea_proportion,
           lambda v, c: E.bands_desc(v, [(.035, "Very High"), (.025, "High"),
                                         (.015, "Medium"), (.005, "Low"),
                                         (None, "Very Low")]), "G3", "exposure"),
        _m("1e", "1e. Proportion of Exposure in Collection (AWC)",
           v_awc_proportion,
           lambda v, c: E.bands_desc(v, [(.035, "Very High"), (.025, "High"),
                                         (.015, "Medium"), (.005, "Low"),
                                         (None, "Very Low")]), "G3", "exposure"),
        _m("1f", "1f. Last 12 Months Policy Exceptions rate",
           v_policy_exception_rate,
           lambda v, c: E.bands_desc(v, [(.075, "Very High"), (.05, "High"),
                                         (.03, "Medium"), (.01, "Low"),
                                         (None, "Very Low")]), "G4", "policy_disp"),
        _m("1g", "1g. Active Dispensations on Wealth Lending",
           v_active_dispensations, lambda v, c: _disp_rating(v),
           "G4", "policy_disp"),
        _m("1h", "1h.Credit Risk Appetite breaches in last 12 months",
           v_cra_breaches, lambda v, c: _breach_rating(v), "G5", "breaches"),
        _m("2a", "2a.Country Risk - Outlook", v_country_outlook, r_outlook,
           "G6", "macro"),
        _m("2b", "2b.Country Risk - Grading", v_country_grading, r_grading,
           "G6", "macro"),
    ]


# small shared rating helpers ------------------------------------------------ #
def _disp_rating(v):
    if v is None:
        return "Not Available"
    if v > 3:
        return "Very High"
    if v == 3:
        return "High"
    if v == 2:
        return "Medium"
    if v == 1:
        return "Low"
    return "Very Low"


def _breach_rating(v):
    if v is None:
        return "Not Available"
    if v > 1:
        return "Very High"
    if v == 1:
        return "High"
    return "Very Low"


def _ppi_rating(v):
    if v is None:
        return "Not Available"
    if v > .05:
        return "Very Low"
    if v > 0:
        return "Low"
    if v > -.05:
        return "Medium"
    if v > -.15:
        return "High"
    return "Very High"


def _wealth_pair(ctx):
    cur, prior = ctx.get("1bi"), ctx.get("1bii")
    if cur is None or prior is None:
        return "Not Available"
    if cur > .0025 and prior > .0025:
        return "Very High"
    if cur > 0 and prior > 0:
        return "High"
    return "Very Low"


# --------------------------------------------------------------------------- #
#  Aggregation groups + weights  (final "Calculated" row)
# --------------------------------------------------------------------------- #
# agg: "single" (one metric) or "max" (worst risk-number in the group).
# weight: PLACEHOLDER fraction - replace from your BB:BD table.

# --------------------------------------------------------------------------- #
#  Final "Calculated Inherent Credit Risk Assessment" aggregation
# --------------------------------------------------------------------------- #
# EXACT spec supplied by the business.  Each group is weighted 1/6 (16.67%).
# Groups are given by LABEL POSITION (1-based) in the metric list for the
# category; a group's value is the MAX risk number across its labels (a single
# label is just that label's risk number).
#
#   score = SUM over groups of  (1/6) * max(risk numbers in the group)
#   rating: >=4.5 Very High / >=3.5 High / >=2.5 Medium / >=1.5 Low / else Very Low
#
# NOTE: Secured & Unsecured have 6 groups (weights sum to 100%); SME & Wealth
# have 5 groups as specified (5 x 16.67% = 83.3%).  Set NORMALISE_WEIGHTS=True
# to instead divide by the actual group count per category (so every category
# sums to 100%).
W6 = 1.0 / 6.0
NORMALISE_WEIGHTS = False

AGG_GROUPS: Dict[str, List[List[int]]] = {
    # Secured (13 labels)
    "Secured": [[1], [2, 3, 4, 5], [6, 7, 8], [9], [10], [11, 12, 13]],
    # Unsecured (11 labels)
    "Unsecured": [[1], [2, 3, 4, 5], [6, 7], [8], [9], [10, 11]],
    # SME Banking (12 labels)
    "SME Banking": [[1], [2, 3, 4, 5, 6, 7], [8, 9], [10], [11, 12]],
    # Wealth Lending (11 labels)
    "Wealth Lending": [[1], [2, 3, 4, 5, 6], [7, 8], [9], [10, 11]],
}

METRICS: Dict[str, Callable[[], List[dict]]] = {
    "Secured": secured_metrics,
    "Unsecured": unsecured_metrics,
    "SME Banking": sme_metrics,
    "Wealth Lending": wealth_metrics,
}

FINAL_LABEL = "Calculated Inherent Credit Risk Assessment:"
