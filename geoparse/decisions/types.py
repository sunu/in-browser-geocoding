"""Decision types. All types serialize to JSON."""
from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Decision(BaseModel, Generic[T]):
    value: T
    confidence: float
    impl: str  # "jev", "rules-v1", "deterministic", "bert-v1"
    trace: dict[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    text: str
    start: int
    end: int
    label: str  # location, landmark, street, facility type, distance, number
    score: float = 1.0
    value: float | None = None  # meters for a distance, the number for a number


class Split(BaseModel):
    """The text of each open slot (and of each closed-slot group) for one template."""

    parts: dict[str, str]


class Candidate(BaseModel):
    id: str
    name: str
    source: Literal["overture", "photon"]
    subtype: str | None = None
    description: str = ""  # text that the decision model sees
    score: float = 0.0  # ranking score from the gazetteer


class Question(BaseModel):
    """A typed question for a DecisionProvider.

    `id` is the decision name. Rule-based providers dispatch on it.
    `context` holds structured inputs that rule-based providers can use. Model providers ignore it.
    """

    id: str
    instructions: str
    context: dict[str, Any] = Field(default_factory=dict)
