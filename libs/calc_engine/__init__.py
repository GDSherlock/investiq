"""
InvestIQ calc_engine — Pure Python financial calculation functions.

Every formula is a tested pure function returning structured results with:
- formula_used: description of the formula
- inputs: dict of inputs applied
- result: computed value
- confidence: float 0-1
"""

from .irr import compute_irr
from .npv import compute_npv
from .dscr import compute_dscr, check_covenant
from .monte_carlo import monte_carlo_simulation, box_muller_normal, cholesky_decomposition

__all__ = [
    "compute_irr",
    "compute_npv",
    "compute_dscr",
    "check_covenant",
    "monte_carlo_simulation",
    "box_muller_normal",
    "cholesky_decomposition",
]
