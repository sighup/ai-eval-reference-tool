"""Running ``claude -p`` as a plain model, with none of Claude Code's own context.

Used by ``record.py --via claude`` (the support agent) and ``judge.py --via claude``.

Two things keep the model's input to what we send it:

* **An empty working directory**, so no ``CLAUDE.md`` or project settings are found.
* **A stripped environment.** Claude Code adds context from its environment: the
  date, memory, skills, attribution rules. Inside another Claude Code session
  (a coding agent running this script) that included a second "today", which
  made the support agent miscount days. Only what sign-in and the network need
  is passed through.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

#: Environment variables passed through to ``claude``. Everything else is dropped.
KEEP = {
    "HOME", "PATH", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TERM", "TMPDIR",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "COMSPEC", "PATHEXT",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_SESSION_INGRESS_TOKEN_FILE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
}
KEEP_PREFIXES = ("ANTHROPIC_",)


def clean_env() -> dict[str, str]:
    return {
        k: v for k, v in os.environ.items() if k in KEEP or k.startswith(KEEP_PREFIXES)
    }


def base_command(model: str, *, system: list[str]) -> list[str]:
    """``claude -p`` with its tools, settings, slash commands and history switched off."""
    return [
        shutil.which("claude") or "claude",
        "-p",
        *system,
        "--strict-mcp-config",
        "--setting-sources", "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--model", model,
    ]


def run(cmd: list[str], stdin: str, timeout: int = 600) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="claude-p-") as cwd:
        return subprocess.run(
            cmd, input=stdin, capture_output=True, text=True, cwd=cwd,
            env=clean_env(), timeout=timeout,
        )
