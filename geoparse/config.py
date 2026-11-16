"""Load the configuration file and the .env file."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
DEFAULT_CONFIG = PACKAGE_DIR / "data" / "config.yaml"

load_dotenv(REPO_ROOT / ".env")


@lru_cache(maxsize=None)
def load_config(path: str | None = None) -> dict[str, Any]:
    p = Path(path or os.environ.get("GEOPARSE_CONFIG", DEFAULT_CONFIG))
    with p.open() as f:
        return yaml.safe_load(f)


def scope(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or load_config()
    s = os.environ.get("GEOPARSE_SCOPE", cfg["data"].get("scope", "country"))
    if s not in ("country", "world"):
        raise ValueError(f"unknown scope: {s}")
    return s


def build_dir(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    default = cfg["data"]["world_build_dir"] if scope(cfg) == "world" else cfg["data"]["build_dir"]
    d = Path(os.environ.get("GEOPARSE_DATA_DIR", default))
    return d if d.is_absolute() else REPO_ROOT / d


def policy() -> dict[str, Any]:
    return load_config()["policy"]
