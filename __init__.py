"""
IRA - Inherent Risk Assessment library
======================================
Reusable, framework-agnostic engine that builds the four IRA output tables
(Secured / Unsecured / SME Banking / Wealth Lending) from the monthly input
tables.

Upload this whole folder to the Dataiku project library at:
    lib/python/IRA/

Then, from a Python recipe or notebook:

    from IRA import ira_loaders, ira_build

    tables    = ira_loaders.load_tables(sheets)          # sheets = {name: rows}
    countries = ira_loaders._all_countries(tables)
    frames    = ira_build.build_all(tables, countries)   # {sheet_name: DataFrame}

Modules
-------
    ira_engine   - shape-aware parsers + maths helpers + risk-number lookup
    ira_config   - metric definitions, thresholds, aggregation groups, weights
    ira_build    - value -> rating -> risk number -> weighted final assessment
    ira_loaders  - raw sheets -> parsed tables (+ dummy fill for missing tables)
"""

from . import ira_engine
from . import ira_io
from . import ira_preview
from . import ira_config
from . import ira_normalize
from . import ira_intermediate
from . import ira_build
from . import ira_loaders
from . import ira_reftables
from . import ira_dispensations
from . import ira_countries
from . import ira_registry
from . import ira_detect
from . import ira_diagnostics

__all__ = ["ira_engine", "ira_config", "ira_normalize",
           "ira_intermediate", "ira_build", "ira_loaders", "ira_countries",
           "ira_registry", "ira_detect", "ira_diagnostics"]
