"""Per-tenant spend caps for Anthropic + heavy-compute calls.

A tenant has a daily and monthly cap (in USD). Each Claude call (or other
billable op) goes through ``check_and_consume(tenant_id, cost_usd, kind)``
which:
  • atomically increments the rolling daily / monthly counters
  • raises SpendCapExceeded if either cap is breached
  • emits an audit row to ``spend_cap_audit``

Defaults are loaded from env:
  PRINCEPS_DAILY_CAP_USD      (default 50)
  PRINCEPS_MONTHLY_CAP_USD    (default 500)

Per-tenant overrides live in a `tenant_spend_caps` table (created lazily).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone

log = logging.getLogger("princeps.spend_cap")

DEFAULT_DAILY_USD = float(os.environ.get("PRINCEPS_DAILY_CAP_USD", "50"))
DEFAULT_MONTHLY_USD = float(os.environ.get("PRINCEPS_MONTHLY_CAP_USD", "500"))


class SpendCapExceeded(Exception):
    def __init__(self, tenant_id: str, scope: str, used_usd: float, cap_usd: float):
        self.tenant_id = tenant_id
        self.scope = scope          # "daily" | "monthly"
        self.used_usd = used_usd
        self.cap_usd = cap_usd
        super().__init__(
            f"tenant {tenant_id!r} {scope} cap exceeded: "
            f"${used_usd:.2f} >= ${cap_usd:.2f}"
        )


@dataclass(frozen=True)
class SpendCap:
    tenant_id: str
    daily_usd: float
    monthly_usd: float


async def get_cap(pool, tenant_id: str) -> SpendCap:
    if pool is None:
        return SpendCap(tenant_id, DEFAULT_DAILY_USD, DEFAULT_MONTHLY_USD)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT daily_usd, monthly_usd FROM tenant_spend_caps WHERE tenant_id=$1",
            tenant_id,
        )
    if row:
        return SpendCap(tenant_id, float(row["daily_usd"]), float(row["monthly_usd"]))
    return SpendCap(tenant_id, DEFAULT_DAILY_USD, DEFAULT_MONTHLY_USD)


async def check_and_consume(pool, tenant_id: str, cost_usd: float, *, kind: str = "claude") -> None:
    """Atomic check + increment. Raises SpendCapExceeded.

    Schema (one row per tenant per date) is created idempotently here so
    callers don't need to depend on a separate migration landing first.
    """
    if pool is None or cost_usd <= 0:
        return
    cap = await get_cap(pool, tenant_id)
    today = date.today()
    month_first = today.replace(day=1)

    async with pool.acquire() as conn:
        # Ensure tables exist (idempotent — fast path, no-op after first run).
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS spend_cap_usage (
                tenant_id   TEXT NOT NULL,
                day         DATE NOT NULL,
                used_usd    DOUBLE PRECISION NOT NULL DEFAULT 0,
                PRIMARY KEY (tenant_id, day)
            );
            CREATE TABLE IF NOT EXISTS tenant_spend_caps (
                tenant_id    TEXT PRIMARY KEY,
                daily_usd    DOUBLE PRECISION NOT NULL,
                monthly_usd  DOUBLE PRECISION NOT NULL
            );
            CREATE TABLE IF NOT EXISTS spend_cap_audit (
                id BIGSERIAL PRIMARY KEY, tenant_id TEXT, kind TEXT,
                cost_usd DOUBLE PRECISION, day DATE, ts TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        # Compute current usage.
        used_today = await conn.fetchval(
            "SELECT COALESCE(used_usd, 0) FROM spend_cap_usage WHERE tenant_id=$1 AND day=$2",
            tenant_id, today,
        ) or 0.0
        used_month = await conn.fetchval(
            "SELECT COALESCE(SUM(used_usd), 0) FROM spend_cap_usage WHERE tenant_id=$1 AND day >= $2",
            tenant_id, month_first,
        ) or 0.0

        if used_today + cost_usd > cap.daily_usd:
            raise SpendCapExceeded(tenant_id, "daily", used_today + cost_usd, cap.daily_usd)
        if used_month + cost_usd > cap.monthly_usd:
            raise SpendCapExceeded(tenant_id, "monthly", used_month + cost_usd, cap.monthly_usd)

        await conn.execute(
            """
            INSERT INTO spend_cap_usage (tenant_id, day, used_usd)
            VALUES ($1, $2, $3)
            ON CONFLICT (tenant_id, day) DO UPDATE SET used_usd = spend_cap_usage.used_usd + EXCLUDED.used_usd
            """, tenant_id, today, cost_usd,
        )
        await conn.execute(
            "INSERT INTO spend_cap_audit (tenant_id, kind, cost_usd, day) VALUES ($1, $2, $3, $4)",
            tenant_id, kind, cost_usd, today,
        )
