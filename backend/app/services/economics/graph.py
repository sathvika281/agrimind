"""The Economics workflow, orchestrated with LangGraph (the same library as the investigation graph; no second framework).

    economic_input -> production_calculation -> cost_calculation -> market_data -> market_analysis
                   -> scenario_calculation -> economics_agent -> economic_result

Every node does ONE job and writes only its own slice of the shared state. A node that cannot run (for example a
calculation whose inputs are missing) is recorded as "skipped" with the reason; a node is never shown as having run when it
did not. The recorded `steps` and the `context.used` list are the real execution record shown on the Economics page.
Nothing here calls a model.
"""
import time
from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..farm_context import FarmContext
from . import agent, calc, market


class EconState(TypedDict, total=False):
    ctx: FarmContext
    inputs: dict
    today: date
    production: dict
    costs: dict
    breakeven: dict | None
    markets: list[dict]
    providers: list[str]
    options: list[dict]
    reference: dict | None
    outlook: dict | None
    grid: dict | None
    window: dict
    context: dict
    reading: agent.Reading
    steps: list[dict]
    result: dict


def _step(state: EconState, node: str, status: str, note: str = "", t0: float | None = None) -> list[dict]:
    s = {"node": node, "status": status, "note": note}
    if t0 is not None:
        s["ms"] = round((time.perf_counter() - t0) * 1000)
    return [*state.get("steps", []), s]


def build():
    def economic_input(state: EconState):
        t0 = time.perf_counter()
        ctx = state["ctx"]
        ok = bool(ctx.crop)
        return {"context": ctx.public(), "window": calc.harvest_window(state["inputs"], ctx.planting_date),
                "steps": _step(state, "economic_input", "ok" if ok else "ok", "crop_known" if ok else "crop_unknown", t0)}

    def production_calculation(state: EconState):
        t0 = time.perf_counter()
        p = calc.production(state["inputs"])
        return {"production": p, "steps": _step(state, "production_calculation", "ok" if not p["missing"] else "skipped", "inputs_missing" if p["missing"] else "calculated", t0)}

    def cost_calculation(state: EconState):
        t0 = time.perf_counter()
        c = calc.costs(state["inputs"], state["production"])
        be = calc.breakeven(c, state["production"])
        done = c["total"] is not None
        return {"costs": c, "breakeven": be, "steps": _step(state, "cost_calculation", "ok" if done else "skipped", "calculated" if done else "no_costs_entered", t0)}

    def market_data(state: EconState):
        t0 = time.perf_counter()
        raw, asked = market.gather(state["inputs"], state["ctx"].crop, state["today"])
        return {"markets": raw, "providers": asked, "steps": _step(state, "market_data", "ok" if raw else "skipped", "quotes_found" if raw else "no_market_data", t0)}

    def market_analysis(state: EconState):
        t0 = time.perf_counter()
        ms = [calc.analyse_market(m, state["today"]) for m in state["markets"]]
        opts = calc.selling_options(ms, state["production"])
        ref = calc.reference_market(ms, opts)
        out = calc.outlook(state["production"], state["costs"], ref)
        return {"markets": ms, "options": opts, "reference": ref, "outlook": out, "steps": _step(state, "market_analysis", "ok" if ref else "skipped", "analysed" if ref else "no_usable_price", t0)}

    def scenario_calculation(state: EconState):
        t0 = time.perf_counter()
        g = calc.scenario_grid(state["production"], state["costs"], state["reference"])
        return {"grid": g, "steps": _step(state, "scenario_calculation", "ok" if g else "skipped", "calculated" if g else "needs_production_cost_price", t0)}

    def economics_agent(state: EconState):
        t0 = time.perf_counter()
        reading = agent.interpret({k: state[k] for k in ("production", "costs", "breakeven", "markets", "options", "reference", "outlook", "grid", "window", "context")})
        return {"reading": reading, "steps": _step(state, "economics_agent", "ok", reading.outlook, t0)}

    def economic_result(state: EconState):
        pub = lambda m: {k: v for k, v in m.items() if not k.startswith("_")}  # noqa: E731
        prod = {k: v for k, v in state["production"].items() if not k.startswith("_")}
        costs = {k: v for k, v in state["costs"].items() if not k.startswith("_")}
        demo = any(m["source"] == "demo" for m in state["markets"])
        result = {
            "crop": state["ctx"].crop, "unit": prod["unit"], "context": state["context"], "window": state["window"], "production": prod, "costs": costs, "breakeven": state["breakeven"],
            "markets": [pub(m) for m in state["markets"]], "options": state["options"], "outlook": state["outlook"], "scenarios": state["grid"], "reading": state["reading"].public(),
            "providers": state["providers"], "demo": demo, "today": state["today"].isoformat(),
            "steps": _step(state, "economic_result", "ok"),
        }
        return {"result": result}

    g = StateGraph(EconState)
    order = [("economic_input", economic_input), ("production_calculation", production_calculation), ("cost_calculation", cost_calculation), ("market_data", market_data),
             ("market_analysis", market_analysis), ("scenario_calculation", scenario_calculation), ("economics_agent", economics_agent), ("economic_result", economic_result)]
    for name, fn in order:
        g.add_node(name, fn)
    g.add_edge(START, order[0][0])
    for (a, _), (b, _) in zip(order, order[1:]):
        g.add_edge(a, b)
    g.add_edge(order[-1][0], END)
    return g.compile()


_GRAPH = None


def run(ctx: FarmContext, inputs: dict, today: date) -> dict:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build()
    out = _GRAPH.invoke({"ctx": ctx, "inputs": inputs, "today": today, "steps": []})
    return out["result"]
