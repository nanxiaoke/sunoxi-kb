#!/usr/bin/env python3
"""Unified LLM service and per-flow policy loader.

This module is the Phase 2-3 foundation. It does not migrate existing
business flows by itself; callers must opt in by using LLMService.

Sensitive values such as API keys are never read from config files. Provider
config may only name an environment variable via `api_key_env`.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

try:
    from llm_provider import OllamaProvider, OpenAIProvider
except ImportError:  # pragma: no cover - supports package-style imports later
    from .llm_provider import OllamaProvider, OpenAIProvider


KB_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = KB_DIR / "llm_runtime.yaml"


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    type: str
    model: str
    label: str = ""
    base_url: str = ""
    api_key_env: str = ""
    timeout_sec: int = 60
    options: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_online(self) -> bool:
        return self.type == "openai_compatible"

    @property
    def has_required_secret(self) -> bool:
        if not self.api_key_env:
            return True
        return bool(os.environ.get(self.api_key_env) or os.environ.get("KB_LLM_API_KEY"))


@dataclass(frozen=True)
class FlowPolicy:
    name: str
    label: str
    providers: List[str]
    allow_fallback: bool = True
    allow_online: bool = True
    fallback_notice: str = "record"
    chunk_chars: int = 4000
    intent: str = "balanced"
    notes: str = ""
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMCallResult:
    content: str
    flow: str
    provider: str
    model: str
    duration_sec: float
    status: str = "ok"
    fallback_from: Optional[str] = None
    fallback_to: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "flow": self.flow,
            "provider": self.provider,
            "model": self.model,
            "duration_sec": round(self.duration_sec, 3),
            "status": self.status,
            "fallback_from": self.fallback_from,
            "fallback_to": self.fallback_to,
            "error": self.error,
        }


class LLMConfig:
    def __init__(self, path: Path = DEFAULT_CONFIG_PATH):
        self.path = Path(path)
        self.raw = self._load()
        self.providers = self._load_providers()
        self.flows = self._load_flows()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(f"LLM runtime config not found: {self.path}")
        with self.path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"LLM runtime config must be a mapping: {self.path}")
        return data

    def _load_providers(self) -> Dict[str, ProviderConfig]:
        providers: Dict[str, ProviderConfig] = {}
        for name, data in (self.raw.get("providers") or {}).items():
            data = data or {}
            providers[name] = ProviderConfig(
                name=name,
                type=str(data.get("type", "")),
                label=str(data.get("label", name)),
                model=str(data.get("model", "")),
                base_url=str(data.get("base_url", "")),
                api_key_env=str(data.get("api_key_env", "")),
                timeout_sec=int(data.get("timeout_sec", 60)),
                options=dict(data.get("options") or {}),
            )
        return providers

    def _load_flows(self) -> Dict[str, FlowPolicy]:
        flows: Dict[str, FlowPolicy] = {}
        for name, data in (self.raw.get("flows") or {}).items():
            data = data or {}
            flows[name] = FlowPolicy(
                name=name,
                label=str(data.get("label", name)),
                providers=list(data.get("providers") or []),
                allow_fallback=bool(data.get("allow_fallback", True)),
                allow_online=bool(data.get("allow_online", True)),
                fallback_notice=str(data.get("fallback_notice", "record")),
                chunk_chars=int(data.get("chunk_chars", 4000)),
                intent=str(data.get("intent", "balanced")),
                notes=str(data.get("notes", "")),
                options=dict(data.get("options") or {}),
            )
        return flows

    def provider(self, name: str) -> ProviderConfig:
        if name not in self.providers:
            raise KeyError(f"Unknown LLM provider: {name}")
        return self.providers[name]

    def flow(self, name: str) -> FlowPolicy:
        if name not in self.flows:
            raise KeyError(f"Unknown LLM flow: {name}")
        return self.flows[name]

    def provider_status(self) -> List[Dict[str, Any]]:
        status = []
        for p in self.providers.values():
            status.append({
                "name": p.name,
                "label": p.label,
                "type": p.type,
                "model": p.model,
                "base_url": p.base_url,
                "api_key_env": p.api_key_env or None,
                "secret_configured": p.has_required_secret,
                "online": p.is_online,
            })
        return status


class LLMService:
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()

    def _provider_client(self, cfg: ProviderConfig):
        if cfg.type == "ollama":
            return OllamaProvider(model_name=cfg.model, base_url=cfg.base_url or "http://127.0.0.1:11434")
        if cfg.type == "openai_compatible":
            api_key = os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else ""
            api_key = api_key or os.environ.get("KB_LLM_API_KEY", "")
            if not api_key:
                raise RuntimeError(f"missing API key env: {cfg.api_key_env or 'KB_LLM_API_KEY'}")
            return OpenAIProvider(model_name=cfg.model, base_url=cfg.base_url, api_key=api_key)
        raise ValueError(f"Unsupported provider type: {cfg.type}")

    def chat(
        self,
        flow_name: str,
        messages: List[Dict[str, str]],
        *,
        provider_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> LLMCallResult:
        policy = self.config.flow(flow_name)
        candidates = [provider_name] if provider_name else list(policy.providers)
        if not candidates:
            raise ValueError(f"Flow has no providers: {flow_name}")

        first_provider = candidates[0]
        last_error: Optional[Exception] = None
        attempted: List[str] = []

        for index, candidate_name in enumerate(candidates):
            if index > 0 and not policy.allow_fallback:
                break
            provider_cfg = self.config.provider(candidate_name)
            if provider_cfg.is_online and not policy.allow_online:
                last_error = RuntimeError(f"online provider not allowed for flow {flow_name}: {candidate_name}")
                attempted.append(candidate_name)
                continue

            merged_options = dict(provider_cfg.options)
            merged_options.update(policy.options)
            if options:
                merged_options.update(options)

            start = time.time()
            try:
                client = self._provider_client(provider_cfg)
                content = client.chat(messages, options=merged_options)
                duration = time.time() - start
                return LLMCallResult(
                    content=content or "",
                    flow=flow_name,
                    provider=provider_cfg.name,
                    model=provider_cfg.model,
                    duration_sec=duration,
                    fallback_from=first_provider if provider_cfg.name != first_provider else None,
                    fallback_to=provider_cfg.name if provider_cfg.name != first_provider else None,
                )
            except Exception as exc:
                duration = time.time() - start
                last_error = exc
                attempted.append(candidate_name)
                if index == len(candidates) - 1 or not policy.allow_fallback:
                    return LLMCallResult(
                        content="",
                        flow=flow_name,
                        provider=provider_cfg.name,
                        model=provider_cfg.model,
                        duration_sec=duration,
                        status="error",
                        fallback_from=first_provider if provider_cfg.name != first_provider else None,
                        fallback_to=provider_cfg.name if provider_cfg.name != first_provider else None,
                        error=str(exc),
                    )

        return LLMCallResult(
            content="",
            flow=flow_name,
            provider=attempted[-1] if attempted else "",
            model="",
            duration_sec=0.0,
            status="error",
            error=str(last_error) if last_error else "no provider attempted",
        )

    def json_chat(self, flow_name: str, messages: List[Dict[str, str]], **kwargs) -> LLMCallResult:
        result = self.chat(flow_name, messages, **kwargs)
        if result.status != "ok":
            return result
        cleaned = (result.content or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.removeprefix("json").strip()
        json.loads(cleaned)
        result.content = cleaned
        return result


def main() -> None:
    config = LLMConfig()
    print(json.dumps({
        "config": str(config.path),
        "providers": config.provider_status(),
        "flows": {name: policy.__dict__ for name, policy in config.flows.items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

