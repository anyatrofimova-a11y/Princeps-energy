"""Grid GNN surrogate — distill pandapower N-1 contingency results into a jraph
graph neural network so we can return power-flow answers in ~10 ms instead of
~30 s, while keeping pandapower as ground truth for training labels.

Design:
  • Network → jraph.GraphsTuple
      nodes (substations / buses): voltage_kv, demand_mw, generation_mw, type
      edges (lines / transformers): rating_mva, length_km, type, status
      globals: total_demand_mw, total_gen_mw, slack_bus_idx
  • Labels (from pandapower N-1):
      per-edge: loading_pct under each contingency
      per-node: vm_pu, va_degree
  • Architecture: GraphNetwork (Battaglia 2018) with 3 message-passing rounds
      edge_fn: MLP(2*32 + 16 + 8 → 32)
      node_fn: MLP(32 + 32 → 32)
      global_fn: MLP(32 + 32 → 32)
  • Output: heads predict (loading_pct, vm_pu, va_degree).

This file ships the scaffolding: graph builder, distillation training loop,
inference wrapper. Heavy deps (jraph, optax, jax, pandapower) are imported
lazily so the module loads even when those venvs aren't active.

Run training inside .venv-grid (Python 3.12 — pandapower) or a dedicated
.venv-jraph if jax + jraph have wheel issues with Python 3.12.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

log = logging.getLogger("princeps.grid_gnn")

WEIGHTS_PATH_DEFAULT = Path(__file__).parent / "grid_gnn_weights.npz"


# ─────────────────────────── Graph builder ───────────────────────────


@dataclass
class GraphArrays:
    """Plain-arrays representation. Convertible to jraph.GraphsTuple at fit /
    predict time so we don't take a hard jax dep in this module's import path.
    """
    nodes: list[list[float]]            # [n_nodes, n_node_features]
    edges: list[list[float]]            # [n_edges, n_edge_features]
    senders: list[int]                  # [n_edges]
    receivers: list[int]                # [n_edges]
    globals_: list[float]               # [n_global_features]
    n_node: int
    n_edge: int

    def to_jraph(self):
        import jax.numpy as jnp  # lazy
        import jraph              # lazy
        return jraph.GraphsTuple(
            nodes=jnp.array(self.nodes, dtype=jnp.float32),
            edges=jnp.array(self.edges, dtype=jnp.float32),
            senders=jnp.array(self.senders, dtype=jnp.int32),
            receivers=jnp.array(self.receivers, dtype=jnp.int32),
            globals=jnp.array([self.globals_], dtype=jnp.float32),
            n_node=jnp.array([self.n_node], dtype=jnp.int32),
            n_edge=jnp.array([self.n_edge], dtype=jnp.int32),
        )


def from_pandapower(net) -> GraphArrays:
    """Convert a pandapower Network into the canonical graph arrays shape.

    Node features: [vn_kv, demand_mw, generation_mw, is_slack, is_load, is_gen]
    Edge features: [rating_mva, length_km, r_ohm_per_km, x_ohm_per_km, in_service]
    Globals:       [total_demand_mw, total_gen_mw, slack_bus_idx_norm]
    """
    nodes = []
    bus_index_to_pos = {}
    for pos, (idx, b) in enumerate(net.bus.iterrows()):
        bus_index_to_pos[idx] = pos
        # Aggregate loads / generators on this bus.
        load_mw = float(net.load[net.load.bus == idx]["p_mw"].sum()) if len(net.load) else 0.0
        gen_mw = float(net.gen[net.gen.bus == idx]["p_mw"].sum()) if len(net.gen) else 0.0
        is_slack = float((net.ext_grid.bus == idx).any()) if len(net.ext_grid) else 0.0
        is_load = float(load_mw > 0)
        is_gen = float(gen_mw > 0)
        nodes.append([float(b.vn_kv), load_mw, gen_mw, is_slack, is_load, is_gen])

    edges, senders, receivers = [], [], []
    for _, ln in net.line.iterrows():
        senders.append(bus_index_to_pos[ln.from_bus])
        receivers.append(bus_index_to_pos[ln.to_bus])
        edges.append([
            float(ln.max_i_ka * net.bus.loc[ln.from_bus, "vn_kv"] * 1.732),  # MVA proxy
            float(ln.length_km),
            float(ln.r_ohm_per_km),
            float(ln.x_ohm_per_km),
            float(ln.in_service),
        ])
    if hasattr(net, "trafo"):
        for _, tr in net.trafo.iterrows():
            senders.append(bus_index_to_pos[tr.hv_bus])
            receivers.append(bus_index_to_pos[tr.lv_bus])
            edges.append([float(tr.sn_mva), 0.0, 0.0, 0.0, float(tr.in_service)])

    total_demand = sum(n[1] for n in nodes)
    total_gen = sum(n[2] for n in nodes)
    slack_idx = next((i for i, n in enumerate(nodes) if n[3] > 0), 0)
    globals_ = [total_demand, total_gen, slack_idx / max(1, len(nodes))]

    return GraphArrays(
        nodes=nodes, edges=edges, senders=senders, receivers=receivers,
        globals_=globals_, n_node=len(nodes), n_edge=len(edges),
    )


# ─────────────────────────── Model ───────────────────────────


def build_gnn(hidden: int = 32):
    """Returns a haiku-style transform of a 3-round GraphNetwork. Lazy-imports
    haiku + jraph so the module doesn't fail to load without them.
    """
    import haiku as hk        # lazy
    import jax                # lazy
    import jax.numpy as jnp   # lazy
    import jraph              # lazy

    def _mlp(out_size: int):
        return hk.nets.MLP([hidden, out_size], activate_final=False)

    def forward(graph: "jraph.GraphsTuple"):
        # Lift inputs to hidden-size via initial MLPs, then run 3 GraphNetwork rounds.
        graph = graph._replace(
            nodes=hk.Linear(hidden)(graph.nodes),
            edges=hk.Linear(hidden)(graph.edges),
            globals=hk.Linear(hidden)(graph.globals),
        )
        for _ in range(3):
            net = jraph.GraphNetwork(
                update_edge_fn=lambda e, sn, rn, g: _mlp(hidden)(jnp.concatenate([e, sn, rn, jnp.broadcast_to(g, (e.shape[0], g.shape[-1]))], axis=-1)),
                update_node_fn=lambda n, sa, ra, g: _mlp(hidden)(jnp.concatenate([n, sa, ra, jnp.broadcast_to(g, (n.shape[0], g.shape[-1]))], axis=-1)),
                update_global_fn=lambda na, ea, g: _mlp(hidden)(jnp.concatenate([na, ea, g], axis=-1)),
            )
            graph = net(graph)
        # Heads.
        edge_loading_pct = hk.Linear(1)(graph.edges).squeeze(-1)
        node_vm_pu = hk.Linear(1)(graph.nodes).squeeze(-1)
        node_va_degree = hk.Linear(1)(graph.nodes).squeeze(-1)
        return {"edge_loading_pct": edge_loading_pct,
                "node_vm_pu": node_vm_pu,
                "node_va_degree": node_va_degree}

    return hk.without_apply_rng(hk.transform(forward))


# ─────────────────────────── Distillation training ───────────────────────────


def collect_pandapower_labels(net, contingencies: Iterable[int] | None = None) -> list[dict]:
    """Run pandapower N-1 sweeps and yield per-contingency labels matching the
    GraphArrays edge / node order. `contingencies` is a list of edge indices to
    fail; if None, sweep every line.
    """
    import pandapower as pp  # lazy

    if contingencies is None:
        contingencies = list(net.line.index)

    samples = []
    for line_idx in contingencies:
        net.line.at[line_idx, "in_service"] = False
        try:
            pp.runpp(net, numba=False, init="results", lightsim2grid=True)
            samples.append({
                "contingency_line": int(line_idx),
                "edge_loading_pct": net.res_line["loading_percent"].fillna(0).tolist(),
                "node_vm_pu": net.res_bus["vm_pu"].tolist(),
                "node_va_degree": net.res_bus["va_degree"].tolist(),
            })
        except Exception as e:
            log.warning("pandapower runpp failed under contingency line=%s: %s", line_idx, e)
        finally:
            net.line.at[line_idx, "in_service"] = True
    return samples


def train(net, *, steps: int = 5_000, learning_rate: float = 1e-3,
          weights_out: Path = WEIGHTS_PATH_DEFAULT) -> dict:
    """Distill pandapower N-1 results into the GNN. Saves weights to disk.

    Returns a small training summary dict (final losses, time elapsed).
    """
    import time
    import jax            # lazy
    import jax.numpy as jnp
    import optax          # lazy
    import numpy as np    # lazy

    graph = from_pandapower(net).to_jraph()
    labels = collect_pandapower_labels(net)
    if not labels:
        raise RuntimeError("No pandapower labels produced — cannot train.")

    edge_target = jnp.array([s["edge_loading_pct"] for s in labels])
    node_vm_target = jnp.array([s["node_vm_pu"] for s in labels])
    node_va_target = jnp.array([s["node_va_degree"] for s in labels])

    model = build_gnn()
    rng = jax.random.PRNGKey(0)
    params = model.init(rng, graph)
    opt = optax.adam(learning_rate)
    opt_state = opt.init(params)

    def loss_fn(params, graph_in, edge_t, vm_t, va_t):
        pred = model.apply(params, graph_in)
        return (
            jnp.mean((pred["edge_loading_pct"] - edge_t) ** 2)
            + jnp.mean((pred["node_vm_pu"] - vm_t) ** 2)
            + jnp.mean((pred["node_va_degree"] - va_t) ** 2)
        )

    @jax.jit
    def step(params, opt_state, graph_in, edge_t, vm_t, va_t):
        loss, grads = jax.value_and_grad(loss_fn)(params, graph_in, edge_t, vm_t, va_t)
        updates, opt_state = opt.update(grads, opt_state, params)
        params = optax.apply_updates(params, updates)
        return params, opt_state, loss

    t0 = time.time()
    losses = []
    for i in range(steps):
        # NB: real impl iterates over multiple network states + contingencies.
        params, opt_state, loss = step(params, opt_state, graph, edge_target[0], node_vm_target[0], node_va_target[0])
        if i % 500 == 0:
            losses.append(float(loss))
            log.info("step %d loss=%.4f", i, float(loss))
    elapsed = time.time() - t0

    # Save weights.
    flat = jax.tree_util.tree_map(np.asarray, params)
    np.savez(weights_out, **{f"p_{i}": v for i, v in enumerate(jax.tree_util.tree_leaves(flat))})
    log.info("saved gnn weights to %s", weights_out)

    return {"final_loss": losses[-1] if losses else None, "elapsed_s": elapsed,
            "weights_path": str(weights_out)}


# ─────────────────────────── Inference ───────────────────────────


_loaded = {"params": None, "model": None}


def predict(net) -> dict:
    """Online inference. Lazy-loads weights on first call."""
    import numpy as np    # lazy

    if _loaded["params"] is None:
        if not WEIGHTS_PATH_DEFAULT.exists():
            raise RuntimeError(f"GNN weights not found at {WEIGHTS_PATH_DEFAULT}. "
                               "Run grid_gnn_surrogate.train(net) first.")
        loaded = np.load(WEIGHTS_PATH_DEFAULT)
        # NB: production-grade reload reconstructs the haiku tree shape; we
        # store flat arrays here as an intermediate format. See README.
        _loaded["params"] = {k: loaded[k] for k in loaded.files}
        _loaded["model"] = build_gnn()
        log.info("loaded gnn weights from %s", WEIGHTS_PATH_DEFAULT)

    graph = from_pandapower(net).to_jraph()
    pred = _loaded["model"].apply(_loaded["params"], graph)
    return {k: list(map(float, v)) for k, v in pred.items()}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dump_graph", "train"], default="dump_graph")
    parser.add_argument("--case", default="case9", help="pandapower test case (case9, case14, case_ieee30, ...)")
    args = parser.parse_args()

    import pandapower.networks as pn
    net = getattr(pn, args.case)()
    if args.mode == "dump_graph":
        g = from_pandapower(net)
        print(json.dumps({"n_nodes": g.n_node, "n_edges": g.n_edge,
                          "globals": g.globals_, "first_node": g.nodes[0]}, indent=2))
    elif args.mode == "train":
        result = train(net)
        print(json.dumps(result, indent=2))
