"""Market data providers behind one small interface.

A provider returns real, dated price quotes for a crop (INR per quintal). Two exist:

  * FarmerQuotes   what the farmer typed in from a real mandi/buyer: market, date, price, distance, transport. This is the
                   working, real input path.
  * DemoMarket     synthetic quotes for trying the screen WITHOUT any data entry. Off by default (ECONOMICS_DEMO_MARKET),
                   and every quote it makes is tagged source="demo" so the page labels it DEMO DATA. It must never be
                   mistaken for live prices.

No live mandi feed is connected. Adding one means implementing `quotes()` and returning source="live"; nothing else changes.
"""
import hashlib
import os
from datetime import date, timedelta
from typing import Protocol


class MarketProvider(Protocol):
    name: str

    def markets(self, inputs: dict, crop: str | None, today: date) -> list[dict]:
        """[{id, name, source, distance_km, transport_per_quintal, prices: [{date, price}]}]"""
        ...


class FarmerQuotes:
    name = "farmer"

    def markets(self, inputs: dict, crop: str | None, today: date) -> list[dict]:
        out = []
        for m in inputs.get("markets") or []:
            out.append({"id": m["id"], "name": m["name"], "source": "farmer", "distance_km": m.get("distance_km"), "transport_per_quintal": m.get("transport_per_quintal"),
                        "prices": [{"date": p["date"], "price": p["price"]} for p in m.get("prices", [])]})
        return out


class DemoMarket:
    """Deterministic synthetic quotes (hash of the crop name), flagged as demo. Only used when the operator turns it on."""

    name = "demo"

    def markets(self, inputs: dict, crop: str | None, today: date) -> list[dict]:
        if not crop:
            return []
        seed = int(hashlib.sha256(crop.lower().encode()).hexdigest(), 16)
        base = 1200 + seed % 2400
        out = []
        for i, (label, dist, tr, drift) in enumerate((("Demo market A", 18, 120, 0.02), ("Demo market B", 65, 260, 0.05))):
            prices = [{"date": (today - timedelta(days=d)).isoformat(), "price": round(base * (1 + drift * (6 - d) / 6 + (i * 0.04)))} for d in (6, 4, 2, 0)]
            out.append({"id": f"demo{i}", "name": label, "source": "demo", "distance_km": dist, "transport_per_quintal": tr, "prices": prices})
        return out


def demo_enabled() -> bool:
    return os.environ.get("ECONOMICS_DEMO_MARKET", "false").strip().lower() == "true"


def providers() -> list[MarketProvider]:
    ps: list[MarketProvider] = [FarmerQuotes()]
    if demo_enabled():
        ps.append(DemoMarket())
    return ps


def gather(inputs: dict, crop: str | None, today: date) -> tuple[list[dict], list[str]]:
    """Quotes from every enabled provider, plus the provider names that were really asked. The farmer's own quotes always come first."""
    markets, asked = [], []
    for p in providers():
        asked.append(p.name)
        markets.extend(p.markets(inputs, crop, today))
    return markets, asked
