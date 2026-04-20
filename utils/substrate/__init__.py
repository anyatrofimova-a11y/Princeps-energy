"""utils.substrate — precision map substrate ingestion.

Three data sources power the Princeps basemap:
  * OS MasterMap Topography Layer (or OS Open Zoomstack fallback) — buildings,
    roads, water, woodland. Requires ``OS_DATA_HUB_KEY`` for the premium
    product; otherwise degrades to OS OpenMap which is free and key-less.
  * Environment Agency National LiDAR Programme — 1 m DTM + DSM rasters.
    Free, no key; ingest fetches individual OSGB 1 km tiles on demand.
  * OpenStreetMap (Overpass API) — power pylons, poles, overhead lines.
    Free, no key.

All ingesters share three conventions:
  1. ``ensure_schema(pool)`` — idempotent DDL (relies on 0009_substrate_schema.sql).
  2. ``fetch_*(bbox)`` — bbox-driven on-demand ingestion. ``bbox`` is
     (min_lon, min_lat, max_lon, max_lat) in WGS84.
  3. Raster / tile artefacts cached under ``data/substrate/{sub}/`` keyed by
     the OSGB tile id for deterministic re-use.
"""

from __future__ import annotations

__all__ = [
    "os_mastermap_ingester",
    "ea_lidar_ingester",
    "osm_pylon_ingester",
    "tiler",
]
