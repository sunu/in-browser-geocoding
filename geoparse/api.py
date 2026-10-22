"""Public API: parse(query), execute(dag), run(query)."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from geoparse.decisions.functions import Decider
from geoparse.execute.executor import Executor, Result
from geoparse.parse.pipeline import ParseResult, Parser


@lru_cache(maxsize=4)
def get_parser(provider: str | None = None) -> Parser:
    """provider: None uses the config file; "rules" or "jev" uses one provider for all decisions."""
    return Parser(Decider(default=provider))


@lru_cache(maxsize=1)
def get_executor() -> Executor:
    return Executor()


class RunResult(BaseModel):
    parse: ParseResult
    result: Result | None = None


def parse(query: str, provider: str | None = None) -> ParseResult:
    return get_parser(provider).parse(query)


def execute(dag: dict[str, Any], with_geometry: bool = True) -> Result:
    return get_executor().execute(dag, with_geometry=with_geometry)


def run(query: str, provider: str | None = None, with_geometry: bool = True) -> RunResult:
    p = parse(query, provider)
    if not p.ok or p.dag is None:
        return RunResult(parse=p)
    return RunResult(parse=p, result=execute(p.dag, with_geometry=with_geometry))
