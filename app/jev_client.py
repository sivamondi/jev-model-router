"""Client for the Jev decision API.

Builds the typed questions, calls Jev, and turns the answers into routing Signals.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .router import COMPLEXITY, LATENCY, SENSITIVITY, Signals

log = logging.getLogger("jev")


class JevError(Exception):
    """Raised when Jev can't be reached or returns something unusable."""


def _criteria(levels: list[str], descriptions: list[str]) -> dict[str, str]:
    return dict(zip(levels, descriptions))


QUESTIONS: dict[str, dict[str, Any]] = {
    "needs_vision": {
        "type": "noul",
        "instructions": "Does answering this request require looking at an image, screenshot, chart, or scanned document?",
    },
    "needs_coding": {
        "type": "noul",
        "instructions": "Is this request mainly about writing, reviewing, or debugging code?",
    },
    "complexity": {
        "type": "score",
        "instructions": "How much reasoning does a good answer require?",
        "criteria": [
            "Lookup, rewording, or translation",
            "Short explanation or single-step task",
            "Multi-step analysis or a structured draft",
            "Planning, trade-offs, or deep technical reasoning",
        ],
    },
    "sensitivity": {
        "type": "score",
        "instructions": "How sensitive is the data or topic in this request?",
        "criteria": [
            "Public or generic content",
            "Internal but not confidential",
            "Confidential business information",
            "Customer personal or financial data, or regulated content",
        ],
    },
    "latency": {
        "type": "choice",
        "instructions": "How quickly does the person need the answer?",
        "criteria": _criteria(LATENCY, [
            "Live conversation or in-app response, under a second",
            "Someone is waiting, a few seconds is fine",
            "Background job, minutes are fine",
        ]),
    },
    "needs_human_review": {
        "type": "noul",
        "instructions": "If the AI's answer to this request were wrong and nobody checked it, could that cause real harm?",
        "criteria": {
            "true": "A mistake could move money wrongly, create a legal or compliance problem, or give a customer wrong or confidential information",
            "false": "Low stakes: a mistake would be easy to spot and cheap to fix, such as a rough draft, a simple translation, or code that will be tested",
        },
    },
}


def build_request(text: str, model: str) -> dict[str, Any]:
    return {"model": model, "state": {"request": text}, "questions": QUESTIONS}


def _noul(answers: dict[str, Any], key: str) -> float:
    a = answers.get(key) or {}
    v = a.get("noul", a.get("probability"))
    if not isinstance(v, (int, float)):
        raise JevError(f"missing or invalid noul answer for {key!r}")
    return max(0.0, min(1.0, float(v)))


def _score_index(answers: dict[str, Any], key: str, levels: list[str]) -> int:
    a = answers.get(key) or {}
    probs = a.get("probabilities") or {}
    # Jev keys score probabilities by level number ("0", "1", ...); accept level names too.
    p = [float(probs.get(str(i), probs.get(level, 0))) for i, level in enumerate(levels)]
    total = sum(p)
    if total > 0:
        pos = sum(i * v for i, v in enumerate(p)) / total
    elif isinstance(a.get("score"), (int, float)):
        pos = float(a["score"])
    else:
        raise JevError(f"missing or invalid score answer for {key!r}")
    return max(0, min(len(levels) - 1, round(pos)))


def _choice(answers: dict[str, Any], key: str, options: list[str]) -> str:
    a = answers.get(key) or {}
    choice = a.get("choice")
    if choice is None and a.get("probabilities"):
        choice = max(a["probabilities"].items(), key=lambda kv: kv[1])[0]
    if choice not in options:
        raise JevError(f"missing or invalid choice answer for {key!r}")
    return choice


def _unwrap(body: dict[str, Any]) -> dict[str, Any]:
    """Jev wraps results as {"code": 0, "message": ..., "data": {"result": {...}}}."""
    if "code" in body and body["code"] != 0:
        raise JevError(f"Jev returned error code {body['code']}: {body.get('message')}")
    data = body.get("data")
    if isinstance(data, dict):
        body = data.get("result", data)
    return body if isinstance(body, dict) else {}


def parse_answers(body: dict[str, Any]) -> Signals:
    answers = _unwrap(body).get("answers")
    if not isinstance(answers, dict):
        raise JevError("response has no 'answers' object")
    return Signals(
        needs_vision=_noul(answers, "needs_vision"),
        needs_coding=_noul(answers, "needs_coding"),
        complexity=_score_index(answers, "complexity", COMPLEXITY),
        sensitivity=_score_index(answers, "sensitivity", SENSITIVITY),
        latency=_choice(answers, "latency", LATENCY),
        needs_review=_noul(answers, "needs_human_review"),
    )


class JevClient:
    def __init__(
        self,
        api_key: str | None,
        url: str,
        model: str,
        timeout_s: float = 5.0,
        retries: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.url = url
        self.model = model
        self.timeout_s = timeout_s
        self.retries = retries
        self.transport = transport

    async def classify(self, text: str) -> tuple[Signals, dict[str, Any]]:
        """Return parsed signals and the raw Jev response body."""
        if not self.api_key:
            raise JevError("JEV_API_KEY is not set. Add it to .env, or use manual signals.")
        payload = build_request(text, self.model)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout_s, transport=self.transport) as client:
            for attempt in range(self.retries + 1):
                try:
                    r = await client.post(self.url, json=payload, headers=headers)
                    if r.status_code >= 500:
                        last = JevError(f"Jev returned HTTP {r.status_code}")
                        continue
                    if r.status_code == 402:
                        raise JevError("Your Jev account is out of credits. Add credits at https://thejevai.com/pricing, then try again.")
                    if r.status_code in (401, 403):
                        raise JevError("Jev didn't accept the API key. Check JEV_API_KEY in .env, then restart the server.")
                    if r.status_code >= 400:
                        raise JevError(f"Jev rejected the request: HTTP {r.status_code} {r.text[:300]}")
                    body = r.json()
                    return parse_answers(body), body
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last = JevError(f"could not reach Jev: {e.__class__.__name__}")
                    log.warning("Jev call failed on attempt %d: %s", attempt + 1, e)
                except ValueError as e:
                    raise JevError(f"Jev returned invalid data: {e}") from e
        raise last or JevError("Jev call failed")
