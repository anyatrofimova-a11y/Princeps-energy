# Chat Godmode Spec — Inline Rendering + Page Context + Tool Coverage

**Status:** SPEC  |  **Owner:** COUNCIL-CH  |  **Date:** 2026-04-19
**Scope:** Fix two complaints: (1) chat responses render as a floating overlay over the page instead of inline bubbles; (2) agent lacks tools to query Princeps data (projects, dockets, alerts, Ofgem decisions, grid data).

---

## 1. Current chat architecture audit

### 1.1 Frontend — two ChatRails exist, only one is live in the shell

| File | Role | Notes |
|------|------|-------|
| `feasi-frontend/src/components/shell/ChatRail.jsx` (721 lines) | **Live shell chat** — the bubble + expanded card in screenshots | Custom SSE reader against `/chat/{session_id}/message` |
| `feasi-frontend/src/canvas/ChatRail.jsx`       (204 lines) | Unused canvas chat against `/api/canvas/chat` (endpoint may 404) | Vercel AI SDK v6, not mounted in main shell |

All findings below refer to the shell ChatRail unless noted.

### 1.2 How the shell ChatRail renders the stream

- Expanded chat is **not a 360px side rail** — it is a `position: fixed; right: 20px; bottom: 52px; width: 380px; height: 560px` **floating card** (`/Users/anyatrofimova/feasibly/feasi-frontend/src/components/shell/ChatRail.jsx:447-461`).
- Messages are appended to in-component React state (`messages`) and rendered inside `<div className="cr-list">` (line 381) — *logically* inline inside the card.
- **But the CSS class `.cr-bubble` is reused for two unrelated components** (root cause of the overlay bug — see §4).

### 1.3 What frontend sends with each user message

From `send()` in shell `ChatRail.jsx:220-225`:
```js
fetch(`/chat/${sid}/message`, {
  method: "POST",
  body: JSON.stringify({ message: text }),   // <- only the message string
});
```
The backend `ChatMessageRequest` accepts `context: dict | None` (`app/routers/chat.py:28`) but the frontend **never sends it**.

Frontend *has* `workspaceCtx.activeWorkspace`, `activeViewMode`, `chatContext.lifecycleTab`, `chatContext.projectContext`, `chatContext.pathname`, plus `projectId` / `parcelId` props — all wasted on the wire.

Additionally, `ChatSessionRequest` (`app/routers/chat.py:22-23`) **omits `project_id`** — frontend sends `project_id` at session create (line 180) but the Pydantic model silently discards it. Session has no idea which project it belongs to.

### 1.4 Backend tools

`app/chat.py` already registers **64 Anthropic tool schemas** (`TOOLS` list, `chat.py:99-1121`). Contrary to the user's impression ("I don't have a tool to search..."), the agent has many tools — but the set is skewed: lots of site / SAM / GeoAI tools, but **no project list / portfolio / docket / alert / regulatory / REPD / Ofgem tools, and no `current_page_context` tool** (see inventory §2). So when the user asks "what projects do I have?" or "has Ofgem published anything on …", Claude correctly reports "no such tool."

Tool dispatch works (`chat.py:1129-1399` — `execute_tool()` with long `elif` ladder). Tool results are threaded back via `_compact_tool_result()` (`chat.py:2265-2291`) before being appended to `session.messages` — that part is healthy.

History management `_prune_history()` (`chat.py:2294-2305`) caps at 300 K chars — fine.

System prompt builder (`chat.py:2308-2380`) already accepts a `ui_context` dict **but nothing in the request path fills it** — because the frontend sends no context (§1.3).

### 1.5 Why responses "render as an overlay"

**The CSS class `cr-bubble` is defined twice with conflicting semantics — and the later message-bubble rule does not reset the pill's `position: fixed`** (see §4 for the fix).

---

## 2. Data-source inventory (what tools *should* wrap)

Legend: `P0` = blocker, `P1` = adds value, `P2` = polish.
Every endpoint below returns JSON already parsed by existing handlers — wrappers are thin.

### 2.1 Projects / portfolios (P0)
| Endpoint | Returns | Proposed tool |
|----------|---------|---------------|
| `GET /api/v1/projects` (`routers/projects.py:174`) | list[{id, name, status, capacity, lat, lon, …}] | `list_projects(status?, limit?)` |
| `GET /api/v1/projects/summary` (`projects.py:222`) | counts + capacity rollups | `get_portfolio_summary()` |
| `GET /api/v1/projects/{id}` (`projects.py:265`) | full project row + joins | `get_project(project_id)` |
| `GET /api/v1/projects/{id}/timeline` (`projects.py:398`) | milestones | `get_project_timeline(project_id)` |
| `GET /api/v1/projects/{id}/candidate-sites` (`projects.py:842`) | candidate list | `get_candidate_sites(project_id)` |
| `GET /portfolios/tree/full` (`portfolios_crud.py:168`) | portfolio→project tree | `list_portfolios()` |
| `GET /api/project-memo/{id}/kpis` (`project_memo.py:73`) | KPI snapshot | `get_project_kpis(project_id)` |

### 2.2 Grid (P0/P1)
| Endpoint | Tool |
|----------|------|
| `GET /grid/substations`, `/grid/substations/nearest` (`grid.py:64,80`) | already covered by `search_substations` |
| `GET /api/grid/substation/{id}/detail`, `/neighbourhood` (`grid.py:291,317`) | **new** `get_substation_detail(id)` (P0) |
| `GET /api/grid/ecr` (`grid.py:408`), `/queue` (`grid.py:448`) | `get_grid_ecr(…)`, `get_grid_queue(…)` (P1) |
| `GET /api/grid/capacity-map` (`grid.py:371`) | `get_capacity_map_geojson(bbox)` (P1) |
| `POST /api/grid/assess`, `/power-flow`, `/connection-forecast` (`grid.py:129,154,185`) | `assess_grid_connection`, existing `run_power_flow`, `forecast_grid_connection` |
| `GET /live/latest` (`nged.py:46`) + `/carbon-intensity` (`neso.py:22`) | already-ish via `get_grid_live` |
| `GET /api/grid/tec-timelines`, `POST /predict-timeline` (`grid.py:231,247`) | `predict_connection_timeline` already exists |

### 2.3 Site / parcel (P1)
| Endpoint | Tool |
|----------|------|
| `GET /api/parcel/{id}/detail` (`parcel.py:224`) | `get_parcel_detail(id)` |
| `POST /api/design/buildable-area` (`analysis.py:139`) | `get_buildable_area(polygon)` |
| `GET /site/{id}/explain` (`site.py:656`) | `explain_site(parcel_id)` |
| `GET /site/{id}/solar_yield` (`site.py:988`) | existing `run_solar_yield` |

### 2.4 Intelligence — dockets / alerts / regulatory (P0)
| Endpoint | Tool |
|----------|------|
| `GET /alerts/library`, `/digest` (`alerts.py:249,381`) | `list_alerts(topic?, limit?)` (P0) |
| `POST /alerts/search` (`alerts.py:794`) | `search_alerts(query)` (P0) |
| `GET /dockets/library` (`dockets.py:158`) | `list_dockets(status?)` (P0) |
| `GET /dockets/{id}`, `/stakeholders`, `/timeline` (`dockets.py:242,306,407`) | `get_docket(id)` (P1) |
| `GET /tenders/energy` + REPD + TEC (`regulatory.py:48,93,191`) | `search_repd(query|bbox)`, `search_tec_queue(…)` (P1) |
| `GET /api/planning/compliance`, `/authority-profile`, `/comparable-decisions` (`planning_ml.py:57,77,91`) | `check_regulatory_compliance`, `get_authority_profile`, `get_comparable_decisions` (P1) |
| Regulatory versions (via `app/regulatory/…`) | `get_regulatory_version(reg_id)` — already see `project_council_bots_session_2026_04_19.md` for call sites |

### 2.5 Analysis (P1)
| Endpoint | Tool |
|----------|------|
| `POST /api/planning/predict` (`planning_ml.py:24`) | `predict_planning_approval` already exists |
| `POST /api/analysis/pypsa-opf|lopf|expansion` (`analysis.py:50-62`) | `run_pypsa_opf(scenario)` (P2) |
| `POST /api/analysis/hosting-capacity` (`analysis.py:68`) | `run_hosting_capacity(bbox)` (P2) |
| `POST /api/analysis/pvlib-simulate` (`analysis.py:76`) | `run_pvlib_simulation(…)` (P2, complements SAM) |
| `POST /api/analysis/cfe-score` (`analysis.py:175`) | `score_carbon_free_energy(…)` (P2) |
| `POST /api/grid/operating-envelope`, `/curtailment-estimate` (`analysis.py:153,160`) | `estimate_curtailment(project_id)` (P1) |
| `GET /api/forecast/site-load` (`forecast.py:50`) | `get_site_load_forecast(polygon|project_id)` (P1) |

### 2.6 Reports (P2)
| Endpoint | Tool |
|----------|------|
| `POST /api/reports/site-assessment` (`reports.py:42`) | `generate_site_memo` |
| `POST /api/reports/grid-connection` (`reports.py:104`) | `generate_grid_connection_report` |
| `POST /api/reports/g99-pack`, `/g99-pdf` (`reports.py:179,257`) | `generate_g99_pack` |
| `POST /api/reports/financial` (`reports.py:292`) | `generate_financial_viability_pdf` |
| `POST /api/reports/nppf-fva` (`reports_fva.py:157`) | `generate_nppf_fva` |
| `POST /api/v1/projects/{id}/site-memo` (`project_memo.py:228`) | `generate_ic_memo` |

### 2.7 Twin (P2)
| Endpoint | Tool |
|----------|------|
| `POST /api/twin/layout` (`twin.py:129`) | `run_twin_layout(project_id)` |
| `POST /api/twin/snapshot/{id}` (`twin.py:154`) | `snapshot_twin(project_id)` |
| `GET /api/dc/ops` (`dc_ops.py:368`) | `get_dc_ops(project_id)` |
| `GET /api/dc/noise-contours`, `/glint-screen` (`dc_ops.py:60,229`) | `calculate_noise_contours`, `calculate_glint_glare` already exist |

---

## 3. Tool schema design (priority-ordered, ≤30)

### P0 — without these chat is useless (8 tools)
1. `current_page_context()` → returns `{workspace, viewMode, lifecycleTab, route, projectId, parcelId, selectedAssetId, picked_location}` — **no args**, read from `session.ui_context` (backend reflects the frontend-supplied `page_context` block, see §5 BOT-CHC).
2. `list_projects(status?, sector?, limit?=20)` → `/api/v1/projects`.
3. `get_project(project_id)` → `/api/v1/projects/{id}`.
4. `get_portfolio_summary()` → `/api/v1/projects/summary`.
5. `list_alerts(topic?, since?, limit?=10)` → `/alerts/library` or `/alerts/digest`.
6. `search_alerts(query, limit?=10)` → `/alerts/search` — answers "Ofgem recent decisions on …".
7. `list_dockets(status?, topic?, limit?=10)` → `/dockets/library`.
8. `get_substation_detail(substation_id)` → `/api/grid/substation/{id}/detail`.

### P1 — adds real value (12 tools)
9. `get_project_timeline(project_id)`
10. `get_candidate_sites(project_id)`
11. `get_project_kpis(project_id)`
12. `get_docket(docket_id)`
13. `search_repd(query|bbox, limit?)`
14. `search_tec_queue(connection_site?, voltage?, limit?)`
15. `get_capacity_map_geojson(bbox, voltage?)`
16. `get_parcel_detail(parcel_id)`
17. `get_buildable_area(polygon_or_parcel_id, setbacks?)`
18. `check_regulatory_compliance(scheme_type, lat, lon, capacity_mw)`
19. `get_authority_profile(lpa)`
20. `get_site_load_forecast(project_id)`

### P2 — polish (10 tools)
21. `run_pypsa_opf(scenario)`
22. `run_hosting_capacity(bbox)`
23. `score_carbon_free_energy(project_id)`
24. `estimate_curtailment(project_id)`
25. `generate_ic_memo(project_id)`
26. `generate_lender_pack(project_id)`
27. `generate_grid_connection_report(project_id)`
28. `run_twin_layout(project_id)`
29. `get_dc_ops(project_id)`
30. `explain_site(parcel_id)`

All wrappers follow the existing `execute_tool` pattern: import helper, call it with `args`, return a dict. The result passes through `_compact_tool_result()` already (chat.py:2510).

---

## 4. Response rendering fix — the *actual* bug

**File:** `feasi-frontend/src/components/shell/ChatRail.jsx`
**Two competing definitions of `.cr-bubble`:**

- L485-503: the collapsed floating pill — `position: fixed; right: 20px; bottom: 52px; padding: 10px 16px; border-radius: 999px; …`
- L618-624: every assistant / user message bubble — `max-width: 92%; padding: 10px 12px; border-radius: 12px; font-size: 13px; white-space: pre-wrap; …`

CSS cascade: the second declaration overrides `padding`, `border-radius`, `font-size` on the pill (so the collapsed pill looks *wrong* too — padding 10/12 vs 10/16, radius 12 vs 999). More importantly, **`position: fixed; right: 20px; bottom: 52px` from L486-488 is never reset by the later rule**, so every `.cr-bubble-user` and `.cr-bubble-assistant` inside `.cr-list` is **yanked out of flow and painted at `right:20px; bottom:52px`**, stacked on top of each other — exactly what the "floating overlay over the page" screenshots show. The `cr-list` scroll container thinks it has no message children to show, and the bubbles render as siblings of the `<aside>` card, on the page.

### Fix (one line of CSS, rename + reset)
Rename the collapsed-pill class so the two never collide, and explicitly reset position on message bubbles:

```css
/* rename everywhere: .cr-bubble -> .cr-fab  (collapsed floating action button) */
.cr-fab { position: fixed; right: 20px; bottom: 52px; … }  /* was .cr-bubble */

/* message bubbles stay .cr-bubble but defensively static */
.cr-bubble { position: static; max-width: 92%; padding: 10px 12px; … }
```

JSX change: line 352 `className="cr-bubble"` → `className="cr-fab"` (collapsed button) only. Lines 45 and 49 (`cr-bubble cr-bubble-user`, `cr-bubble cr-bubble-assistant`) stay as-is but now get the defensive `position: static`.

This is the one-file, ~6-line fix that lands the complaint.

### Secondary (optional) — convert shell chat to an actual side rail
Long-term (not blocking): move `.cr-root` from `position: fixed; width: 380px; height: 560px` to a proper flex sibling of the main workspace column at `width: 360px; height: 100%;`, matching the "persistent chat rail" direction in `project_ui_redesign_2026_04.md`. This is orthogonal to the rendering bug — left as a Phase 2 note for BOT-CHR.

---

## 5. Execution plan — 4 disjoint bot briefs

### BOT-CHR — Render fix (blocks demo)
**Owned files (exclusive):** `feasi-frontend/src/components/shell/ChatRail.jsx`
**Task:**
1. Rename collapsed-pill class `cr-bubble` → `cr-fab` everywhere in this file (JSX line 352 + CSS L485-515).
2. Add `position: static` to the `.cr-bubble` message-bubble rule at L618.
3. Verify pill → expand → message bubbles render **inside** `.cr-list`, not as page-level overlays.
4. Optional (nice-to-have): add `.cr-root { position: fixed }` comment noting the intended future move to a side-rail layout.
**Acceptance:** screenshot with 3+ message bubbles all visually stacked inside the 380×560 card, scrollable, no element painted outside the card outline.

### BOT-CHT — Backend P0 tools (unblocks "understands the page")
**Owned files (exclusive):** `app/chat.py` (TOOLS list + `execute_tool` dispatch only)
**Task:** add 8 P0 tool schemas + handlers:
- `current_page_context`, `list_projects`, `get_project`, `get_portfolio_summary`, `list_alerts`, `search_alerts`, `list_dockets`, `get_substation_detail`.
Each handler imports from the matching router module's underlying helper (not via HTTP — call the function directly or run the DB query the router runs). All results pass through the existing `_compact_tool_result` path in `stream_chat_response` — no change to the streaming loop needed.
**Acceptance:** asking "list my projects" triggers `list_projects` and returns rows; asking "what is this page?" triggers `current_page_context` and returns workspace/route/projectId.

### BOT-CHC — Context injection (glue layer)
**Owned files (exclusive):**
- `feasi-frontend/src/components/shell/ChatRail.jsx` (only the `send()` body + `ensureSession()` body — BOT-CHR stays in the render/CSS region)
- `app/routers/chat.py` (request models + endpoint wiring)
- `app/chat.py` (`ChatSession` dataclass + `build_system_prompt` only — NOT the TOOLS list)

**Task:**
1. Frontend: on every `send()`, collect:
   ```js
   const page_context = {
     workspace: activeWorkspace,
     viewMode: activeViewMode,
     lifecycleTab: chatContext.lifecycleTab,
     pathname: chatContext.pathname,
     projectId, parcelId,
     selectedAssetId: window.__princepsSelectedAssetId || null,
     route_params: window.__princepsRouteParams || {},
   };
   // ship alongside message
   body: JSON.stringify({ message: text, context: page_context })
   ```
2. Also ship `project_id` at `POST /chat/session` and widen `ChatSessionRequest` to include it (`app/routers/chat.py:22`) so the session remembers the project it was born under.
3. Backend: when a `context` arrives, store it on `session.ui_context` (new field on `ChatSession`); `build_system_prompt` already renders it.
4. Expose a `current_page_context` tool that simply returns `session.ui_context` — **this hand-off to BOT-CHT is the only cross-bot interface.** Document the shape in a comment block at the top of `chat.py`.
**Acceptance:** backend logs show non-null `ui_context` on every message; `current_page_context` tool returns the live payload.

### BOT-CHX — Backend P1 + P2 tools (fires after BOT-CHT lands)
**Owned files (exclusive):** `app/chat.py` (TOOLS list + `execute_tool` dispatch only, same file as BOT-CHT but **different tools** — merge-coordinate by having BOT-CHT commit first).
**Task:** add the 22 P1+P2 tools (§3). Same wrapper pattern.
**Acceptance:** every tool callable, `/chat/.../message` returns a `tool_result` event for each.

### Bot ordering
1. **BOT-CHR** (fixes the visible-now bug, zero backend risk — ship first).
2. **BOT-CHC** in parallel with **BOT-CHT** (different file regions; CHC's tool stub for `current_page_context` lives in CHT's section, so CHC writes schema + CHT writes handler — coordinate via a short Slack-thread).
3. **BOT-CHX** last, on top of CHT's scaffolding.

---

## Appendix — open questions
- Should `list_projects` auto-filter to the logged-in user? Currently no auth scoping on `/api/v1/projects` — confirm with BOT-CHC before P0 lands.
- `current_page_context` leaks route_params — is that OK or should we allow-list? Recommend allow-listing `project_id`, `parcel_id`, `dno`, `tab` initially.
- `canvas/ChatRail.jsx` (the Vercel-AI-SDK one) appears unused — confirm with frontend owner that it can be deleted to avoid future confusion.
