"""GitHub intelligence: a factual, read-only summary of a repository (PRs, issues, CI).

Uses GITHUB_TOKEN from the server environment; the token never reaches a client.
The summary is built from the API data directly (no AI), so nothing is invented.
"""
from __future__ import annotations

import re

import httpx

from app.config import Settings
from app.errors import ConfigurationError, NotFoundError, ProviderError, ValidationFailed
from app.services.http import shared_client

API = "https://api.github.com"
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.settings.github_token)

    def resolve_repo(self, repo: str | None) -> str:
        repo = (repo or self.settings.github_default_repo or "").strip().removeprefix("https://github.com/").strip("/")
        if not repo:
            raise ValidationFailed("Say which repository (owner/name), or set GITHUB_DEFAULT_REPO on the server.")
        if not _REPO.match(repo):
            raise ValidationFailed(f"'{repo}' is not an owner/name repository")
        return repo

    async def _get(self, path: str, **params: str) -> object:
        if not self.configured:
            raise ConfigurationError("GitHub isn't connected. Add GITHUB_TOKEN on the server (read-only is enough).")
        client = self._client or shared_client()
        r = await client.get(API + path, params=params, timeout=15,
                             headers={"Authorization": f"Bearer {self.settings.github_token}",
                                      "Accept": "application/vnd.github+json",
                                      "X-GitHub-Api-Version": "2022-11-28"})
        if r.status_code == 404:
            raise NotFoundError("Repository not found, or the token can't see it")
        if r.status_code in (401, 403):
            raise ProviderError(f"GitHub refused the request ({r.status_code}). Check the token's access.",
                                code="provider_auth")
        if r.status_code >= 400:
            raise ProviderError(f"GitHub error {r.status_code}")
        return r.json()

    async def summary(self, repo: str | None) -> str:
        if not self.configured:
            raise ConfigurationError("GitHub isn't connected. Add GITHUB_TOKEN on the server (read-only is enough).")
        repo = self.resolve_repo(repo)
        info = await self._get(f"/repos/{repo}")
        pulls = await self._get(f"/repos/{repo}/pulls", state="open", per_page="10")
        runs = await self._get(f"/repos/{repo}/actions/runs", per_page="10")
        issues = await self._get(f"/repos/{repo}/issues", state="open", per_page="10")
        real_issues = [i for i in issues if "pull_request" not in i]  # type: ignore[union-attr]
        lines = [f"{repo}: {info.get('open_issues_count', 0)} open issues and pull requests, "  # type: ignore[union-attr]
                 f"default branch {info.get('default_branch')}."]  # type: ignore[union-attr]
        if pulls:
            lines.append(f"Open pull requests ({len(pulls)}{'+' if len(pulls) == 10 else ''}): " +  # type: ignore[arg-type]
                         "; ".join(f"#{p['number']} {p['title']}" for p in pulls[:5]))  # type: ignore[index]
        else:
            lines.append("No open pull requests.")
        wf = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
        failed = [r for r in wf if r.get("conclusion") == "failure"]
        if wf:
            latest = wf[0]
            lines.append(f"Latest CI run: {latest.get('name')} on {latest.get('head_branch')} - "
                         f"{latest.get('conclusion') or latest.get('status')}.")
        if failed:
            lines.append("Recent failures: " + "; ".join(f"{r.get('name')} on {r.get('head_branch')}"
                                                        for r in failed[:3]))
        if real_issues:
            lines.append("Newest issues: " + "; ".join(f"#{i['number']} {i['title']}" for i in real_issues[:3]))
        return "\n".join(lines)
