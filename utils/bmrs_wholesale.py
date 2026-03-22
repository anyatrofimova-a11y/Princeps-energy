"""Real BMRS wholesale price data — replaces simulated prices."""
import httpx
import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger("princeps.bmrs_wholesale")
BMRS = "https://data.elexon.co.uk/bmrs/api/v1"


async def fetch_system_prices(days_back: int = 7) -> dict:
    """Fetch real system buy/sell prices from DETSYSPRICES."""
    async with httpx.AsyncClient(timeout=15) as client:
        from_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        resp = await client.get(
            f"{BMRS}/balancing/pricing/system-price",
            params={"from": from_date, "to": to_date, "format": "json"},
        )
        if resp.status_code == 200:
            data = resp.json()
            records = data if isinstance(data, list) else data.get("data", [])
            return {
                "source": "BMRS_DETSYSPRICES",
                "from": from_date,
                "to": to_date,
                "records": len(records),
                "prices": [
                    {
                        "date": r.get("settlementDate"),
                        "sp": r.get("settlementPeriod"),
                        "buy_price": r.get("systemBuyPrice"),
                        "sell_price": r.get("systemSellPrice"),
                    }
                    for r in records
                ],
                "stats": _compute_stats(records),
            }
    return {"error": "BMRS API unavailable", "source": "fallback"}


async def fetch_day_ahead_prices(date: str = None) -> dict:
    """Fetch N2EX day-ahead auction prices."""
    # Use market index as proxy
    async with httpx.AsyncClient(timeout=15) as client:
        params = {"format": "json"}
        if date:
            params["settlementDate"] = date
        resp = await client.get(f"{BMRS}/balancing/pricing/market-index", params=params)
        if resp.status_code == 200:
            data = resp.json()
            records = data if isinstance(data, list) else data.get("data", [])
            return {
                "source": "BMRS_MID",
                "records": len(records),
                "prices": [
                    {
                        "date": r.get("settlementDate"),
                        "sp": r.get("settlementPeriod"),
                        "price": r.get("price"),
                        "volume": r.get("volume"),
                    }
                    for r in records
                ],
            }
    return {"error": "unavailable"}


async def fetch_imbalance_prices(days_back: int = 1) -> dict:
    """Fetch real imbalance (cash-out) prices."""
    async with httpx.AsyncClient(timeout=15) as client:
        from_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        resp = await client.get(
            f"{BMRS}/balancing/pricing/system-price",
            params={"from": from_date, "format": "json"},
        )
        if resp.status_code == 200:
            data = resp.json()
            records = data if isinstance(data, list) else data.get("data", [])
            return {
                "source": "BMRS_imbalance",
                "records": len(records),
                "prices": [
                    {
                        "date": r.get("settlementDate"),
                        "sp": r.get("settlementPeriod"),
                        "buy": r.get("systemBuyPrice"),
                        "sell": r.get("systemSellPrice"),
                        "net_volume": r.get("netImbalanceVolume"),
                    }
                    for r in records
                ],
            }
    return {"error": "unavailable"}


async def current_wholesale_price() -> dict:
    """Get the most recent wholesale price for use in revenue calculations."""
    async with httpx.AsyncClient(timeout=10) as client:
        # Try market index first
        resp = await client.get(f"{BMRS}/balancing/pricing/market-index", params={"format": "json"})
        if resp.status_code == 200:
            data = resp.json()
            records = data if isinstance(data, list) else data.get("data", [])
            if records:
                latest = records[-1]
                return {
                    "price_gbp_mwh": latest.get("price"),
                    "settlement_period": latest.get("settlementPeriod"),
                    "date": latest.get("settlementDate"),
                    "source": "BMRS_MID",
                }
        # Fallback to system price
        resp = await client.get(f"{BMRS}/balancing/pricing/system-price", params={"format": "json"})
        if resp.status_code == 200:
            data = resp.json()
            records = data if isinstance(data, list) else data.get("data", [])
            if records:
                latest = records[-1]
                return {
                    "price_gbp_mwh": latest.get("systemSellPrice"),
                    "settlement_period": latest.get("settlementPeriod"),
                    "source": "BMRS_SSP",
                }
    return {"price_gbp_mwh": 48.0, "source": "fallback"}


def _compute_stats(records):
    sells = [r.get("systemSellPrice") for r in records if r.get("systemSellPrice") is not None]
    buys = [r.get("systemBuyPrice") for r in records if r.get("systemBuyPrice") is not None]
    if not sells:
        return {}
    return {
        "avg_sell_price": round(sum(sells) / len(sells), 2),
        "avg_buy_price": round(sum(buys) / len(buys), 2) if buys else None,
        "max_sell_price": round(max(sells), 2),
        "min_sell_price": round(min(sells), 2),
        "spread_avg": round((sum(buys) / len(buys)) - (sum(sells) / len(sells)), 2) if buys else None,
        "count": len(sells),
    }
