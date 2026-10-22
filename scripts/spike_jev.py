"""Spike 0(a): call Jev through the OpenRouter Decisions API.

Asks one template-choice question, one pick_split question, and one is_subquery question.
Runs each question 5 times alone, then 5 times with all three in one request.
Writes the raw responses to logs/spike_jev.jsonl.
"""
import json
import os
import statistics
import time
from pathlib import Path

import httpx

from geoparse.config import REPO_ROOT, load_config

cfg = load_config()["decisions"]["jev"]
URL, MODEL = cfg["url"], cfg["model"]
HEADERS = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"}
QUERY = "hospitals within 2 km of coastal districts of Odisha"

QUESTIONS = {
    "template": (
        {"query": QUERY},
        {
            "type": "choice",
            "instructions": "What type of result does the query ask for? Look at the outermost operation of the query.",
            "criteria": {
                "lookup": "One named place, for example a city, a neighborhood, or a state",
                "modifier": "A shape made from one named place, for example an area around it, its center, or its northern part",
                "hierarchy": "The sub-regions inside a place, the region that contains a place, or the regions that border a place",
                "predicate_filter": "Sub-regions of a place that have a property, for example coastal states of a country",
                "set_algebra": "A combination of places, for example X and Y, or X except Y",
                "relational": "The area between two places, or a strip along a line feature",
                "features": "Points of a category, for example hospitals or schools, in or near an area",
                "attribute": "Sub-regions of a place filtered by a number, for example cities with population over 1 million",
            },
        },
    ),
    "split": (
        {"query": QUERY, "template": "Points of a category within a distance of an area"},
        {
            "type": "choice",
            "instructions": "Which split of the query into category, distance, and area is correct?",
            "criteria": {
                "a": "category = 'hospitals'; distance = '2 km'; area = 'coastal districts of Odisha'",
                "b": "category = 'hospitals'; distance = '2 km'; area = 'coastal districts'",
                "c": "category = 'hospitals within 2 km of coastal districts'; distance = none; area = 'Odisha'",
                "d": "category = 'hospitals'; distance = '2 km of coastal'; area = 'districts of Odisha'",
            },
        },
    ),
    "is_subquery": (
        {"text": "coastal districts of Odisha"},
        {
            "type": "noul",
            "instructions": "Does the text describe a set of places by a rule, instead of naming one place?",
            "criteria": {
                "true": "The text describes places by a property or a relation, for example 'coastal districts of Odisha' or 'states that border Nepal'.",
                "false": "The text is the name of one place, for example 'Odisha', 'MG Road, Bangalore', or 'Koramangala'.",
            },
        },
    ),
}

log = (REPO_ROOT / "logs").resolve()
log.mkdir(exist_ok=True)
out = (log / "spike_jev.jsonl").open("a")
client = httpx.Client(timeout=60)


def call(state, questions):
    body = {"model": MODEL, "state": state, "questions": questions}
    t0 = time.time()
    r = client.post(URL, headers=HEADERS, json=body)
    dt = time.time() - t0
    r.raise_for_status()
    data = r.json()
    out.write(json.dumps({"request": body, "response": data, "latency_s": dt}) + "\n")
    return data, dt


def summarize(name, ans):
    if ans["type"] == "noul":
        return f"noul={ans['noul']}"
    probs = ", ".join(f"{k}={v}" for k, v in ans["probabilities"].items())
    return f"choice={ans['choice']} conf={ans['confidence']} [{probs}]"


print(f"model {MODEL}\n")
for name, (state, q) in QUESTIONS.items():
    lats, costs, answers = [], [], []
    for i in range(5):
        data, dt = call(state, {name: q})
        ans = data["answers"][name]
        lats.append(dt)
        costs.append(data["usage"]["cost"])
        answers.append(ans.get("choice", ans.get("noul")))
        print(f"{name:12s} run {i+1}: {dt*1000:5.0f} ms  cost ${data['usage']['cost']:.7f}  in_tok {data['usage']['input_tokens']}  {summarize(name, ans)}")
    print(f"{name:12s} median {statistics.median(lats)*1000:.0f} ms; answers stable: {len(set(map(str, answers))) == 1}\n")
    if name == "template":
        print("raw response shape:", json.dumps(data, indent=1)[:900], "\n")

# All three questions in one request. The state is merged, so each question names the field it reads.
merged_state = {"query": QUERY, "template": QUESTIONS["split"][0]["template"], "text": "coastal districts of Odisha"}
lats = []
for i in range(5):
    data, dt = call(merged_state, {k: v[1] for k, v in QUESTIONS.items()})
    lats.append(dt)
    print(f"combined run {i+1}: {dt*1000:5.0f} ms cost ${data['usage']['cost']:.7f} " +
          "; ".join(f"{k}: {summarize(k, a)}" for k, a in data["answers"].items()))
print(f"combined median {statistics.median(lats)*1000:.0f} ms")
