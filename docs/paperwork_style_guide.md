# Princeps Paperwork Style Guide
**Cross-cutting scaffolding for all pack-rewrite bots.** Paired with
`docs/audits/paperwork_rewrite_spec.md` (COUNCIL-1) and
`docs/audits/industry_standards_index.md` (single-source citation index).

This guide is half a page of rules. Follow them or the pack fails audit.

---

## 1. The five partials

All partials live in `templates/report/_partials/`:

| Partial | Purpose | Use |
|---|---|---|
| `_brand.html` | Canonical gold palette + typography + cover / header / footer macros | `{% include "report/_partials/_brand.html" %}` in `<head>` once |
| `_revision.html` | Prepared/reviewed/approved block + revision history table + PROJ-PACK-REV code | `{% import ... as rev %}` then `{{ rev.block(revisions, signatories, doc_ref) }}` |
| `_reliance.html` | Addressee list + limit-of-liability boilerplate | `{% import ... as rel %}` then `{{ rel.statement(reliance_type="lender", ...) }}` |
| `_provenance.html` | Footnote / provenance table | `{% import ... as prov %}` then `{{ prov.footnotes(provenance_entries) }}` |
| `_citation_macros.html` | `cite(n)`, `cite_block(...)`, `regcite(key)`, `regcite_register(keys)` | `{% import ... as c %}` then `{{ c.cite(1) }}` inline |

All partials accept an empty/missing context and render clearly-marked
`TO POPULATE` stubs instead of crashing.

---

## 2. Python-side glue (one line per pack)

`regcite` looks up regulatory citations from `app.regulatory.versions`
(BOT-R2 deliverable) with a hard-coded fallback table. The lookup is in
Python, not the template, so citations update when the module updates.

**Every pack bot must do this once when constructing its Jinja `Environment`:**

```python
from jinja2 import Environment, FileSystemLoader
from templates.report._partials.helpers import register_jinja_helpers

env = Environment(loader=FileSystemLoader("templates"))
register_jinja_helpers(env)  # registers regcite, regcite_dict, default_revision_code, prov_entry
```

That is the only shared-pipeline edit required. Do NOT edit
`utils/report_renderer.py` or similar shared modules — each pack wires this
itself so bots can ship independently.

---

## 3. Required template-block names (per pack)

Every pack must expose these Jinja blocks (for future report-assembly tooling):

```jinja
{% block cover %}...{% endblock %}
{% block exec_summary %}...{% endblock %}
{% block body %}...{% endblock %}
{% block appendices %}...{% endblock %}
```

Inside `{% block appendices %}`, always emit these, in order, A through F:

- **Appendix A** Data Provenance &mdash; use `prov.footnotes(...)`.
- **Appendix B** Methodology & Assumptions &mdash; pack-specific.
- **Appendix C** Glossary & Abbreviations &mdash; pack-specific.
- **Appendix D** Regulatory & Standards Register &mdash; use `c.regcite_register([...])`.
- **Appendix E** Revision History &mdash; use `rev.block(...)`.
- **Appendix F** Reliance Statement &mdash; use `rel.statement(...)`.

---

## 4. Figure and table numbering

- Body: `Figure 1.`, `Figure 2.`, &hellip; `Table 1.`, `Table 2.`, &hellip; &mdash;
  restart at each top-level section: `Figure 1.1` (section 1 figure 1),
  `Figure 2.1`, etc.
- Appendices: `Figure A1.1`, `Table A1.1` &mdash; appendix letter + index within
  appendix.
- Packs ≥20 pages MUST emit a List of Figures and List of Tables page after
  the Contents page.
- Every figure caption: `Figure N.M. Title.` Every table caption:
  `Table N.M. Title.` Both in bold gold (`var(--gold-dark)`), 9pt.

---

## 5. Revision code pattern

`{PROJECT}-{PACK}-{REV}`. Example: `OXFO-GCR-P01`.

- **PROJECT**: 4-letter short code from `projects.code` (uppercase).
- **PACK**: 3-letter pack code (`GCR`, `G99`, `PLA`, `DCO`, `BNG`, `CDM`,
  `LND`, `FVA`, `ICM`, `SAR`, `EIA`, `ESR`, `DCR`, `CON`) &mdash; per
  paperwork_rewrite_spec section (h).
- **REV**: `P01`, `P02`, &hellip; for pre-issue; then `01`, `02`, &hellip;
  after formal issue.

Use `default_revision_code(project_code, pack_type, rev)` from
`helpers.py` to build it.

---

## 6. PDF file naming (per spec h)

`{ProjectName}-{PackType}-{Rev}-{ISO-date}.pdf` &mdash; this is the output
filename, separate from the in-document revision code.

---

## 7. Palette discipline (hard rule)

The canonical palette lives ONLY in `_brand.html` as CSS variables:

```
--gold:       #C9A64B;
--gold-dark:  #A88732;
--gold-light: #F5E9C8;
--ink:        #1a1a1a;
--ink-muted:  #4a4a4a;
--rule:       #E6D9B8;
```

Pack templates MUST reference `var(--gold)` etc. and MUST NOT redefine the
hex values locally. The drifted palettes (purple `#7c5cfc`, gold `#F5B731`,
gold `#D4A018`, teal `#007A8C`) are retired.

---

## 8. TO-POPULATE discipline

Any `[Developer Name]` / `[Company number]` / `[Phone]` style placeholder in
rendered output is a failure. If a context variable is missing, the partials
render a visible `.princeps-todo` badge so QA can spot it. Never ship a pack
flagged "submission-ready" while those badges remain.
