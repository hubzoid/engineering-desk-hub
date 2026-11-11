"""Engineering Desk's commit hook: a secret check on staged changes only.
Gitleaks, a few seconds, no model call. It stops a key before it leaves the
laptop. Opt in per repo with install.py beside this file.

Exit 10 stops the commit when Gitleaks finds a secret (the hook turns it into
1). When Gitleaks or the Desk's own code cannot run (offline on first use, no
build for this machine, the Desk moved), the commit goes ahead and the hook
says the check was skipped: a missing tool never blocks work.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parents[2]
BLOCKED = 10


def scanners():
    path = HUB / "workflows" / "engineering_desk" / "lib" / "scanners.py"
    name = "engineering_desk_hook_scanners"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclasses look the module up while it loads
        spec.loader.exec_module(module)
    return sys.modules[name]


def main() -> int:
    try:
        tool = scanners().find("gitleaks")
    except Exception as exc:  # noqa: BLE001 - the Desk's code moved or broke: never block a commit for it
        print(f"Engineering Desk: secret check skipped (could not load the Desk's scanners: "
              f"{type(exc).__name__}: {str(exc)[:160]}).", file=sys.stderr)
        return 0
    if not tool.ready:
        print(f"Engineering Desk: secret check skipped ({tool.note}).", file=sys.stderr)
        return 0
    proc = subprocess.run([tool.path, "git", "--pre-commit", "--staged", "--redact", "--no-banner", "--exit-code", "1",
                           "--log-level", "warn", "--verbose", "."], capture_output=True, text=True)
    if proc.returncode == 0:
        return 0
    if proc.returncode == 1:
        print(proc.stdout + proc.stderr, file=sys.stderr)
        print("Engineering Desk stopped this commit: the staged changes contain what looks like a secret "
              "(shown redacted above). Remove it and load it from the environment instead. If it is not a "
              "real secret, commit with --no-verify, or add a `gitleaks:allow` comment on that line.",
              file=sys.stderr)
        return BLOCKED
    print(f"Engineering Desk: secret check could not run (gitleaks exit {proc.returncode}): "
          f"{(proc.stderr.strip().splitlines() or [''])[-1][:200]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
