"""Code in local folders, for `source: local`: the same calls as
`github.GitHub` that checks, profiles, the audit and chat make, read from
git working copies on this machine. No token, no network.

Only what git tracks at the current commit is read (`git archive HEAD`), so
ignored files such as `.env` never fill a result and uncommitted edits wait
for their commit. There are no pull requests: PR reviews and reports need
GitHub. Nothing is ever written to the folder.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .github import GitHubError

MAX_FILE_CHARS = 200_000
STATUS = {"A": "added", "D": "removed", "M": "modified", "R": "renamed", "C": "added", "T": "modified"}


class LocalError(GitHubError):
    """A folder that is missing or not a git working copy. A GitHubError, so
    every caller reports it the way it reports an unreadable repo."""


class LocalRepos:
    name = "local"
    dry_run = True

    def __init__(self, folders: dict[str, str | Path]):
        self.folders = {repo: Path(path).expanduser() for repo, path in folders.items()}
        self.outbox: list[dict] = []  # never written to: there is nothing to post to

    # --------------------------------------------------------------- plumbing

    def folder(self, repo: str) -> Path:
        if repo not in self.folders:
            raise LocalError(f"{repo} has no folder in workflows/settings.yaml (path:)")
        path = self.folders[repo]
        if not path.is_dir():
            raise LocalError(f"{repo}: the folder {path} does not exist")
        return path

    def _git(self, repo: str, *args: str, text: bool = True, check: bool = True):
        try:
            # The folder's own git config can name programs to run (fsmonitor, external
            # diff tools); these read-only calls turn them off.
            proc = subprocess.run(["git", "-C", str(self.folder(repo)), "-c", "core.fsmonitor=false",
                                   "-c", "diff.external=", *args], capture_output=True, text=text, timeout=300,
                                  env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        except FileNotFoundError:
            raise LocalError("git is not installed: Engineering Desk reads local folders with git") from None
        except subprocess.TimeoutExpired:
            raise LocalError(f"{repo}: git {args[0]} took over 300 s") from None
        if check and proc.returncode != 0:
            err = proc.stderr if text else proc.stderr.decode(errors="replace")
            if "not a git repository" in err:
                raise LocalError(f"{repo}: {self.folders[repo]} is not a git working copy; "
                                 "Engineering Desk reads what git tracks there") from None
            raise LocalError(f"{repo}: git {args[0]} failed: {err.strip()[:200]}") from None
        return proc

    # ------------------------------------------------------------------ reads

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def login(self) -> str:
        return "local"

    def default_branch(self, repo: str) -> str:
        """The branch the folder is on, or HEAD when it is detached."""
        out = self._git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
        return out or "HEAD"

    def branch_sha(self, repo: str, branch: str) -> str:
        proc = self._git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
        if "not a git repository" in proc.stderr:
            self._git(repo, "rev-parse", "HEAD")  # raises the "not a git working copy" error
        sha = proc.stdout.strip()
        if not sha:
            raise LocalError(f"{repo}: the folder has no commit yet; commit the code to check it")
        return sha

    def tarball(self, repo: str, ref: str, max_bytes: int = 300_000_000) -> bytes:
        """The tracked files at `ref`, as GitHub's tarball has them: one top folder."""
        data = self._git(repo, "archive", "--format=tar.gz", f"--prefix={Path(repo).name}/", ref, text=False).stdout
        if len(data) > max_bytes:
            raise LocalError(f"{repo} is larger than {max_bytes // 1_000_000} MB; not checked out")
        return data

    def file(self, repo: str, path: str, ref: str | None = None) -> str | None:
        proc = self._git(repo, "show", f"{ref or 'HEAD'}:{path}", check=False)
        return proc.stdout[:MAX_FILE_CHARS] if proc.returncode == 0 else None

    def compare_files(self, repo: str, base: str, head: str) -> list[dict] | None:
        """Files changed from `base` to `head`, or None when `base` is no longer
        an ancestor (history rewritten)."""
        if self._git(repo, "merge-base", "--is-ancestor", base, head, check=False).returncode != 0:
            return None
        out = []
        for line in self._git(repo, "diff", "--no-ext-diff", "--no-textconv", "--name-status", "-M", base,
                              head).stdout.splitlines():
            parts = line.split("\t")
            kind = STATUS.get(parts[0][:1], "modified")
            out.append({"filename": parts[-1], "status": kind, "additions": 0, "deletions": 0, "patch": None,
                        "previous_filename": parts[1] if kind == "renamed" and len(parts) > 2 else None})
        return out

    def commits(self, repo: str, path: str | None = None, since: datetime | None = None, limit: int = 30) -> list[dict]:
        args = ["log", f"-{limit}", "--format=%H%x1f%an%x1f%aI%x1f%s"]
        if since:
            args.append(f"--since={since.isoformat()}")
        if path:
            args += ["--", path]
        rows = []
        for line in self._git(repo, *args).stdout.splitlines():
            sha, author, date, message = (line.split("\x1f") + ["", "", "", ""])[:4]
            rows.append({"sha": sha, "message": message[:500], "author": author, "date": date})
        return rows

    def open_pulls(self, repo: str) -> list[dict]:
        self.folder(repo)
        return []

    def ci_status(self, repo: str, sha: str) -> str:
        return "none: a local folder has no CI"
