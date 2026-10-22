"""Geocoder protocol and the Photon implementation.

Photon usage policy: fair use only. The client identifies itself with GEOPARSE_USER_AGENT,
sends at most one request per `min_interval_s`, and caches every response on disk.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from geoparse.config import REPO_ROOT, load_config


class GeoFeature(BaseModel):
    id: str  # "osm:N123"
    name: str
    lon: float
    lat: float
    osm_key: str | None = None
    osm_value: str | None = None
    kind: str | None = None  # Photon "type": house, street, locality, city, state, ...
    extent: list[float] | None = None  # [minlon, maxlat, maxlon, minlat] as Photon sends it
    label: str = ""  # name with its address context, for the decision model
    props: dict[str, Any] = {}


class Geocoder(Protocol):
    name: str

    def search(self, q: str, *, limit: int = 5, bbox: tuple[float, float, float, float] | None = None,
               osm_tag: str | None = None) -> list[GeoFeature]: ...


class GeocoderError(RuntimeError):
    pass


def _label(p: dict[str, Any]) -> str:
    parts = [p.get("name")]
    for k in ("street", "locality", "district", "city", "county", "state"):
        v = p.get(k)
        if v and v not in parts:
            parts.append(v)
    return ", ".join(x for x in parts if x)


class PhotonGeocoder:
    """Photon client. mode: live, cached (cache first, then network), replay (cache only)."""

    name = "photon"
    _lock = threading.Lock()
    _last = 0.0

    def __init__(self, url: str | None = None, cache_dir: str | Path | None = None, mode: str = "cached",
                 user_agent: str | None = None, min_interval_s: float | None = None):
        cfg = load_config()["geocoder"]
        self.url = url or cfg["photon_url"]
        d = Path(cache_dir or cfg["cache_dir"])
        self.cache_dir = d if d.is_absolute() else REPO_ROOT / d
        self.mode = mode
        self.user_agent = user_agent or os.environ.get("GEOPARSE_USER_AGENT") or "geoparse/0.1 (experimental)"
        self.min_interval_s = cfg["min_interval_s"] if min_interval_s is None else min_interval_s
        self._client = httpx.Client(timeout=20, headers={"User-Agent": self.user_agent})

    def _cache_file(self, params: dict[str, Any]) -> Path:
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:24]
        return self.cache_dir / f"{key}.json"

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        f = self._cache_file(params)
        if self.mode in ("cached", "replay") and f.exists():
            return json.loads(f.read_text())["response"]
        if self.mode == "replay":
            raise GeocoderError(f"Photon replay cache miss: {params}")
        with PhotonGeocoder._lock:
            wait = PhotonGeocoder._last + self.min_interval_s - time.time()
            if wait > 0:
                time.sleep(wait)
            r = self._client.get(self.url, params=params)
            PhotonGeocoder._last = time.time()
        if r.status_code != 200:
            raise GeocoderError(f"Photon HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"params": params, "response": data}))
        return data

    def search(self, q: str, *, limit: int = 5, bbox: tuple[float, float, float, float] | None = None,
               osm_tag: str | None = None) -> list[GeoFeature]:
        params: dict[str, Any] = {"q": q, "limit": limit, "lang": "en"}
        if bbox:
            params["bbox"] = ",".join(f"{v:.5f}" for v in bbox)
        if osm_tag:
            params["osm_tag"] = osm_tag
        data = self._get(params)
        out = []
        for feat in data.get("features", []):
            p = feat["properties"]
            lon, lat = feat["geometry"]["coordinates"][:2]
            out.append(GeoFeature(
                id=f"osm:{p.get('osm_type', '?')}{p.get('osm_id', '')}",
                name=p.get("name") or p.get("street") or q,
                lon=lon, lat=lat,
                osm_key=p.get("osm_key"), osm_value=p.get("osm_value"), kind=p.get("type"),
                extent=p.get("extent"), label=_label(p), props=p,
            ))
        return out
