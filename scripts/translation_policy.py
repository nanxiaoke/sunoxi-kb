#!/usr/bin/env python3
"""Shared bilingual translation policy helpers for import flows."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


DEFAULT_TRANSLATION_POLICY: Dict[str, Any] = {
    "enabled": True,
    "mode": "bilingual_on_import",
    "targets": "auto_opposite",
    "fallback_on_failure": "preview_only",
    "candidate_tiers": ["A", "B"],
    "preserve_original_full": True,
    "max_chunk_chars": 3500,
    "full_translate": {
        "url_import": True,
        "file_upload": True,
        "candidate_import": True,
        "rss_candidate_preview": False,
        "wechat_candidate_import": True,
    },
    "chinese_source": {
        "translate_to_english": True,
    },
    "english_source": {
        "translate_to_chinese": True,
    },
}


def _deepcopy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def deep_merge(defaults: Dict[str, Any], data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = _deepcopy_json(defaults)
    for key, value in (data or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_translation_policy(base_dir: Path) -> Dict[str, Any]:
    """Load the WebUI translation policy, falling back to safe defaults."""
    path = Path(base_dir) / "config" / "webui.yaml"
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            import yaml  # type: ignore
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict) and isinstance(raw.get("translation_policy"), dict):
                data = raw["translation_policy"]
        except Exception:
            data = {}
    return deep_merge(DEFAULT_TRANSLATION_POLICY, data)


def detect_language(text: str) -> str:
    """Return zh/en/mixed/unknown based on lightweight character ratios."""
    sample = (text or "")[:6000]
    if not sample.strip():
        return "unknown"
    zh = len(re.findall(r"[\u4e00-\u9fff]", sample))
    en = len(re.findall(r"[A-Za-z]", sample))
    total = zh + en
    if total <= 0:
        return "unknown"
    if zh / total > 0.22:
        return "zh"
    if en / total > 0.50:
        return "en"
    return "mixed"


def _target_enabled(policy: Dict[str, Any], source_language: str, target_language: str) -> bool:
    if source_language == "zh" and target_language == "en":
        return bool(policy.get("chinese_source", {}).get("translate_to_english", True))
    if source_language == "en" and target_language == "zh":
        return bool(policy.get("english_source", {}).get("translate_to_chinese", True))
    return False


def target_languages_for(policy: Dict[str, Any], source_language: str) -> list[str]:
    """Resolve configured target languages for one source language."""
    targets = str(policy.get("targets") or "auto_opposite").strip().lower()
    if source_language not in {"zh", "en"}:
        return []

    if targets == "auto_opposite":
        candidates = ["en"] if source_language == "zh" else ["zh"]
    elif targets in {"zh", "en"}:
        candidates = [targets]
    elif targets in {"zh,en", "en,zh", "both"}:
        candidates = ["zh", "en"]
    else:
        candidates = []

    return [
        lang for lang in candidates
        if lang != source_language and _target_enabled(policy, source_language, lang)
    ]


def candidate_tier_allowed(policy: Dict[str, Any], tier: str) -> bool:
    configured = policy.get("candidate_tiers") or ["A", "B"]
    values = {str(x).strip().upper() for x in configured if str(x).strip()}
    if "ALL" in values:
        return True
    return str(tier or "").strip().upper() in values


def full_translate_enabled(policy: Dict[str, Any], key: str) -> bool:
    return bool(policy.get("full_translate", {}).get(key, False))


def import_policy_enabled(policy: Dict[str, Any]) -> bool:
    mode = str(policy.get("mode") or "").strip()
    return bool(policy.get("enabled", True)) and mode in {"bilingual_on_import", "bilingual_for_selected"}


def should_translate_import(
    policy: Dict[str, Any],
    *,
    path_key: str,
    source_language: str,
    candidate_tier: str = "",
) -> bool:
    if not import_policy_enabled(policy):
        return False
    if not full_translate_enabled(policy, path_key):
        return False
    if candidate_tier and not candidate_tier_allowed(policy, candidate_tier):
        return False
    return bool(target_languages_for(policy, source_language))


def section_title_for(target_language: str) -> str:
    return "🌐 中文翻译" if target_language == "zh" else "🌍 English Translation"


def source_label_for(source_language: str) -> str:
    return "中文原文" if source_language == "zh" else "English Original"


def unique_languages(languages: Iterable[str]) -> list[str]:
    result: list[str] = []
    for lang in languages:
        if lang and lang not in result:
            result.append(lang)
    return result
