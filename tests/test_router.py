import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, load_models, load_policy
from app.jev_client import JevClient, JevError, parse_answers
from app.main import JEV_CACHE, app, get_jev
from app.router import Signals, estimate_tokens, route

MODELS = load_models(ROOT / "config" / "models.yaml")
POLICY = load_policy(ROOT / "config" / "policy.yaml")


def sig(vision=0.0, coding=0.0, complexity=0, sensitivity=0, latency="interactive", review=0.0):
    return Signals(vision, coding, complexity, sensitivity, latency, review)


# ---------- Routing engine ----------

def test_trivial_realtime_goes_to_smallest_model():
    d = route(sig(complexity=0, latency="realtime"), 50, MODELS, POLICY)
    assert d.selected == "small-fast"
    assert not d.human_review


def test_vision_request_needs_vision_model():
    d = route(sig(vision=0.95, complexity=1, sensitivity=1), 1500, MODELS, POLICY)
    assert d.selected == "vision-lite"


def test_coding_request_goes_to_code_model():
    d = route(sig(coding=0.97, complexity=2), 100, MODELS, POLICY)
    assert d.selected == "code-mid"


def test_long_document_only_fits_long_context():
    d = route(sig(complexity=3, sensitivity=1, latency="batch"), 420_000, MODELS, POLICY)
    assert d.selected == "long-context"
    frontier = next(c for c in d.candidates if c.model == "frontier")
    assert any("context window" in r for r in frontier.ruled_out)


def test_high_sensitivity_stays_private_and_is_reviewed():
    d = route(sig(complexity=2, sensitivity=3, review=0.2), 6000, MODELS, POLICY)
    assert d.selected == "private-hosted"
    assert d.human_review
    assert "sensitivity" in d.review_reason


def test_review_threshold():
    d = route(sig(review=0.92), 100, MODELS, POLICY)
    assert d.human_review and "human check" in d.review_reason


def test_no_capable_model_goes_to_review():
    # Needs vision, high sensitivity: no model in the catalog has both.
    d = route(sig(vision=0.9, sensitivity=3), 100, MODELS, POLICY)
    assert d.selected is None
    assert d.human_review


def test_realtime_limit_rules_out_slow_models():
    d = route(sig(complexity=3, latency="realtime"), 100, MODELS, POLICY)
    assert d.selected is None
    assert all(any("latency" in r or "reasoning" in r for r in c.ruled_out) for c in d.candidates)


def test_invalid_signals_rejected():
    with pytest.raises(ValueError):
        Signals(1.5, 0, 0, 0, "batch", 0)


def test_token_estimate():
    assert estimate_tokens("abcd" * 10, 100) == 110


# ---------- Jev response parsing ----------

JEV_BODY = {
    "model": "jev-1.13.0",
    "answers": {
        "needs_vision": {"type": "noul", "noul": 0.03},
        "needs_coding": {"type": "noul", "noul": 0.96},
        "complexity": {"type": "score", "probabilities": {"trivial": 0.0, "simple": 0.1, "moderate": 0.7, "hard": 0.2}},
        "sensitivity": {"type": "score", "score": 0.2},
        "latency": {"type": "choice", "choice": "interactive", "confidence": 0.9},
        "needs_human_review": {"type": "noul", "noul": 0.1},
    },
}


def test_parse_answers():
    s = parse_answers(JEV_BODY)
    assert s.needs_coding == 0.96
    assert s.complexity == 2
    assert s.sensitivity == 0
    assert s.latency == "interactive"


def test_parse_score_probabilities_keyed_by_level_number():
    body = {"answers": {**JEV_BODY["answers"], "complexity": {
        "type": "score", "score": 2.9, "probabilities": {"0": 0.0, "1": 0.0, "2": 0.1, "3": 0.9}}}}
    assert parse_answers(body).complexity == 3


def test_score_criteria_sent_as_ordered_lists():
    from app.jev_client import QUESTIONS
    assert QUESTIONS["complexity"]["criteria"][0] == "Lookup, rewording, or translation"
    assert isinstance(QUESTIONS["sensitivity"]["criteria"], list)


def test_parse_unwraps_jev_envelope():
    body = {"code": 0, "message": "ok", "data": {"result": JEV_BODY, "creditsUsed": 1}}
    assert parse_answers(body).needs_coding == 0.96


def test_parse_reports_jev_error_code():
    with pytest.raises(JevError, match="quota"):
        parse_answers({"code": 4001, "message": "quota exceeded", "data": None})


def test_parse_rejects_missing_answers():
    with pytest.raises(JevError):
        parse_answers({"answers": {"needs_vision": {"noul": 0.1}}})


# ---------- API ----------

def fake_jev(handler):
    return lambda: JevClient(api_key="test-key", url="https://jev.test/v1/systemone", model="jev-latest",
                             transport=httpx.MockTransport(handler), retries=1)


@pytest.fixture
def client():
    JEV_CACHE.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    JEV_CACHE.clear()


def test_api_routes_with_jev(client):
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=JEV_BODY)

    app.dependency_overrides[get_jev] = fake_jev(handler)
    r = client.post("/api/route", json={"text": "Write a Java retry decorator with tests"})
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "jev"
    assert data["decision"]["selected"] == "code-mid"
    assert seen["auth"] == "Bearer test-key"
    assert set(seen["body"]["questions"]) == {"needs_vision", "needs_coding", "complexity", "sensitivity", "latency", "needs_human_review"}


def test_api_user_facts_override_jev(client):
    app.dependency_overrides[get_jev] = fake_jev(lambda request: httpx.Response(200, json=JEV_BODY))
    data = client.post("/api/route", json={"text": "What does this error mean?", "has_image": True,
                                           "latency": "realtime"}).json()
    assert data["signals"]["latency"] == "realtime"
    assert data["signals"]["needs_vision"] == 1.0
    assert set(data["user_set"]) == {"latency", "needs_vision"}


def test_api_reuses_jev_answers_for_same_text(client):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=JEV_BODY)

    app.dependency_overrides[get_jev] = fake_jev(handler)
    first = client.post("/api/route", json={"text": "same text"}).json()
    second = client.post("/api/route", json={"text": "same text", "latency": "batch"}).json()
    assert calls["n"] == 1
    assert not first["cached"] and second["cached"]
    assert second["signals"]["latency"] == "batch"


def test_api_out_of_credits_is_explained(client):
    app.dependency_overrides[get_jev] = fake_jev(
        lambda request: httpx.Response(402, json={"code": -1, "message": "Insufficient credits."}))
    data = client.post("/api/route", json={"text": "hello"}).json()
    assert data["source"] == "fallback"
    assert "out of credits" in data["error"]


def test_api_retries_then_falls_back_to_review(client):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    app.dependency_overrides[get_jev] = fake_jev(handler)
    data = client.post("/api/route", json={"text": "hello"}).json()
    assert calls["n"] == 2
    assert data["source"] == "fallback"
    assert data["decision"]["human_review"] is True
    assert data["decision"]["selected"] is None


def test_api_missing_key_falls_back(client):
    app.dependency_overrides[get_jev] = lambda: JevClient(api_key=None, url="x", model="jev-latest")
    data = client.post("/api/route", json={"text": "hello"}).json()
    assert data["source"] == "fallback"
    assert "JEV_API_KEY" in data["error"]


def test_api_manual_signals_skip_jev(client):
    def handler(request):
        raise AssertionError("Jev should not be called")

    app.dependency_overrides[get_jev] = fake_jev(handler)
    body = {"text": "Translate thank you into Spanish", "signals": {
        "needs_vision": 0, "needs_coding": 0, "complexity": "trivial",
        "sensitivity": "none", "latency": "realtime", "needs_review": 0}}
    data = client.post("/api/route", json=body).json()
    assert data["source"] == "manual"
    assert data["decision"]["selected"] == "small-fast"


def test_api_validates_input(client):
    assert client.post("/api/route", json={"text": ""}).status_code == 422
    bad = {"text": "x", "signals": {"needs_vision": 2, "needs_coding": 0, "complexity": "trivial",
                                    "sensitivity": "none", "latency": "realtime", "needs_review": 0}}
    assert client.post("/api/route", json=bad).status_code == 422


def test_config_and_ui_served(client):
    cfg = client.get("/api/config").json()
    assert len(cfg["models"]) == 7
    assert client.get("/").status_code == 200
