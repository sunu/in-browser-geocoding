"""Public API: parse(query), execute(dag), run(query)."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from geoparse.decisions.functions import Decider
from geoparse.execute.executor import Executor, Result
from geoparse.execute.geocoder import PhotonGeocoder
from geoparse.parse.pipeline import ParseResult, Parser


@lru_cache(maxsize=4)
def get_parser(provider: str | None = None) -> Parser:
    """provider: None uses the config file; "rules" or "jev" uses one provider for all decisions."""
    return Parser(Decider(default=provider), geocoder=PhotonGeocoder())


@lru_cache(maxsize=1)
def get_executor() -> Executor:
    return Executor()


class RunResult(BaseModel):
    parse: ParseResult
    result: Result | None = None


def parse(query: str, provider: str | None = None, view: list[float] | None = None) -> ParseResult:
    """view: map view (xmin, ymin, xmax, ymax) for the ranking of places. None: the configured bbox."""
    return get_parser(provider).parse(query, view=view)


def execute(dag: dict[str, Any], with_geometry: bool = True, view: list[float] | None = None) -> Result:
    return get_executor().execute(dag, with_geometry=with_geometry, view=view)


def run(query: str, provider: str | None = None, with_geometry: bool = True,
        view: list[float] | None = None) -> RunResult:
    p = parse(query, provider, view)
    if not p.ok or p.dag is None:
        return RunResult(parse=p)
    return RunResult(parse=p, result=execute(p.dag, with_geometry=with_geometry, view=view))
