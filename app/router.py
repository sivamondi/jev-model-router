"""Routing engine.

Pure functions with no I/O, so the policy can be unit tested without Jev or a server.
Jev supplies judgments (signals). Code supplies facts (token counts) and the final decision.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

COMPLEXITY = ["trivial", "simple", "moderate", "hard"]
SENSITIVITY = ["none", "low", "medium", "high"]
LATENCY = ["realtime", "interactive", "batch"]
CODING = ["none", "basic", "good", "strong"]
# How each sensitivity level reads in plain language.
SENSITIVITY_DATA = ["public", "internal", "confidential", "highly sensitive"]

# Expected output size by reasoning depth, used only for cost estimates.
OUTPUT_TOKENS = [150, 400, 1000, 2500]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    input_price: float          # dollars per million input tokens
    output_price: float         # dollars per million output tokens
    context_k: int              # context window in thousands of tokens
    vision: bool
    coding: int                 # index into CODING
    max_reasoning: int          # index into COMPLEXITY
    p50_latency_s: float
    max_sensitivity: int        # index into SENSITIVITY
    note: str = ""


@dataclass(frozen=True)
class Signals:
    needs_vision: float         # 0..1
    needs_coding: float         # 0..1
    complexity: int             # index into COMPLEXITY
    sensitivity: int            # index into SENSITIVITY
    latency: str                # one of LATENCY
    needs_review: float         # 0..1

    def __post_init__(self) -> None:
        for name in ("needs_vision", "needs_coding", "needs_review"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1, got {v}")
        if not 0 <= self.complexity < len(COMPLEXITY):
            raise ValueError(f"complexity index out of range: {self.complexity}")
        if not 0 <= self.sensitivity < len(SENSITIVITY):
            raise ValueError(f"sensitivity index out of range: {self.sensitivity}")
        if self.latency not in LATENCY:
            raise ValueError(f"latency must be one of {LATENCY}, got {self.latency!r}")


@dataclass(frozen=True)
class Policy:
    vision_threshold: float = 0.5
    coding_threshold: float = 0.5
    review_threshold: float = 0.7
    review_high_sensitivity: bool = True
    realtime_max_s: float = 1.0
    interactive_max_s: float = 3.0


@dataclass
class Candidate:
    model: str
    estimated_cost: float
    ruled_out: list[str] = field(default_factory=list)


@dataclass
class RouteDecision:
    selected: str | None
    estimated_cost: float | None
    human_review: bool
    review_reason: str | None
    input_tokens: int
    output_tokens_estimate: int
    requirements: list[str]
    candidates: list[Candidate]


def estimate_tokens(text: str, attachment_tokens: int = 0) -> int:
    """Rough estimate: about 4 characters per token for English text."""
    return math.ceil(len(text) / 4) + max(0, attachment_tokens)


def _latency_limit(latency: str, policy: Policy) -> float:
    if latency == "realtime":
        return policy.realtime_max_s
    if latency == "interactive":
        return policy.interactive_max_s
    return math.inf


def route(signals: Signals, input_tokens: int, models: list[ModelSpec], policy: Policy) -> RouteDecision:
    need_vision = signals.needs_vision >= policy.vision_threshold
    need_coding = signals.needs_coding >= policy.coding_threshold
    # Simple coding tasks need good coding; moderate or hard ones need strong coding.
    coding_required = (3 if signals.complexity >= 2 else 2) if need_coding else 0
    latency_limit = _latency_limit(signals.latency, policy)
    output_tokens = OUTPUT_TOKENS[signals.complexity]

    requirements: list[str] = []
    if need_vision:
        requirements.append("vision")
    if need_coding:
        requirements.append(f"{CODING[coding_required]} coding")
    requirements += [
        f"{COMPLEXITY[signals.complexity]} reasoning",
        f"{SENSITIVITY[signals.sensitivity]} sensitivity",
        f"{signals.latency} latency",
        f"{input_tokens:,} input tokens",
    ]

    candidates: list[Candidate] = []
    for m in models:
        reasons: list[str] = []
        if input_tokens > m.context_k * 1000:
            reasons.append(f"Too long: its context window holds {m.context_k}k tokens, this needs {math.ceil(input_tokens / 1000)}k")
        if need_vision and not m.vision:
            reasons.append("Can't read images")
        if coding_required and m.coding < coding_required:
            reasons.append(f"Coding skill is {CODING[m.coding]}, this needs {CODING[coding_required]}")
        if signals.complexity > m.max_reasoning:
            reasons.append(f"Handles up to {COMPLEXITY[m.max_reasoning]} reasoning, this needs {COMPLEXITY[signals.complexity]}")
        if signals.sensitivity > m.max_sensitivity:
            reasons.append(f"Not approved for {SENSITIVITY_DATA[signals.sensitivity]} data (only up to {SENSITIVITY_DATA[m.max_sensitivity]})")
        if m.p50_latency_s > latency_limit:
            reasons.append(f"Too slow: typical latency {m.p50_latency_s:g}s, {signals.latency} needs {latency_limit:g}s or less")
        cost = (input_tokens * m.input_price + output_tokens * m.output_price) / 1_000_000
        candidates.append(Candidate(model=m.name, estimated_cost=round(cost, 6), ruled_out=reasons))

    candidates.sort(key=lambda c: c.estimated_cost)
    pick = next((c for c in candidates if not c.ruled_out), None)

    review_reason = None
    if signals.needs_review >= policy.review_threshold:
        review_reason = f"Jev rates the need for a human check at {signals.needs_review:.0%} (policy threshold {policy.review_threshold:.0%})"
    elif policy.review_high_sensitivity and signals.sensitivity >= SENSITIVITY.index("high"):
        review_reason = "The data is highly sensitive, and policy requires a person to check all high-sensitivity output"
    elif pick is None:
        review_reason = "No model in the catalog meets every requirement"

    return RouteDecision(
        selected=pick.model if pick else None,
        estimated_cost=pick.estimated_cost if pick else None,
        human_review=review_reason is not None,
        review_reason=review_reason,
        input_tokens=input_tokens,
        output_tokens_estimate=output_tokens,
        requirements=requirements,
        candidates=candidates,
    )
