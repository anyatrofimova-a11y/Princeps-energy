"""
Princeps ontology — typed domain objects + action registry.

The point
---------
Before the ontology, agents and routers all spoke their own dialect to
the database: one agent wrote to ``prospect_candidates``, another
queried ``missions``, chat produced free-form tool calls Claude sometimes
hallucinated. Every new feature was bespoke.

The ontology collapses that into three primitives:

  * **Objects** (``Project``, ``Site``, ``Layout``, …) — typed views over
    the existing tables, with a stable ``kind`` + ``id``, an explicit
    schema, and a canonical ``.fetch()`` / ``.save()`` contract.

  * **Actions** (``Project.advance_stage``, ``Site.score``, …) — the only
    legitimate way to mutate an object. Every action has a Pydantic
    input model, a ``preview()`` that returns a diff without committing,
    and a ``commit()`` that runs inside a transaction and appends to
    ``ontology_action_log``.

  * **Registry** — single import-time dict so chat, agents, and REST all
    discover the same action surface. Chat uses it to generate Claude
    tool-use schemas; the agent worker uses it for programmatic calls;
    the ``POST /api/actions/dispatch`` endpoint exposes it to the UI.

What you don't need to know
---------------------------
Callers never touch raw SQL for a modelled object. The ontology layer
owns the mapping between objects and tables, so if we rename
``prospect_candidates`` tomorrow nothing outside this package cares.
"""

from .base import (
    Action,
    ActionResult,
    Object,
    ObjectNotFound,
    ActionForbidden,
    registry,
    register,
)

__all__ = [
    "Action",
    "ActionResult",
    "Object",
    "ObjectNotFound",
    "ActionForbidden",
    "registry",
    "register",
]
