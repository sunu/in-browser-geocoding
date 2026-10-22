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
        parts = question.id.split(".")
        for i in range(len(parts), 0, -1):
            key = ".".join(parts[:i])
            if key in self.rules:
                return self.rules[key]
        raise ProviderError(f"RulesProvider has no rule for decision '{question.id}'")

    def choose(self, text: State, question: Question, options: dict[str, str]) -> Decision[str]:
        return self._rule(question)(text, question, options)

    def predicate(self, text: State, question: Question) -> Decision[bool]:
        return self._rule(question)(text, question)

    def score(self, text: State, question: Question, scale: list[str]) -> Decision[float]:
        return self._rule(question)(text, question, scale)


class LocalClassifierProvider:
    """Local cross-encoder ("local Jev", plan-006). Scores each option; softmax with a calibrated temperature.

    The confidence uses the same formulas as Jev, so that the thresholds stay comparable.
    """

    name = "local"

    def __init__(self, model_dir: str | Path, device: str = "cpu", max_length: int = 128):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.dir = Path(model_dir)
        if not self.dir.exists():
            raise FileNotFoundError(f"local model not found: {self.dir}")
        self.tok = AutoTokenizer.from_pretrained(str(self.dir))
        self.model = AutoModelForSequenceClassification.from_pretrained(str(self.dir)).eval().to(device)
        self.device = device
        self.max_length = max_length
        calib = self.dir / "calibration.json"
        self.temps: dict[str, float] = json.loads(calib.read_text()) if calib.exists() else {}
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "LocalClassifierProvider":
        from geoparse.config import REPO_ROOT

        d = Path(os.environ.get("GEOPARSE_LOCAL_DIR") or cfg.get("model_dir", "models/local/current"))
        d = d if d.is_absolute() else REPO_ROOT / d
        return cls(d, device=cfg.get("device", "cpu"))

    def _temperature(self, decision: str) -> float:
        parts = decision.split(".")
        for i in range(len(parts), 0, -1):
            k = ".".join(parts[:i])
            if k in self.temps:
                return float(self.temps[k])
        return float(self.temps.get("default", 1.0))

    def probs(self, decision: str, instructions: str, state: Any, options: dict[str, str]) -> dict[str, float]:
        from geoparse.decisions.xenc_format import pair

        pairs = [pair(decision, instructions, state, k, v, i) for i, (k, v) in enumerate(options.items())]
        enc = self.tok([a for a, _ in pairs], [b for _, b in pairs], return_tensors="pt", padding=True,
                       truncation=True, max_length=self.max_length).to(self.device)
        with self._lock, self.torch.no_grad():
            logits = self.model(**enc).logits.squeeze(-1).float()
        p = self.torch.softmax(logits / self._temperature(decision), dim=0).tolist()
        return {k: round(float(v), 6) for k, v in zip(options, p)}

    def choose(self, text: State, question: Question, options: dict[str, str]) -> Decision[str]:
        t0 = time.time()
        state = _state(text)
        probs = self.probs(question.id, question.instructions, state, options)
        best = max(probs, key=probs.get)
        return Decision[str](value=best, confidence=choice_confidence(probs), impl=f"local:{self.dir.name}",
                             trace={"state": state, "probabilities": probs, "latency_s": round(time.time() - t0, 4)})

    def predicate(self, text: State, question: Question) -> Decision[bool]:
        t0 = time.time()
        state = _state(text)
        crit = question.context.get("criteria") or {"true": "Yes", "false": "No"}
        probs = self.probs(question.id, question.instructions, state, {"true": crit["true"], "false": crit["false"]})
        p = probs["true"]
        return Decision[bool](value=p >= 0.5, confidence=abs(2 * p - 1), impl=f"local:{self.dir.name}",
                              trace={"state": state, "p_yes": p, "latency_s": round(time.time() - t0, 4)})

    def score(self, text: State, question: Question, scale: list[str]) -> Decision[float]:
        d = self.choose(text, question, {str(i): s for i, s in enumerate(scale)})
        return Decision[float](value=float(d.value), confidence=d.confidence, impl=d.impl, trace=d.trace)
