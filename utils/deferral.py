"""
Network deferral analysis utilities.

Pure-math functions for capacity-year / PV calculations (eqs 2, 7-8),
plus a greedy heuristic allocator for demo use.
"""

import math
from typing import Callable

import asyncpg


# ---------------------------------------------------------------------------
# Pure-math helpers (no DB dependency)
# ---------------------------------------------------------------------------

def years_to_capacity(cap_l: float, d_l: float, load_r_pct: float) -> float:
    """Simple conventional estimate: n = log(Cap_l / D_l) / log(1 + load_r)."""
    if d_l <= 0:
        return float("inf")
    r = load_r_pct / 100.0
    if r <= 0:
        return float("inf")
    return math.log(cap_l / d_l) / math.log(1 + r)


def net_growth_func(
    downstream_nodes: list[str],
    nodes_state: dict[str, dict],
    add_load_per_node: dict[str, float],
    add_gen_per_node: dict[str, float],
    load_r_pct: float,
    dg_r_pct: float,
) -> Callable[[float], tuple[float, float]]:
    """Return f(n) -> (P_growth, Q_growth) summed over downstream nodes (eqs 7-8)."""
    lr = load_r_pct / 100.0
    dr = dg_r_pct / 100.0

    def f(n: float) -> tuple[float, float]:
        p_sum = 0.0
        q_sum = 0.0
        for k in downstream_nodes:
            state = nodes_state[k]
            load_growth = (state["load"] + add_load_per_node.get(k, 0.0)) * ((1 + lr) ** n - 1)
            dg_growth = (state["gen"] + add_gen_per_node.get(k, 0.0)) * ((1 + dr) ** n - 1)
            net_p = load_growth - dg_growth
            pf = state.get("pf", 0.98)
            net_q = abs(net_p) * math.tan(math.acos(pf))
            p_sum += net_p
            q_sum += net_q
        return p_sum, q_sum

    return f


def solve_n_for_component(
    cap_l_mva: float,
    initial_flow_mw: float,
    growth_func: Callable[[float], tuple[float, float]],
    max_n: float = 500.0,
    tol: float = 1e-3,
) -> float:
    """Bisection to find n where MVA magnitude reaches cap_l_mva."""

    def residual(n: float) -> float:
        p_growth, q_growth = growth_func(n)
        p_total = initial_flow_mw + p_growth
        return math.sqrt(p_total**2 + q_growth**2) - cap_l_mva

    if residual(0.0) >= 0:
        return 0.0
    if residual(max_n) < 0:
        return max_n

    lo, hi = 0.0, max_n
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        r = residual(mid)
        if abs(r) < tol:
            return mid
        if r > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def present_value_of_cost(
    asset_cost_gbp: float, years: float, discount_pct: float
) -> float:
    """NPV of an asset cost deferred by `years`."""
    d = discount_pct / 100.0
    return asset_cost_gbp / ((1 + d) ** years)


# ---------------------------------------------------------------------------
# Greedy heuristic allocator (DB-backed, for demo)
# ---------------------------------------------------------------------------

async def compute_downstream_capacity(conn: asyncpg.Connection) -> dict[str, float]:
    """Sum of capacity (kW) on components adjacent to each node."""
    rows = await conn.fetch(
        """
        SELECT n.node_id,
               COALESCE(SUM(c.capacity_mva), 0) * 1000.0 AS cap_kw
        FROM network_nodes n
        LEFT JOIN network_components c
            ON c.from_node = n.node_id OR c.to_node = n.node_id
        GROUP BY n.node_id
        """
    )
    return {r["node_id"]: float(r["cap_kw"]) for r in rows}


async def get_node_ids(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch("SELECT node_id FROM network_nodes ORDER BY node_id")
    return [r["node_id"] for r in rows]


async def greedy_allocate(
    conn: asyncpg.Connection,
    total_load_kw: float,
    total_gen_kw: float,
) -> dict[str, dict[str, float]]:
    """
    Demo greedy allocator.
    Generation -> nodes with largest downstream headroom first.
    Load -> nodes with smallest headroom first (local balancing).
    """
    nodes = await get_node_ids(conn)
    headroom = await compute_downstream_capacity(conn)

    alloc: dict[str, dict[str, float]] = {n: {"load_kw": 0.0, "gen_kw": 0.0} for n in nodes}

    # Generation: descending headroom
    remaining = total_gen_kw
    for n in sorted(nodes, key=lambda n: headroom.get(n, 0.0), reverse=True):
        if remaining <= 0:
            break
        assign = min(remaining, max(0.0, headroom.get(n, 0.0) * 0.10))
        if assign > 0:
            alloc[n]["gen_kw"] += assign
            remaining -= assign
    if remaining > 0:
        per = remaining / max(1, len(nodes))
        for n in nodes:
            alloc[n]["gen_kw"] += per

    # Load: ascending headroom
    remaining = total_load_kw
    for n in sorted(nodes, key=lambda n: headroom.get(n, 0.0)):
        if remaining <= 0:
            break
        assign = min(remaining, max(100.0, headroom.get(n, 0.0) * 0.05))
        alloc[n]["load_kw"] += assign
        remaining -= assign
    if remaining > 0:
        per = remaining / max(1, len(nodes))
        for n in nodes:
            alloc[n]["load_kw"] += per

    return alloc


async def store_allocations(
    conn: asyncpg.Connection,
    plan_name: str,
    alloc: dict[str, dict[str, float]],
) -> None:
    """Persist allocation results to opt_allocations table."""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS opt_allocations (
            plan_name TEXT,
            node_id   TEXT,
            load_kw   NUMERIC,
            gen_kw    NUMERIC,
            PRIMARY KEY (plan_name, node_id)
        )
        """
    )
    for node, v in alloc.items():
        await conn.execute(
            """
            INSERT INTO opt_allocations (plan_name, node_id, load_kw, gen_kw)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (plan_name, node_id) DO UPDATE
            SET load_kw = EXCLUDED.load_kw, gen_kw = EXCLUDED.gen_kw
            """,
            plan_name,
            node,
            v["load_kw"],
            v["gen_kw"],
        )
