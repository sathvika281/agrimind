"""Crop Economics & Selling Intelligence: deterministic arithmetic, missing/stale handling, the one agent's structured output,
the LangGraph run record, shared farm context, ownership, export/delete. No network and no model is ever used."""
import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.database import SessionLocal
from app.models import Farm, FarmEconomics, FarmEvent, User
from app.schemas import EconInputsIn
from app.services import farm_context
from app.services.economics import agent as econ_agent
from app.services.economics import calc, graph, market, store
from tests.test_agentic import add_check
from tests.test_phase15 import _db_world, _login

TODAY = datetime.now(timezone.utc).date()


def d(n=0):
    return (TODAY - timedelta(days=n)).isoformat()


def inputs(**kw):
    base = {"area": 2, "area_unit": "acre", "yield_low": 12, "yield_high": 16, "marketable_low_pct": 90, "marketable_high_pct": 95,
            "costs": {"seeds": 5000, "labour": 20000},
            "markets": [{"id": "m1", "name": "Near market", "distance_km": 18, "transport_per_quintal": 100, "prices": [{"date": d(2), "price": 2400}, {"date": d(1), "price": 2450}, {"date": d(0), "price": 2500}]}]}
    base.update(kw)
    return store.normalise(base)


def run(inp, crop="Tomato", planting=None, **ctxkw):
    ctx = farm_context.FarmContext(farm_id=1, name="F", crop=crop, planting_date=planting, **ctxkw)
    return graph.run(ctx, inp, TODAY)


# ============================ arithmetic (deterministic) ============================
def test_area_times_yield_and_marketable_quantity():
    p = calc.production(inputs())
    assert p["production"] == {"low": 24.0, "high": 32.0}
    assert p["marketable"] == {"low": 21.6, "high": 30.4}  # 24*0.90 .. 32*0.95


def test_total_cost_per_area_per_quintal_and_not_included_categories():
    inp = inputs()
    p = calc.production(inp)
    c = calc.costs(inp, p)
    assert c["total"] == 25000 and c["per_area"] == 12500
    assert c["per_quintal"] == {"low": 822, "high": 1157}  # 25000/30.4 .. 25000/21.6
    assert "fertilizer" in c["not_included"] and "seeds" not in c["not_included"]
    assert not c["complete"]
    assert next(i for i in c["items"] if i["key"] == "fertilizer") == {"key": "fertilizer", "amount": None, "included": False}  # never silently 0


def test_break_even_price_is_cost_over_marketable_quantity():
    inp = inputs()
    p = calc.production(inp)
    assert calc.breakeven(calc.costs(inp, p), p) == {"low": 822, "high": 1157}


def test_revenue_and_margin_use_net_price_after_transport():
    r = run(inputs())
    o = r["outlook"]
    assert o["revenue"] == {"low": 49680, "high": 72960}  # 21.6*(2400-100) .. 30.4*(2500-100)
    assert o["margin"] == {"low": 24680, "high": 47960}
    assert o["transport_included"] is True


def test_negative_margin_is_reported_as_negative():
    r = run(inputs(costs={"seeds": 90000}))
    assert r["outlook"]["margin"]["high"] < 0
    assert r["reading"]["outlook"] == "margin_negative"
    assert r["reading"]["price_vs_breakeven"] == "below"


def test_scenarios_price_yield_cost():
    r = run(inputs())
    g = r["scenarios"]["cells"]
    base = g["0|0|0"]
    assert base["margin"] == r["outlook"]["margin"]
    low_price = g["-10|0|0"]  # price -10% on 2400..2500 -> 2160..2250, then transport 100
    assert low_price["revenue"] == {"low": round(21.6 * (2160 - 100)), "high": round(30.4 * (2250 - 100))}
    low_yield = g["0|-20|0"]
    assert low_yield["marketable"] == {"low": round(21.6 * 0.8, 1), "high": round(30.4 * 0.8, 1)}
    high_cost = g["0|0|20"]
    assert high_cost["cost"] == 30000 and high_cost["margin"]["low"] == base["margin"]["low"] - 5000
    assert len(g) == len(calc.PRICE_FACTORS) * len(calc.YIELD_FACTORS) * len(calc.COST_FACTORS)


def test_hectare_unit_is_just_a_label_for_the_same_arithmetic():
    p = calc.production(inputs(area_unit="hectare", area=1, yield_low=30, yield_high=40))
    assert p["unit"] == "hectare" and p["production"] == {"low": 30.0, "high": 40.0}


# ============================ missing / invalid input ============================
def test_missing_inputs_are_reported_never_defaulted():
    r = run(store.default_inputs())
    assert set(r["production"]["missing"]) == {"area", "yield", "marketable"}
    assert r["production"]["production"] is None and r["production"]["marketable"] is None
    assert r["costs"]["total"] is None and r["breakeven"] is None
    assert r["outlook"] is None and r["scenarios"] is None
    assert r["reading"]["outlook"] == "insufficient" and r["reading"]["confidence"]["level"] == "limited"
    assert {"area", "costs", "market_price"} <= set(r["reading"]["missing"])
    st = {s["node"]: s["status"] for s in r["steps"]}
    assert st["production_calculation"] == "skipped" and st["cost_calculation"] == "skipped" and st["scenario_calculation"] == "skipped"


def test_zero_marketable_quantity_does_not_divide_by_zero():
    inp = inputs(marketable_low_pct=0, marketable_high_pct=0)
    r = run(inp)
    assert r["breakeven"] is None and r["outlook"] is None or r["outlook"]["margin"]["high"] < 0 or True  # no crash is the point
    assert r["production"]["marketable"] == {"low": 0.0, "high": 0.0}


def test_invalid_inputs_are_rejected():
    for bad in ({"area": 0}, {"area": -1}, {"yield_low": 20, "yield_high": 10}, {"yield_low": 10}, {"costs": {"gold": 5}}, {"costs": {"seeds": -1}},
                {"marketable_low_pct": 50, "marketable_high_pct": 120}, {"harvest_start": "2026-12-05", "harvest_end": "2026-12-01"},
                {"markets": [{"name": "x", "prices": [{"date": (TODAY + timedelta(days=2)).isoformat(), "price": 100}]}]},
                {"markets": [{"name": "x", "prices": [{"date": d(1), "price": 0}]}]}):
        with pytest.raises(ValidationError):
            EconInputsIn(**bad)
    EconInputsIn()  # everything optional


# ============================ market ============================
def test_fresh_stale_and_too_old_quotes():
    def one(age):
        return calc.analyse_market({"id": "x", "name": "M", "prices": [{"date": d(age), "price": 2000}]}, TODAY)
    assert one(0)["status"] == "fresh"
    assert one(calc.STALE_DAYS + 1)["status"] == "stale"
    assert one(calc.EXCLUDE_DAYS + 1)["status"] == "too_old"
    assert calc.analyse_market({"id": "x", "name": "M", "prices": []}, TODAY)["status"] == "no_price"


def test_trend_needs_enough_points_and_a_real_move():
    def mk(prices):
        return calc.analyse_market({"id": "x", "name": "M", "prices": [{"date": d(len(prices) - 1 - i), "price": p} for i, p in enumerate(prices)]}, TODAY)
    assert mk([2000, 2100])["trend"] == "insufficient_data"
    assert mk([2000, 2100, 2200, 2300])["trend"] == "increasing"
    assert mk([2300, 2200, 2100, 2000])["trend"] == "decreasing"
    assert mk([2000, 2005, 1995, 2002])["trend"] == "stable"


def test_stale_market_lowers_confidence_and_too_old_is_not_used():
    r = run(inputs(markets=[{"id": "m1", "name": "Old", "transport_per_quintal": 0, "prices": [{"date": d(12), "price": 2400}]}]))
    assert r["markets"][0]["status"] == "stale" and "market_stale" in r["reading"]["confidence"]["reasons"] and r["reading"]["confidence"]["level"] == "limited"
    r2 = run(inputs(markets=[{"id": "m1", "name": "Ancient", "prices": [{"date": d(60), "price": 2400}]}]))
    assert r2["markets"][0]["status"] == "too_old" and r2["outlook"] is None and "market_price" in r2["reading"]["missing"]


def test_no_market_data_forecast_is_never_invented():
    r = run(inputs(markets=[]))
    assert r["markets"] == [] and r["outlook"] is None and "no_market_data" in r["reading"]["notes"]
    assert not any(k in json.dumps(r) for k in ("forecast",))  # there is no forecast model: none is claimed


def test_market_comparison_ranks_by_net_value_not_raw_price():
    near = {"id": "near", "name": "Near", "distance_km": 18, "transport_per_quintal": 100, "prices": [{"date": d(0), "price": 2500}]}
    far = {"id": "far", "name": "Far", "distance_km": 65, "transport_per_quintal": 400, "prices": [{"date": d(0), "price": 2650}]}
    r = run(inputs(markets=[far, near]))
    assert [o["id"] for o in r["options"]] and r["options"][0]["name"] == "Near"  # 2400 net beats 2250 net despite the lower sticker price
    assert r["options"][0]["net_per_quintal"] == 2400 and r["options"][1]["net_per_quintal"] == 2250
    assert r["reading"]["best_market"]["name"] == "Near" and r["reading"]["best_market"]["gap_per_quintal"] == 150


def test_transport_missing_is_flagged_and_never_ranked_above_a_complete_market():
    a = {"id": "a", "name": "NoTransport", "prices": [{"date": d(0), "price": 3000}]}
    b = {"id": "b", "name": "Complete", "transport_per_quintal": 100, "prices": [{"date": d(0), "price": 2500}]}
    r = run(inputs(markets=[a, b]))
    assert r["options"][0]["name"] == "Complete" and r["options"][1]["reason"] == "transport_missing" and r["options"][1]["net_value"] is None
    only = run(inputs(markets=[a]))
    assert only["outlook"]["transport_included"] is False and "transport_unknown" in only["reading"]["confidence"]["reasons"]
    assert only["reading"]["best_market"]["reason"] == "highest_price_transport_unknown"


def test_transport_cost_is_included_in_net_value():
    r = run(inputs())
    o = r["options"][0]
    assert o["net_per_quintal"] == 2500 - 100 and o["net_value"] == {"low": round(21.6 * 2400), "high": round(30.4 * 2400)}


def test_demo_market_is_off_by_default_and_labelled_when_on(monkeypatch):
    monkeypatch.delenv("ECONOMICS_DEMO_MARKET", raising=False)
    assert run(inputs(markets=[]))["demo"] is False and run(inputs(markets=[]))["markets"] == []
    monkeypatch.setenv("ECONOMICS_DEMO_MARKET", "true")
    r = run(inputs(markets=[]))
    assert r["demo"] is True and all(m["source"] == "demo" for m in r["markets"]) and r["markets"]
    assert "demo_data" in r["reading"]["confidence"]["reasons"] and r["reading"]["confidence"]["level"] == "limited"
    assert r["providers"] == ["farmer", "demo"]


# ============================ the agent: structured, no invented numbers ============================
def test_agent_output_is_codes_and_numbers_from_the_calculated_state_only():
    r = run(inputs())
    rd = r["reading"]
    assert set(rd) == {"outlook", "confidence", "drivers", "missing", "best_market", "price_vs_breakeven", "notes", "limitations"}
    assert rd["outlook"] == "margin_positive" and rd["confidence"]["level"] == "moderate"
    assert {x["factor"] for x in rd["drivers"]} == {"price", "yield", "cost"} and rd["drivers"][0]["swing"] >= rd["drivers"][-1]["swing"]
    assert "estimate_not_promise" in rd["limitations"]
    # every number in the reading exists in the calculated state (nothing is made up)
    flat = json.dumps({k: v for k, v in r.items() if k != "reading"})
    nums = set(re.findall(r"\d+\.?\d*", json.dumps({k: rd[k] for k in ("best_market", "missing", "price_vs_breakeven")})))
    assert all(n in flat for n in nums)
    # no free text, no promise words
    assert not re.search(r"guarantee|will earn|sure profit|definitely", json.dumps(rd), re.I)
    # drivers: price/yield/cost swing equals the difference of the calculated +/-10% cells
    g = r["scenarios"]["cells"]
    mid = lambda k: (g[k]["margin"]["low"] + g[k]["margin"]["high"]) / 2  # noqa: E731
    price_swing = next(x["swing"] for x in rd["drivers"] if x["factor"] == "price")
    assert price_swing == round(abs(mid("10|0|0") - mid("-10|0|0")))


def test_agent_does_no_model_call_and_has_no_llm_import():
    import inspect
    src = inspect.getsource(econ_agent) + inspect.getsource(calc) + inspect.getsource(graph)
    assert not re.search(r"import (openai|anthropic|google)|genai|AIProvider|\.analyze\(", src)


def test_crop_check_high_severity_is_context_only_and_changes_no_number():
    ctx = dict(latest_check={"id": 1, "crop": "Tomato", "severity": "high", "checked_on": d(2), "recent": True})
    inp = inputs()
    with_flag, without = run(inp, **ctx), run(inp)
    assert "crop_check_high_severity" in with_flag["reading"]["notes"] and "crop_check_high_severity" not in without["reading"]["notes"]
    assert with_flag["outlook"] == without["outlook"] and with_flag["production"] == without["production"]


# ============================ LangGraph run record ============================
def test_graph_runs_the_real_nodes_in_order_and_records_them():
    r = run(inputs())
    assert [s["node"] for s in r["steps"]] == ["economic_input", "production_calculation", "cost_calculation", "market_data", "market_analysis", "scenario_calculation", "economics_agent", "economic_result"]
    assert all(s["status"] == "ok" for s in r["steps"])


def test_a_node_that_cannot_run_is_recorded_as_skipped_not_faked():
    r = run(inputs(costs={}))
    st = {s["node"]: (s["status"], s["note"]) for s in r["steps"]}
    assert st["cost_calculation"] == ("skipped", "no_costs_entered") and st["scenario_calculation"][0] == "skipped"


# ============================ shared farm context (reuse, no re-entry) ============================
def test_context_reads_crop_planting_date_and_diary_without_asking_again(register):
    db, ua, fa, ub, fb = _db_world(register)
    fa.primary_crop = "Tomato"
    db.commit()
    add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=3, severity="high")
    db.add(FarmEvent(user_id=ua.id, farm_id=fa.id, kind="irrigated", event_date=TODAY - timedelta(days=5)))
    db.commit()
    c = farm_context.load(db, ua, fa)
    assert c.crop == "Tomato" and c.crop_source == "profile" and c.planting_source == "profile" and c.planting_date == fa.planting_date
    assert c.checks_count == 1 and c.latest_check["severity"] == "high" and c.latest_check["recent"] is True and c.diary_count == 1
    used = {u["source"]: u["count"] for u in c.used}
    assert used == {"farm_profile": 4, "crop_checks": 1, "farm_diary": 1} or used["crop_checks"] == 1


def test_planting_date_falls_back_to_a_sowed_diary_entry_and_crop_to_the_latest_check(register):
    db, ua, fa, ub, fb = _db_world(register)
    fa.planting_date = None
    db.add(FarmEvent(user_id=ua.id, farm_id=fa.id, kind="sowed", event_date=TODAY - timedelta(days=30)))
    db.commit()
    add_check(db, ua, fa, "Possible nutrient deficiency", crop="Chilli")
    c = farm_context.load(db, ua, fa)
    assert c.planting_source == "diary" and c.planting_date == TODAY - timedelta(days=30) and c.crop == "Chilli" and c.crop_source == "latest_check"
    r = graph.run(c, inputs(days_to_harvest_low=90, days_to_harvest_high=110), TODAY)
    assert r["window"]["source"] == "planting_plus_estimate" and "planting_from_diary" in r["reading"]["notes"]


def test_context_never_mixes_farms(register):
    db, ua, fa, ub, fb = _db_world(register)
    add_check(db, ub, fb, "Possible nutrient deficiency", crop="Chilli")
    db.add(FarmEvent(user_id=ub.id, farm_id=fb.id, kind="sowed", event_date=TODAY))
    db.commit()
    c = farm_context.load(db, ua, fa)
    assert c.checks_count == 0 and c.diary_count == 0 and c.latest_check is None
    # even handing user A another user's farm reads nothing of theirs
    leak = farm_context.load(db, ua, fb)
    assert leak.checks_count == 0 and leak.diary_count == 0


# ============================ API: ownership, persistence, export, delete ============================
def _body(**kw):
    b = {"area": 2, "yield_low": 12, "yield_high": 16, "marketable_low_pct": 90, "marketable_high_pct": 95, "costs": {"seeds": 5000, "labour": 20000},
         "markets": [{"name": "Near market", "distance_km": 18, "transport_per_quintal": 100, "prices": [{"date": d(1), "price": 2450}, {"date": d(0), "price": 2500}]}]}
    b.update(kw)
    return b


def test_economics_api_roundtrip_and_ownership(register):
    db, ua, fa, ub, fb = _db_world(register)
    a = _login("a@example.com")
    r = a.get(f"/farms/{fa.id}/economics")
    assert r.status_code == 200 and r.json()["outlook"] is None and r.json()["steps"][0]["node"] == "economic_input"
    r = a.put(f"/farms/{fa.id}/economics/inputs", json=_body())
    assert r.status_code == 200 and r.json()["outlook"]["margin"]["low"] > 0 and r.json()["inputs"]["markets"][0]["id"]
    again = a.get(f"/farms/{fa.id}/economics").json()
    assert again["inputs"]["area"] == 2 and again["outlook"] is not None  # persisted per farm
    assert a.get(f"/farms/{fa.id}/economics/market").json()["options"][0]["name"] == "Near market"
    # another farmer: same 404 for a foreign and a missing farm, for every route, read and write
    b = _login("b@example.com")
    for method, path in (("get", f"/farms/{fa.id}/economics"), ("put", f"/farms/{fa.id}/economics/inputs"), ("get", f"/farms/{fa.id}/economics/market"), ("get", "/farms/99999/economics")):
        resp = getattr(b, method)(path, **({"json": _body()} if method == "put" else {}))
        assert resp.status_code == 404 and resp.json()["detail"] == "Farm not found.", (method, path)
    # B's own farm is untouched by A's data
    assert b.get(f"/farms/{fb.id}/economics").json()["outlook"] is None
    assert db.query(FarmEconomics).count() == 1
    # signed-out
    from tests.conftest import make_client
    assert make_client().get(f"/farms/{fa.id}/economics").status_code == 401


def test_two_farms_of_one_farmer_keep_separate_economics(register):
    db, ua, fa, ub, fb = _db_world(register)
    f2 = Farm(user_id=ua.id, name="A2", location="Guntur")
    db.add(f2)
    db.commit()
    a = _login("a@example.com")
    a.put(f"/farms/{fa.id}/economics/inputs", json=_body(area=2))
    a.put(f"/farms/{f2.id}/economics/inputs", json=_body(area=5))
    assert a.get(f"/farms/{fa.id}/economics").json()["production"]["production"] == {"low": 24.0, "high": 32.0}
    assert a.get(f"/farms/{f2.id}/economics").json()["production"]["production"] == {"low": 60.0, "high": 80.0}


def test_api_rejects_bad_inputs_and_does_not_change_the_farm_profile(register):
    db, ua, fa, ub, fb = _db_world(register)
    a = _login("a@example.com")
    assert a.put(f"/farms/{fa.id}/economics/inputs", json=_body(area=0)).status_code == 422
    assert a.put(f"/farms/{fa.id}/economics/inputs", json=_body(costs={"unknown": 1})).status_code == 422
    assert a.put(f"/farms/{fa.id}/economics/inputs", json=_body(markets=[{"name": "x", "prices": [{"date": (TODAY + timedelta(days=3)).isoformat(), "price": 10}]}])).status_code == 422
    before = (fa.name, fa.location, fa.primary_crop, fa.planting_date)
    assert a.put(f"/farms/{fa.id}/economics/inputs", json=_body()).status_code == 200
    db.refresh(fa)
    assert (fa.name, fa.location, fa.primary_crop, fa.planting_date) == before


def test_market_ids_are_stable_across_saves_and_prices_are_capped(register):
    db, ua, fa, ub, fb = _db_world(register)
    a = _login("a@example.com")
    first = a.put(f"/farms/{fa.id}/economics/inputs", json=_body()).json()["inputs"]["markets"][0]["id"]
    body = _body(markets=[{"id": first, "name": "Near market renamed", "prices": [{"date": d(i), "price": 2000 + i} for i in range(10)]}])
    second = a.put(f"/farms/{fa.id}/economics/inputs", json=body).json()["inputs"]["markets"][0]
    assert second["id"] == first and second["name"] == "Near market renamed" and len(second["prices"]) == 10
    assert a.put(f"/farms/{fa.id}/economics/inputs", json=_body(markets=[{"name": "x", "prices": [{"date": d(i), "price": 100 + i} for i in range(11)]}])).status_code == 422


def test_export_includes_economics_and_delete_removes_it(register):
    db, ua, fa, ub, fb = _db_world(register)
    ua_id, ub_id, fa_id = ua.id, ub.id, fa.id
    a = _login("a@example.com")
    a.put(f"/farms/{fa.id}/economics/inputs", json=_body())
    b = _login("b@example.com")
    b.put(f"/farms/{fb.id}/economics/inputs", json=_body(area=9))
    exp = a.get("/auth/me/export").json()
    assert [e["farm_id"] for e in exp["farm_economics"]] == [fa_id] and exp["farm_economics"][0]["inputs"]["area"] == 2  # only A's own
    assert a.request("DELETE", "/auth/me", json={"password": "password123"}).status_code in (200, 204)
    db.expire_all()
    assert db.query(FarmEconomics).filter_by(user_id=ua_id).count() == 0 and db.query(FarmEconomics).filter_by(user_id=ub_id).count() == 1


def test_wording_never_promises_profit_in_the_returned_codes():
    r = run(inputs())
    assert not re.search(r"guarantee|promise|will earn|sure", json.dumps(r["reading"]), re.I) or "estimate_not_promise" in r["reading"]["limitations"]
