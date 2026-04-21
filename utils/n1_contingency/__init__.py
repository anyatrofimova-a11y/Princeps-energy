"""UK N-1 Contingency Map — Princeps crown-jewel manufactured dataset.

For every primary substation in GB, we pre-compute:

  * which upstream transformer / line outage would overload which downstream
    feeder above its thermal limit,
  * the worst-case post-contingency overload percentage,
  * the expected customer-minutes-lost / restoration time (BSC Supply Security
    Standard P2/7 targets: 15 min urban, 60 min rural),
  * an overall reliability score 0-100.

The pipeline:

  1. `schema.N1Contingency` — canonical Pydantic record (one per substation).
  2. `analyser.run_substation_n1(substation_id, pool)` — sweeps upstream assets
     (2 electrical hops) and calls `utils/grid_power_flow.py::run_contingency`
     via subprocess (pandapower in `.venv-grid/`).
  3. `batch_runner.run_batch(...)` — weekly `ProcessPoolExecutor(4)` job that
     upserts every primary substation's record into `n1_contingency_map`.

Published as a paid data-subscription slug `uk-n1-contingency-map`
(Enterprise £15k/mo, quarterly refresh for end-users; internal batch weekly).

Public surface
--------------
    from utils.n1_contingency import (
        N1Contingency, N1Event,
        run_substation_n1,
        run_batch,
    )
"""

from __future__ import annotations

from .schema import (
    N1Contingency,
    N1Event,
    OutageAssetType,
    MODEL_VERSION,
)

# Heavy imports (pandapower subprocess, asyncpg) deferred so tests / FastAPI
# startup don't pay for them.
try:
    from .analyser import run_substation_n1, gather_upstream_assets  # noqa: F401
except Exception:  # pragma: no cover - keep import robust
    run_substation_n1 = None  # type: ignore
    gather_upstream_assets = None  # type: ignore

try:
    from .batch_runner import run_batch  # noqa: F401
except Exception:  # pragma: no cover
    run_batch = None  # type: ignore


__all__ = [
    "N1Contingency",
    "N1Event",
    "OutageAssetType",
    "MODEL_VERSION",
    "run_substation_n1",
    "gather_upstream_assets",
    "run_batch",
]
