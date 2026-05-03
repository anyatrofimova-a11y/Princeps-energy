"""FMU / Twin runner — subprocess bridge for FMPy + OpenIPSL transient stability,
plus optional Ansys PyTwin for partner-supplied unlicensed .twin files.

Mirrors the pattern of utils/grid_power_flow.py + utils/sam_runner.py:
  • reads JSON from stdin
  • writes JSON to stdout
  • errors → JSON {"error": ...} on stdout + non-zero exit code

Run inside .venv-pytwin (Python 3.12) — kept separate from main 3.14 venv
because FMPy + pytwin pin older numpy/scipy than Princeps' core stack.

Environment:
  TWIN_PYTHON   path to .venv-pytwin/bin/python (set in app/.env)

Caller pattern (from FastAPI):
  proc = await asyncio.create_subprocess_exec(
      os.environ['TWIN_PYTHON'], 'utils/twin_runner.py',
      stdin=PIPE, stdout=PIPE, stderr=PIPE,
  )
  out, err = await proc.communicate(json.dumps(request).encode())

Request schema:
  {
    "action": "list_models" | "simulate_fmu" | "simulate_twin",
    "fmu":    "ieee9_bess.fmu",            # for simulate_fmu
    "twin":   "vendor_bess_thermal.twin",  # for simulate_twin
    "inputs": {<varname>: <scalar> | [[t,v], ...]},
    "t_end":  60.0,
    "dt":     0.005,
    "outputs": ["frequency", "v_bus_5", ...]
  }

Response schema:
  {"time": [...], "outputs": {<name>: [...]}}
or
  {"error": "...", "type": "...", "trace": "..."}

License guard: artifact ids 'fmpy_runtime' (BSD-2), 'openipsl_models' (BSD-3),
'pytwin_runtime' (MIT) are commercial-safe. Customer-supplied .twin files
must be registered in licenses.yaml individually before use.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "twin_models"


def _list_models(_req):
    fmus = sorted(p.name for p in MODELS_DIR.glob("*.fmu"))
    twins = sorted(p.name for p in MODELS_DIR.glob("*.twin"))
    return {"fmus": fmus, "twins": twins, "models_dir": str(MODELS_DIR)}


def _simulate_fmu(req):
    from fmpy import simulate_fmu  # lazy

    fmu_path = MODELS_DIR / req["fmu"]
    if not fmu_path.exists():
        raise FileNotFoundError(f"FMU not found: {fmu_path}")

    inputs = req.get("inputs") or {}
    outputs = req.get("outputs")
    t_end = float(req.get("t_end", 60.0))
    dt = float(req.get("dt", 0.005))

    start_values = {}
    for k, v in inputs.items():
        if isinstance(v, (int, float, bool, str)):
            start_values[k] = v
        # Time-series inputs would be passed via `input` arg to simulate_fmu;
        # we keep this v1 simple and only support scalar start_values.

    result = simulate_fmu(
        str(fmu_path),
        start_time=0.0,
        stop_time=t_end,
        step_size=dt,
        start_values=start_values,
        output=outputs,
    )

    time = result["time"].tolist()
    out = {}
    for name in outputs or [n for n in result.dtype.names if n != "time"]:
        if name in result.dtype.names:
            out[name] = result[name].tolist()
    return {"time": time, "outputs": out}


def _simulate_twin(req):
    """Run an Ansys .twin file via PyTwin. Caller must have exported the
    .twin as 'unlicensed' (Twin Builder 2023 R1 SP1+) — otherwise an Ansys
    License Manager feature is required and we should refuse here.
    """
    from pytwin import TwinModel  # lazy

    twin_path = MODELS_DIR / req["twin"]
    if not twin_path.exists():
        raise FileNotFoundError(f"Twin not found: {twin_path}")

    inputs = req.get("inputs") or {}
    t_end = float(req.get("t_end", 60.0))
    dt = float(req.get("dt", 0.005))

    twin = TwinModel(model_filepath=str(twin_path))
    twin.initialize_evaluation(
        parameters=inputs.get("parameters"),
        inputs=inputs.get("inputs"),
    )

    times = [0.0]
    outputs = {k: [v] for k, v in (twin.outputs or {}).items()}
    t = 0.0
    while t < t_end:
        t = min(t + dt, t_end)
        twin.evaluate_step_by_step(step_size=dt, inputs=inputs.get("inputs"))
        times.append(t)
        for k, v in (twin.outputs or {}).items():
            outputs.setdefault(k, []).append(v)
    return {"time": times, "outputs": outputs}


HANDLERS = {
    "list_models": _list_models,
    "simulate_fmu": _simulate_fmu,
    "simulate_twin": _simulate_twin,
}


def main():
    try:
        req = json.loads(sys.stdin.read() or "{}")
        action = req.get("action") or "list_models"
        if action not in HANDLERS:
            raise ValueError(f"Unknown action: {action!r}. Valid: {list(HANDLERS)}")
        result = HANDLERS[action](req)
        sys.stdout.write(json.dumps(result, default=str))
        sys.exit(0)
    except Exception as exc:
        sys.stdout.write(json.dumps({
            "error": str(exc),
            "type": type(exc).__name__,
            "trace": traceback.format_exc(),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
