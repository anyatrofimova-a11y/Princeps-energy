# Hypercube / CAIRN gap analysis & integration plan — 2026-05-30

Reference: https://wearehypercube.com/cairn-platform/, Contract Intelligence UI screenshot (Windy View CTA v1/v2 diff).

## TL;DR

Cairn is **Palantir-Foundry-shaped for energy operators** with three pillars: Asset Manager, Procurement Manager, Contract Intelligence — all sitting on an "energy ontology" and an agentic answer layer powered by Wordsmith Legal AI for documents and a per-tenant deployment story.

Princeps already wins on **pre-development** (planning, grid headroom, financial dispatch, polygon-to-verdict). Princeps loses on **post-FID operations**, especially the **document/contract spine** that Cairn has wrapped in a clause-cited, confidence-rated chat. Closing the gap is mostly additive: we already have the typed-action registry, AGE graph, Conjure IDL, and agent council — what we lack is the **document/obligation ontology** and the **clause-grounded chat surface**.

## Side-by-side capability map

| # | Cairn capability | Princeps today | Gap | Priority |
|---|---|---|---|---|
| 1 | Project-scoped document workspace ("4 docs loaded for Windy View") | Per-message file upload in chat (ephemeral) | No persistent project-doc index | **P0** |
| 2 | Clause-level citation (`§1.1 · P.11` verbatim quote) | Tool-result display with file paths | No clause/page targeting; no verbatim pane | **P0** |
| 3 | Confidence rating per answer (LOW / MED / HIGH) with `JUSTIFY →` button | None on chat answers; GO/CAUTION/NO-GO only on agent verdicts | Generalise verdict schema to every chat turn | **P0** |
| 4 | Bounded-uncertainty statement ("Schedules 1-16 have not been compared") | None | Need an explicit "what wasn't checked" surface | **P1** |
| 5 | Multi-draft diff ("verbatim diff between March and April") | None | Doc-pair clause alignment + diff engine | **P1** |
| 6 | Obligation / penalty / response-condition extraction | None | Typed `Obligation` schema + extractor | **P1** |
| 7 | Cross-document dependency mapping | None | Clause-to-clause edges in AGE | **P2** |
| 8 | Change alerts when a new draft lands | None | Doc-version watcher swarm | **P2** |
| 9 | Consent tracking | None | Typed `Consent` records | **P2** |
| 10 | "Powered by Wordsmith Legal AI" | Generic Claude | Energy-contract-specialised prompt suite (or Wordsmith on Bedrock) | **P1** |
| 11 | Asset Manager (real-time portfolio decisions, +0.5–1.5% availability) | BESS live revenue + portfolio performance + 3D twin | **At parity / ahead** on physical sim | — |
| 12 | Procurement Manager (bid eval, 30–50% time savings) | `procurement_intelligence.py` (tender classification, bid viability, tender-to-site match) | **At parity** | — |
| 13 | BYOC / customer-owned data | Multi-tenant on Fly + Supabase RLS | Need a "deploy-in-your-cloud" packaging for enterprise | **P2** |
| 14 | Energy ontology (assets, markets, contracts) | DTDL v3 + Conjure IDL + Apache AGE — but no `Document`/`Clause`/`Obligation` types | Extend ontology with the document spine | **P0** |
| 15 | Wordsmith-style legal Q&A | Princeps chat is grid/finance/planning-tuned | Add legal/contract intents | **P1** |

## Integration plan — agentic + ontology

The unlock is that **everything Cairn shows in the right rail can be expressed as paths in our AGE graph**. A citation is `Claim ← supports ← Clause ← part_of ← DocumentDraft ← belongs_to ← Project`. Confidence is the coverage ratio of `claims_made / claims_with_supporting_clause`. "Justify" is just rendering that path.

### Phase A — Ontology spine (P0, ~2 days)

Extend `conjure/idl/` with five types and ship the AGE schema:

```
Document        { rid, project_rid, kind: enum(CTA|OEM|EPC|PPA|GridAgreement|...), title, party_first, party_second }
DocumentDraft   { rid, document_rid, version, draft_date, page_count, source_hash }
Clause          { rid, draft_rid, section, page, span_start, span_end, text }
Obligation      { rid, clause_rid, party, trigger, action, penalty, deadline_iso, status }
Citation        { rid, claim_rid, clause_rid, verbatim, similarity }
```

Edges in AGE:
- `(Project) -[:HAS_DOCUMENT]-> (Document)`
- `(Document) -[:HAS_DRAFT]-> (DocumentDraft)`
- `(DocumentDraft) -[:CONTAINS_CLAUSE]-> (Clause)`
- `(Clause) -[:GIVES_RISE_TO]-> (Obligation)`
- `(Clause) -[:CITED_BY]-> (Claim)` — claim is whatever the agent emits

Migration: `migrations/2026_05_30_document_spine.sql`.

### Phase B — Document ingestion (P0, ~1 day)

`utils/document_ingester.py` — already have `pdfplumber` + `pymupdf` in requirements.

1. PDF → page-aware extraction (pymupdf gives `(page, bbox, text)` per block).
2. Heading regex (`§\d+(\.\d+)*`, `SCHEDULE \d+`, `\bClause \d+\.\d+\b`) → clause boundaries.
3. Embed each clause (Voyage-3-large via Anthropic) → `clause_embeddings` pgvector column.
4. Hash the source file → `source_hash` → cheap drift detection for change alerts.

### Phase C — Clause-cited chat tool (P0, ~1 day)

New typed action `cite_clause` in `app/actions/`:

```python
class CiteClause(ActionType):
    ACTION_ID = "cite_clause"
    project_rid: str
    query: str
    document_filter: list[str] | None = None
    top_k: int = 5
    async def execute(self, ctx):
        # 1. Embed query
        # 2. pgvector cosine on clause_embeddings within project_rid
        # 3. Return list[{clause_rid, doc_title, section, page, verbatim, similarity}]
```

Chat layer (`app/chat.py`):
- On every assistant turn, after generation, call `cite_clause` for each emitted claim, attach citations as a structured field on the message.
- Frontend renders a right-rail mirroring the Cairn screenshot: `RATING` + `CITATIONS` + `SOURCES`.

### Phase D — Confidence + Justify (P0, ~0.5 day)

Generalise the existing `verdict.py` (currently agent-only) to a `ConfidenceVerdict` emitted on every chat turn:

```python
class ConfidenceVerdict(BaseModel):
    rating: Literal["low", "med", "high"]
    justification: str
    bounds: list[str]   # ← "Schedules 1-16 not compared"
    coverage: float     # claims_grounded / claims_total
```

Rating rule:
- `high` if every claim has ≥1 citation with similarity ≥0.85
- `med` if every claim has ≥1 citation, some <0.85
- `low` if any claim has 0 citations

`bounds[]` is auto-populated from what the embedding query *didn't* retrieve. If 47 schedules exist but only schedules 1–16 had clauses cited, add `"Schedules 17-47 have not been compared"` automatically. This matches the Cairn pattern verbatim.

### Phase E — Multi-draft diff (P1, ~1 day)

New action `diff_drafts(document_rid, version_a, version_b)`:
- Align clauses by `section` first, then by name-similarity fallback.
- Per pair, compute character-level diff (`difflib.unified_diff` or `python-levenshtein`).
- Emit `{section, page_a, page_b, status: 'unchanged'|'modified'|'added'|'removed', diff_text}`.
- Frontend: render the Cairn-style "COD change is a verbatim diff" with the two source quotes side-by-side.

### Phase F — Obligation extractor (P1, ~1.5 days)

New action `extract_obligations(draft_rid)` invokes Claude with a structured-output schema:

```
For each Clause classified as obligation-bearing, return:
  trigger     (string — event that activates the obligation)
  party       (Owner|Contractor|Lender|...)
  action      (the obligor must do X)
  penalty     (consequence on breach)
  deadline    (ISO date or "within N days of trigger")
```

Run once on ingest, then again on each new draft via the change-watcher swarm. Stored as `Obligation` records linked to `Clause`.

### Phase G — Change-alert swarm (P2, ~0.5 day)

Add `swarms/document_watcher.py` that subscribes to AGE `(Document)-[:HAS_DRAFT]->(DocumentDraft)` insert events. On a new draft:
1. Find previous draft of same `document_rid`.
2. Fire `diff_drafts`.
3. Fire `extract_obligations` on the new draft.
4. Compute symmetric difference vs prior obligation set.
5. Emit a typed `ChangeAlert` action with summary + delta.
6. Push to project workspace toast + agent council inbox.

### Phase H — UI (P0 in parallel with C/D)

New component `feasi-frontend/src/components/workspace/ContractIntelligencePanel.jsx`:

- Left pane = chat with `Confidence: HIGH | Justify →` badge under every assistant turn.
- Right pane = `JUSTIFYING / RATING / CITATIONS / SOURCES` rail driven by the verdict + citation payload.
- New tab on `ProjectWorkspace.jsx` named **"Documents"** — lists all `Document` records, drag-and-drop new drafts, shows the change-watcher feed.

Reuse the existing chat SSE infrastructure (`app/chat.py`) — just extend the streamed message envelope with `{citations: [...], verdict: {...}}`.

## What we already have that Cairn doesn't

These are the lines we should lean on in any head-to-head:

- **Pre-FID land + grid + planning fusion**: polygon → REPD/NSIP precedent → DNO headroom → BNG cost → £/MWh in one verdict. Cairn is operations-focused; they don't surface this.
- **PostGIS-grade 3D twin** (deck.gl ColumnLayer + ArcLayer + WebSocket live feed). Cairn shows portfolio dashboards; we ship grid topology.
- **Open-data spine** (REPD 14k+, NSIP/DCO, NESO TEC 2.2k, BMRS prices, NGED LTDS CIM). Cairn integrates customer systems; we additionally bring upstream open data.
- **Pre-built financial dispatch + AR7 CfD + Modo BESS revenue benchmark**. Cairn does asset perf; we do revenue forecasting.
- **Council swarm + typed-action audit log**: every action emits a typed result with a trail. Cairn shows "audit trails"; we have a structured, queryable one.

## Sequencing

```
Week 1  | A (ontology) → B (ingest) → C (cite_clause) → D (verdict) → H (UI)
Week 2  | E (diff) → F (obligations) → G (change watcher) → polish
Week 3  | Pilot with one user holding a real CTA + side-by-side memo
```

Net effect after Week 1: Princeps has a clause-cited, confidence-rated chat across project documents — the screenshot's exact shape. Week 2 adds the diff/obligation/change layer. Week 3 closes the loop.

## What I'm explicitly NOT proposing

- Building a Wordsmith equivalent from scratch. Specialist legal models take a team; we just need clause-grounded prompts on a strong general model.
- Replacing the Asset / Procurement modules — we already match or exceed.
- "BYOC in customer cloud" packaging — defer until a paying enterprise asks.
- Free-standing contract intelligence as a product — keep it as a Princeps workspace tab so it pulls value from our pre-development context (a CTA for a site Princeps already underwrites is worth more than a CTA in isolation).
