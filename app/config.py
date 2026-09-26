"""Settings from environment variables and routing config from YAML files."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .router import CODING, COMPLEXITY, SENSITIVITY, ModelSpec, Policy

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    jev_api_key: str | None
    jev_url: str
    jev_model: str
    jev_timeout_s: float
    models_file: Path
    policy_file: Path


def get_settings() -> Settings:
    return Settings(
        jev_api_key=os.getenv("JEV_API_KEY") or None,
        jev_url=os.getenv("JEV_URL", "https://thejevai.com/v1/systemone"),
        jev_model=os.getenv("JEV_MODEL", "jev-latest"),
        jev_timeout_s=float(os.getenv("JEV_TIMEOUT_S", "5")),
        models_file=Path(os.getenv("MODELS_FILE", ROOT / "config" / "models.yaml")),
        policy_file=Path(os.getenv("POLICY_FILE", ROOT / "config" / "policy.yaml")),
    )


def _level(value: str, levels: list[str], field: str, model: str) -> int:
    if value not in levels:
        raise ValueError(f"model {model!r}: {field} must be one of {levels}, got {value!r}")
    return levels.index(value)


def load_models(path: Path) -> list[ModelSpec]:
    data = yaml.safe_load(path.read_text())
    models = []
    for m in data.get("models", []):
        name = m["name"]
        models.append(ModelSpec(
            name=name,
            input_price=float(m["input_price"]),
            output_price=float(m["output_price"]),
            context_k=int(m["context_k"]),
            vision=bool(m["vision"]),
            coding=_level(m["coding"], CODING, "coding", name),
            max_reasoning=_level(m["max_reasoning"], COMPLEXITY, "max_reasoning", name),
            p50_latency_s=float(m["p50_latency_s"]),
            max_sensitivity=_level(m["max_sensitivity"], SENSITIVITY, "max_sensitivity", name),
            note=m.get("note", ""),
        ))
    if not models:
        raise ValueError(f"no models defined in {path}")
    return models


def load_policy(path: Path) -> Policy:
    data = yaml.safe_load(path.read_text()) or {}
    return Policy(**data.get("policy", {}))
