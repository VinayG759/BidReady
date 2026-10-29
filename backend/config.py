"""Load the project's .env before any module reads its settings."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Minimal .env reader (KEY=VALUE lines). Non-empty values in the project's .env win over the shell;
    on Vercel there is no .env (see .vercelignore) and the dashboard's variables are used."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:
            os.environ[k.strip()] = v


_load_env_file(ROOT / ".env")
MODE = os.environ.get("BIDREADY_MODE", "live")
