"""Decision functions. Each function has a fixed signature and calls the provider configured for it.

If a decision has only one option, the function returns it with impl "deterministic" and does not
call the provider. Every decision goes to the trace and to the JSONL log.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from geoparse.config import load_config
from geoparse.decisions.log import DecisionLogger
from geoparse.decisions.providers import DecisionProvider, JevProvider, LocalClassifierProvider, RulesProvider
from geoparse.decisions.types import Candidate, Decision, Question, Span, Split
from geoparse.options import option_descriptions

# Instructions for the decision model. Write them literally: the model reads them at face value.
INSTRUCTIONS = {
    "pick_family": "What type of result does the query ask for? Choose by the outermost operation of the query, "
                   "that is, the type of the final result, not by the places mentioned inside the query.",
    "pick_template": "Which description matches the final result that the query asks for?",
    "pick_template_flat": "Which description matches the final result that the query asks for?",
    "pick_split": "The query has the form given in 'template'. Which option splits the query into its parts correctly?",
    "is_subquery": "Does the text describe a set of places by a rule or a relation, instead of giving the name of one place?",
    "select_source": "Is the text the name of an administrative area, or the name of something else such as a street, "
                     "an address, a building, a landmark, a business, or a station?",
    "bind_anchor": "Which option is the name of the place that the text is about? Other words in the text only give its location.",
    "disambiguate": "Which place does the query mean by the name in 'name'?",
    "fill_closed_slot.admin_level": "Which level of administrative division does the text name?",
    "fill_closed_slot.predicate": "Which property of places does the text name?",
    "fill_closed_slot.direction": "Which direction does the text name?",
    "fill_closed_slot.category.group": "Which group of places does the text name?",
    "fill_closed_slot.category": "Which type of place does the text name?",
    "fill_closed_slot.attr": "Which measured quantity of places does the text name?",
    "fill_closed_slot.op": "Which comparison does the text name?",
}

IS_SUBQUERY_CRITERIA = {
    "true": "The text describes places by a property, a level, a distance, or a relation, or it lists more than "
            "one place, for example 'coastal districts of Odisha', 'states that border Nepal', '10 km around "
            "Whitefield', or 'Kolkata and Howrah'.",
    "false": "The text is the name of one place, with or without its city or state, for example 'Odisha', "
             "'Bengaluru Urban', 'MG Road, Bangalore', or 'Gateway of India'.",
}

NONE_OPTION = "The text does not name any of the other options"

SOURCE_OPTIONS = {
    "overture": "An administrative area: a country, state, district, city, town, village, or neighbourhood",
    "photon": "Something else: a street, a road, an address, a building, a landmark, a monument, a business, "
              "a station, a park, or a point of interest",
}


class Decider:
    """Holds the provider for each decision, thresholds, the logger, and the trace of one parse."""

    def __init__(self, providers: dict[str, DecisionProvider] | None = None, default: str | None = None,
                 logger: DecisionLogger | None = None, config: dict[str, Any] | None = None,
                 use_ner: bool = True, jev_mode: str = "live", jev_cache: str | None = None):
        cfg = config or load_config()
        dcfg = cfg["decisions"]
        self.thresholds: dict[str, float] = dcfg["thresholds"]
        self.logger = logger or DecisionLogger()
        self.use_ner = use_ner
        # Provider names for each decision key, from the config. `default` replaces all of them.
        self._names: dict[str, str] = {k: (default or v) for k, v in dcfg["providers"].items()}
        self._impls: dict[str, DecisionProvider] = {}
        self._overrides: dict[str, DecisionProvider] = dict(providers or {})
        self._make_args = {"dcfg": dcfg, "jev_mode": jev_mode, "jev_cache": jev_cache}
        self._make_lock = threading.Lock()
        self.run_id = uuid.uuid4().hex[:12]
        self.trace: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def fork(self) -> "Decider":
        """A Decider with the same providers and a new, empty trace. Use one fork for each parse."""
        import copy

        d = copy.copy(self)
        d.run_id = uuid.uuid4().hex[:12]
        d.trace = []
        d._lock = threading.Lock()
        return d

    @staticmethod
    def _keys(decision: str) -> list[str]:
        """Config keys for a decision, most specific first.
        fill_closed_slot.category.group -> [fill_closed_slot.category.group, fill_closed_slot.category, fill_closed_slot]"""
        parts = decision.split(".")
        keys = [".".join(parts[:i]) for i in range(len(parts), 0, -1)]
        if parts[0] == "pick_template_flat":
            keys.append("pick_template")
        return keys

    def _make(self, name: str) -> DecisionProvider:
        with self._make_lock:
            if name not in self._impls:
                dcfg = self._make_args["dcfg"]
                if name == "jev":
                    j = dcfg["jev"]
                    self._impls[name] = JevProvider(model=j["model"], url=j["url"], timeout_s=j["timeout_s"],
                                                    mode=self._make_args["jev_mode"], cache_path=self._make_args["jev_cache"])
                elif name == "rules":
                    self._impls[name] = RulesProvider()
                elif name == "local":
                    self._impls[name] = LocalClassifierProvider.from_config(dcfg.get("local", {}))
                else:
                    raise ValueError(f"unknown provider {name}")
            return self._impls[name]

    def provider_name(self, decision: str) -> str:
        for k in self._keys(decision):
            if k in self._overrides:
                return getattr(self._overrides[k], "name", "custom")
            if k in self._names:
                return self._names[k]
        raise KeyError(f"no provider configured for decision {decision}")

    def provider(self, decision: str) -> DecisionProvider:
        for k in self._keys(decision):
            if k in self._overrides:
                return self._overrides[k]
            if k in self._names:
                return self._make(self._names[k])
        raise KeyError(f"no provider configured for decision {decision}")

    def threshold(self, decision: str) -> float:
        base = decision.split(".")[0]
        if base == "pick_template_flat":
            base = "pick_template"
        return float(self.thresholds.get(base, 0.0))

    # ------------------------------------------------------------ core

    def _record(self, decision: str, depth: int, inputs: dict[str, Any], options: Any, d: Decision, dt: float):
        rec = {
            "decision": decision, "depth": depth, "inputs": inputs, "options": options,
            "value": d.value if not isinstance(d.value, list) else [getattr(v, "model_dump", lambda: v)() for v in d.value],
            "confidence": round(float(d.confidence), 4), "impl": d.impl, "latency_s": round(dt, 4),
            "threshold": self.threshold(decision), "trace": d.trace,
        }
        with self._lock:
            self.trace.append(rec)
        self.logger.decision(decision=decision, run_id=self.run_id, inputs=inputs, options=options,
                             output=rec["value"], confidence=rec["confidence"], impl=d.impl, trace=d.trace)

    def _choose(self, decision: str, depth: int, state: dict[str, Any], options: dict[str, str],
                context: dict[str, Any], inputs: dict[str, Any]) -> Decision[str]:
        t0 = time.time()
        if len(options) == 1:
            d = Decision[str](value=next(iter(options)), confidence=1.0, impl="deterministic")
        else:
            q = Question(id=decision, instructions=INSTRUCTIONS[decision], context=context)
            d = self.provider(decision).choose(state, q, options)
            if d.value not in options:
                d = Decision[str](value=d.value, confidence=0.0, impl=d.impl, trace={**d.trace, "error": "value not in options"})
        self._record(decision, depth, inputs, options, d, time.time() - t0)
        return d

    def below(self, decision: str, d: Decision) -> bool:
        return d.confidence < self.threshold(decision)

    # ------------------------------------------------------------ decision functions

    def extract_spans(self, query: str, depth: int = 0) -> Decision[list[Span]]:
        from geoparse.parse.spans import extract_spans

        t0 = time.time()
        d = extract_spans(query, use_model=self.use_ner)
        self._record("extract_spans", depth, {"query": query}, None, d, time.time() - t0)
        return d

    def pick_family(self, query: str, spans: list[Span], families: dict[str, str], *, depth: int = 0,
                    context: dict[str, Any] | None = None) -> Decision[str]:
        return self._choose("pick_family", depth, {"query": query}, families, context or {},
                            {"query": query, "spans": [s.text for s in spans]})

    def pick_template(self, query: str, spans: list[Span], family: str, templates: dict[str, str], *,
                      depth: int = 0, context: dict[str, Any] | None = None) -> Decision[str]:
        return self._choose("pick_template", depth, {"query": query}, templates, context or {},
                            {"query": query, "family": family, "spans": [s.text for s in spans]})

    def pick_template_flat(self, query: str, spans: list[Span], templates: dict[str, str], *,
                           depth: int = 0, context: dict[str, Any] | None = None) -> Decision[str]:
        return self._choose("pick_template_flat", depth, {"query": query}, templates, context or {},
                            {"query": query, "spans": [s.text for s in spans]})

    def pick_split(self, query: str, template_desc: str, candidates: list[Split], *, depth: int = 0,
                   labels: dict[str, str] | None = None, context: dict[str, Any] | None = None) -> Decision[Split]:
        labels = labels or {}
        opts = {f"s{i}": "; ".join(f"{labels.get(k, k)} = '{v}'" for k, v in c.parts.items())
                for i, c in enumerate(candidates)}
        d = self._choose("pick_split", depth, {"query": query, "template": template_desc}, opts, context or {},
                         {"query": query, "template": template_desc})
        idx = int(d.value[1:]) if d.value in opts else 0
        return Decision[Split](value=candidates[idx], confidence=d.confidence, impl=d.impl, trace=d.trace)

    def fill_closed_slot(self, text: str, slot_type: str, options_ref: str, *, depth: int = 0,
                         query: str = "", allow_none: bool = False) -> Decision[str]:
        none_desc = NONE_OPTION
        if slot_type == "category":
            groups = option_descriptions("categories")
            if allow_none:
                groups["none"] = none_desc
            g = self._choose("fill_closed_slot.category.group", depth, {"text": text},
                             groups,
                             {"options_ref": "categories", "segment": text, "step": "group"},
                             {"text": text, "slot_type": slot_type, "query": query})
            if self.below("fill_closed_slot", g) or g.value == "none":
                return g
            from geoparse.options import categories

            items = {k: v["description"] for k, v in categories()[g.value]["items"].items()}
            leaf = self._choose("fill_closed_slot.category", depth, {"text": text}, items,
                                {"options_ref": "categories", "segment": text, "step": "leaf"},
                                {"text": text, "slot_type": slot_type, "query": query, "group": g.value})
            conf = min(g.confidence, leaf.confidence)
            return Decision[str](value=leaf.value, confidence=conf, impl=leaf.impl,
                                 trace={"group": g.value, "group_confidence": g.confidence})
        opts = {k: v for k, v in option_descriptions(options_ref).items() if k != "none"}
        if allow_none:
            opts["none"] = none_desc if options_ref != "admin_levels" else option_descriptions(options_ref)["none"]
        return self._choose(f"fill_closed_slot.{slot_type}", depth, {"text": text}, opts,
                            {"options_ref": options_ref, "segment": text},
                            {"text": text, "slot_type": slot_type, "query": query})

    def bind_anchor(self, query: str, slot_text: str, spans: list[Span], *, depth: int = 0) -> Decision[Span]:
        whole = Span(text=slot_text, start=0, end=len(slot_text), label="whole")
        opts: dict[str, str] = {}
        for i, s in enumerate(spans):
            opts[f"s{i}"] = s.text
        opts["whole"] = slot_text
        if len(spans) == 0 or (len(spans) == 1 and spans[0].text == slot_text):
            opts = {"whole": slot_text}
        d = self._choose("bind_anchor", depth, {"text": slot_text}, opts,
                         {"spans": [s.model_dump() for s in spans]}, {"query": query, "text": slot_text})
        span = whole if d.value == "whole" or d.value not in opts else spans[int(d.value[1:])]
        return Decision[Span](value=span, confidence=d.confidence, impl=d.impl, trace=d.trace)

    def is_subquery(self, span_text: str, *, depth: int = 0, context: dict[str, Any] | None = None) -> Decision[bool]:
        t0 = time.time()
        q = Question(id="is_subquery", instructions=INSTRUCTIONS["is_subquery"],
                     context={"criteria": IS_SUBQUERY_CRITERIA, "text": span_text, **(context or {})})
        d = self.provider("is_subquery").predicate({"text": span_text}, q)
        self._record("is_subquery", depth, {"text": span_text}, ["true", "false"], d, time.time() - t0)
        return d

    def select_source(self, span_text: str, context: dict[str, Any], *, depth: int = 0) -> Decision[str]:
        state = {"text": span_text, "gazetteer_match": context.get("gazetteer_match") or "none"}
        return self._choose("select_source", depth, state, SOURCE_OPTIONS, {"text": span_text, **context},
                            {"text": span_text, **{k: v for k, v in context.items() if k != "candidates"}})

    def disambiguate(self, name: str, candidates: list[Candidate], *, query: str = "", depth: int = 0) -> Decision[Candidate]:
        opts = {f"c{i}": c.description for i, c in enumerate(candidates)}
        d = self._choose("disambiguate", depth, {"name": name, "query": query}, opts,
                         {"scores": {f"c{i}": c.score for i, c in enumerate(candidates)}},
                         {"name": name, "query": query})
        idx = int(d.value[1:]) if d.value in opts else 0
        return Decision[Candidate](value=candidates[idx], confidence=d.confidence, impl=d.impl, trace=d.trace)
