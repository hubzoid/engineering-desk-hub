"""Turn on Engineering Desk's secret check on commit for one repo (opt-in).

    python client/hooks/install.py ~/code/ios-app            # turn it on
    python client/hooks/install.py ~/code/ios-app --remove   # turn it off

It writes the repo's pre-commit hook, which runs secret_check.py with this
hub's Python. An existing pre-commit hook that is not Engineering Desk's is
never replaced: the installer says how to call the check from it instead.
"""
from __future__ import annotations

import argparse
import stat
import subprocess
import sys
from pathlib import Path

MARKER = "# Engineering Desk secret check"
CHECK = Path(__file__).resolve().with_name("secret_check.py")


def hook_path(repo: Path) -> Path:
    """The pre-commit hook git will run, honouring core.hooksPath."""
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks/pre-commit"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"{repo} is not a git working copy.")
    path = Path(out.stdout.strip())
    return path if path.is_absolute() else repo / path


BLOCKED = 10  # secret_check.py's exit code for a secret found; anything else never blocks


def script() -> str:
    """The hook. A missing Desk (moved, deleted, its .venv rebuilt) or a check
    that cannot run lets the commit through with a note: only a secret found
    (exit 10) stops it."""
    off = f"python {Path(__file__).resolve()} <repo> --remove"
    return f"""#!/bin/sh
{MARKER} (opt-in). Turn it off: {off}
PY="{sys.executable}"
CHECK="{CHECK}"
if [ ! -x "$PY" ] || [ ! -f "$CHECK" ]; then
  echo "Engineering Desk: secret check skipped (Desk not found at $CHECK or its Python at $PY). Turn it off: {off}" >&2
  exit 0
fi
"$PY" "$CHECK"
status=$?
if [ "$status" -eq {BLOCKED} ]; then
  exit 1
fi
if [ "$status" -ne 0 ]; then
  echo "Engineering Desk: secret check skipped (it could not run, exit $status)." >&2
fi
exit 0
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Engineering Desk's secret check on commit, for one repo.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--remove", action="store_true", help="turn the check off")
    args = parser.parse_args(argv)
    hook = hook_path(args.repo.expanduser().resolve())
    ours = hook.is_file() and MARKER in hook.read_text(errors="replace")
    if args.remove:
        if ours:
            hook.unlink()
            print(f"Removed the secret check from {hook}.")
        else:
            print("No Engineering Desk secret check to remove.")
        return 0
    if hook.exists() and not ours:
        print(f"{hook} already exists and is not Engineering Desk's; it was left as it is.\n"
              f"To add the check, put this line in it:\n"
              f"  \"{sys.executable}\" \"{CHECK}\"; [ $? -ne {BLOCKED} ] || exit 1")
        return 1
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(script())
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Secret check on: each commit in {args.repo} is checked by Gitleaks first ({hook}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
