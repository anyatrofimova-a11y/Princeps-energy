"""
MIQCP model sketch for DNO reinforcement deferral optimisation.

Requires gurobipy. This is a structural blueprint — supply real breakpoint
coefficients (thermal_a/b/c, obj_a/b) and the D_lk incidence matrix from
your network topology to make it operational.
"""

from gurobipy import Model, GRB, quicksum  # type: ignore[import-untyped]


def build_miqcp_model(
    nodes: list[str],
    components: list[dict],
    params: dict,
) -> Model:
    """
    Build the MIQCP model.

    components: list of dicts with keys 'id', 'fnode', 'tnode', 'asset_cost', 'capacity_mva'
    params: dict with keys:
        thermal_a, thermal_b, thermal_c  -- lists[float] of length Mobj
        obj_a, obj_b                     -- lists[float] of length Mobj
        total_load_mw, total_gen_mw      -- floats
        Mobj                             -- int (number of breakpoints, default 6)
    """
    m = Model("deferral_miqcp")

    Mobj = params.get("Mobj", 6)

    # Decision variables: access allocation per node (kW)
    P_load = {k: m.addVar(lb=0.0, name=f"P_load_{k}") for k in nodes}
    P_dg = {k: m.addVar(lb=0.0, name=f"P_DG_{k}") for k in nodes}

    # Years-to-reinforcement per component
    n_l = {c["id"]: m.addVar(lb=0.0, name=f"n_{c['id']}") for c in components}

    # Piecewise binary selectors + thermal growth vars
    w, P_th, Q_th, eps = {}, {}, {}, {}
    for c in components:
        lid = c["id"]
        w[lid] = {i: m.addVar(vtype=GRB.BINARY, name=f"w_{lid}_{i}") for i in range(Mobj)}
        P_th[lid] = {i: m.addVar(lb=0.0, name=f"Pth_{lid}_{i}") for i in range(Mobj)}
        Q_th[lid] = {i: m.addVar(lb=0.0, name=f"Qth_{lid}_{i}") for i in range(Mobj)}
        eps[lid] = {i: m.addVar(lb=0.0, name=f"eps_{lid}_{i}") for i in range(Mobj)}

        # Exactly one breakpoint active
        m.addConstr(quicksum(w[lid][i] for i in range(Mobj)) == 1)

    # Linearised thermal constraints per breakpoint
    for c in components:
        lid = c["id"]
        cap = c["capacity_mva"] * 1000.0  # kW
        for i in range(Mobj):
            a = params["thermal_a"][i]
            b = params["thermal_b"][i]
            c_ = params["thermal_c"][i]
            m.addConstr(
                a * P_th[lid][i] + b * Q_th[lid][i] + c_ * cap * w[lid][i] + eps[lid][i] == 0
            )

        # Quadratic thermal capacity check (MIQCP)
        Psum = quicksum(P_th[lid][i] for i in range(Mobj))
        Qsum = quicksum(Q_th[lid][i] for i in range(Mobj))
        m.addQConstr(Psum * Psum + Qsum * Qsum <= cap * cap)

    # Total demand / generation targets
    total_load_kw = params.get("total_load_mw", 5.0) * 1000.0
    total_gen_kw = params.get("total_gen_mw", 4.0) * 1000.0
    m.addConstr(quicksum(P_load[k] for k in nodes) == total_load_kw)
    m.addConstr(quicksum(P_dg[k] for k in nodes) == total_gen_kw)

    # PV variables + piecewise objective linearisation
    PV = {c["id"]: m.addVar(lb=0.0, name=f"PV_{c['id']}") for c in components}
    for c in components:
        lid = c["id"]
        for i in range(Mobj):
            a_obj = params["obj_a"][i]
            b_obj = params["obj_b"][i]
            m.addConstr(PV[lid] >= a_obj * n_l[lid] + b_obj - (1 - w[lid][i]) * 1e9)

    # Objective: minimise total PV + penalty on slack
    m.setObjective(
        quicksum(PV[c["id"]] for c in components)
        + 1e3 * quicksum(eps[c["id"]][i] for c in components for i in range(Mobj)),
        GRB.MINIMIZE,
    )

    m.params.OutputFlag = 1
    return m
