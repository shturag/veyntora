"""Documentation in Git repositories on GitHub or GitLab (cloud or self-hosted).

- One branch per repository (its default branch unless one is chosen) is read through
  the provider's API: no clone, no git binary. The file tree lists every file with its
  blob id, which tells changed files apart.
- Only documents are read: Markdown (also .mdx), reStructuredText and AsciiDoc (as
  text), plain text, HTML, PDF and Office files. Code is left out.
- Who may read: the source's readers and folder rules ("owner/repo/docs/…"); repository
  permissions are not mapped. The token needs read access to the repositories' contents
  (GitHub: a fine-grained token with "Contents: read"; GitLab: read_api or
  read_repository).
"""

from __future__ import annotations

import posixpath
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx
from veyntora_api.knowledge.connectors import GitSettings

from veyntora_workers.connectors.listing import Entry, Listing

_MAX_FILES = 20_000
# Read as: the extension the indexer knows them by.
DOCUMENTS = {
    ".md": ".md",
    ".markdown": ".md",
    ".mdx": ".md",
    ".rst": ".txt",
    ".adoc": ".txt",
    ".asciidoc": ".txt",
    ".txt": ".txt",
    ".html": ".html",
    ".htm": ".html",
    ".pdf": ".pdf",
    ".docx": ".docx",
    ".pptx": ".pptx",
    ".xlsx": ".xlsx",
    ".csv": ".csv",
}


def document_name(path: str) -> str | None:
    """The file's name with the extension it is indexed as, or None for non-documents."""
    name = posixpath.basename(path)
    stem, ext = posixpath.splitext(name)
    as_ext = DOCUMENTS.get(ext.lower())
    if as_ext is None:
        return None
    return name if as_ext == ext.lower() else f"{name}{as_ext}" if stem else None


class GitReader:
    def __init__(
        self,
        cfg: GitSettings,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cfg = cfg
        if cfg.provider == "github":
            self.api = (cfg.base_url or "https://api.github.com").rstrip("/")
            self.web = (
                "https://github.com"
                if not cfg.base_url
                else self.api.removesuffix("/api/v3").removesuffix("/api")
            )
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        else:
            self.web = (cfg.base_url or "https://gitlab.com").rstrip("/")
            self.api = f"{self.web}/api/v4"
            headers = {"PRIVATE-TOKEN": token}
        self.http = httpx.AsyncClient(timeout=60, headers=headers, transport=transport)
        self.listed_all = False
        # (repository, blob id) of each listed file, for the download.
        self._blobs: dict[str, tuple[str, str]] = {}

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, url: str, **params: Any) -> httpx.Response:
        res = await self.http.get(url, params=params or None)
        res.raise_for_status()
        return res

    def _project(self, repo: str) -> str:
        return f"{self.api}/projects/{quote(repo, safe='')}"

    async def _branch(self, repo: str) -> str:
        if self.cfg.branch:
            return self.cfg.branch
        url = f"{self.api}/repos/{repo}" if self.cfg.provider == "github" else self._project(repo)
        return str((await self._get(url)).json()["default_branch"])

    async def check(self) -> str:
        repo = self.cfg.repositories[0]
        return f"Repository {repo} is readable (branch {await self._branch(repo)})."

    async def _tree(self, repo: str, branch: str) -> tuple[list[tuple[str, str, int | None]], bool]:
        """(path, blob id, size) of every file, and whether the list is complete."""
        if self.cfg.provider == "github":
            data = (
                await self._get(
                    f"{self.api}/repos/{repo}/git/trees/{quote(branch, safe='')}", recursive="1"
                )
            ).json()
            files = [
                (str(t["path"]), str(t["sha"]), t.get("size"))
                for t in data.get("tree") or []
                if t.get("type") == "blob"
            ]
            return files, not data.get("truncated")
        files = []
        url: str | None = f"{self._project(repo)}/repository/tree"
        params: dict[str, Any] = {
            "recursive": "true",
            "ref": branch,
            "per_page": 100,
            "pagination": "keyset",
        }
        while url:
            res = await self._get(url, **params)
            files += [
                (str(t["path"]), str(t["id"]), None) for t in res.json() if t.get("type") == "blob"
            ]
            nxt = res.links.get("next")
            url, params = (nxt["url"], {}) if nxt else (None, {})
        return files, True

    def _included(self, path: str) -> bool:
        if not self.cfg.include_paths:
            return True
        lowered = path.lower()
        return any(lowered.startswith(p.lower() + "/") for p in self.cfg.include_paths)

    def _url(self, repo: str, branch: str, path: str) -> str:
        sep = "/-/blob/" if self.cfg.provider == "gitlab" else "/blob/"
        return f"{self.web}/{repo}{sep}{quote(branch)}/{quote(path)}"

    async def entries(self) -> AsyncIterator[Entry]:
        complete = True
        count = 0
        for repo in self.cfg.repositories:
            branch = await self._branch(repo)
            files, listed = await self._tree(repo, branch)
            complete = complete and listed
            for path, blob, size in files:
                name = document_name(path)
                if name is None or not self._included(path):
                    continue
                count += 1
                if count > _MAX_FILES:
                    return
                key = f"{repo}:{path}"
                self._blobs[key] = (repo, blob)
                yield Entry(
                    external_id=key,
                    path=f"{repo}/{path}",
                    name=name,
                    url=self._url(repo, branch, path),
                    version=blob,
                    size=int(size) if isinstance(size, int) else None,
                    modified=None,
                )
        self.listed_all = complete

    async def download(self, entry: Entry) -> bytes:
        repo, blob = self._blobs[entry.external_id]
        if self.cfg.provider == "github":
            res = await self.http.get(
                f"{self.api}/repos/{repo}/git/blobs/{blob}",
                headers={"Accept": "application/vnd.github.raw+json"},
            )
        else:
            res = await self.http.get(f"{self._project(repo)}/repository/blobs/{blob}/raw")
        res.raise_for_status()
        return res.content

    def listing(self) -> Listing:
        return Listing(
            entries=self.entries(), download=self.download, complete=lambda: self.listed_all
        )
