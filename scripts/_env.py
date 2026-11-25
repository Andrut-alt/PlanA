"""Tiny helper for local scripts: load KEY=VALUE pairs from .env and put src/ on sys.path."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def require(*names):
    load_env()
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)} (put them in .env, see .env.example)")
    return [os.environ[n] for n in names]
