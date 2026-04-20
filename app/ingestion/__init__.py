"""
app/ingestion — Princeps Phase 7a Intelligence ingestion workers.

Every worker is an async subclass of :class:`IngestionWorker` in
``base.py`` and targets one upstream source (Ofgem, NESO TEC, PINS NSIP,
PlanIt, DESNZ, BMRS balancing events, HSE COMAH, Companies House,
Find-a-Tender). Workers write into the ``documents`` / ``dockets``
tables declared in ``app/migrations/0001_intelligence_schema.sql`` and
log each run to ``intelligence_ingestion_log`` (migration 0002).

Scheduling is handled by ``scheduler.py`` which registers an
``AsyncIOScheduler`` with cron triggers per worker. The scheduler is
started from ``app/startup.py`` only when ``PRINCEPS_INGESTION_ENABLED=true``.
"""
