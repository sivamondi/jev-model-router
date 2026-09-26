"""FastAPI app: serves the UI and the routing API.

POST /api/route   route a request (calls Jev, or uses manual signals if provided)
GET  /api/config  catalog, policy, and level names for the UI
GET  /healthz     liveness check
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import asdict, replace
from functools import lru_cache
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT, get_settings, load_models, load_policy
from .jev_client import JevClient, JevError, build_request
from .router import CODING, COMPLEXITY, LATENCY, SENSITIVITY, Signals, estimate_tokens, route

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("router")

app = FastAPI(title="Jev model router", version="1.0.0")


@lru_cache
def get_catalog():
    s = get_settings()
    return load_models(s.models_file), load_policy(s.policy_file)


# Jev's answers depend only on the text, so repeat requests reuse them instead of spending credits.
JEV_CACHE: OrderedDict[str, tuple[Signals, dict]] = OrderedDict()
JEV_CACHE_SIZE = 256


def get_jev() -> JevClient:
    s = get_settings()
    return JevClient(api_key=s.jev_api_key, url=s.jev_url, model=s.jev_model, timeout_s=s.jev_timeout_s)


class SignalsIn(BaseModel):
    needs_vision: float = Field(ge=0, le=1)
    needs_coding: float = Field(ge=0, le=1)
    complexity: Literal["trivial", "simple", "moderate", "hard"]
    sensitivity: Literal["none", "low", "medium", "high"]
    latency: Literal["realtime", "interactive", "batch"]
    needs_review: float = Field(ge=0, le=1)

    def to_signals(self) -> Signals:
        return Signals(
            needs_vision=self.needs_vision,
            needs_coding=self.needs_coding,
            complexity=COMPLEXITY.index(self.complexity),
            sensitivity=SENSITIVITY.index(self.sensitivity),
            latency=self.latency,
            needs_review=self.needs_review,
        )


class RouteIn(BaseModel):
    text: str = Field(min_length=1, max_length=400_000)
    attachment_tokens: int = Field(default=0, ge=0, le=10_000_000)
    # Facts the user states. Jev can't see attachments, and urgency is rarely in the text,
    # so these override Jev's answers when given.
    has_image: bool = False
    latency: Optional[Literal["realtime", "interactive", "batch"]] = None
    signals: Optional[SignalsIn] = None


def signals_out(s: Signals) -> dict:
    return {
        "needs_vision": s.needs_vision,
        "needs_coding": s.needs_coding,
        "complexity": COMPLEXITY[s.complexity],
        "sensitivity": SENSITIVITY[s.sensitivity],
        "latency": s.latency,
        "needs_review": s.needs_review,
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    models, policy = get_catalog()
    s = get_settings()
    return {
        "jev_configured": bool(s.jev_api_key),
        "jev_model": s.jev_model,
        "levels": {"complexity": COMPLEXITY, "sensitivity": SENSITIVITY, "latency": LATENCY, "coding": CODING},
        "policy": asdict(policy),
        "models": [
            {**asdict(m),
             "coding": CODING[m.coding],
             "max_reasoning": COMPLEXITY[m.max_reasoning],
             "max_sensitivity": SENSITIVITY[m.max_sensitivity]}
            for m in models
        ],
    }


@app.post("/api/jev-request")
def jev_request(body: RouteIn):
    """The exact body sent to Jev, for inspection. Contains no API key."""
    return build_request(body.text, get_settings().jev_model)


@app.post("/api/route")
async def route_request(body: RouteIn, jev: JevClient = Depends(get_jev)):
    models, policy = get_catalog()
    tokens = estimate_tokens(body.text, body.attachment_tokens)
    raw = None
    error = None
    user_set: list[str] = []
    cached = False

    if body.signals is not None:
        source = "manual"
        try:
            signals = body.signals.to_signals()
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    else:
        try:
            if body.text in JEV_CACHE:
                JEV_CACHE.move_to_end(body.text)
                signals, raw = JEV_CACHE[body.text]
                cached = True
            else:
                signals, raw = await jev.classify(body.text)
                JEV_CACHE[body.text] = (signals, raw)
                if len(JEV_CACHE) > JEV_CACHE_SIZE:
                    JEV_CACHE.popitem(last=False)
            source = "jev"
        except JevError as e:
            # Fail safe: without signals, don't guess a model. Send the request to a person.
            log.warning("Jev unavailable, falling back to human review: %s", e)
            return {
                "source": "fallback",
                "error": str(e),
                "signals": None,
                "user_set": user_set,
                "decision": {
                    "selected": None,
                    "estimated_cost": None,
                    "human_review": True,
                    "review_reason": "Jev was unavailable, so the request goes to a person",
                    "input_tokens": tokens,
                    "output_tokens_estimate": None,
                    "requirements": [],
                    "candidates": [],
                },
            }
        if body.latency is not None:
            signals = replace(signals, latency=body.latency)
            user_set.append("latency")
        if body.has_image:
            signals = replace(signals, needs_vision=1.0)
            user_set.append("needs_vision")

    decision = route(signals, tokens, models, policy)
    # Log the decision, not the request text, so logs don't collect customer content.
    log.info("route source=%s tokens=%d selected=%s review=%s", source, tokens, decision.selected, decision.human_review)
    return {
        "source": source,
        "error": error,
        "signals": signals_out(signals),
        "user_set": user_set,
        "jev_response": raw,
        "cached": cached,
        "decision": asdict(decision),
    }


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
