# Princeps Agent Architecture

This document describes two distinct agent systems for Princeps:

1. **Dev team subagents** — Claude Code subagents that help build Princeps (in `.claude/agents/`)
2. **Runtime agent bots** — production workers that do autonomous work for Princeps users

They share design principles (specialisation, bounded scope, observable behaviour) but live in different places.

---

## Part 1 — Dev team subagents (in-IDE)

Nine Claude Code subagents live in `.claude/agents/*.md`. Invoke via the Claude Code `Agent` tool or by name when the subject matter matches.

| Agent | Role | Invokes |
|---|---|---|
| `chief-of-staff` | Orchestration, status updates, delegation | The others |
| `strategist` | GTM, pricing, competitive positioning, pitch | Researcher for market data |
| `researcher` | Regulation, markets, science, due diligence | — |
| `backend-engineer` | FastAPI, Python, subprocess bridges, DB | Data engineer for schema, QA for tests |
| `frontend-engineer` | React, Vite, Mapbox, deck.gl, gold theme | QA for visual verification |
| `data-engineer` | PostGIS, ingestion pipelines, raster/DEM | Backend for query wiring |
| `ml-engineer` | Forecasting, GeoAI, XGBoost, evaluation | Data engineer for training data |
| `devops-engineer` | Railway, Docker, secrets, health checks | QA for smoke tests |
| `qa-engineer` | Pytest, vitest, Playwright, regression | Everyone |

**Convention:** `chief-of-staff` is the default entry point for ambiguous requests; it delegates.

---

## Part 2 — Runtime agent bots (on Railway)

Six autonomous agent bots run as Railway services. Each consumes an ARQ queue, runs Claude-backed reasoning where needed, and writes results to Postgres.

### Services overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Railway Project: princeps                │
├─────────────────────────────────────────────────────────────┤
│  Web tier                                                   │
│    princeps-web          (FastAPI, enqueues jobs)           │
│    princeps-frontend     (nginx + built Vite)               │
│                                                             │
│  Worker tier (ARQ consumers)                                │
│    princeps-worker-prospector                               │
│    princeps-worker-grid-monitor                             │
│    princeps-worker-procurement                              │
│    princeps-worker-ingestion                                │
│    princeps-worker-report                                   │
│    princeps-worker-analyst                                  │
│    princeps-worker-rnd                                      │
│                                                             │
│  Scheduler                                                  │
│    princeps-scheduler    (APScheduler → enqueues crons)     │
│                                                             │
│  Data plane                                                 │
│    princeps-postgres     (Railway plugin)                   │
│    princeps-redis        (Railway plugin — ARQ broker)      │
│    Neo4j Aura            (external, free tier initially)    │
└─────────────────────────────────────────────────────────────┘
```

### The seven bots

#### 1. ProspectorAgent
- **Purpose:** Continuously scans UK regions for viable sites matching user criteria (solar, BESS, DC). Writes candidates to `prospect_candidates` table. Sends weekly digest to user (Slack/email).
- **Trigger:** Scheduled (daily sweep) + on-demand via API
- **Builds on:** `utils/autonomous_prospector.py`, `utils/site_prospector.py`, `utils/auto_prospector.py`
- **Claude use:** Judgement calls on edge cases (e.g., "is this ex-industrial site actually available?"), natural-language explanation of why each candidate passed/failed
- **Outputs:** Postgres rows + Slack digest with map links

#### 2. GridMonitorAgent
- **Purpose:** Watches NESO/DNO data feeds for constraint changes (new ECR entries, voltage issues, contingency flags). Re-runs grid connection analysis for affected user sites, flags changes.
- **Trigger:** Scheduled (hourly for priority sites, daily for others) + webhook if NESO pushes one
- **Builds on:** `utils/alert_engine.py`, `utils/grid_connection_analyser.py`, `utils/constraint_forecaster.py`
- **Claude use:** Summarising what changed in plain language, severity assessment
- **Outputs:** Alert rows + email notifications

#### 3. ProcurementAgent
- **Purpose:** Daily sweep of Find-a-Tender, Contracts Finder, and OJEU equivalents. Classifies tenders, scores bid viability, matches to user sites.
- **Trigger:** Daily cron
- **Builds on:** `utils/procurement_intelligence.py`
- **Claude use:** Tender classification, extracting key requirements from RFP text, match explanation
- **Outputs:** `procurement_tenders` table + weekly digest

#### 4. IngestionAgent
- **Purpose:** Scheduled data refreshes with anomaly detection — BMRS demand, NESO FES updates, DNO OpenDataSoft/CKAN, GeeFlow Earth Engine pulls, OSM Overpass.
- **Trigger:** Various schedules (BMRS hourly, FES monthly, GeeFlow weekly, OSM monthly)
- **Builds on:** `utils/demand_data_ingester.py`, `utils/grid_data_ingester.py`, `utils/geeflow_runner.py`, `utils/bmrs_datasets.py`
- **Claude use:** Minimal — this is mostly data plumbing. Claude is used only for anomaly triage (e.g., "demand dropped 40% — real or sensor failure?")
- **Outputs:** Row counts to `ingestion_log`, alerts on anomalies

#### 5. ReportAgent
- **Purpose:** Weekly per-user portfolio PDF — status of each site, grid changes, market moves, action items. Emailed via Resend/Postmark.
- **Trigger:** Weekly cron (Monday 07:00 UK time)
- **Builds on:** `utils/report_financial.py`, existing PDF generators (Jinja2 + Playwright)
- **Claude use:** Writing the executive summary section in plain English, ranking portfolio risks
- **Outputs:** PDF in S3/Railway volume + email sent

#### 6. AnalystAgent
- **Purpose:** On-demand deep research triggered from chat. When a user asks a question the interactive chat can't answer in 30s (e.g., "compare 15 sites on connection cost under 3 scenarios"), chat enqueues a job for AnalystAgent to work on for minutes/hours.
- **Trigger:** API (enqueued by `princeps-web`)
- **Builds on:** Existing `app/chat.py` + tool infrastructure, but with higher iteration budget
- **Claude use:** Extensive — this is a long-horizon agent with full tool access, spawns parallel Claude sub-agents via Claude Agent SDK
- **Outputs:** Analysis written back to the chat session + optionally a PDF

#### 7. CompetitorRnDAgent
- **Purpose:** Continuously scouts the energy/grid software market (Envision Greenwich, Arup, WSP, TNEI, Roadnight Taylor, Dune Energy, LandTech, new entrants) and **drafts upgrade proposals / PRs for Princeps** based on what it learns. This is the R&D engine — it keeps Princeps ahead by making competitive intel actionable in code.
- **Trigger:** Daily scout sweep; weekly upgrade-proposal generation; ad-hoc via API ("monitor this company")
- **Two modes:**
  1. **Scout mode** — crawls competitor product pages, marketing sites, careers pages (job listings reveal roadmap), GitHub orgs, case studies, press releases, conference talks (YouTube transcripts), LinkedIn announcements. Extracts: new features shipped, customers won, pricing changes, personnel moves, technology stack hints.
  2. **R&D mode** — consumes scout output + Princeps' own feature backlog + user feedback, proposes feature upgrades. Uses Claude Code SDK to draft: design docs, stub code, tests, migration plans. Opens a **draft PR** on a feature branch. Never merges autonomously.
- **Claude use:**
  - Scout: Claude parses semi-structured web content, extracts entity/feature/event triples, deduplicates
  - R&D: Claude Code SDK + parallel sub-agents for multi-file code generation; Claude Sonnet for scanning, Claude Opus for design + code
- **Guardrails:**
  - Opens draft PRs only — human (chief-of-staff or Anya) reviews and merges
  - Touches only `feature/rnd-*` branches, never `main`
  - Spend cap: £50/month in Claude API, alerts at 80%
  - Every proposal ships with: motivation doc, risk list, test plan, estimated engineering effort
  - Scout respects `robots.txt` and uses polite rate limits (1 req/5s per domain)
- **Outputs:** `competitor_signals` table (raw intel), `upgrade_proposals` table (synthesised), GitHub draft PRs, weekly intel digest emailed to Anya

---

## Claude-within-bots: the 100x multiplier

Every runtime bot is a Claude agent. To get exponential leverage from Claude across the system, we use four patterns:

### 1. Parallel Claude calls
For any bot evaluating N items (ProspectorAgent scoring 50 sites, ProcurementAgent classifying 30 tenders, CompetitorRnDAgent parsing 20 competitor pages), dispatch N Claude calls concurrently via `asyncio.gather` with a `Semaphore(10)` cap. Typical speedup: 10–40×.

### 2. Claude Agent SDK sub-agents
Long-horizon bots (AnalystAgent, CompetitorRnDAgent in R&D mode) spawn sub-agents via the Claude Agent SDK. Pattern:
- Parent agent plans the work, splits into independent subtasks
- Each subtask runs as a sub-agent with its own tool access, context, and budget
- Parent synthesises sub-agent outputs into a single result
- Depth limit: 2 (parent → sub-agents, no deeper) to avoid runaway cost

### 3. Prompt caching (ephemeral, 5-min and 1-hour)
All bots share substantial "standing context" — Princeps data model, code snippets, competitive landscape, regulatory corpus. We cache these as `cache_control: {"type": "ephemeral", "ttl": "1h"}` blocks. Expected cost reduction: 70–90% on bots that run frequently with stable context.

### 4. Claude Code SDK for code generation
CompetitorRnDAgent's R&D mode uses the Claude Code SDK to autonomously produce multi-file code changes. It runs in a sandboxed git worktree, can invoke real tools (pytest, typecheck), and opens a draft PR with the diff. This closes the loop from "competitor shipped X" to "Princeps has a draft implementation of Y" in hours, not weeks.

### Model selection strategy
| Task | Model |
|---|---|
| Entity extraction, classification, anomaly triage | `claude-haiku-4-5` (cheap + fast) |
| Routine reasoning, summaries, tender matching | `claude-sonnet-4-6` (balanced) |
| Design docs, code generation, long-horizon research | `claude-opus-4-6` (best quality) |

Bots default to Sonnet; upgrade to Opus only for design/code output, downgrade to Haiku for high-volume classification.

---

## Shared infrastructure

### Queue library: ARQ
- Async-native (fits Princeps' asyncio codebase)
- Redis-backed (Railway has a managed Redis plugin)
- Lighter than Celery, no broker config acrobatics
- Workers: `arq app.agents.worker.WorkerSettings`

### Scheduling: APScheduler
- Runs in `princeps-scheduler` service
- Fires `arq.enqueue_job(...)` on schedule
- Schedules live in `app/agents/scheduler.py` as a declarative dict

### Base class
All bots inherit from `app.agents.base.BaseAgent`:

```python
class BaseAgent:
    name: str
    async def run(self, ctx: ArqContext, payload: dict) -> dict: ...
    async def on_success(self, result: dict) -> None: ...
    async def on_failure(self, exc: Exception) -> None: ...
```

Shared utilities:
- `self.db` — asyncpg pool
- `self.claude` — Anthropic SDK client with prompt caching enabled
- `self.log` — structured logger
- `self.notify(channel, message)` — Slack/email abstraction

### Secrets (Railway Variables)
All workers share: `DATABASE_URL`, `REDIS_URL`, `CLAUDE_API_KEY`, `JWT_SECRET`, `NEO4J_URI/USER/PASSWORD`, `RESEND_API_KEY`, `MAPBOX_TOKEN`, subprocess venv paths.

### Observability
- `LOG_FORMAT=json` — all agents emit structured logs
- `/metrics` endpoint on web tier exposes queue depth, job success rate
- Failed jobs write to `agent_failures` table for inspection

---

## Build sequence

### Phase A — Dev team subagents ✅
Written. Available in `.claude/agents/`.

### Phase B — Reference runtime bot
1. `app/agents/__init__.py`, `app/agents/base.py`
2. `app/agents/worker.py` (ARQ WorkerSettings)
3. `app/agents/prospector.py` (reference implementation)
4. Railway service config for `princeps-worker-prospector`
5. End-to-end test: enqueue a job from `princeps-web`, verify worker picks it up, result in DB

### Phase C — Remaining 5 bots
Clone the prospector template for each. Each takes ~30 min once the pattern is set.

### Phase D — Scheduler
`app/agents/scheduler.py` with APScheduler + Railway service.

### Phase E — Full deploy
All services running on Railway Pro plan. Estimated baseline cost ~$30–50/month.

---

## Cost estimate (Railway Pro, steady state)

| Service | RAM | Expected usage | Est. monthly |
|---|---|---|---|
| princeps-web | 1GB | 24/7, light | $5 |
| princeps-frontend | 256MB | 24/7, static | $2 |
| 7× workers | 512MB each | 24/7, bursty | $18 |
| princeps-scheduler | 256MB | 24/7 | $2 |
| Postgres plugin | 1GB | steady | $10 |
| Redis plugin | 256MB | steady | $5 |
| **Total** | | | **~$42/month** |

Plus Claude API usage (billed separately). With prompt caching enabled and per-bot spend caps:
- Steady state: **~$50–150/month** (scout + routine classification dominated by Haiku/Sonnet)
- Heavy AnalystAgent + CompetitorRnDAgent R&D weeks: **up to ~$300/month**
- Budget alert wired at 80% of each bot's monthly cap.

---

## Open questions

- Neo4j: stay on Aura free tier or move to Railway template? Depends on `cluster_graph` data volume.
- Notifications: Slack (webhook), email (Resend), or both? Currently leaning both.
- Multi-tenancy: how are users isolated in ProspectorAgent's scans? Per-user queue partitions or shared queue with user_id on jobs? Shared queue is simpler.
- Cost caps: per-agent Claude API spend limit — enforce at the base class level (refuse to run if this month's budget exceeded).
