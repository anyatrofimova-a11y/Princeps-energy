"""Seed package — one-shot `data_subscriptions` + reference-data upserts.

Each submodule exposes a single `async def seed(pool)` entry point and is
safe to run repeatedly. `app/db_setup.py` wires these in at startup.
"""
