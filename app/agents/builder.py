"""
BuilderAgent — autonomously contributes code to the Princeps repo.

Given a GitHub issue number on ``anyatrofimova-a11y/feasibly``, this agent:

  1. Clones the repo into a temp workspace (shallow, single-branch).
  2. Creates a feature branch ``agent/builder/<issue>-<mission>``.
  3. Launches ``claude-agent-sdk`` with a scoped system prompt + path
     allowlist, letting Claude read/edit/test inside the workspace.
  4. After Claude's session ends: runs static checks (ruff/pytest if
     present), commits on behalf of the agent, pushes the branch, opens
     a DRAFT pull request via ``gh``.
  5. Posts the PR URL back to Slack and into the mission outcome.

Safety posture
--------------
  * DRAFT PRs only — never auto-merge, never push to ``main``.
  * Path allowlist enforced AFTER Claude's session: any edits outside the
    allowlist cause the branch to be discarded (no push, no PR).
  * Per-mission hard cap on wall-clock (30 min) and spend (£5 default).
  * No secret material is ever read from the workspace — the clone is
    shallow and the GITHUB_TOKEN is used only in the remote URL, never
    written to a file inside the repo.
  * This agent does NOT read from or write to the Princeps database
    beyond the ``missions`` / ``agent_runs`` bookkeeping tables.

Payload:
    {
        "issue_number": 42,                         # required
        "repo": "anyatrofimova-a11y/feasibly",      # optional; defaults to env
        "allow_paths": ["app/", "utils/", "tests/"],# optional override
        "max_turns": 30,                            # optional
        "max_cost_gbp": 5.0                         # optional; hard cap
    }

Env:
    GITHUB_TOKEN   — PAT or GitHub App token with contents+PR write
    BUILDER_REPO   — default repo (owner/name)
    CLAUDE_API_KEY — used by claude-agent-sdk (already in worker ctx)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from app.agents.base import (
    MODEL_OPUS,
    MODEL_SONNET,
    AgentContext,
    AgentResult,
    BaseAgent,
    BudgetExceeded,
)
from app.agents.coordination import (
    ActionStation,
    Coordinator,
    MissionConflict,
    SailingOrders,
)

log = logging.getLogger("princeps.agents.builder")


# Default path allowlist. Anything Claude edits outside these prefixes
# causes the branch to be discarded after the session.
DEFAULT_ALLOW_PATHS = (
    "app/",
    "utils/",
    "tests/",
    "sql/",
    "docs/",
    "feasi-frontend/src/",
)

# Hard deny — even if a caller tries to allow these, we refuse.
DENY_PATHS = (
    ".github/workflows/",    # CI config changes need human review via normal PR
    ".env",                  # never
    "fly.toml", "fly.frontend.toml",
    "sql/migrations/",       # schema migrations: human-only
    "Dockerfile",            # infra changes: human-only
    "Dockerfile.worker",
    "Dockerfile.scheduler",
    "Dockerfile.frontend",
)


_SYSTEM_PROMPT = """You are a senior engineer on the Princeps platform (UK energy feasibility).

You have been handed a GitHub issue. Your job is to:
  1. Read the issue description and any referenced files.
  2. Locate the relevant code.
  3. Make the smallest correct change that resolves the issue.
  4. Run any tests that exist for the affected code.
  5. Commit with a clear message.

Hard rules:
  * Edit ONLY files under the allow-listed paths you were given.
  * Never modify migrations, Dockerfiles, CI workflows, or secrets.
  * Prefer editing existing files over creating new ones.
  * Match the existing code style — do not reformat untouched code.
  * If the task is ambiguous or out of scope, STOP and write a note
    explaining what you'd need, rather than guessing.
  * Do not push the branch or open the PR — the orchestrator handles
    that. Your job ends at the final commit on the feature branch.

When you are done, output a short summary (under 200 words) of what
changed and what verification you ran."""


class BuilderAgent(BaseAgent):
    name = "builder"
    default_model = MODEL_SONNET
    model_ceiling = MODEL_OPUS

    # Builder runs are expensive; cap aggressively.
    monthly_budget_gbp     = 120.0
    daily_budget_gbp       = 20.0
    max_cost_per_run_gbp   = 5.0
    max_tokens_per_call    = 8_000
    max_tokens_out_per_run = 200_000

    # Wall-clock ceiling. Builder jobs that exceed this are killed.
    max_wall_seconds: int = 30 * 60

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        issue_number = payload.get("issue_number")
        if not issue_number:
            return AgentResult(
                ok=False,
                summary="builder requires 'issue_number' in payload",
                data={"error": "missing_issue_number"},
            )

        repo = payload.get("repo") or os.getenv("BUILDER_REPO", "anyatrofimova-a11y/feasibly")
        allow_paths = tuple(payload.get("allow_paths") or DEFAULT_ALLOW_PATHS)
        max_turns = int(payload.get("max_turns", 30))
        max_cost = float(payload.get("max_cost_gbp", self.max_cost_per_run_gbp))

        orders = SailingOrders.from_payload(self.name, payload)
        orders.goal = f"builder: resolve {repo}#{issue_number}"
        orders.action_station = ActionStation.TRAFALGAR        # highest-risk tier
        orders.touches_paths = list(allow_paths)
        orders.touches_tables = []                             # no DB writes

        try:
            async with Coordinator(ctx.db, orders) as mission:
                result = await self._do_build(
                    ctx,
                    repo=repo,
                    issue_number=int(issue_number),
                    allow_paths=allow_paths,
                    max_turns=max_turns,
                    max_cost=max_cost,
                    mission_id=orders.mission_id,
                )
                mission.record_outcome({
                    k: v for k, v in result.data.items()
                    if isinstance(v, (str, int, float, bool, type(None)))
                })
                return result
        except MissionConflict as conflict:
            return AgentResult(
                ok=False,
                summary=f"Skipped — {conflict}",
                data={"gated": True, "reason": "MissionConflict"},
            )

    # ── Orchestration ───────────────────────────────────────────────────────

    async def _do_build(
        self,
        ctx: AgentContext,
        *,
        repo: str,
        issue_number: int,
        allow_paths: tuple[str, ...],
        max_turns: int,
        max_cost: float,
        mission_id: str,
    ) -> AgentResult:
        gh_token = os.getenv("GITHUB_TOKEN")
        if not gh_token:
            return AgentResult(
                ok=False, summary="GITHUB_TOKEN not set.",
                data={"error": "no_github_token"},
            )

        start = time.monotonic()
        workspace = Path(tempfile.mkdtemp(prefix=f"builder-{mission_id[:8]}-"))
        branch = f"agent/builder/issue-{issue_number}-{mission_id[:8]}"
        log.info("builder.start repo=%s issue=%d branch=%s ws=%s",
                 repo, issue_number, branch, workspace)

        try:
            # 1. Clone + branch.
            await self._clone_and_branch(repo, gh_token, branch, workspace)

            # 2. Fetch issue body so Claude has the mission text.
            issue = await self._fetch_issue(repo, gh_token, issue_number)

            # 3. Run the Claude Agent SDK session inside the workspace.
            session_result = await asyncio.wait_for(
                self._run_sdk_session(
                    workspace=workspace,
                    issue=issue,
                    allow_paths=allow_paths,
                    max_turns=max_turns,
                    max_cost=max_cost,
                ),
                timeout=self.max_wall_seconds,
            )

            # 4. Enforce path allowlist on the actual diff.
            changed = await self._changed_paths(workspace)
            forbidden = [
                p for p in changed
                if any(p.startswith(deny) for deny in DENY_PATHS)
                or not any(p.startswith(allow) for allow in allow_paths)
            ]
            if forbidden:
                log.warning("builder.denylist_hit mission=%s files=%s",
                            mission_id[:8], forbidden[:8])
                return AgentResult(
                    ok=False,
                    summary=f"Rejected — Claude touched disallowed paths: {forbidden[:5]}",
                    data={
                        "error": "path_allowlist_violation",
                        "forbidden_paths": forbidden,
                        "sdk_summary": session_result.get("summary"),
                    },
                    cost_gbp=session_result.get("cost_gbp", 0),
                )

            if not changed:
                return AgentResult(
                    ok=True,
                    summary="Claude session ended with no file changes.",
                    data={"changed_files": 0, "sdk_summary": session_result.get("summary")},
                    cost_gbp=session_result.get("cost_gbp", 0),
                )

            # 5. Optional checks (best-effort).
            checks = await self._run_checks(workspace)

            # 6. Commit + push (on top of what claude-agent-sdk already did).
            await self._commit_any_remaining(workspace, issue_number)
            await self._push(workspace, branch)

            # 7. Open the DRAFT PR.
            pr_url = await self._open_pr(
                repo=repo, token=gh_token, branch=branch,
                issue=issue, session_summary=session_result.get("summary", ""),
                checks=checks,
            )

            elapsed = time.monotonic() - start
            await self.notify_slack(
                ctx,
                f"*Builder* opened DRAFT PR for #{issue_number}: {pr_url} "
                f"(cost £{session_result.get('cost_gbp', 0):.2f}, {elapsed:.0f}s, "
                f"{len(changed)} files)",
            )

            return AgentResult(
                ok=True,
                summary=f"Opened draft PR {pr_url} for issue #{issue_number}",
                data={
                    "pr_url": pr_url,
                    "branch": branch,
                    "issue_number": issue_number,
                    "changed_files": len(changed),
                    "checks": checks,
                    "sdk_summary": session_result.get("summary"),
                },
                cost_gbp=session_result.get("cost_gbp", 0),
                tokens_in=session_result.get("tokens_in", 0),
                tokens_out=session_result.get("tokens_out", 0),
            )

        except asyncio.TimeoutError:
            return AgentResult(
                ok=False,
                summary=f"Timed out after {self.max_wall_seconds}s.",
                data={"error": "wall_clock_timeout"},
            )
        except BudgetExceeded as be:
            return AgentResult(
                ok=False,
                summary=f"Halted — {be}",
                data={"error": "budget_exceeded"},
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    # ── Git / gh plumbing ────────────────────────────────────────────────────

    @staticmethod
    async def _clone_and_branch(
        repo: str, token: str, branch: str, workspace: Path
    ) -> None:
        remote = f"https://x-access-token:{token}@github.com/{repo}.git"
        await _run(["git", "clone", "--depth", "1", remote, str(workspace)])
        # Commits authored as the Princeps7 bot account so PRs are
        # correctly attributed in GitHub (verified noreply email).
        await _run(
            ["git", "config", "user.email",
             "276416581+Princeps7@users.noreply.github.com"],
            cwd=workspace,
        )
        await _run(
            ["git", "config", "user.name", "Princeps7"], cwd=workspace,
        )
        await _run(["git", "checkout", "-b", branch], cwd=workspace)

    @staticmethod
    async def _fetch_issue(repo: str, token: str, number: int) -> dict:
        env = {**os.environ, "GH_TOKEN": token}
        out = await _run(
            ["gh", "issue", "view", str(number), "--repo", repo,
             "--json", "number,title,body,labels,url"],
            env=env,
        )
        return json.loads(out)

    @staticmethod
    async def _changed_paths(workspace: Path) -> list[str]:
        """All tracked+untracked changes relative to HEAD's parent commit."""
        out = await _run(
            ["git", "status", "--porcelain"], cwd=workspace,
        )
        paths: list[str] = []
        for line in out.splitlines():
            # Porcelain v1 format: "XY path" (2 char status + space + path)
            if len(line) > 3:
                paths.append(line[3:].split(" -> ")[-1].strip())
        return paths

    @staticmethod
    async def _commit_any_remaining(workspace: Path, issue_number: int) -> None:
        """If claude-agent-sdk left uncommitted changes, wrap them up."""
        out = await _run(["git", "status", "--porcelain"], cwd=workspace)
        if not out.strip():
            return
        await _run(["git", "add", "-A"], cwd=workspace)
        await _run(
            ["git", "commit", "-m", f"builder: additional changes for #{issue_number}"],
            cwd=workspace,
        )

    @staticmethod
    async def _push(workspace: Path, branch: str) -> None:
        await _run(["git", "push", "-u", "origin", branch], cwd=workspace)

    @staticmethod
    async def _run_checks(workspace: Path) -> dict[str, Any]:
        """Best-effort static + unit checks. Never blocks the PR."""
        out: dict[str, Any] = {}
        # ruff (if pyproject.toml or ruff.toml present)
        if (workspace / "pyproject.toml").exists() or (workspace / "ruff.toml").exists():
            code, stdout = await _run_capture(["ruff", "check", "."], cwd=workspace)
            out["ruff"] = {"exit": code, "tail": stdout[-1500:]}
        # pytest on tests/ if present
        if (workspace / "tests").is_dir():
            code, stdout = await _run_capture(
                ["pytest", "-x", "-q", "tests/"], cwd=workspace
            )
            out["pytest"] = {"exit": code, "tail": stdout[-3000:]}
        return out

    async def _open_pr(
        self,
        *,
        repo: str,
        token: str,
        branch: str,
        issue: dict,
        session_summary: str,
        checks: dict,
    ) -> str:
        title = f"[builder] {issue.get('title', '')}"[:120]
        body = (
            f"Resolves #{issue['number']}\n\n"
            f"## Summary\n{session_summary[:2000]}\n\n"
            f"## Checks\n```\n{json.dumps(checks, indent=2)[:2000]}\n```\n\n"
            "_This PR was opened by the Princeps builder agent. "
            "It is a DRAFT — human review required before merge._"
        )
        env = {**os.environ, "GH_TOKEN": token}
        out = await _run(
            [
                "gh", "pr", "create",
                "--repo", repo,
                "--head", branch,
                "--base", "main",
                "--title", title,
                "--body", body,
                "--draft",
                "--label", "agent:builder",
            ],
            env=env,
        )
        return out.strip().splitlines()[-1]

    # ── claude-agent-sdk session ─────────────────────────────────────────────

    async def _run_sdk_session(
        self,
        *,
        workspace: Path,
        issue: dict,
        allow_paths: tuple[str, ...],
        max_turns: int,
        max_cost: float,
    ) -> dict[str, Any]:
        """Drive a claude-agent-sdk session inside ``workspace``.

        We import the SDK lazily so other agents don't pay the import cost.
        """
        try:
            from claude_agent_sdk import (          # type: ignore[import-not-found]
                query,
                ClaudeAgentOptions,
            )
        except ImportError as e:
            raise RuntimeError(
                "claude-agent-sdk not installed. "
                "Add it to requirements.txt for the builder worker image."
            ) from e

        prompt = (
            f"GitHub issue #{issue['number']}: {issue.get('title', '')}\n\n"
            f"{issue.get('body', '').strip()}\n\n"
            f"Labels: {[l.get('name') for l in issue.get('labels') or []]}\n\n"
            f"Allowed paths (prefixes): {list(allow_paths)}\n"
            f"Workspace: {workspace}\n"
        )

        options = ClaudeAgentOptions(
            cwd=str(workspace),
            system_prompt=_SYSTEM_PROMPT,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            permission_mode="acceptEdits",
            max_turns=max_turns,
        )

        summary_parts: list[str] = []
        tokens_in = tokens_out = 0
        cost_usd = 0.0

        async for message in query(prompt=prompt, options=options):
            mtype = type(message).__name__
            if mtype == "AssistantMessage":
                for block in getattr(message, "content", []) or []:
                    if getattr(block, "type", None) == "text":
                        summary_parts.append(getattr(block, "text", "")[:1200])
            elif mtype == "ResultMessage":
                cost_usd = float(getattr(message, "total_cost_usd", 0) or 0)
                usage = getattr(message, "usage", None) or {}
                tokens_in = int(usage.get("input_tokens", 0) or 0)
                tokens_out = int(usage.get("output_tokens", 0) or 0)
                # Surface the SDK's own final summary if it provided one.
                text = getattr(message, "result", None)
                if text:
                    summary_parts.append(str(text)[:1500])

            # Per-mission cost trip.
            if cost_usd * 0.82 > max_cost:
                log.warning("builder: tripping cost cap mid-session: $%.2f", cost_usd)
                raise BudgetExceeded(
                    f"builder session hit £{max_cost} cap (spent ${cost_usd:.2f})"
                )

        return {
            "summary": "\n---\n".join(summary_parts)[:6000],
            "cost_gbp": round(cost_usd * 0.82, 4),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }


# ── subprocess helpers ──────────────────────────────────────────────────────


async def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
) -> str:
    """Run a subprocess, raise CalledProcessError on non-zero."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=out, stderr=err,
        )
    return out


async def _run_capture(
    cmd: list[str], *, cwd: Path | None = None
) -> tuple[int, str]:
    """Run a subprocess, return (exit_code, combined_output). Never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return int(proc.returncode or 0), stdout.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return 127, f"{cmd[0]}: command not found"
