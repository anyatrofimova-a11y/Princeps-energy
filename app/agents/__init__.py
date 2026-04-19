"""
Princeps runtime agent bots.

Autonomous workers that consume ARQ queues, reason with Claude, write results
to Postgres, and notify users via Slack/email. Deployed as independent Railway
services under the princeps project.

Agent roster:
- ProspectorAgent      — scans UK regions for viable sites
- GridMonitorAgent     — watches NESO/DNO feeds for constraint changes
- ProcurementAgent     — daily tender sweep + bid viability scoring
- IngestionAgent       — scheduled data refreshes with anomaly triage
- ReportAgent          — weekly portfolio PDFs
- AnalystAgent         — on-demand deep research triggered from chat
- CompetitorRnDAgent   — scouts market + drafts upgrade PRs

See docs/agent-architecture.md for the full design.
"""

from app.agents.base import BaseAgent, AgentContext, AgentResult

__all__ = ["BaseAgent", "AgentContext", "AgentResult"]
