# External integration triage — 2026-04-28

Council agent: general-purpose (a28a62d1029d9d883). No secret values printed.

## Integrations inventory

| Service | Used by (file:line) | Env var(s) | Cred | Public reachability |
|---|---|---|---|---|
| Anthropic Claude | `app/main.py:69`, `app/agent.py:549`, `app/chat.py:3441`, `app/ingestion/claude.py:40` | `CLAUDE_API_KEY`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | present (both, `sk-ant-` prefix verified) | n/a |
| OpenAI embeddings (opt) | `app/ingestion/embeddings.py:41` | `OPENAI_API_KEY` | missing | n/a |
| Mapbox (frontend) | `feasi-frontend/src/components/{NOMMap,MapView,CesiumGlobe,OnboardingFlow,InsiderDCDesign}.jsx` | `VITE_MAPBOX_TOKEN`, `MAPBOX_TOKEN` | present (both) | n/a |
| Google Earth Engine | `utils/geeflow_runner.py:29`, `app/helpers.py:77,380-458` | `GEE_PROJECT`, `GEEFLOW_PYTHON` | present | n/a |
| BMRS / Elexon | `utils/demand_data_ingester.py:24,38` | none | n/a | 200 |
| NESO CKAN | `utils/grid_data_ingester.py:144,813` | none | n/a | 200 |
| OpenDataSoft UKPN | `utils/grid_data_ingester.py:48`, `utils/dno_opendata_ingester.py:45` | `UKPN_ODS_APIKEY` | present | 200 |
| OpenDataSoft SPEN | `utils/grid_data_ingester.py:90` | `SPEN_ODS_APIKEY` | missing | 200 |
| OpenDataSoft ENWL | `utils/grid_data_ingester.py:104` | `ENWL_ODS_APIKEY` | missing | 200 |
| OpenDataSoft NPG | `utils/grid_data_ingester.py:78` | `NPG_ODS_APIKEY` | missing | 200 |
| SSEN data API | `utils/grid_data_ingester.py:119` | `SSEN_ODS_APIKEY` | missing | **403 at root** |
| NGED CKAN | `utils/grid_data_ingester.py:129` | `NGED_ODS_APIKEY` | missing | 200 |
| Overpass / OSM | `utils/grid_data_ingester.py:720` | none | n/a | 200 |
| Companies House | `utils/landowner_lookup.py:170,199`, `app/ingestion/companies_house.py:72` | `COMPANIES_HOUSE_API_KEY` | missing | n/a |
| Gemini | `utils/gemini_asset_modeller.py:18` | `GEMINI_API_KEY` | missing | n/a |
| Resend | `app/agents/base.py:578`, `utils/market_intelligence.py:33` | `RESEND_API_KEY` | missing | n/a |
| SendGrid | `utils/market_intelligence.py:32` | `SENDGRID_API_KEY` | missing | n/a |
| Slack webhook | `app/agents/base.py:567` | `SLACK_WEBHOOK_URL` | missing | n/a |
| GitHub builder | `app/agents/builder.py:191` | `GITHUB_TOKEN` | missing | n/a |
| CDS Copernicus | `app/routers/twin_dynamic.py:192` | `CDS_API_KEY` | missing | n/a |
| Electricity Maps | env-only | `ELECTRICITYMAPS_API_KEY` | present | n/a |
| Neo4j | `utils/neo4j_graph_populator.py:37`, `app/graph.py` | `NEO4J_URI/USER/PASSWORD` | missing (defaults) | local :7687 down |
| JWT auth | `app/auth.py` | `JWT_SECRET` | missing — masked by `PRINCEPS_DEMO_MODE=true` | n/a |

`.env` contains 10 keys: `DATABASE_URL`, `CLAUDE_API_KEY`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `SAM_PYTHON`, `GEEFLOW_PYTHON`, `GEE_PROJECT`, `MAPBOX_TOKEN`, `UKPN_ODS_APIKEY`, `ELECTRICITYMAPS_API_KEY`.

## Missing creds
`OPENAI_API_KEY`, `SPEN_ODS_APIKEY`, `ENWL_ODS_APIKEY`, `NPG_ODS_APIKEY`, `SSEN_ODS_APIKEY`, `NGED_ODS_APIKEY`, `COMPANIES_HOUSE_API_KEY`, `GEMINI_API_KEY`, `RESEND_API_KEY`, `SENDGRID_API_KEY`, `SLACK_WEBHOOK_URL`, `GITHUB_TOKEN`, `CDS_API_KEY`, `JWT_SECRET`, `NEO4J_*`.

## Unreachable services
- `https://data-api.ssen.co.uk/` → **403** at root. Likely path-dependent rather than down — re-ping with the actual dataset URL the adapter constructs.
- All other 6 public endpoints (BMRS, NESO CKAN, 4 OpenDataSoft DNOs, NGED CKAN, Overpass) → 200.

## Top 5 integration risks (priority)
1. **`.env.example` GEE name drift** — example documents `GEE_PROJECT_ID` but code reads `GEE_PROJECT` (`app/helpers.py:77`). Local works because the real `.env` already uses `GEE_PROJECT`; any new contributor copying the example will silently break GeeFlow.
2. **DNO ingest broken** — five of six DNO keys absent + SSEN 403. Aligns with known-broken ingest at `docs/audits/regulatory_call_sites_2026.md` (memory task #21).
3. **`JWT_SECRET` missing** — auth survives only because `PRINCEPS_DEMO_MODE=true`. Production deploy with demo off = 100% auth failure.
4. **`OPENAI_API_KEY` missing** — Alerts semantic search silently downgrades to tsvector; no error surface, just worse results.
5. **Phase-2 agents read-only** — missing `GITHUB_TOKEN`, `SLACK_WEBHOOK_URL`, `RESEND_API_KEY`, `COMPANIES_HOUSE_API_KEY` means builder/notifier/market-intel agents run but can't publish, alert, or look up landowners.

## Confirmed quirks
- BMRS pagination at `utils/demand_data_ingester.py:36` chunks at `timedelta(days=7)`, no auth, base `https://data.elexon.co.uk/bmrs/api/v1` — matches memory.
- Mapbox split correct: backend `MAPBOX_TOKEN`, frontend `VITE_MAPBOX_TOKEN` (`feasi-frontend/.env`).
- Anthropic key shape verified via prefix grep only (value never echoed).
