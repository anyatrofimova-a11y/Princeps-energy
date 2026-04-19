# Agents — Phase 2 deployment notes

This is the delta to roll Phase 2 to Railway. Phase 2 adds two domain
agents (`planning_monitor`, `market_intel`), a coordination/self-improvement
layer on `BaseAgent`, and a `builder` agent that opens PRs via the Claude
Agent SDK.

## What landed in this PR

| Change | File |
|---|---|
| Superpowers-style `plan()` / `critique()` / `verify()` / `plan_and_execute()` on every agent | `app/agents/base.py` |
| Nelson-style mission coordinator (conflict detection, action stations, sailing orders) | `app/agents/coordination.py` |
| Planning monitor agent (UK planning portals → watches → alerts) | `app/agents/planning_monitor.py` |
| Market-intel agent (Ofgem / NESO / DESNZ → weekly digest with self-critique) | `app/agents/market_intel.py` |
| Builder agent (GitHub issue → claude-agent-sdk → draft PR) | `app/agents/builder.py` |
| Schema: `missions`, `planning_watches`, `planning_alerts`, `market_signals`, `market_digests` | `sql/migrate_agents_phase2.sql` |
| Registry + scheduler | `app/agents/worker.py`, `app/agents/scheduler.py` |
| Worker image: `git` + `gh` for the builder | `Dockerfile.worker` |
| Pin: `claude-agent-sdk` | `requirements.txt` |

## Database migration

```bash
psql "$DATABASE_URL" -f sql/migrate_agents_phase2.sql
```

Run it once against the Railway `postgis` service. Idempotent.

## Railway services to create

Three new services, all running the **same `Dockerfile.worker` image** as the
existing workers, distinguished by env:

### 1. `princeps-worker-planning`

| Setting | Value |
|---|---|
| Image | (same repo, `Dockerfile.worker`) |
| Start cmd | `arq app.agents.worker.WorkerSettings` |
| Env `AGENT_NAME` | `planning_monitor` |
| Env `WORKER_CONCURRENCY` | `2` |
| Env `DATABASE_URL` | (reference `postgis`) |
| Env `REDIS_URL` | (reference `Redis`) |
| Env `CLAUDE_API_KEY` | (shared secret) |
| Env `SLACK_WEBHOOK_URL` | (shared secret) |

### 2. `princeps-worker-market`

Same as above, with `AGENT_NAME=market_intel`.

### 3. `princeps-worker-builder`

Same as above, with:

| Setting | Value |
|---|---|
| Env `AGENT_NAME` | `builder` |
| Env `WORKER_CONCURRENCY` | `1`  *(serialise — one PR at a time per worker)* |
| Env `WORKER_JOB_TIMEOUT_S` | `2400`  *(40 min)* |
| Env `GITHUB_TOKEN` | **new secret** — PAT with `repo` + `workflow` scope on `anyatrofimova-a11y/feasibly`, or a dedicated GitHub App token |
| Env `BUILDER_REPO` | `anyatrofimova-a11y/feasibly` |

Do **not** give the builder worker a `CLAUDE_API_KEY` that outranks your
budget caps — it's the most expensive agent in the fleet. If you want a
hard external gate, point it at a separate Anthropic project with its own
monthly cap.

### Scheduler update

The scheduler service (`princeps-scheduler`) needs a redeploy — the new
cron entries for `planning_monitor` and `market_intel` are in the image.
No env changes required on the scheduler.

## Triggering the builder on demand

Two safe mechanisms:

1. **Manual, from a backend shell.** Publish an ARQ job:
   ```py
   await redis.enqueue_job(
       "dispatch",
       {"issue_number": 123, "_orders": {"action_station": "trafalgar"}},
       _queue_name="arq:builder",
   )
   ```

2. **GitHub label webhook.** Add a FastAPI route (not in this PR) that
   listens for `issues.labeled` with label `agent:build` and enqueues the
   same job. This is the intended production path.

The builder **always** opens a DRAFT PR. Nothing merges automatically.
Merges are human-approved; Railway redeploys on merge to main, closing the
loop.

## Guardrails recap (builder)

The builder agent has four layers of defence, in order:

1. `BaseAgent` per-run / per-day / per-month cost caps (`£5 / £20 / £120` default)
2. Claude Agent SDK `max_turns` + in-flight cost trip inside the session
3. 30-minute wall-clock timeout on the whole orchestration
4. **Post-session path allowlist check** — if Claude edited any file
   outside `app/ utils/ tests/ sql/ docs/ feasi-frontend/src/` OR touched
   any deny-listed path (migrations, Dockerfiles, CI workflows, `.env`),
   the branch is discarded and no PR is opened.

If any of those trip, the mission is closed with `ok=false` and
`error=path_allowlist_violation | budget_exceeded | wall_clock_timeout`
and Slack gets a warning.

## Coordination — what changes for existing agents

Nothing. `Coordinator` is opt-in. The three new agents use it; existing
agents (`prospector`, `grid_monitor`, etc.) continue to run unchanged.
When you're ready to wire the existing agents into coordination, the
pattern is:

```py
async def run(self, ctx, payload):
    orders = SailingOrders.from_payload(self.name, payload)
    orders.touches_tables = ["prospect_candidates"]
    async with Coordinator(ctx.db, orders) as mission:
        result = await self._do_run(ctx, payload)
        mission.record_outcome({"stars": result.data.get("go_count", 0)})
        return result
```
