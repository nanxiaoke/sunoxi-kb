#!/usr/bin/env python3
"""Non-network smoke checks for LLM runtime configuration wiring."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from llm_provider import OllamaProvider, OpenAIProvider  # noqa: E402
from llm_service import LLMConfig, LLMService  # noqa: E402


def main() -> int:
    config = LLMConfig(BASE_DIR / "llm_runtime.yaml")
    service = LLMService(config)
    failures: list[str] = []

    for provider in config.providers.values():
        if provider.timeout_sec <= 0:
            failures.append(f"{provider.name}: timeout_sec must be positive")
            continue

        previous = None
        if provider.api_key_env:
            previous = os.environ.get(provider.api_key_env)
            os.environ[provider.api_key_env] = "smoke-test-key"

        try:
            client = service._provider_client(provider)
        except Exception as exc:
            failures.append(f"{provider.name}: failed to build client: {exc}")
            continue
        finally:
            if provider.api_key_env:
                if previous is None:
                    os.environ.pop(provider.api_key_env, None)
                else:
                    os.environ[provider.api_key_env] = previous

        if provider.type == "ollama" and not isinstance(client, OllamaProvider):
            failures.append(f"{provider.name}: expected OllamaProvider")
        if provider.type == "openai_compatible" and not isinstance(client, OpenAIProvider):
            failures.append(f"{provider.name}: expected OpenAIProvider")
        if getattr(client, "timeout_sec", None) != provider.timeout_sec:
            failures.append(
                f"{provider.name}: timeout not wired "
                f"({getattr(client, 'timeout_sec', None)} != {provider.timeout_sec})"
            )

    if failures:
        print("FAIL LLM runtime smoke")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"PASS LLM runtime smoke -> {len(config.providers)} providers checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
