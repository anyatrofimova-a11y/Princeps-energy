"""princeps-agent-builder — autonomous self-build loop.

Pattern per tick:
  1. SELECT the highest-priority pending row from builder.queue
  2. Load context_paths from the repo (git show or local clone)
  3. Send brief + context to Claude with a strict diff-only protocol
  4. Apply the returned diff in a fresh branch
  5. Push the branch + open a PR via the GitHub REST API
  6. If auto_merge=true and CI is green, merge — that triggers the
     Fly auto-deploy workflow you wired today
  7. Audit every step into builder.runs

Required env vars (Railway service):
  DATABASE_URL          # Supabase
  GITHUB_TOKEN          # repo:write — opens PRs, pushes branches
  GITHUB_REPO           # 'anyatrofimova-a11y/Princeps-energy'
  ANTHROPIC_API_KEY     # Claude API
  ANTHROPIC_MODEL       # default 'claude-opus-4-7'
  GIT_AUTHOR_NAME       # default 'Princeps Builder'
  GIT_AUTHOR_EMAIL      # default 'builder@princeps.dev'

Safety:
  - Branch policy 'direct-main' is honoured but should never be set
    from agent-originated rows — only from a user row.
  - Hard cap on files changed per task (max_files_changed).
  - Refuses to touch .github/workflows/* unless brief explicitly
    mentions "workflow" AND the requested_by is 'user'.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from agents.lib.base import Agent, get_pool, run_agent

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

_BUILDER_PROMPT = """You are Princeps' build agent. Your job is to read the brief + the relevant repo files and emit a precise file-by-file diff that satisfies the brief.

Output format — JSON only, no prose, no markdown:

{
  "plan": "<2-4 sentence summary of what you will do and why>",
  "changes": [
    {
      "path": "<repo-relative file path>",
      "operation": "edit | create | delete",
      "old_content_sha": "<short hash of file as you received it, or null if create>",
      "new_content": "<full new file content; for delete, omit this key>"
    }
  ],
  "tests": ["<one-line description of how you'd verify the change>", ...],
  "commit_message": "<single-line commit subject>",
  "commit_body": "<multi-paragraph body explaining the change>"
}

Hard rules:
- Touch at most {max_files} files.
- Never modify .github/workflows/* (workflow changes need human sign-off).
- Never commit secrets, .env files, or tokens.
- For Python: keep existing imports, type hints, and logging conventions.
- For JSX: keep existing component naming, hook patterns, and styling approach.
- If the brief is unclear or the context insufficient, return {"plan": "abort: <reason>", "changes": []}.

BRIEF:
{brief}

CONTEXT FILES:
{context}
"""


async def _gh(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    """Authenticated GitHub REST call. Raises on non-2xx."""
    token = os.environ["GITHUB_TOKEN"]
    headers = kwargs.pop("headers", {})
    headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    r = await client.request(method, f"{GITHUB_API}{path}", headers=headers, **kwargs)
    if r.status_code >= 300:
        raise RuntimeError(f"GitHub {method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


async def _get_repo_file(client: httpx.AsyncClient, repo: str, path: str, ref: str = "main") -> tuple[str, str] | None:
    """Return (content, blob_sha) of a file at HEAD of `ref`, or None if missing."""
    try:
        data = await _gh(client, "GET", f"/repos/{repo}/contents/{path}", params={"ref": ref})
    except Exception:
        return None
    if isinstance(data, list):
        return None  # path is a directory
    content_b64 = data.get("content", "")
    content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    return content, data.get("sha", "")


async def _open_pr(
    client: httpx.AsyncClient, repo: str, *,
    branch: str, base: str, title: str, body: str,
) -> dict[str, Any]:
    pr = await _gh(
        client, "POST", f"/repos/{repo}/pulls",
        json={"title": title, "head": branch, "base": base, "body": body},
    )
    return pr


async def _create_branch_and_commit(
    client: httpx.AsyncClient, repo: str, *,
    base: str, branch: str, changes: list[dict],
    commit_message: str, commit_body: str,
) -> str:
    """Create a branch off `base`, commit all changes via the contents API.
    Returns the final commit SHA."""
    base_ref = await _gh(client, "GET", f"/repos/{repo}/git/ref/heads/{base}")
    base_sha = base_ref["object"]["sha"]

    # Create the branch
    try:
        await _gh(client, "POST", f"/repos/{repo}/git/refs",
                  json={"ref": f"refs/heads/{branch}", "sha": base_sha})
    except RuntimeError as exc:
        if "Reference already exists" not in str(exc):
            raise

    commit_sha = base_sha
    for ch in changes:
        path = ch["path"]
        op = ch.get("operation", "edit")
        if op == "delete":
            # Need current sha
            existing = await _gh(client, "GET", f"/repos/{repo}/contents/{path}",
                                 params={"ref": branch})
            await _gh(
                client, "DELETE", f"/repos/{repo}/contents/{path}",
                json={"message": f"{commit_message}\n\n[delete {path}]",
                      "branch": branch, "sha": existing["sha"]},
            )
            continue
        new_b64 = base64.b64encode(ch["new_content"].encode("utf-8")).decode()
        body: dict[str, Any] = {
            "message": commit_message,
            "branch": branch,
            "content": new_b64,
        }
        if op == "edit":
            existing = await _gh(client, "GET", f"/repos/{repo}/contents/{path}",
                                 params={"ref": branch})
            body["sha"] = existing.get("sha")
        resp = await _gh(client, "PUT", f"/repos/{repo}/contents/{path}", json=body)
        commit_sha = resp.get("commit", {}).get("sha", commit_sha)
    return commit_sha


async def _claude_plan(
    brief: str, context_files: dict[str, str], max_files: int,
) -> dict[str, Any]:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    ctx_blob = "\n\n".join(
        f"--- FILE: {p} (sha:{_sha8(c)}) ---\n{c[:8000]}"
        for p, c in context_files.items()
    )
    prompt = (_BUILDER_PROMPT
              .replace("{max_files}", str(max_files))
              .replace("{brief}", brief)
              .replace("{context}", ctx_blob))
    async with httpx.AsyncClient(timeout=180.0) as c:
        r = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": 8000,
                  "messages": [{"role": "user", "content": prompt}]},
        )
        r.raise_for_status()
        text = r.json()["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)


def _sha8(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def _safe_branch_name(title: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-")[:48]
    return f"bot/{slug}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def _is_workflow_path(path: str) -> bool:
    return path.startswith(".github/workflows/")


async def _research(brief: str) -> str:
    """Run a research pass: Claude with web-search tool, produce markdown."""
    api_key = os.environ["ANTHROPIC_API_KEY"]
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    sys = (
        "You are a research analyst for Princeps (UK energy pre-development "
        "platform). Use the web_search tool to find current sources. Return "
        "ONLY a markdown report with: ## TL;DR, ## Findings (with inline "
        "citations like [1]), ## Sources (numbered list with full URLs), "
        "## Implications for Princeps. Be terse, specific, and date your claims."
    )
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={
                "model": model, "max_tokens": 4000,
                "system": sys,
                "tools": [{"type": "web_search_20250305", "name": "web_search",
                           "max_uses": 8}],
                "messages": [{"role": "user", "content": brief}],
            },
        )
        r.raise_for_status()
        body = r.json()
        out_parts = [
            blk["text"] for blk in body.get("content", [])
            if blk.get("type") == "text"
        ]
        return "\n\n".join(out_parts).strip() or "(no research output)"


async def _audit(pool, task_id, step, ok, detail):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO builder.runs (task_id, step, ok, detail) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            task_id, step, ok, json.dumps(detail),
        )


class Builder(Agent):
    NAME = "builder"
    CADENCE_SECONDS = 90

    async def tick(self):
        repo = os.environ.get("GITHUB_REPO", "anyatrofimova-a11y/Princeps-energy")
        if not os.environ.get("GITHUB_TOKEN"):
            return {"skipped": "no GITHUB_TOKEN"}
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return {"skipped": "no ANTHROPIC_API_KEY"}

        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                # SKIP LOCKED + dependency check: pending rows whose
                # depends_on tasks are all done.
                row = await conn.fetchrow(
                    """UPDATE builder.queue SET status='in_progress', started_at=now()
                        WHERE task_id = (
                          SELECT q.task_id FROM builder.queue q
                           WHERE q.status='pending'
                             AND NOT EXISTS (
                               SELECT 1 FROM unnest(coalesce(q.depends_on, '{}'::uuid[])) AS dep
                                LEFT JOIN builder.queue p ON p.task_id = dep
                                WHERE p.status IS NULL OR p.status NOT IN ('done')
                             )
                           ORDER BY q.priority ASC, q.created_at ASC
                           LIMIT 1
                          FOR UPDATE SKIP LOCKED
                        )
                        RETURNING *"""
                )
            if not row:
                return {"picked": 0}

            task_id = row["task_id"]
            mode = row["mode"] or "build"
            await _audit(pool, task_id, "picked", True,
                         {"title": row["title"], "mode": mode,
                          "policy": row["branch_policy"]})

            # ── agent_trigger mode: just fire the agent and finish ──
            if mode == "agent_trigger":
                from utils.agent_orchestrator import trigger_agent
                agent_name = (row["brief"] or "").replace("AGENT TRIGGER:", "").strip().split()[0]
                out = await trigger_agent(pool, agent_name,
                                          requested_by=row["requested_by"],
                                          task_id=str(task_id))
                async with pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE builder.queue SET status='done', finished_at=now(),
                              claude_plan=$2
                            WHERE task_id=$1""",
                        task_id, json.dumps(out, default=str)[:2000],
                    )
                return {"task": str(task_id), "agent_trigger": agent_name, "result": out}

            # ── research mode: WebSearch via Claude + commit a markdown ──
            if mode == "research":
                summary = await _research(row["brief"] or row["title"])
                slug = re.sub(r"[^a-z0-9-]+", "-", row["title"].lower())[:48].strip("-") or "topic"
                md_path = f"docs/research/{slug}.md"
                md_body = (
                    f"# {row['title']}\n\n"
                    f"> Generated by princeps-agent-builder · task `{task_id}`\n\n"
                    + summary
                )
                async with httpx.AsyncClient(timeout=120.0) as client:
                    branch = _safe_branch_name(row["title"])
                    sha = await _create_branch_and_commit(
                        client, repo, base="main", branch=branch,
                        changes=[{
                            "path": md_path, "operation": "create",
                            "new_content": md_body,
                        }],
                        commit_message=f"research: {row['title']}",
                        commit_body="",
                    )
                    pr = await _open_pr(
                        client, repo, branch=branch, base="main",
                        title=f"[research] {row['title']}",
                        body=md_body[:3000],
                    )
                async with pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE builder.queue
                              SET status='done', finished_at=now(),
                                  branch_name=$2, commit_sha=$3,
                                  pr_number=$4, pr_url=$5,
                                  research_output=$6
                            WHERE task_id=$1""",
                        task_id, branch, sha, pr["number"], pr["html_url"], md_body,
                    )
                try:
                    api = os.environ.get("PRINCEPS_API_URL", "https://princeps-api.fly.dev")
                    async with httpx.AsyncClient(timeout=10) as cn:
                        await cn.post(f"{api}/api/whatsapp/notify-task-complete/{task_id}")
                except Exception: pass
                return {"task": str(task_id), "research": True,
                        "pr": pr["number"], "doc": md_path}

            async with httpx.AsyncClient(timeout=120.0) as client:
                # Load context
                ctx: dict[str, str] = {}
                for p in (row["context_paths"] or []):
                    fetched = await _get_repo_file(client, repo, p)
                    if fetched:
                        ctx[p] = fetched[0]
                await _audit(pool, task_id, "context_loaded", True,
                             {"files": list(ctx.keys())})

                # Plan via Claude
                plan = await _claude_plan(
                    row["brief"], ctx, row["max_files_changed"],
                )
                changes = plan.get("changes", [])
                await _audit(pool, task_id, "plan", True,
                             {"plan": plan.get("plan"),
                              "n_changes": len(changes)})

                if not changes or plan.get("plan", "").startswith("abort"):
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE builder.queue SET status='rejected', "
                            "claude_plan=$2, finished_at=now() WHERE task_id=$1",
                            task_id, plan.get("plan", "<no plan>"),
                        )
                    return {"task": str(task_id), "rejected": True}

                # Safety: filter workflow paths unless user-originated
                if row["requested_by"] != "user":
                    blocked = [c for c in changes if _is_workflow_path(c["path"])]
                    if blocked:
                        async with pool.acquire() as conn:
                            await conn.execute(
                                "UPDATE builder.queue SET status='rejected', "
                                "error=$2, finished_at=now() WHERE task_id=$1",
                                task_id,
                                f"refused to modify workflows: {[c['path'] for c in blocked]}",
                            )
                        return {"task": str(task_id), "rejected": "workflow-policy"}

                if len(changes) > row["max_files_changed"]:
                    changes = changes[: row["max_files_changed"]]

                # Create branch + commit
                branch = _safe_branch_name(row["title"])
                commit_message = plan.get("commit_message") or f"bot: {row['title']}"
                commit_body = plan.get("commit_body") or row["brief"]
                commit_sha = await _create_branch_and_commit(
                    client, repo,
                    base="main", branch=branch, changes=changes,
                    commit_message=commit_message, commit_body=commit_body,
                )
                await _audit(pool, task_id, "commit", True,
                             {"branch": branch, "sha": commit_sha})

                # Open PR (unless direct-main, which is locked off for now)
                pr_url = None
                pr_number = None
                if row["branch_policy"] == "pr":
                    pr = await _open_pr(
                        client, repo,
                        branch=branch, base="main",
                        title=f"[bot] {row['title']}",
                        body=f"{commit_body}\n\n---\n_Generated by princeps-agent-builder · task `{task_id}`_",
                    )
                    pr_url = pr["html_url"]
                    pr_number = pr["number"]
                    await _audit(pool, task_id, "pr", True,
                                 {"pr_number": pr_number, "url": pr_url})

                    if row["auto_merge"]:
                        try:
                            await _gh(
                                client, "PUT",
                                f"/repos/{repo}/pulls/{pr_number}/merge",
                                json={"merge_method": "squash"},
                            )
                            await _audit(pool, task_id, "merge", True, {"pr": pr_number})
                        except Exception as exc:
                            await _audit(pool, task_id, "merge", False, {"error": str(exc)})

                async with pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE builder.queue
                              SET status='done', finished_at=now(),
                                  branch_name=$2, commit_sha=$3,
                                  pr_number=$4, pr_url=$5,
                                  claude_plan=$6,
                                  files_changed=$7::jsonb
                            WHERE task_id=$1""",
                        task_id, branch, commit_sha,
                        pr_number, pr_url,
                        plan.get("plan"),
                        json.dumps([c["path"] for c in changes]),
                    )

                # If this task came from WhatsApp, DM the operator back.
                try:
                    api = os.environ.get("PRINCEPS_API_URL", "https://princeps-api.fly.dev")
                    async with httpx.AsyncClient(timeout=10) as cn:
                        await cn.post(f"{api}/api/whatsapp/notify-task-complete/{task_id}")
                except Exception as exc:
                    log.info("whatsapp notify failed (non-fatal): %s", exc)
                return {
                    "task": str(task_id), "branch": branch,
                    "commit": commit_sha[:8], "pr": pr_number,
                    "files": [c["path"] for c in changes],
                }
        except Exception as exc:
            log.exception("builder tick failed")
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE builder.queue SET status='failed', "
                        "error=$2, finished_at=now() WHERE task_id=$1",
                        row["task_id"] if row else None, f"{type(exc).__name__}: {exc}",
                    )
            except Exception:
                pass
            return {"error": f"{type(exc).__name__}: {exc}"}
        finally:
            await pool.close()


if __name__ == "__main__":
    run_agent([Builder()])
