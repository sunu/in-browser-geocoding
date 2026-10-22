"""Decision providers.

A provider answers three question shapes: choose (one of several options), predicate (yes or no),
and score (position on an ordered scale). Options are a dict of option key to description.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

import httpx

from geoparse.decisions.types import Decision, Question

State = str | dict[str, Any]


@runtime_checkable
class DecisionProvider(Protocol):
    name: str

    def choose(self, text: State, question: Question, options: dict[str, str]) -> Decision[str]: ...

    def predicate(self, text: State, question: Question) -> Decision[bool]: ...

    def score(self, text: State, question: Question, scale: list[str]) -> Decision[float]: ...


def _state(text: State) -> dict[str, Any]:
    return text if isinstance(text, dict) else {"text": text}


def choice_confidence(probs: dict[str, float]) -> float:
    """TypeSafe Choice formula: (p_max - 1/n) / (1 - 1/n)."""
    n = len(probs)
    if n < 2:
        return 1.0
    return (max(probs.values()) - 1 / n) / (1 - 1 / n)


class ProviderError(RuntimeError):
    pass


class JevProvider:
    """TypeSafe Jev through the OpenRouter Decisions API.

    mode:
      live    call the API
      record  call the API and save each response in the cache file
      replay  read responses from the cache file only; a cache miss is an error
      cached  read from the cache file; on a miss call the API and save the response
    """

    name = "jev"

    def __init__(
        self,
        model: str = "typesafe/jev-1.13",
        url: str = "https://openrouter.ai/api/alpha/decisions",
        api_key: str | None = None,
        timeout_s: float = 30.0,
        mode: str = "live",
        cache_path: str | Path | None = None,
    ):
        self.model = model
        self.url = url
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.mode = mode
        self.cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, Any] = {}
        self._lock = threading.Lock()
        if self.cache_path and self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._cache[rec["key"]] = rec["response"]
        self._client = httpx.Client(timeout=timeout_s)

    @staticmethod
    def _key(body: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:32]

    def ask(self, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Send one request with several questions. Returns (answers, meta)."""
        body = {"model": self.model, "state": state, "questions": questions}
        key = self._key(body)
        if self.mode in ("replay", "cached") and key in self._cache:
            data = self._cache[key]
            return data["answers"], {"cached": True, "latency_s": 0.0, "cost": 0.0, "model": data.get("model")}
        if self.mode == "replay":
            raise ProviderError(f"Jev replay cache miss for key {key}: {json.dumps(questions)[:200]}")
        if not self.api_key:
            raise ProviderError("OPENROUTER_API_KEY is not set")
        t0 = time.time()
        r = None
        for attempt in range(4):
            try:
                r = self._client.post(self.url, headers={"Authorization": f"Bearer {self.api_key}"}, json=body)
            except httpx.TransportError as e:
                if attempt == 3:
                    raise ProviderError(f"Jev network error: {e}") from e
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        dt = time.time() - t0
        if r.status_code != 200:
            raise ProviderError(f"Jev HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        if self.mode in ("record", "cached") and self.cache_path:
            with self._lock:
                self._cache[key] = data
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                with self.cache_path.open("a") as f:
                    f.write(json.dumps({"key": key, "response": data}) + "\n")
        meta = {"cached": False, "latency_s": round(dt, 3), "cost": data.get("usage", {}).get("cost"), "model": data.get("model")}
        return data["answers"], meta

    # Single-question helpers. The orchestrator can also send many questions with ask().

    @staticmethod
    def choice_question(question: Question, options: dict[str, str]) -> dict[str, Any]:
        return {"type": "choice", "instructions": question.instructions, "criteria": options}

    @staticmethod
    def noul_question(question: Question) -> dict[str, Any]:
        q: dict[str, Any] = {"type": "noul", "instructions": question.instructions}
        crit = question.context.get("criteria")
        if crit:
            q["criteria"] = crit
        return q

    @staticmethod
    def parse_choice(ans: dict[str, Any], options: dict[str, str], meta: dict[str, Any], state: dict[str, Any]) -> Decision[str]:
        return Decision[str](
            value=ans["choice"],
            confidence=float(ans.get("confidence", choice_confidence(ans["probabilities"]))),
            impl="jev",
            trace={"state": state, "options": list(options), "probabilities": ans["probabilities"], **meta},
        )

    @staticmethod
    def parse_noul(ans: dict[str, Any], meta: dict[str, Any], state: dict[str, Any]) -> Decision[bool]:
        p = float(ans["noul"])
        return Decision[bool](
            value=p >= 0.5, confidence=abs(2 * p - 1), impl="jev", trace={"state": state, "p_yes": p, **meta}
        )

    def choose(self, text: State, question: Question, options: dict[str, str]) -> Decision[str]:
        state = _state(text)
        answers, meta = self.ask(state, {"q": self.choice_question(question, options)})
        return self.parse_choice(answers["q"], options, meta, state)

    def predicate(self, text: State, question: Question) -> Decision[bool]:
        state = _state(text)
        answers, meta = self.ask(state, {"q": self.noul_question(question)})
        return self.parse_noul(answers["q"], meta, state)

    def score(self, text: State, question: Question, scale: list[str]) -> Decision[float]:
        state = _state(text)
        answers, meta = self.ask(state, {"q": {"type": "score", "instructions": question.instructions, "criteria": scale}})
        a = answers["q"]
        return Decision[float](value=float(a["score"]), confidence=float(a["confidence"]), impl="jev",
                               trace={"state": state, "probabilities": a["probabilities"], **meta})


RuleFn = Callable[..., Decision]


class RulesProvider:
    """Rule-based provider for tests and offline use.

    Rules are registered per decision name (Question.id). A choose rule gets (text, question, options),
    a predicate rule gets (text, question), and a score rule gets (text, question, scale).
    """

    name = "rules"

    def __init__(self, rules: dict[str, RuleFn] | None = None):
        if rules is None:
            from geoparse.decisions.rules import DEFAULT_RULES

            rules = DEFAULT_RULES
        self.rules = rules

    def _rule(self, question: Question) -> RuleFn:
        if question.id not in self.rules:
            raise ProviderError(f"RulesProvider has no rule for decision '{question.id}'")
        return self.rules[question.id]

    def choose(self, text: State, question: Question, options: dict[str, str]) -> Decision[str]:
        return self._rule(question)(text, question, options)

    def predicate(self, text: State, question: Question) -> Decision[bool]:
        return self._rule(question)(text, question)

    def score(self, text: State, question: Question, scale: list[str]) -> Decision[float]:
        return self._rule(question)(text, question, scale)


class LocalClassifierProvider:
    """Stub for a later local ONNX classifier trained from the decision logs."""

    name = "local"

    def __init__(self, model_dir: str | Path | None = None):
        self.model_dir = model_dir

    def choose(self, text: State, question: Question, options: dict[str, str]) -> Decision[str]:
        raise NotImplementedError("LocalClassifierProvider is a stub. Train a model from the decision logs first.")

    def predicate(self, text: State, question: Question) -> Decision[bool]:
        raise NotImplementedError("LocalClassifierProvider is a stub.")

    def score(self, text: State, question: Question, scale: list[str]) -> Decision[float]:
        raise NotImplementedError("LocalClassifierProvider is a stub.")
