#!/usr/bin/env python3
"""
Sunoxi知识库 — Web UI
Flask-based web interface with document management, search, and knowledge graph.

Usage:
  python3 web_ui.py                 # Start on default port 5080, bind to all interfaces
  python3 web_ui.py --port 9090     # Custom port
  python3 web_ui.py --host 127.0.0.1  # Localhost-only
"""

import os
import sys
import csv
import io
import json
import shutil
import hashlib
import re
import logging
import argparse
import tempfile
import mimetypes
import threading
import time
import yaml
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List

# ── KB base dir ──────────────────────────────────────────────────
KB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KB_DIR / "scripts"))

# ── Flask setup ──────────────────────────────────────────────────
from flask import Flask, request, jsonify, send_from_directory, send_file, Response
from flask_cors import CORS

app = Flask(__name__, static_folder=None)
CORS(app)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("web_ui")
LLM_RUNTIME_CONFIG = KB_DIR / "llm_runtime.yaml"
LLM_CONFIG_BACKUP_DIR = KB_DIR / "backups" / "llm_runtime"
WEBUI_CONFIG = KB_DIR / "config" / "webui.yaml"
WEBUI_CONFIG_BACKUP_DIR = KB_DIR / "backups" / "webui"
LLM_SECRET_ENV_FILE = Path.home() / ".config" / "karpathy-kb" / "llm.env"
LLM_SYSTEMD_DROPIN = Path.home() / ".config" / "systemd" / "user" / "karpathy-kb.service.d" / "10-llm-env.conf"
LLM_SECRET_INSTALL_SCRIPT = KB_DIR / "scripts" / "install_llm_env.sh"
LLM_DEPLOYMENT_MODES = {
    "local": {
        "label": "纯本地",
        "description": "所有 LLM 业务流只走 local_gemma4，不使用在线模型。",
    },
    "online": {
        "label": "纯在线",
        "description": "所有 LLM 业务流只走 DeepSeek Flash/Pro，需要 DEEPSEEK_API_KEY。",
    },
    "hybrid": {
        "label": "混合",
        "description": "批量/低成本任务本地优先，质量敏感翻译走在线优先。",
    },
}
_batch_import_lock = threading.Lock()
_batch_import_job = {
    "running": False,
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "tier": None,
    "limit": 0,
    "max_retries": 0,
    "total": 0,
    "processed": 0,
    "imported": 0,
    "failed": 0,
    "current": None,
    "items": [],
    "error_items": [],
    "maintenance": None,
    "result": None,
    "error": None,
}

# ── Lazy imports ─────────────────────────────────────────────────
_searcher = None
_embedder = None
_graph = None
_importer = None

def _get_searcher():
    global _searcher
    if _searcher is None:
        from search import WikiSearcher
        _searcher = WikiSearcher(KB_DIR)
        _searcher.build_index(rebuild=False)
    return _searcher

def _get_embedder():
    global _embedder
    if _embedder is None:
        from embeddings import EmbeddingEngine
        _embedder = EmbeddingEngine(KB_DIR)
    return _embedder

def _get_graph():
    global _graph
    if _graph is None:
        from knowledge_graph import KnowledgeGraph
        _graph = KnowledgeGraph(KB_DIR)
    return _graph

def _get_importer():
    global _importer
    if _importer is None:
        from auto_importer import AutoImporter
        _importer = AutoImporter(KB_DIR)
    return _importer

# ── Allowed extensions ───────────────────────────────────────────
ALLOWED_EXTENSIONS = {
    "md", "txt", "pdf", "docx", "py", "js", "ts", "go", "rs",
    "java", "cpp", "c", "h", "json", "yaml", "yml", "toml",
    "html", "css", "csv", "xml", "rst",
}

MAX_UPLOAD_MB = 50

WEBUI_CONFIG_DEFAULTS = {
    "app": {
        "name": "Sunoxi KB",
        "title": "Sunoxi 知识库",
        "subtitle": "Personal Knowledge Base",
        "logo": "/static/favicon.svg?v=4",
    },
    "features": {
        "chat": True,
        "graph": True,
        "documents": True,
        "upload": True,
        "url_import": True,
        "candidates": True,
        "rss": True,
        "wechat": True,
        "llm_settings": True,
        "llm_audit": True,
    },
    "translation_policy": {
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
    },
}


def _allowed_file(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def _file_hash(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _deep_merge_defaults(defaults: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    merged = json.loads(json.dumps(defaults, ensure_ascii=False))
    for key, value in (data or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_webui_config_raw() -> Dict[str, Any]:
    if not WEBUI_CONFIG.exists():
        return {}
    data = yaml.safe_load(WEBUI_CONFIG.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"WebUI config must be a mapping: {WEBUI_CONFIG}")
    return data


def _webui_config_payload() -> Dict[str, Any]:
    config = _deep_merge_defaults(WEBUI_CONFIG_DEFAULTS, _load_webui_config_raw())
    return {
        "config_path": str(WEBUI_CONFIG),
        "exists": WEBUI_CONFIG.exists(),
        "app": config["app"],
        "features": config["features"],
        "translation_policy": config["translation_policy"],
    }


def _clean_webui_config_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    current = _webui_config_payload()
    app_in = payload.get("app") if isinstance(payload.get("app"), dict) else {}
    features_in = payload.get("features") if isinstance(payload.get("features"), dict) else {}
    policy_in = payload.get("translation_policy") if isinstance(payload.get("translation_policy"), dict) else {}

    app = dict(current["app"])
    for key in ("name", "title", "subtitle", "logo"):
        if key in app_in:
            value = str(app_in.get(key) or "").strip()
            if key in {"name", "title"} and not value:
                raise ValueError(f"app.{key} is required")
            if len(value) > 160:
                raise ValueError(f"app.{key} is too long")
            app[key] = value

    features = dict(current["features"])
    for key in WEBUI_CONFIG_DEFAULTS["features"]:
        if key in features_in:
            features[key] = bool(features_in[key])

    policy = copy_llm_runtime(current["translation_policy"])
    for key in ("enabled", "preserve_original_full"):
        if key in policy_in:
            policy[key] = bool(policy_in[key])
    for key, allowed in {
        "mode": {"off", "preview_only", "bilingual_on_import", "bilingual_for_selected"},
        "targets": {"auto_opposite", "zh", "en", "zh,en"},
        "fallback_on_failure": {"preview_only", "skip", "fail_import"},
    }.items():
        if key in policy_in:
            value = str(policy_in.get(key) or "").strip()
            if value not in allowed:
                raise ValueError(f"translation_policy.{key} must be one of: {', '.join(sorted(allowed))}")
            policy[key] = value
    if "candidate_tiers" in policy_in:
        tiers_raw = policy_in.get("candidate_tiers")
        tiers = tiers_raw if isinstance(tiers_raw, list) else re.split(r"[,，\s]+", str(tiers_raw or ""))
        cleaned_tiers = []
        for tier in tiers:
            t = str(tier).strip().upper()
            if t == "ALL":
                cleaned_tiers = ["all"]
                break
            if t in {"A", "B", "C", "D"} and t not in cleaned_tiers:
                cleaned_tiers.append(t)
        policy["candidate_tiers"] = cleaned_tiers or ["A", "B"]
    if "max_chunk_chars" in policy_in:
        policy["max_chunk_chars"] = max(500, min(int(policy_in.get("max_chunk_chars") or 3500), 20000))
    for group in ("full_translate", "chinese_source", "english_source"):
        if isinstance(policy_in.get(group), dict):
            for key in policy.get(group, {}):
                if key in policy_in[group]:
                    policy[group][key] = bool(policy_in[group][key])

    return {"app": app, "features": features, "translation_policy": policy}


def _backup_webui_config(reason: str = "manual") -> Optional[Path]:
    if not WEBUI_CONFIG.exists():
        return None
    WEBUI_CONFIG_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    safe_reason = re.sub(r"[^A-Za-z0-9_-]+", "-", reason).strip("-")[:32] or "manual"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = WEBUI_CONFIG_BACKUP_DIR / f"webui_{stamp}_{safe_reason}.yaml"
    shutil.copy2(WEBUI_CONFIG, backup)
    return backup


def _write_webui_config(cleaned: Dict[str, Any]) -> None:
    WEBUI_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = WEBUI_CONFIG.with_suffix(".yaml.tmp")
    header = "# Local WebUI runtime configuration. Do not store secrets here.\n\n"
    tmp.write_text(header + yaml.safe_dump(cleaned, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(WEBUI_CONFIG)


def _feature_enabled(name: str) -> bool:
    try:
        return bool(_webui_config_payload()["features"].get(name, True))
    except Exception as e:
        logger.warning(f"Feature config load failed; allowing {name}: {e}")
        return True


def _feature_disabled_response(name: str):
    return jsonify({"error": f"feature disabled: {name}", "feature": name}), 403


def _import_recovery(raw_path: str, error: str = "") -> Dict[str, Any]:
    return {
        "can_retry": bool(raw_path),
        "raw_path": raw_path,
        "retry_endpoint": "/api/documents/retry-import",
        "hint": "原始文件已保留，可修正模型配置或依赖后重新处理。",
        "error": error or None,
    }


def _is_generated_wiki_page(relpath: Path) -> bool:
    """Return True for generated navigation/index pages, not real knowledge articles."""
    name = relpath.name
    return name in {"00_INDEX.md", "DOCUMENTS.md"} or name.startswith("category_")




def _clean_wiki_text_for_quality(text: str) -> str:
    text = text or ""
    text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', text)
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^\s*[#>\-]*\s*(候选来源|作者|公众号\w*|发布时间|原文链接|抓取时间|状态|建议分类|来源|处理时间|分类|原始格式)\s*[:：].*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_section_text(text: str, header: str) -> str:
    m = re.search(rf'##\s*{re.escape(header)}\s*\n(.*?)(?=\n##\s+|\Z)', text or '', flags=re.S)
    return m.group(1).strip() if m else ''


def _quality_status_for_content(text: str) -> dict:
    summary = _extract_section_text(text, '📝 摘要')
    keypoints = _extract_section_text(text, '🔑 关键点')
    entities = _extract_section_text(text, '🏷️ 实体与概念')
    issues = []
    if not summary or 'AI生成的摘要' in summary or len(_clean_wiki_text_for_quality(summary)) < 40:
        issues.append('summary_placeholder')
    if not keypoints or 'AI提取的关键点' in keypoints or len(_clean_wiki_text_for_quality(keypoints)) < 40:
        issues.append('keypoints_placeholder')
    if not entities or '未提取到实体' in entities or len(_clean_wiki_text_for_quality(entities)) < 6:
        issues.append('entities_placeholder')
    return {"ok": not issues, "issues": issues, "score": max(0, 100 - len(issues) * 30)}


def _source_body_for_quality(text: str) -> str:
    marker = '## 📄 原始内容预览'
    body = text.split(marker, 1)[1] if marker in text else text
    body = body.split('*此条目由AI自动生成', 1)[0]
    return _clean_wiki_text_for_quality(body)


def _sentences_for_quality(body: str):
    return [x.strip() for x in re.split(r'(?<=[。！？.!?])\s*|\n+', body or '') if len(x.strip()) >= 20]


def _generate_quality_sections(text: str) -> dict:
    body = _source_body_for_quality(text)
    sentences = _sentences_for_quality(body)
    title_match = re.search(r'^#\s+(.+)$', text or '', flags=re.M)
    title = title_match.group(1).strip() if title_match else '文档'
    summary_src = '。'.join(sentences[:3]).strip('。')
    if not summary_src:
        summary_src = body[:260]
    summary = f"本文围绕《{title}》展开，核心内容包括：{summary_src[:260]}。"
    key_sents = []
    for sent in sentences:
        if any(bad in sent for bad in ['候选来源', '公众号', '原文链接', '抓取时间', '建议分类']):
            continue
        key_sents.append(sent)
        if len(key_sents) >= 5:
            break
    keypoints = '\n'.join([f"{i}. {x[:160]}" for i, x in enumerate(key_sents or sentences[:5], 1)])
    candidates = re.findall(r'[A-Za-z][A-Za-z0-9+._/-]{2,}|[\u4e00-\u9fff]{2,8}', body[:5000])
    stop = {'本文','这个','一个','通过','可以','什么','时候','因为','但是','进行','实现','使用','需要','包括','内容','文档'}
    entities = []
    for c in candidates:
        c = c.strip(' ，。、；;:：()（）[]【】')
        if c and c not in stop and c not in entities:
            entities.append(c)
        if len(entities) >= 12:
            break
    return {"summary": summary, "keypoints": keypoints, "entities": '，'.join(entities)}


def _replace_section(text: str, header: str, new_body: str) -> str:
    pattern = rf'(##\s*{re.escape(header)}\s*\n)(.*?)(?=\n##\s+|\Z)'
    replacement = rf'\1\n{new_body.strip()}\n'
    if re.search(pattern, text, flags=re.S):
        return re.sub(pattern, replacement, text, count=1, flags=re.S)
    return text + f"\n\n## {header}\n\n{new_body.strip()}\n"


def _parse_frontmatter_value(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ""
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", parts[1])
    return m.group(1).strip().strip('"\'') if m else ""


def _split_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}
    return meta, parts[2]


def _write_frontmatter(meta: Dict[str, Any], body: str) -> str:
    body = body if body.startswith("\n") else "\n" + body
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip() + "\n---" + body


def _upsert_frontmatter_mapping(text: str, key: str, value: Dict[str, Any]) -> str:
    meta, body = _split_frontmatter(text)
    meta[key] = value
    return _write_frontmatter(meta, body)


def _replace_frontmatter_value(text: str, key: str, value: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    fm, body = parts[1], parts[2]
    line = f'{key}: "{value}"'
    if re.search(rf"(?m)^{re.escape(key)}\s*:", fm):
        fm = re.sub(rf"(?m)^{re.escape(key)}\s*:.*$", line, fm)
    else:
        fm = fm.rstrip() + "\n" + line + "\n"
    return "---" + fm + "---" + body


def _replace_h1(text: str, title: str) -> str:
    return re.sub(r"(?m)^#\s+.+$", f"# {title}", text, count=1)


def _source_file_for_wiki(text: str) -> Optional[Path]:
    raw = _parse_frontmatter_value(text, "source")
    if not raw:
        m = re.search(r"(?m)^>\s*\*\*来源\*\*:\s*(.+?)\s*$", text)
        raw = m.group(1).strip() if m else ""
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = KB_DIR / raw
    try:
        p = p.resolve()
        if str(p).startswith(str(KB_DIR.resolve())) and p.exists():
            return p
    except Exception:
        return None
    return None


def _original_title_from_raw(raw_text: str, fallback: str) -> str:
    for pattern in [
        r'(?m)^title:\s*["\']?(.+?)["\']?\s*$',
        r"(?m)^#\s+(.+?)\s*$",
    ]:
        m = re.search(pattern, raw_text[:3000])
        if m:
            title = m.group(1).strip().strip('"\'')
            if title:
                return title
    return fallback


def _translation_models() -> List[Dict[str, Any]]:
    try:
        from llm_service import LLMConfig
        config = LLMConfig()
        flow = config.flow("retranslation")
        providers = []
        for provider_name in flow.providers:
            p = config.provider(provider_name)
            providers.append({
                "id": p.name,
                "provider": p.name,
                "kind": "online" if p.is_online else "local",
                "provider_name": p.name,
                "label": p.label,
                "model": p.model,
                "base_url": p.base_url,
                "available": p.has_required_secret,
                "key_env": p.api_key_env or None,
                "timeout_sec": p.timeout_sec,
                "online": p.is_online,
                "flow": flow.name,
            })
        return providers
    except Exception:
        logger.exception("Load translation model config failed")
        return []


def _resolve_translation_provider(provider: str) -> str:
    provider = (provider or "").strip()
    models = _translation_models()
    for item in models:
        if provider in {item.get("id"), item.get("provider"), item.get("provider_name")}:
            return item.get("provider_name") or provider
    if provider in {"online", "local"}:
        for item in models:
            if item.get("kind") == provider:
                return item.get("provider_name") or item.get("id")
    raise ValueError(f"unknown translation provider: {provider}")


def _term_guide() -> str:
    try:
        from translator import CandidateTranslator
        return CandidateTranslator(KB_DIR)._term_guide()
    except Exception:
        return "技术术语首次出现尽量中英并列；产品名、模型名、项目名、URL、代码、命令和配置项不要翻译。"


def _chunks(text: str, max_chars: int = 3500) -> List[str]:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    parts = re.split(r"(\n\n+)", text)
    chunks, cur = [], ""
    for part in parts:
        if len(cur) + len(part) > max_chars and cur.strip():
            chunks.append(cur.strip())
            cur = part
        else:
            cur += part
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _load_translation_policy() -> Dict[str, Any]:
    try:
        from translation_policy import load_translation_policy
        return load_translation_policy(KB_DIR)
    except Exception:
        logger.exception("Load translation_policy failed; using defaults")
        return {
            "enabled": True,
            "mode": "bilingual_on_import",
            "targets": "auto_opposite",
            "chinese_source": {"translate_to_english": True},
            "english_source": {"translate_to_chinese": True},
        }


def _strip_translated_meta(text: str) -> str:
    """Remove already-translated artefacts before sending source back to the LLM.

    Avoids LLM hallucinating the previous translation footer or echoing the
    existing Chinese translation section when re-running retranslation.
    """
    if not text:
        return text
    drop_section_patterns = [
        r"(?ms)^##\s*(?:🌐\s*中文翻译|🌍\s*English Translation|中文译文|英文原文|📄\s*原始内容预览)\s*$.*?(?=^##\s|\Z)",
    ]
    cleaned = text
    for pat in drop_section_patterns:
        cleaned = re.sub(pat, "", cleaned)
    cleaned = re.sub(r"(?m)^>\s*\*?\*?翻译模型\*?\*?:\s*.*$", "", cleaned)
    cleaned = re.sub(r"(?m)^>\s*\*?\*?重新翻译时间\*?\*?:\s*.*$", "", cleaned)
    cleaned = re.sub(r"(?m)^>\s*\*?\*?Translation Model\*?\*?:\s*.*$", "", cleaned)
    cleaned = re.sub(r"(?m)^>\s*\*?\*?Retranslation Time\*?\*?:\s*.*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _detect_wiki_source_language(wiki_text: str, raw_text: str) -> str:
    try:
        from translation_policy import detect_language
    except Exception:
        return "en"
    candidate_samples: List[str] = []
    for text in (raw_text, wiki_text):
        if not text:
            continue
        for marker in ("## 英文原文", "## English Original", "## 原始内容", "## 原文", "## 原始内容预览"):
            idx = text.find(marker)
            if idx >= 0:
                tail = text[idx + len(marker): idx + len(marker) + 6000]
                if tail.strip():
                    candidate_samples.append(tail)
        if len(text) > 1800:
            candidate_samples.append(text[1800:7800])
        candidate_samples.append(text[:6000])
    for sample in candidate_samples:
        if not sample or not sample.strip():
            continue
        lang = detect_language(sample)
        if lang in {"zh", "en"}:
            return lang
    return "en"


def _resolve_retranslation_target(policy: Dict[str, Any], source_language: str) -> str:
    try:
        from translation_policy import target_languages_for
        targets = target_languages_for(policy, source_language)
    except Exception:
        targets = []
    if targets:
        return targets[0]
    if source_language == "zh":
        return "en"
    if source_language == "en":
        return "zh"
    return "zh"


def _build_retranslation_prompts(target_language: str) -> Dict[str, str]:
    if target_language == "zh":
        system = "你是专业的 AI/软件工程技术翻译。标题必须保留原文，不翻译标题。输出忠实、准确、自然、可检索的中文。"
        summary_instruction = "请为下面英文技术文档生成中文知识库元数据。标题必须保留原文，不要翻译标题。"
        summary_fields = (
            "- summary_zh: 150-300字中文摘要\n"
            "- keypoints_zh: 3-5条中文关键点数组\n"
            "- category_zh: 技术/学术论文/笔记/代码/教程/新闻/其他 之一\n"
            "- entities_zh: 核心实体和术语数组，术语尽量中英并列"
        )
        chunk_instruction = (
            "请把下面英文技术内容翻译成中文。标题、项目名、产品名、模型名、代码、命令、URL 不要翻译；"
            "技术术语首次出现中英并列。只输出中文译文，不要解释。"
        )
    else:
        system = (
            "You are a professional technical translator. Preserve the original title exactly, "
            "do not translate product names, model names, code, commands, or URLs. "
            "Output faithful, accurate, and natural English suitable for a knowledge base."
        )
        summary_instruction = (
            "Generate English knowledge-base metadata for the following Chinese technical document. "
            "Preserve the original title exactly; do not translate it."
        )
        summary_fields = (
            "- summary_en: 150-300 word English summary\n"
            "- keypoints_en: 3-5 English key points (array)\n"
            "- category_en: technology / paper / notes / code / tutorial / news / other\n"
            "- entities_en: core entities and terms (array), prefer concise English"
        )
        chunk_instruction = (
            "Translate the Chinese technical content below into natural, accurate, searchable English. "
            "Do not translate product names, model names, code, commands, or URLs. "
            "Output only the English translation, no extra commentary."
        )
    return {
        "system": system,
        "summary_instruction": summary_instruction,
        "summary_fields": summary_fields,
        "chunk_instruction": chunk_instruction,
    }


def _translate_wiki_document(wiki_text: str, *, provider_name: str, model: str) -> Dict[str, Any]:
    from llm_service import LLMService

    source_file = _source_file_for_wiki(wiki_text)
    raw_text_raw = source_file.read_text(encoding="utf-8", errors="ignore") if source_file else wiki_text
    old_title = _parse_frontmatter_value(wiki_text, "title")
    if not old_title:
        m = re.search(r"(?m)^#\s+(.+?)\s*$", wiki_text)
        old_title = m.group(1).strip() if m else "Untitled"
    original_title = _original_title_from_raw(raw_text_raw, old_title)
    policy = _load_translation_policy()
    source_language = _detect_wiki_source_language(wiki_text, raw_text_raw)
    target_language = _resolve_retranslation_target(policy, source_language)
    raw_text = _strip_translated_meta(raw_text_raw)
    if not raw_text.strip():
        raise ValueError("source content is empty after stripping translated metadata")
    llm = LLMService()
    resolved_provider = _resolve_translation_provider(provider_name)
    provider_cfg = llm.config.provider(resolved_provider)
    if model and model != provider_cfg.model:
        raise ValueError("model override is not supported yet; choose a configured provider instead")
    flow = llm.config.flow("retranslation")
    options = {"temperature": 0.1, "think": False, "max_tokens": 2500, "num_predict": 1800}
    prompts = _build_retranslation_prompts(target_language)
    guide = _term_guide()

    summary_prompt = f"""{prompts['summary_instruction']}

{guide}

原文标题：{original_title}
原文内容：
{raw_text[:12000]}

只输出 JSON，不要 Markdown 代码块。字段：
{prompts['summary_fields']}
"""
    meta_result = llm.chat("retranslation", [
        {"role": "system", "content": prompts["system"] + (" 只输出严格 JSON。" if target_language == "zh" else " Output strict JSON only.")},
        {"role": "user", "content": summary_prompt},
    ], provider_name=resolved_provider, options=options)
    if meta_result.status != "ok":
        raise RuntimeError(meta_result.error or "translation metadata generation failed")
    meta_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (meta_result.content or "").strip(), flags=re.S).strip()
    meta = json.loads(meta_text)
    if target_language == "zh":
        summary_value = (meta.get("summary_zh") or "").strip()
        keypoints_value = list(meta.get("keypoints_zh") or [])
        category_value = (meta.get("category_zh") or "").strip()
        entities_value = list(meta.get("entities_zh") or [])
    else:
        summary_value = (meta.get("summary_en") or "").strip()
        keypoints_value = list(meta.get("keypoints_en") or [])
        category_value = (meta.get("category_en") or "").strip()
        entities_value = list(meta.get("entities_en") or [])

    translated_parts = []
    chunk_meta = []
    chunk_failures: List[Dict[str, Any]] = []
    chunks = _chunks(raw_text, flow.chunk_chars)
    for i, chunk in enumerate(chunks, 1):
        prompt = f"""{prompts['chunk_instruction']}

{guide}

原文标题：{original_title}
分片：{i}

待翻译内容：
{chunk}

只输出译文，不要解释。"""
        result = llm.chat("retranslation", [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompt},
        ], provider_name=resolved_provider, options=options)
        item = result.to_dict()
        item["chunk_index"] = i
        item["chunk_chars"] = len(chunk)
        item.pop("content", None)
        if result.status != "ok":
            chunk_failures.append(item)
            item["status"] = "error"
        else:
            translated_parts.append((result.content or "").strip())
        chunk_meta.append(item)

    if not translated_parts:
        first_err = chunk_failures[0].get("error") if chunk_failures else "no chunks succeeded"
        raise RuntimeError(f"all translation chunks failed: {first_err}")

    return {
        "title": original_title,
        "summary": summary_value,
        "keypoints": "\n".join(f"{idx}. {x}" for idx, x in enumerate(keypoints_value, 1)),
        "category": category_value,
        "entities": "，".join(entities_value),
        "translation": "\n\n".join(x for x in translated_parts if x),
        "model": meta_result.model,
        "provider": meta_result.provider,
        "source_language": source_language,
        "target_language": target_language,
        "chunk_failures": chunk_failures,
        "llm_result": meta_result.to_dict(),
        "llm_chunks": chunk_meta,
        "chunk_count": len(chunks),
    }

# ═══════════════════════════════════════════════════════════════════
#  API Routes
# ═══════════════════════════════════════════════════════════════════

# ── WebUI runtime settings ───────────────────────────────────────

@app.route("/api/webui/config", methods=["GET"])
def get_webui_config():
    try:
        return jsonify(_webui_config_payload())
    except Exception as e:
        logger.error(f"Load WebUI config failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/webui/config", methods=["PATCH"])
def update_webui_config():
    data = request.get_json(silent=True) or {}
    try:
        cleaned = _clean_webui_config_update(data)
        backup = _backup_webui_config("before-webui-save")
        _write_webui_config(cleaned)
        payload = _webui_config_payload()
        payload["backup"] = str(backup.relative_to(KB_DIR)) if backup else None
        logger.info("WebUI runtime config updated")
        return jsonify(payload)
    except Exception as e:
        logger.error(f"Update WebUI config failed: {e}")
        return jsonify({"error": str(e)}), 400


# ── Document management ──────────────────────────────────────────

@app.route("/api/documents", methods=["GET"])
def list_documents():
    """List wiki documents with metadata.

    By default this returns only real knowledge articles. Generated pages
    such as 00_INDEX.md and category_*.md can be requested with
    ?include_generated=true for maintenance/debug views.
    """
    category = request.args.get("category", "")
    include_generated = request.args.get("include_generated", "false").lower() == "true"
    wiki_dir = KB_DIR / "wiki"
    docs = []
    generated_count = 0

    for f in sorted(wiki_dir.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        rel = f.relative_to(wiki_dir)
        is_generated = _is_generated_wiki_page(rel)
        if is_generated:
            generated_count += 1
            if not include_generated:
                continue
        cat = str(rel.parent) if str(rel.parent) != "." else "root"
        if category and cat != category:
            continue
        st = f.stat()
        quality = {"ok": True, "issues": [], "score": 100}
        if not is_generated:
            try:
                quality = _quality_status_for_content(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                quality = {"ok": False, "issues": ["quality_scan_failed"], "score": 0}
        docs.append({
            "path": str(rel),
            "category": cat,
            "name": rel.stem,
            "generated": is_generated,
            "quality": quality,
            "size_bytes": st.st_size,
            "size_kb": round(st.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })

    return jsonify({
        "total": len(docs),
        "generated_hidden": 0 if include_generated else generated_count,
        "include_generated": include_generated,
        "documents": docs,
    })


@app.route("/api/documents", methods=["POST"])
def upload_document():
    """Upload one or more documents. Auto-categorizes and triggers processing."""
    if not _feature_enabled("upload"):
        return _feature_disabled_response("upload")
    files = request.files.getlist("files")
    category = request.form.get("category", "notes")
    auto_process = request.form.get("auto_process", "true").lower() == "true"

    if not files or all(not f.filename for f in files):
        return jsonify({"error": "No files provided"}), 400

    results = []
    raw_dir = KB_DIR / "raw" / category
    raw_dir.mkdir(parents=True, exist_ok=True)

    for f in files:
        if not f.filename:
            continue
        if not _allowed_file(f.filename):
            results.append({"filename": f.filename, "status": "rejected", "reason": "unsupported extension"})
            continue

        # Check file size (read into memory for small files; stream for large)
        f.seek(0, os.SEEK_END)
        size_mb = f.tell() / (1024 * 1024)
        f.seek(0)
        if size_mb > MAX_UPLOAD_MB:
            results.append({"filename": f.filename, "status": "rejected", "reason": f"exceeds {MAX_UPLOAD_MB}MB limit"})
            continue

        dest = raw_dir / f.filename
        if dest.exists():
            f.seek(0)
            content = f.read()
            h = hashlib.sha256(content).hexdigest()[:8]
            stem, ext = Path(f.filename).stem, Path(f.filename).suffix
            dest = raw_dir / f"{stem}_{h}{ext}"
            with open(dest, "wb") as out:
                out.write(content)
        else:
            f.save(str(dest))

        file_hash_val = _file_hash(dest)
        results.append({
            "filename": f.filename,
            "status": "ok",
            "saved_as": str(dest.relative_to(KB_DIR)),
            "size_kb": round(dest.stat().st_size / 1024, 1),
            "hash": file_hash_val,
        })

    # Auto-process if requested
    processed = []
    if auto_process:
        importer = _get_importer()
        for r in results:
            if r["status"] == "ok":
                filepath = KB_DIR / r["saved_as"]
                item = {
                    "filename": r["filename"],
                    "stage": "auto_process",
                    "raw_path": r["saved_as"],
                    "processed": False,
                    "wiki_path": None,
                    "llm": None,
                    "message": "",
                    "error": None,
                }
                try:
                    ok, msg = importer.process_file(filepath)
                    item["processed"] = bool(ok)
                    item["message"] = str(msg)
                    if ok and msg:
                        wiki_path = Path(str(msg))
                        if not wiki_path.is_absolute():
                            wiki_path = KB_DIR / "wiki" / str(msg)
                        if wiki_path.exists():
                            item["wiki_path"] = str(wiki_path.relative_to(KB_DIR / "wiki"))
                            meta, _body = _split_frontmatter(wiki_path.read_text(encoding="utf-8", errors="ignore"))
                            item["llm"] = meta.get("llm") if isinstance(meta.get("llm"), dict) else None
                    if not ok:
                        item["error"] = str(msg)
                        item["recovery"] = _import_recovery(r["saved_as"], str(msg))
                    processed.append(item)
                except Exception as e:
                    logger.warning(f"Auto-process failed for {filepath}: {e}", exc_info=True)
                    item["stage"] = "auto_process_error"
                    item["error"] = str(e)
                    item["message"] = f"处理失败: {e}"
                    item["recovery"] = _import_recovery(r["saved_as"], str(e))
                    processed.append(item)
        if any(p.get("processed") for p in processed):
            _rebuild_index()

    return jsonify({
        "uploaded": len([r for r in results if r["status"] == "ok"]),
        "results": results,
        "processed": processed if processed else None,
    })


@app.route("/api/documents/retry-import", methods=["POST"])
def retry_import_document():
    """Retry processing an existing raw file after configuration/dependency fixes."""
    if not (_feature_enabled("upload") or _feature_enabled("url_import")):
        return _feature_disabled_response("upload")
    data = request.get_json(silent=True) or {}
    raw_path = str(data.get("raw_path") or "").strip()
    if not raw_path:
        return jsonify({"error": "raw_path is required"}), 400
    raw_file = (KB_DIR / raw_path).resolve()
    raw_root = (KB_DIR / "raw").resolve()
    if not str(raw_file).startswith(str(raw_root)) or not raw_file.exists() or not raw_file.is_file():
        return jsonify({"error": "raw file not found or outside raw directory"}), 404

    try:
        importer = _get_importer()
        ok, msg = importer.process_file(raw_file)
        payload = {
            "raw_path": str(raw_file.relative_to(KB_DIR)),
            "processed": bool(ok),
            "message": str(msg),
            "wiki_path": None,
            "error": None if ok else str(msg),
        }
        if ok and msg:
            wiki_path = Path(str(msg))
            if not wiki_path.is_absolute():
                wiki_path = KB_DIR / "wiki" / str(msg)
            if wiki_path.exists():
                payload["wiki_path"] = str(wiki_path.relative_to(KB_DIR / "wiki"))
        else:
            payload["recovery"] = _import_recovery(payload["raw_path"], str(msg))
        if ok:
            _rebuild_index()
        return jsonify(payload), 200 if ok else 500
    except Exception as e:
        logger.error(f"Retry import failed for {raw_path}: {e}", exc_info=True)
        return jsonify({
            "raw_path": raw_path,
            "processed": False,
            "error": str(e),
            "recovery": _import_recovery(raw_path, str(e)),
        }), 500


@app.route("/api/documents/<path:relpath>", methods=["DELETE"])
def delete_document(relpath: str):
    """Delete a wiki document and optionally its raw source."""
    delete_raw = request.args.get("delete_raw", "false").lower() == "true"

    wiki_file = (KB_DIR / "wiki" / relpath).resolve()
    if not str(wiki_file).startswith(str(KB_DIR.resolve())):
        return jsonify({"error": "Path traversal denied"}), 403
    if not wiki_file.exists():
        return jsonify({"error": "Document not found"}), 404

    wiki_file.unlink()

    raw_deleted = []
    if delete_raw:
        stem = wiki_file.stem
        for rf in (KB_DIR / "raw").rglob(f"{stem}*"):
            if rf.is_file():
                rf.unlink()
                raw_deleted.append(str(rf.relative_to(KB_DIR)))

    _purge_empty_dirs(KB_DIR / "wiki")
    _purge_empty_dirs(KB_DIR / "raw")
    _rebuild_index()

    return jsonify({
        "deleted": str(relpath),
        "raw_deleted": raw_deleted,
    })


@app.route("/api/documents/<path:relpath>", methods=["PUT"])
def update_document(relpath: str):
    """Update a wiki document's content."""
    wiki_file = (KB_DIR / "wiki" / relpath).resolve()
    if not str(wiki_file).startswith(str(KB_DIR.resolve())):
        return jsonify({"error": "Path traversal denied"}), 403
    if not wiki_file.exists():
        return jsonify({"error": "Document not found"}), 404

    data = request.get_json(silent=True)
    if not data or "content" not in data:
        return jsonify({"error": "Missing 'content' field"}), 400

    wiki_file.write_text(data["content"], encoding="utf-8")
    _rebuild_index()

    return jsonify({
        "updated": str(relpath),
        "size_kb": round(wiki_file.stat().st_size / 1024, 1),
    })


@app.route("/api/documents/<path:relpath>/rename", methods=["PATCH"])
def rename_document(relpath: str):
    """Rename or move a wiki document to another category."""
    wiki_file = (KB_DIR / "wiki" / relpath).resolve()
    if not str(wiki_file).startswith(str(KB_DIR.resolve())):
        return jsonify({"error": "Path traversal denied"}), 403
    if not wiki_file.exists():
        return jsonify({"error": "Document not found"}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    new_name = data.get("name")
    new_category = data.get("category")

    if not new_name and not new_category:
        return jsonify({"error": "Provide 'name' and/or 'category'"}), 400

    parent = wiki_file.parent if not new_category else (KB_DIR / "wiki" / new_category)
    stem = new_name if new_name else wiki_file.stem
    new_path = (parent / f"{stem}.md").resolve()

    if not str(new_path).startswith(str(KB_DIR.resolve())):
        return jsonify({"error": "Path traversal denied"}), 403
    if new_path.exists() and new_path != wiki_file:
        return jsonify({"error": "Target already exists"}), 409

    new_path.parent.mkdir(parents=True, exist_ok=True)
    wiki_file.rename(new_path)
    _purge_empty_dirs(KB_DIR / "wiki")
    _rebuild_index()

    return jsonify({
        "old": str(relpath),
        "new": str(new_path.relative_to(KB_DIR / "wiki")),
    })


@app.route("/api/documents/batch", methods=["DELETE"])
def batch_delete():
    """Batch delete multiple wiki documents."""
    data = request.get_json(silent=True)
    if not data or "paths" not in data:
        return jsonify({"error": "Missing 'paths' array"}), 400

    deleted, failed = [], []
    for relpath in data["paths"]:
        wf = (KB_DIR / "wiki" / relpath).resolve()
        if not str(wf).startswith(str(KB_DIR.resolve())):
            failed.append({"path": relpath, "reason": "path traversal"})
        elif not wf.exists():
            failed.append({"path": relpath, "reason": "not found"})
        else:
            wf.unlink()
            deleted.append(relpath)

    _purge_empty_dirs(KB_DIR / "wiki")
    _rebuild_index()
    return jsonify({"deleted": deleted, "failed": failed})


def _purge_empty_dirs(root: Path):
    """Remove empty directories under root."""
    for d in sorted(root.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            logger.info(f"Removed empty dir: {d.relative_to(root)}")


def _rebuild_index():
    """Rebuild search index and invalidate caches."""
    global _searcher, _embedder, _graph
    _searcher = _embedder = _graph = None
    try:
        from search import WikiSearcher
        s = WikiSearcher(KB_DIR)
        s.build_index(rebuild=True)
    except Exception as e:
        logger.warning(f"Index rebuild failed: {e}")


_qa_system = None

def _get_qa_system():
    """复用 QA 实例，避免每次请求重复加载索引/模型适配器。"""
    global _qa_system
    if _qa_system is None:
        from qa import KnowledgeBaseQA
        _qa_system = KnowledgeBaseQA(KB_DIR)
    return _qa_system

# ── Search ───────────────────────────────────────────────────────

@app.route("/api/search", methods=["GET"])
def search():
    """Keyword + semantic hybrid search or QA generation."""
    if not _feature_enabled("chat"):
        return _feature_disabled_response("chat")
    q = request.args.get("q", "").strip()
    mode = request.args.get("mode", "hybrid")  # keyword | semantic | hybrid
    limit = int(request.args.get("limit", 10))
    is_qa = request.args.get("qa", "false").lower() == "true"
    qa_mode = request.args.get("answer_mode", request.args.get("qa_mode", "extractive")).lower().strip()
    if qa_mode not in ("extractive", "llm"):
        qa_mode = "extractive"

    if not q:
        return jsonify({"error": "Empty query"}), 400

    if is_qa:
        try:
            qa_sys = _get_qa_system()
            # Model-generated answers can be wrong or stale; keep caching only for deterministic extractive answers.
            result = qa_sys.answer_question(q, max_docs=4, use_cache=(qa_mode == "extractive"), answer_mode=qa_mode)
            # 兼容前端预期格式
            return jsonify({
                "query": q,
                "answer": result.get("answer", "未能生成答案。"),
                "documents": result.get("documents", []),
                "citations": result.get("citations", []),
                "latency": result.get("latency"),
                "cache_hit": result.get("cache_hit", False),
                "context_preview": result.get("context_preview", ""),
                "diagnostics": result.get("diagnostics", {}),
                "answer_mode": result.get("answer_mode", ""),
                "response_language": result.get("response_language", ""),
                "llm": result.get("llm"),
            })
        except Exception as e:
            logger.error(f"QA failed: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e), "answer": f"生成答案时发生错误: {e}"}), 500

    results = []
    keyword_scores = {}
    keyword_meta = {}
    keyword_query_tokens = []

    # Keyword search
    if mode in ("keyword", "hybrid"):
        try:
            searcher = _get_searcher()
            raw = searcher.search(q, limit=limit * 2)
            if raw:
                keyword_query_tokens = raw[0].get("query_tokens") or []
            for item in raw:
                doc_path = item.get("path", "")
                if doc_path:
                    keyword_scores[doc_path] = item.get("score", 0)
                    keyword_meta[doc_path] = item
        except Exception as e:
            logger.warning(f"Keyword search failed: {e}")

    # Semantic search
    semantic_scores = {}
    if mode in ("semantic", "hybrid"):
        try:
            embedder = _get_embedder()
            searcher = _get_searcher()
            sem_raw = embedder.search(q, top_k=limit * 2)
            for doc_id, score in sem_raw:
                doc_info = searcher.doc_index.get(doc_id)
                if doc_info and "path" in doc_info:
                    semantic_scores[doc_info["path"]] = score
        except Exception as e:
            logger.warning(f"Semantic search failed: {e}")

    # Merge & deduplicate
    all_ids = set(keyword_scores.keys()) | set(semantic_scores.keys())
    merged = []
    for doc_id in all_ids:
        ks = keyword_scores.get(doc_id, 0)
        ss = semantic_scores.get(doc_id, 0)
        if mode == "keyword":
            total = ks
        elif mode == "semantic":
            total = ss
        else:  # hybrid
            total = ks * 0.4 + ss * 0.6
        merged.append((doc_id, total, ks, ss))

    merged.sort(key=lambda x: x[1], reverse=True)
    top = merged[:limit]

    # Fetch doc details
    wiki_dir = KB_DIR / "wiki"
    for doc_id, total_score, ks, ss in top:
        fpath = wiki_dir / doc_id
        if fpath.exists():
            rel = fpath.relative_to(wiki_dir)
            preview = _read_preview(fpath, 200)
            meta = keyword_meta.get(doc_id, {})
            snippets = meta.get("matched_snippets") or meta.get("highlights") or []
            results.append({
                "path": str(rel),
                "name": fpath.stem,
                "category": str(rel.parent) if str(rel.parent) != "." else "root",
                "preview": snippets[0] if snippets else preview,
                "matched_snippets": snippets[:3],
                "title": meta.get("title") or fpath.stem,
                "score_keyword": round(ks, 3),
                "score_semantic": round(ss, 3),
                "score_total": round(total_score, 3),
            })

    return jsonify({
        "query": q,
        "mode": mode,
        "diagnostics": {
            "keyword_hits": len(keyword_scores),
            "semantic_hits": len(semantic_scores),
            "query_tokens": keyword_query_tokens,
        },
        "total": len(results),
        "results": results,
    })


def _read_preview(filepath: Path, max_chars: int = 200) -> str:
    try:
        text = filepath.read_text(encoding="utf-8")
        # Skip YAML frontmatter
        if text.startswith("---"):
            parts = text.split("---", 2)
            text = parts[2].strip() if len(parts) >= 3 else text
        return text[:max_chars].replace("\n", " ").strip()
    except Exception:
        return ""

@app.route("/api/documents/url", methods=["POST"])
def upload_url():
    """Fetch and import a URL. Uses concurrent multi-source fetch with fallback."""
    if not _feature_enabled("url_import"):
        return _feature_disabled_response("url_import")
    data = request.get_json(silent=True)
    url = data.get("url", "") if data else request.form.get("url", "")
    auto_process = data.get("auto_process", True) if data else True

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        from web_collector import WebCollector
        collector = WebCollector(str(KB_DIR))

        # 用 v3 并发抓取
        ok, content, metadata = collector.fetch(url)
        if not ok:
            return jsonify({"error": content}), 500

        raw_filepath = collector.save(url, content, metadata)
        if not raw_filepath:
            return jsonify({"error": "Failed to save URL content"}), 500

        result = {
            "status": "ok",
            "source_url": url,
            "raw_path": str(raw_filepath.relative_to(KB_DIR)),
            "method_used": metadata.get("method_used", "unknown"),
        }

        if auto_process:
            try:
                importer = _get_importer()
                ok_p, msg = importer.process_file(raw_filepath)
                result["processed"] = ok_p
                result["wiki_path"] = str(msg) if ok_p else None
                result["message"] = msg if not ok_p else None
                if not ok_p:
                    result["recovery"] = _import_recovery(result["raw_path"], str(msg))
            except Exception as pe:
                logger.warning(f"Import failed after fetch: {pe}")
                result["processed"] = False
                result["message"] = f"抓取成功但处理失败: {pe}"
                result["recovery"] = _import_recovery(result["raw_path"], str(pe))

        _rebuild_index()
        return jsonify(result)
    except Exception as e:
        logger.error(f"URL fetch error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/documents/<path:relpath>", methods=["GET"])
def get_document(relpath: str):
    """Get full document content."""
    wiki_file = (KB_DIR / "wiki" / relpath).resolve()
    if not str(wiki_file).startswith(str(KB_DIR.resolve())):
        return jsonify({"error": "Path traversal denied"}), 403
    if not wiki_file.exists():
        return jsonify({"error": "Not found"}), 404

    content = wiki_file.read_text(encoding="utf-8")
    meta, _body = _split_frontmatter(content)
    quality = _quality_status_for_content(content)
    llm_meta = meta.get("llm") if isinstance(meta.get("llm"), dict) else {}
    full_translation_meta = meta.get("llm_full_translation") if isinstance(meta.get("llm_full_translation"), dict) else {}
    retranslation_meta = meta.get("llm_retranslation") if isinstance(meta.get("llm_retranslation"), dict) else {}
    quality_repair_meta = meta.get("quality_repair") if isinstance(meta.get("quality_repair"), dict) else {}
    related_docs = []
    association_meta = None
    try:
        report_path = KB_DIR / "reports" / "knowledge-associations-latest.json"
        if not report_path.exists():
            from association_report import build_report
            assoc_report = build_report(KB_DIR)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(assoc_report, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            assoc_report = json.loads(report_path.read_text(encoding="utf-8"))
        doc_assoc = next((d for d in assoc_report.get("docs", []) if d.get("path") == relpath), None)
        if doc_assoc:
            related_docs = doc_assoc.get("related", [])
            association_meta = {
                "incoming_count": doc_assoc.get("incoming_count", 0),
                "outgoing_count": doc_assoc.get("outgoing_count", 0),
                "related_count": doc_assoc.get("related_count", len(related_docs)),
                "entities": doc_assoc.get("entities", []),
                "tags": doc_assoc.get("tags", []),
                "link_suggestions": doc_assoc.get("link_suggestions", []),
            }
    except Exception as e:
        logger.warning(f"Load associations for {relpath} failed: {e}")
    return jsonify({
        "path": relpath,
        "name": wiki_file.stem,
        "content": content,
        "meta": {
            "title": str(meta.get("title") or wiki_file.stem),
            "category": str(meta.get("category") or wiki_file.parent.name),
            "quality": quality,
            "llm": llm_meta,
            "llm_full_translation": full_translation_meta,
            "llm_retranslation": retranslation_meta,
            "quality_repair": quality_repair_meta,
        },
        "size_kb": round(wiki_file.stat().st_size / 1024, 1),
        "modified": datetime.fromtimestamp(wiki_file.stat().st_mtime, tz=timezone.utc).isoformat(),
        "related": related_docs,
        "association": association_meta,
    })


@app.route("/api/quality", methods=["GET"])
def quality_report():
    wiki_dir = KB_DIR / "wiki"
    items = []
    for f in wiki_dir.rglob("*.md"):
        rel = f.relative_to(wiki_dir)
        if _is_generated_wiki_page(rel):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        q = _quality_status_for_content(text)
        if not q["ok"] or request.args.get("all", "false").lower() == "true":
            items.append({"path": str(rel), "name": rel.stem, "quality": q})
    return jsonify({"total": len(items), "bad": sum(1 for x in items if not x["quality"]["ok"]), "items": items})


@app.route("/api/documents/<path:relpath>/repair-quality", methods=["POST"])
def repair_document_quality(relpath: str):
    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get("dry_run"))
    wiki_file = (KB_DIR / "wiki" / relpath).resolve()
    if not str(wiki_file).startswith(str((KB_DIR / "wiki").resolve())):
        return jsonify({"error": "Path traversal denied"}), 403
    if not wiki_file.exists():
        return jsonify({"error": "Not found"}), 404
    text = wiki_file.read_text(encoding="utf-8", errors="ignore")
    before = _quality_status_for_content(text)
    sections = _generate_quality_sections(text)
    new_text = text
    if 'summary_placeholder' in before['issues']:
        new_text = _replace_section(new_text, '📝 摘要', sections['summary'])
    if 'keypoints_placeholder' in before['issues']:
        new_text = _replace_section(new_text, '🔑 关键点', sections['keypoints'])
    if 'entities_placeholder' in before['issues']:
        new_text = _replace_section(new_text, '🏷️ 实体与概念', sections['entities'])
    changed = new_text != text
    if changed and not dry_run:
        new_text = _upsert_frontmatter_mapping(new_text, "quality_repair", {
            "method": "rule_based",
            "issues": before.get("issues", []),
            "status": "ok",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        wiki_file.write_text(new_text, encoding="utf-8")
        _rebuild_index()
    after = _quality_status_for_content(new_text)
    return jsonify({
        "path": relpath,
        "changed": changed,
        "dry_run": dry_run,
        "before": before,
        "after": after,
        "sections": sections if dry_run else None,
    })


@app.route("/api/translation/models", methods=["GET"])
def translation_models():
    return jsonify({"models": _translation_models()})


def _load_llm_runtime_raw() -> Dict[str, Any]:
    if not LLM_RUNTIME_CONFIG.exists():
        raise FileNotFoundError(f"LLM runtime config not found: {LLM_RUNTIME_CONFIG}")
    data = yaml.safe_load(LLM_RUNTIME_CONFIG.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("LLM runtime config must be a mapping")
    return data


def _provider_type_sets(raw: Dict[str, Any]) -> tuple[set[str], set[str]]:
    local = set()
    online = set()
    for name, data in (raw.get("providers") or {}).items():
        if data.get("type") == "openai_compatible" or data.get("api_key_env"):
            online.add(name)
        else:
            local.add(name)
    return local, online


def _infer_llm_deployment_mode(raw: Dict[str, Any]) -> str:
    local, online = _provider_type_sets(raw)
    used = set()
    for data in (raw.get("flows") or {}).values():
        used.update(data.get("providers") or [])
    if used and used.issubset(local):
        return "local"
    if used and used.issubset(online):
        return "online"
    return "hybrid"


def _apply_llm_deployment_mode(raw: Dict[str, Any], mode: str) -> Dict[str, Any]:
    if mode not in LLM_DEPLOYMENT_MODES:
        raise ValueError("mode must be local, online, or hybrid")
    providers = raw.get("providers") or {}
    if "local_gemma4" not in providers:
        raise ValueError("local_gemma4 provider is required for deployment mode presets")
    if mode in {"online", "hybrid"} and not {"deepseek_flash", "deepseek_pro"}.issubset(providers.keys()):
        raise ValueError("deepseek_flash and deepseek_pro providers are required for online/hybrid mode")

    cleaned = copy_llm_runtime(raw)
    flows = cleaned.get("flows") or {}

    def set_flow(name: str, providers_chain: List[str], *, allow_online: bool, allow_fallback: bool, intent: str, notes: str, fallback_notice: str = "record") -> None:
        if name not in flows:
            return
        flows[name]["providers"] = providers_chain
        flows[name]["allow_online"] = allow_online
        flows[name]["allow_fallback"] = allow_fallback
        flows[name]["intent"] = intent
        flows[name]["notes"] = notes
        flows[name]["fallback_notice"] = fallback_notice

    if mode == "local":
        for name in list(flows.keys()):
            set_flow(
                name,
                ["local_gemma4"],
                allow_online=False,
                allow_fallback=False,
                intent="local_only",
                notes="Deployment preset: pure local. Uses local_gemma4 only; no online calls.",
                fallback_notice="none",
            )
    elif mode == "online":
        flash_flows = {
            "url_import_structure", "file_import_structure", "candidate_preview", "candidate_quality_check",
            "entity_extraction", "processor_summary", "processor_keypoints", "processor_category",
            "maintenance_links",
        }
        for name in list(flows.keys()):
            provider = "deepseek_flash" if name in flash_flows else "deepseek_pro"
            set_flow(
                name,
                [provider],
                allow_online=True,
                allow_fallback=False,
                intent="online_only",
                notes="Deployment preset: pure online. Requires DEEPSEEK_API_KEY and does not fall back to local.",
                fallback_notice="required",
            )
    else:
        for name in ["url_import_structure", "file_import_structure", "entity_extraction", "processor_summary", "processor_keypoints", "processor_category"]:
            set_flow(
                name,
                ["local_gemma4", "deepseek_flash"],
                allow_online=True,
                allow_fallback=True,
                intent="cost_first",
                notes="Deployment preset: hybrid. Bulk work uses local first, DeepSeek Flash fallback.",
            )
        set_flow(
            "candidate_preview",
            ["local_gemma4", "deepseek_flash"],
            allow_online=True,
            allow_fallback=True,
            intent="volume_first",
            notes="Deployment preset: hybrid. Candidate previews are local first with online fallback.",
        )
        set_flow(
            "candidate_quality_check",
            ["local_gemma4", "deepseek_flash"],
            allow_online=True,
            allow_fallback=True,
            intent="balanced",
            notes="Deployment preset: hybrid. Quality checks are local first with online fallback.",
        )
        for name in ["full_translation", "retranslation"]:
            set_flow(
                name,
                ["deepseek_pro", "local_gemma4"],
                allow_online=True,
                allow_fallback=False,
                intent="quality_first",
                notes="Deployment preset: hybrid. Quality-sensitive translation is online first; explicit local selection remains available.",
                fallback_notice="required",
            )
        set_flow(
            "qa",
            ["local_gemma4", "deepseek_pro"],
            allow_online=True,
            allow_fallback=True,
            intent="user_selectable",
            notes="Deployment preset: hybrid. QA defaults local and can fall back online for hard questions.",
        )
        set_flow(
            "maintenance_links",
            ["local_gemma4"],
            allow_online=False,
            allow_fallback=False,
            intent="rules_first",
            notes="Deployment preset: hybrid. Link maintenance stays local/rules-first.",
            fallback_notice="none",
        )
    return cleaned


def copy_llm_runtime(raw: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(raw, ensure_ascii=False))


def _write_llm_runtime_config(cleaned: Dict[str, Any]) -> None:
    tmp = LLM_RUNTIME_CONFIG.with_suffix(".yaml.tmp")
    header = "# Non-sensitive runtime configuration for LLM calls.\n# Do not store API keys in this file. Use api_key_env to name the environment variable.\n\n"
    tmp.write_text(header + yaml.safe_dump(cleaned, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(LLM_RUNTIME_CONFIG)


def _llm_config_payload() -> Dict[str, Any]:
    from llm_service import LLMConfig

    raw = _load_llm_runtime_raw()
    config = LLMConfig(LLM_RUNTIME_CONFIG)
    provider_status = {p["name"]: p for p in config.provider_status()}
    providers = []
    for name, data in (raw.get("providers") or {}).items():
        status = provider_status.get(name, {})
        providers.append({
            "name": name,
            "type": data.get("type", ""),
            "label": data.get("label", name),
            "model": data.get("model", ""),
            "base_url": data.get("base_url", ""),
            "api_key_env": data.get("api_key_env", ""),
            "timeout_sec": int(data.get("timeout_sec", 60)),
            "options": data.get("options") or {},
            "online": bool(status.get("online")),
            "secret_configured": bool(status.get("secret_configured")),
        })
    flows = []
    for name, data in (raw.get("flows") or {}).items():
        flows.append({
            "name": name,
            "label": data.get("label", name),
            "providers": data.get("providers") or [],
            "allow_fallback": bool(data.get("allow_fallback", True)),
            "allow_online": bool(data.get("allow_online", True)),
            "fallback_notice": data.get("fallback_notice", "record"),
            "chunk_chars": int(data.get("chunk_chars", 4000)),
            "intent": data.get("intent", "balanced"),
            "notes": data.get("notes", ""),
            "options": data.get("options") or {},
        })
    return {
        "version": raw.get("version", 1),
        "mode": _infer_llm_deployment_mode(raw),
        "mode_options": [
            {"id": key, **value} for key, value in LLM_DEPLOYMENT_MODES.items()
        ],
        "config_path": str(LLM_RUNTIME_CONFIG),
        "secret_setup": _llm_secret_setup_payload(),
        "providers": providers,
        "flows": flows,
    }


def _llm_secret_setup_payload() -> Dict[str, Any]:
    env_exists = LLM_SECRET_ENV_FILE.exists()
    mode = None
    if env_exists:
        mode = oct(LLM_SECRET_ENV_FILE.stat().st_mode & 0o777)
    return {
        "env_file": str(LLM_SECRET_ENV_FILE),
        "env_file_exists": env_exists,
        "env_file_mode": mode,
        "systemd_dropin": str(LLM_SYSTEMD_DROPIN),
        "systemd_dropin_exists": LLM_SYSTEMD_DROPIN.exists(),
        "install_script": str(LLM_SECRET_INSTALL_SCRIPT),
        "install_command": f"cd {KB_DIR} && ./scripts/install_llm_env.sh",
    }


def _clean_llm_config_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    current = _load_llm_runtime_raw()
    providers_in = payload.get("providers")
    flows_in = payload.get("flows")
    if not isinstance(providers_in, list) or not isinstance(flows_in, list):
        raise ValueError("providers and flows must be arrays")

    provider_names = set()
    providers: Dict[str, Dict[str, Any]] = {}
    for item in providers_in:
        if not isinstance(item, dict):
            raise ValueError("provider item must be an object")
        name = str(item.get("name", "")).strip()
        if not re.match(r"^[A-Za-z0-9_-]+$", name):
            raise ValueError(f"invalid provider name: {name}")
        if name in provider_names:
            raise ValueError(f"duplicate provider name: {name}")
        provider_names.add(name)
        provider_type = str(item.get("type", "")).strip()
        if provider_type not in {"ollama", "openai_compatible"}:
            raise ValueError(f"unsupported provider type for {name}: {provider_type}")
        safe = {
            "type": provider_type,
            "label": str(item.get("label", name)).strip() or name,
            "model": str(item.get("model", "")).strip(),
            "base_url": str(item.get("base_url", "")).strip(),
            "timeout_sec": max(1, int(item.get("timeout_sec") or 60)),
            "options": item.get("options") if isinstance(item.get("options"), dict) else {},
        }
        api_key_env = str(item.get("api_key_env", "")).strip()
        if api_key_env:
            if not re.match(r"^[A-Z][A-Z0-9_]*$", api_key_env):
                raise ValueError(f"invalid api_key_env for {name}: {api_key_env}")
            safe["api_key_env"] = api_key_env
        providers[name] = safe

    flows: Dict[str, Dict[str, Any]] = {}
    for item in flows_in:
        if not isinstance(item, dict):
            raise ValueError("flow item must be an object")
        name = str(item.get("name", "")).strip()
        if not re.match(r"^[A-Za-z0-9_-]+$", name):
            raise ValueError(f"invalid flow name: {name}")
        selected = [str(p).strip() for p in (item.get("providers") or []) if str(p).strip()]
        unknown = [p for p in selected if p not in provider_names]
        if unknown:
            raise ValueError(f"flow {name} references unknown provider(s): {', '.join(unknown)}")
        if not selected:
            raise ValueError(f"flow {name} must include at least one provider")
        flows[name] = {
            "label": str(item.get("label", name)).strip() or name,
            "providers": selected,
            "allow_fallback": bool(item.get("allow_fallback", True)),
            "allow_online": bool(item.get("allow_online", True)),
            "fallback_notice": str(item.get("fallback_notice", "record")).strip() or "record",
            "chunk_chars": max(1, int(item.get("chunk_chars") or 4000)),
            "intent": str(item.get("intent", "balanced")).strip() or "balanced",
            "notes": str(item.get("notes", "")).strip(),
            "options": item.get("options") if isinstance(item.get("options"), dict) else {},
        }

    return {
        "version": current.get("version", 1),
        "providers": providers,
        "flows": flows,
    }


def _backup_llm_runtime_config(reason: str = "manual") -> Optional[Path]:
    if not LLM_RUNTIME_CONFIG.exists():
        return None
    LLM_CONFIG_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    safe_reason = re.sub(r"[^A-Za-z0-9_-]+", "-", reason).strip("-")[:32] or "manual"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = LLM_CONFIG_BACKUP_DIR / f"llm_runtime_{stamp}_{safe_reason}.yaml"
    shutil.copy2(LLM_RUNTIME_CONFIG, backup)
    return backup


def _llm_config_backups() -> List[Dict[str, Any]]:
    if not LLM_CONFIG_BACKUP_DIR.exists():
        return []
    items = []
    for path in sorted(LLM_CONFIG_BACKUP_DIR.glob("llm_runtime_*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = path.stat()
        items.append({
            "name": path.name,
            "path": str(path.relative_to(KB_DIR)),
            "size_bytes": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    return items[:30]


def _llm_audit_payload() -> Dict[str, Any]:
    wiki_dir = KB_DIR / "wiki"
    items: List[Dict[str, Any]] = []
    by_flow: Counter = Counter()
    by_provider: Counter = Counter()
    by_model: Counter = Counter()
    by_status: Counter = Counter()
    by_translation_provider: Counter = Counter()
    by_translation_model: Counter = Counter()
    missing = 0
    fallback_count = 0
    full_translation_count = 0
    retranslated_count = 0
    translation_legacy_count = 0
    quality_repair_count = 0

    for path in sorted(wiki_dir.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        rel = path.relative_to(wiki_dir)
        if _is_generated_wiki_page(rel):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        meta, _body = _split_frontmatter(text)
        llm = meta.get("llm") if isinstance(meta.get("llm"), dict) else {}
        full_translation = meta.get("llm_full_translation") if isinstance(meta.get("llm_full_translation"), dict) else {}
        retranslation = meta.get("llm_retranslation") if isinstance(meta.get("llm_retranslation"), dict) else {}
        translation_legacy = meta.get("llm_translation_legacy") if isinstance(meta.get("llm_translation_legacy"), dict) else {}
        quality_repair = meta.get("quality_repair") if isinstance(meta.get("quality_repair"), dict) else {}
        if not llm:
            missing += 1
        else:
            flow = str(llm.get("flow") or "unknown")
            provider = str(llm.get("provider") or "unknown")
            model = str(llm.get("model") or "unknown")
            status = str(llm.get("status") or "unknown")
            by_flow[flow] += 1
            by_provider[provider] += 1
            by_model[model] += 1
            by_status[status] += 1
            if llm.get("fallback_from") or llm.get("fallback_to"):
                fallback_count += 1
        if full_translation:
            full_translation_count += 1
            by_translation_provider[str(full_translation.get("provider") or "unknown")] += 1
            by_translation_model[str(full_translation.get("model") or "unknown")] += 1
        if retranslation:
            retranslated_count += 1
        if quality_repair:
            quality_repair_count += 1
        if translation_legacy:
            translation_legacy_count += 1
            by_translation_provider[str(translation_legacy.get("provider") or "unknown")] += 1
            by_translation_model[str(translation_legacy.get("model") or "unknown")] += 1
        st = path.stat()
        generation_chain = []
        if llm:
            generation_chain.append({"type": "import", "flow": llm.get("flow"), "provider": llm.get("provider"), "model": llm.get("model"), "status": llm.get("status")})
        if full_translation:
            generation_chain.append({"type": "full_translation", "flow": full_translation.get("flow"), "provider": full_translation.get("provider"), "model": full_translation.get("model"), "status": full_translation.get("status"), "target_language": full_translation.get("target_language")})
        if retranslation:
            generation_chain.append({"type": "retranslation", "flow": retranslation.get("flow"), "provider": retranslation.get("provider"), "model": retranslation.get("model"), "status": retranslation.get("status")})
        if quality_repair:
            generation_chain.append({"type": "quality_repair", "method": quality_repair.get("method"), "status": quality_repair.get("status"), "issues": quality_repair.get("issues", [])})
        if translation_legacy:
            generation_chain.append({"type": "legacy_translation", "provider": translation_legacy.get("provider"), "model": translation_legacy.get("model")})
        items.append({
            "path": str(rel),
            "title": str(meta.get("title") or rel.stem),
            "category": str(meta.get("category") or rel.parent),
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "llm": llm,
            "llm_full_translation": full_translation,
            "llm_retranslation": retranslation,
            "llm_translation_legacy": translation_legacy,
            "quality_repair": quality_repair,
            "generation_chain": generation_chain,
        })

    total = len(items)
    return {
        "total": total,
        "with_llm": total - missing,
        "missing_llm": missing,
        "coverage": round((total - missing) / total, 3) if total else 0,
        "fallback_count": fallback_count,
        "full_translation_count": full_translation_count,
        "retranslated_count": retranslated_count,
        "translation_legacy_count": translation_legacy_count,
        "quality_repair_count": quality_repair_count,
        "by_flow": dict(by_flow.most_common()),
        "by_provider": dict(by_provider.most_common()),
        "by_model": dict(by_model.most_common()),
        "by_status": dict(by_status.most_common()),
        "by_translation_provider": dict(by_translation_provider.most_common()),
        "by_translation_model": dict(by_translation_model.most_common()),
        "items": items[:200],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _llm_audit_filters_from_request() -> Dict[str, Any]:
    return {
        "flow": (request.args.get("flow") or "").strip(),
        "provider": (request.args.get("provider") or "").strip(),
        "model": (request.args.get("model") or "").strip(),
        "status": (request.args.get("status") or "").strip(),
        "missing": request.args.get("missing", "").lower() in {"1", "true", "yes"},
        "fallback": request.args.get("fallback", "").lower() in {"1", "true", "yes"},
        "retranslated": request.args.get("retranslated", "").lower() in {"1", "true", "yes"},
    }


def _apply_llm_audit_filters(payload: Dict[str, Any], filters: Dict[str, Any]) -> Dict[str, Any]:
    def match(item: Dict[str, Any]) -> bool:
        llm = item.get("llm") if isinstance(item.get("llm"), dict) else {}
        retr = item.get("llm_retranslation") if isinstance(item.get("llm_retranslation"), dict) else {}
        if filters.get("flow") and str(llm.get("flow") or "") != filters["flow"]:
            return False
        if filters.get("provider") and str(llm.get("provider") or "") != filters["provider"]:
            return False
        if filters.get("model") and str(llm.get("model") or "") != filters["model"]:
            return False
        if filters.get("status") and str(llm.get("status") or "") != filters["status"]:
            return False
        if filters.get("missing") and llm:
            return False
        if filters.get("fallback") and not (llm.get("fallback_from") or llm.get("fallback_to")):
            return False
        if filters.get("retranslated") and not retr:
            return False
        return True

    filtered = [item for item in payload.get("items", []) if match(item)]
    filtered_payload = dict(payload)
    filtered_payload["items"] = filtered[:200]
    filtered_payload["filtered_total"] = len(filtered)
    filtered_payload["filters"] = {k: v for k, v in filters.items() if v}
    return filtered_payload


def _llm_audit_csv_response(payload: Dict[str, Any]) -> Response:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["path", "title", "category", "modified", "flow", "provider", "model", "status", "fallback_from", "fallback_to", "full_translation_provider", "full_translation_model", "full_translation_target", "retranslation_provider", "retranslation_model", "quality_repair_method", "quality_repair_issues", "generation_chain"])
    for item in payload.get("items", []):
        llm = item.get("llm") if isinstance(item.get("llm"), dict) else {}
        full = item.get("llm_full_translation") if isinstance(item.get("llm_full_translation"), dict) else {}
        retr = item.get("llm_retranslation") if isinstance(item.get("llm_retranslation"), dict) else {}
        repair = item.get("quality_repair") if isinstance(item.get("quality_repair"), dict) else {}
        writer.writerow([
            item.get("path", ""),
            item.get("title", ""),
            item.get("category", ""),
            item.get("modified", ""),
            llm.get("flow", ""),
            llm.get("provider", ""),
            llm.get("model", ""),
            llm.get("status", ""),
            llm.get("fallback_from", ""),
            llm.get("fallback_to", ""),
            full.get("provider", ""),
            full.get("model", ""),
            full.get("target_language", ""),
            retr.get("provider", ""),
            retr.get("model", ""),
            repair.get("method", ""),
            "|".join(str(x) for x in (repair.get("issues") or [])),
            "|".join(str(x.get("type", "")) for x in (item.get("generation_chain") or [])),
        ])
    return Response(
        out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=llm-audit.csv"},
    )


@app.route("/api/llm/config", methods=["GET"])
def get_llm_config():
    if not _feature_enabled("llm_settings"):
        return _feature_disabled_response("llm_settings")
    try:
        return jsonify(_llm_config_payload())
    except Exception as e:
        logger.error(f"Load LLM config failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/llm/config", methods=["PATCH"])
def update_llm_config():
    if not _feature_enabled("llm_settings"):
        return _feature_disabled_response("llm_settings")
    data = request.get_json(silent=True) or {}
    try:
        cleaned = _clean_llm_config_update(data)
        backup = _backup_llm_runtime_config("before-webui-save")
        _write_llm_runtime_config(cleaned)
        logger.info("LLM runtime config updated from WebUI")
        payload = _llm_config_payload()
        payload["backup"] = str(backup.relative_to(KB_DIR)) if backup else None
        payload["backups"] = _llm_config_backups()
        return jsonify(payload)
    except Exception as e:
        logger.error(f"Update LLM config failed: {e}")
        return jsonify({"error": str(e)}), 400


@app.route("/api/llm/mode", methods=["POST"])
def set_llm_mode():
    if not _feature_enabled("llm_settings"):
        return _feature_disabled_response("llm_settings")
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode") or "").strip().lower()
    try:
        raw = _load_llm_runtime_raw()
        cleaned = _apply_llm_deployment_mode(raw, mode)
        backup = _backup_llm_runtime_config(f"before-mode-{mode}")
        _write_llm_runtime_config(cleaned)
        payload = _llm_config_payload()
        payload["backup"] = str(backup.relative_to(KB_DIR)) if backup else None
        payload["backups"] = _llm_config_backups()
        logger.info(f"LLM deployment mode changed from WebUI: {mode}")
        return jsonify(payload)
    except Exception as e:
        logger.error(f"Set LLM deployment mode failed: {e}")
        return jsonify({"error": str(e)}), 400


@app.route("/api/llm/config/backups", methods=["GET"])
def list_llm_config_backups():
    if not _feature_enabled("llm_settings"):
        return _feature_disabled_response("llm_settings")
    return jsonify({"backups": _llm_config_backups()})


@app.route("/api/llm/config/backups/<path:backup_name>/restore", methods=["POST"])
def restore_llm_config_backup(backup_name: str):
    if not _feature_enabled("llm_settings"):
        return _feature_disabled_response("llm_settings")
    try:
        if "/" in backup_name or "\\" in backup_name or not backup_name.startswith("llm_runtime_") or not backup_name.endswith(".yaml"):
            return jsonify({"error": "invalid backup name"}), 400
        backup = (LLM_CONFIG_BACKUP_DIR / backup_name).resolve()
        if not str(backup).startswith(str(LLM_CONFIG_BACKUP_DIR.resolve())) or not backup.exists():
            return jsonify({"error": "backup not found"}), 404
        _backup_llm_runtime_config("before-restore")
        candidate = yaml.safe_load(backup.read_text(encoding="utf-8")) or {}
        if not isinstance(candidate, dict) or "providers" not in candidate or "flows" not in candidate:
            return jsonify({"error": "backup is not a valid LLM runtime config"}), 400
        shutil.copy2(backup, LLM_RUNTIME_CONFIG)
        payload = _llm_config_payload()
        payload["restored_from"] = backup.name
        payload["backups"] = _llm_config_backups()
        logger.info(f"LLM runtime config restored from backup: {backup.name}")
        return jsonify(payload)
    except Exception as e:
        logger.error(f"Restore LLM config backup failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/llm/audit", methods=["GET"])
def llm_audit():
    if not _feature_enabled("llm_audit"):
        return _feature_disabled_response("llm_audit")
    try:
        payload = _apply_llm_audit_filters(_llm_audit_payload(), _llm_audit_filters_from_request())
        if (request.args.get("format") or "").lower() == "csv":
            return _llm_audit_csv_response(payload)
        return jsonify(payload)
    except Exception as e:
        logger.error(f"Load LLM audit failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/translation/backfill", methods=["GET", "POST"])
def translation_backfill():
    """Audit or safely backfill missing opposite-language full translations."""
    if not _feature_enabled("llm_audit"):
        return _feature_disabled_response("llm_audit")
    try:
        from translation_backfill import audit_backfill, run_backfill

        if request.method == "GET":
            limit = max(1, min(int(request.args.get("limit") or 50), 200))
            paths = request.args.getlist("path") or None
            return jsonify(audit_backfill(KB_DIR, limit=limit, paths=paths))

        data = request.get_json(silent=True) or {}
        limit = max(1, min(int(data.get("limit") or 5), 20))
        dry_run = bool(data.get("dry_run", True))
        provider_name = str(data.get("provider") or "").strip()
        paths_in = data.get("paths") or ([data.get("path")] if data.get("path") else None)
        paths = [str(p) for p in paths_in if str(p).strip()] if isinstance(paths_in, list) else None
        result = run_backfill(
            KB_DIR,
            limit=limit,
            dry_run=dry_run,
            provider_name=provider_name,
            paths=paths,
        )
        if result.get("applied"):
            _rebuild_index()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Translation backfill failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/llm/providers/<provider_name>/test", methods=["POST"])
def test_llm_provider(provider_name: str):
    if not _feature_enabled("llm_settings"):
        return _feature_disabled_response("llm_settings")
    try:
        from llm_service import LLMService
        service = LLMService()
        service.config.provider(provider_name)
        result = service.chat(
            "qa",
            [{"role": "user", "content": "Reply with exactly: OK"}],
            provider_name=provider_name,
            options={"temperature": 0, "think": False, "num_predict": 16, "max_tokens": 16},
        )
        payload = result.to_dict()
        payload["ok"] = result.status == "ok"
        payload["content_preview"] = (result.content or "")[:120]
        payload.pop("content", None)
        return jsonify(payload), 200 if result.status == "ok" else 500
    except Exception as e:
        logger.error(f"Test LLM provider failed: {provider_name}: {e}")
        return jsonify({"ok": False, "provider": provider_name, "status": "error", "error": str(e)}), 500


@app.route("/api/documents/<path:relpath>/translate", methods=["POST"])
def retranslate_document(relpath: str):
    wiki_file = (KB_DIR / "wiki" / relpath).resolve()
    if not str(wiki_file).startswith(str((KB_DIR / "wiki").resolve())):
        return jsonify({"error": "Path traversal denied"}), 403
    if not wiki_file.exists():
        return jsonify({"error": "Not found"}), 404

    data = request.get_json(silent=True) or {}
    provider_name = (data.get("provider") or "deepseek_pro").strip()
    try:
        resolved_provider = _resolve_translation_provider(provider_name)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    model = (data.get("model") or "").strip()
    dry_run = bool(data.get("dry_run"))

    try:
        old_text = wiki_file.read_text(encoding="utf-8", errors="ignore")
        result = _translate_wiki_document(old_text, provider_name=resolved_provider, model=model)
        new_text = _replace_frontmatter_value(old_text, "title", result["title"])
        new_text = _replace_h1(new_text, result["title"])
        if result.get("category"):
            new_text = _replace_frontmatter_value(new_text, "category", result["category"])
            new_text = re.sub(r"(?m)^>\s*\*\*分类\*\*:\s*.*$", f"> **分类**: {result['category']}", new_text)
        if result.get("summary"):
            new_text = _replace_section(new_text, "📝 摘要", result["summary"])
        if result.get("keypoints"):
            new_text = _replace_section(new_text, "🔑 关键点", result["keypoints"])
        if result.get("entities"):
            new_text = _replace_section(new_text, "🏷️ 实体与概念", result["entities"])
        target_language = result.get("target_language") or "zh"
        translation_section = "🌍 English Translation" if target_language == "en" else "🌐 中文翻译"
        if result.get("translation"):
            new_text = _replace_section(new_text, translation_section, result["translation"])
        stamp_provider = f"{result['provider']} / {result['model'] or 'default'}"
        stamp = f"> **翻译模型**: {stamp_provider}\n> **重新翻译时间**: {datetime.now(timezone.utc).isoformat()}\n> **源语言**: {result.get('source_language', 'unknown')}\n> **目标语言**: {target_language}"
        if f"## {translation_section}" in new_text:
            new_text = re.sub(r"(## " + re.escape(translation_section) + r"\s*\n)", r"\1\n" + stamp + "\n\n", new_text, count=1)
        new_text = _upsert_frontmatter_mapping(new_text, "llm_retranslation", {
            "flow": "retranslation",
            "provider": result.get("provider", ""),
            "model": result.get("model", ""),
            "status": result.get("llm_result", {}).get("status", "ok"),
            "duration_sec": result.get("llm_result", {}).get("duration_sec"),
            "chunk_count": result.get("chunk_count", len(result.get("llm_chunks", []))),
            "chunks": result.get("llm_chunks", []),
            "source_language": result.get("source_language", ""),
            "target_language": target_language,
            "chunk_failures": result.get("chunk_failures", []),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        if not dry_run:
            wiki_file.write_text(new_text, encoding="utf-8")
            _rebuild_index()
        return jsonify({
            "path": relpath,
            "title": result["title"],
            "provider": result["provider"],
            "model": result["model"],
            "source_language": result.get("source_language", ""),
            "target_language": target_language,
            "dry_run": dry_run,
            "changed": new_text != old_text,
            "size_kb": round((len(new_text.encode("utf-8")) if dry_run else wiki_file.stat().st_size) / 1024, 1),
            "preview": {
                "summary": result.get("summary", "")[:260],
                "keypoints": result.get("keypoints", "")[:360],
                "entities": result.get("entities", "")[:220],
                "translation": result.get("translation", "")[:500],
            } if dry_run else None,
            "llm": result.get("llm_result", {}),
            "chunk_count": result.get("chunk_count", len(result.get("llm_chunks", []))),
            "chunk_failures": result.get("chunk_failures", []),
        })
    except Exception as e:
        logger.error(f"Retranslate failed for {relpath}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/quality/repair", methods=["POST"])
def repair_all_quality():
    data = request.get_json(silent=True) or {}
    limit = int(data.get("limit") or 20)
    dry_run = bool(data.get("dry_run"))
    wiki_dir = KB_DIR / "wiki"
    results = []
    for f in wiki_dir.rglob("*.md"):
        rel = f.relative_to(wiki_dir)
        if _is_generated_wiki_page(rel):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        q = _quality_status_for_content(text)
        if q["ok"]:
            continue
        sections = _generate_quality_sections(text)
        new_text = text
        if 'summary_placeholder' in q['issues']:
            new_text = _replace_section(new_text, '📝 摘要', sections['summary'])
        if 'keypoints_placeholder' in q['issues']:
            new_text = _replace_section(new_text, '🔑 关键点', sections['keypoints'])
        if 'entities_placeholder' in q['issues']:
            new_text = _replace_section(new_text, '🏷️ 实体与概念', sections['entities'])
        changed = new_text != text
        if changed and not dry_run:
            new_text = _upsert_frontmatter_mapping(new_text, "quality_repair", {
                "method": "rule_based",
                "issues": q.get("issues", []),
                "status": "ok",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            })
            f.write_text(new_text, encoding="utf-8")
        results.append({
            "path": str(rel),
            "changed": changed,
            "before": q,
            "after": _quality_status_for_content(new_text),
            "sections": sections if dry_run else None,
        })
        if len(results) >= limit:
            break
    if results and not dry_run:
        _rebuild_index()
    return jsonify({"repaired": len(results), "planned": len(results), "dry_run": dry_run, "results": results})


# ── Stats ────────────────────────────────────────────────────────

@app.route("/api/stats", methods=["GET"])
def stats():
    """Overall knowledge base statistics."""
    wiki_dir = KB_DIR / "wiki"
    raw_dir = KB_DIR / "raw"

    wiki_files = list(wiki_dir.rglob("*.md"))
    real_wiki_files = [f for f in wiki_files if not _is_generated_wiki_page(f.relative_to(wiki_dir))]
    generated_wiki_files = [f for f in wiki_files if _is_generated_wiki_page(f.relative_to(wiki_dir))]
    raw_files = [
        f for f in raw_dir.rglob("*")
        if f.is_file() and not any(part.startswith(".") for part in f.relative_to(raw_dir).parts)
    ]

    categories = {}
    for f in real_wiki_files:
        rel = f.relative_to(wiki_dir)
        cat = str(rel.parent) if str(rel.parent) != "." else "root"
        categories[cat] = categories.get(cat, 0) + 1

    total_size = sum(f.stat().st_size for f in real_wiki_files)

    # Search index stats
    idx_stats = {}
    try:
        idx_path = KB_DIR / "search_index.json"
        if idx_path.exists():
            with open(idx_path) as fh:
                idx = json.load(fh)
            idx_stats = {
                "documents": len(idx.get("doc_index", {})),
                "terms": len(idx.get("fulltext_index", {})),
                "entities": len(idx.get("entity_index", {})),
            }
    except Exception:
        pass

    return jsonify({
        "wiki_documents": len(real_wiki_files),
        "real_wiki_documents": len(real_wiki_files),
        "generated_wiki_pages": len(generated_wiki_files),
        "total_wiki_files": len(wiki_files),
        "raw_files": len(raw_files),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "categories": categories,
        "search_index": idx_stats,
    })


# ── Knowledge graph ──────────────────────────────────────────────

@app.route("/api/graph", methods=["GET"])
def graph_data():
    """Return graph JSON for ECharts/Force-Graph visualization."""
    if not _feature_enabled("graph"):
        return _feature_disabled_response("graph")
    entity = request.args.get("entity", "")
    mode = request.args.get("mode", "full")  # full | neighbors
    limit = int(request.args.get("limit", 50))  # top N nodes
    try:
        g = _get_graph()
        if entity and mode == "neighbors":
            data = g.get_entity_neighbors(entity, depth=1, max_nodes=60)
        elif entity:
            matches = g.search_entities(entity, limit=1)
            if matches:
                data = g.get_entity_neighbors(matches[0]["label"], depth=1, max_nodes=60)
            else:
                data = g.extract_graph(min_cooccur=1)
                data["nodes"] = data["nodes"][:limit]
        else:
            data = g.extract_graph(min_cooccur=1)
            data["nodes"] = data["nodes"][:limit]

        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        # 裁剪边：只保留两端都在 top N 节点中的边
        top_ids = {n["id"] for n in nodes}
        edges = [e for e in edges if e["source"] in top_ids and e["target"] in top_ids]

        # 增强：将文档也作为节点显式添加
        doc_nodes = {}
        for node in nodes:
            node.setdefault("type", "entity")
            node.setdefault("name", node.get("label", node.get("id")))
            for doc_title in node.get("relatedDocs", []):
                doc_node_id = f"doc_{hash(doc_title) & 0x7fffffff}"
                if doc_node_id not in doc_nodes:
                    doc_path = ""
                    if g.searcher:
                        for did, dinfo in g.searcher.doc_index.items():
                            if dinfo.get("title") == doc_title:
                                doc_path = dinfo.get("path", "")
                                break
                    doc_nodes[doc_node_id] = {
                        "id": doc_node_id,
                        "name": doc_title,
                        "type": "document",
                        "categories": ["文档"],
                        "path": doc_path,
                    }
                edges.append({
                    "source": doc_node_id,
                    "target": node["id"],
                    "weight": 1,
                })

        nodes.extend(list(doc_nodes.values()))
        data["nodes"] = nodes
        data["links"] = edges
        return jsonify(data)
    except Exception as e:
        logger.error(f"Graph generation error: {e}")
        return jsonify({"error": str(e), "nodes": [], "links": []})


# ── WeChat subscriptions/discovery ───────────────────────────────

def _get_wechat_discovery():
    from wechat_discovery import WeChatDiscovery
    return WeChatDiscovery(KB_DIR)


@app.route("/api/wechat/sources", methods=["GET"])
def list_wechat_sources():
    if not _feature_enabled("wechat"):
        return _feature_disabled_response("wechat")
    wd = _get_wechat_discovery()
    return jsonify({"sources": wd.list_sources()})


@app.route("/api/wechat/sources", methods=["POST"])
def upsert_wechat_source():
    if not _feature_enabled("wechat"):
        return _feature_disabled_response("wechat")
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [x.strip() for x in tags.split(",") if x.strip()]
    try:
        wd = _get_wechat_discovery()
        return jsonify(wd.upsert_source(name, data.get("sample_url", ""), tags, data.get("priority", "normal")))
    except Exception as e:
        logger.error(f"Upsert wechat source failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/wechat/discover", methods=["POST"])
def discover_wechat_articles():
    if not _feature_enabled("wechat"):
        return _feature_disabled_response("wechat")
    data = request.get_json(silent=True) or {}
    try:
        wd = _get_wechat_discovery()
        result = wd.discover(
            source=(data.get("source") if isinstance(data.get("source"), str) else None) or None,
            since=data.get("since") or None,
            limit=int(data.get("limit") or 10),
            url=data.get("url") or None,
        )
        return jsonify(result), 200 if result.get("ok") else 400
    except Exception as e:
        logger.error(f"WeChat discovery failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


# ── RSS subscription management ─────────────────────────────────

def _get_rss_manager():
    from rss_sync import RSSManager
    return RSSManager(KB_DIR)


@app.route("/api/rss/feeds", methods=["GET"])
def list_rss_feeds():
    if not _feature_enabled("rss"):
        return _feature_disabled_response("rss")
    mgr = _get_rss_manager()
    feeds = []
    for k, v in mgr.config.items():
        from dataclasses import asdict
        d = asdict(v)
        d["key"] = k
        feeds.append(d)
    return jsonify({"feeds": feeds, "total": len(feeds)})


@app.route("/api/rss/feeds", methods=["POST"])
def upsert_rss_feed():
    if not _feature_enabled("rss"):
        return _feature_disabled_response("rss")
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url required"}), 400
    try:
        from rss_sync import FeedSource, RSSManager
        mgr = _get_rss_manager()
        key = data.get("key") or (data.get("name") or urlparse(url).netloc).lower().replace(" ", "_")
        mgr.config[key] = FeedSource(
            url=url,
            name=data.get("name", key),
            category=data.get("category", "articles"),
            enabled=data.get("enabled", True),
            priority=data.get("priority", "medium"),
            tags=data.get("tags", []),
            language=data.get("language", "en"),
            interval_minutes=int(data.get("interval_minutes", 360)),
            max_articles=int(data.get("max_articles", 10)),
            notes=data.get("notes", ""),
        )
        mgr._save_config()
        return jsonify({"ok": True, "key": key})
    except Exception as e:
        logger.error(f"Upsert RSS feed failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/rss/feeds/<key>", methods=["DELETE"])
def delete_rss_feed(key: str):
    if not _feature_enabled("rss"):
        return _feature_disabled_response("rss")
    try:
        mgr = _get_rss_manager()
        if key in mgr.config:
            del mgr.config[key]
            mgr._save_config()
        else:
            # try by name
            found = [k for k, v in mgr.config.items() if v.name == key]
            for k in found:
                del mgr.config[k]
            mgr._save_config()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rss/feeds/<key>", methods=["PATCH"])
def update_rss_feed(key: str):
    if not _feature_enabled("rss"):
        return _feature_disabled_response("rss")
    data = request.get_json(silent=True) or {}
    try:
        from rss_sync import RSSManager
        mgr = _get_rss_manager()
        key_match = None
        if key in mgr.config:
            key_match = key
        else:
            for k in mgr.config:
                if mgr.config[k].name == key:
                    key_match = k
                    break
        if not key_match:
            return jsonify({"error": f"feed not found: {key}"}), 404
        feed = mgr.config[key_match]
        if "enabled" in data:
            feed.enabled = bool(data["enabled"])
        if "priority" in data:
            feed.priority = str(data["priority"])
        if "interval_minutes" in data:
            feed.interval_minutes = int(data["interval_minutes"])
        if "max_articles" in data:
            feed.max_articles = int(data["max_articles"])
        mgr._save_config()
        from dataclasses import asdict
        return jsonify({"ok": True, "feed": asdict(feed)})
    except Exception as e:
        logger.error(f"Update RSS feed failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/rss/sync", methods=["POST"])
def sync_rss():
    if not _feature_enabled("rss"):
        return _feature_disabled_response("rss")
    data = request.get_json(silent=True) or {}
    try:
        mgr = _get_rss_manager()
        limit = int(data.get("limit", 5))
        feed_key = data.get("feed_key") or None
        if feed_key:
            if feed_key not in mgr.config:
                return jsonify({"ok": False, "error": f"feed not found: {feed_key}"}), 400
            result = mgr._sync_source(mgr.config[feed_key], max_articles=limit)
            mgr._save_imported()
            return jsonify({"ok": True, "new": result.get("new", 0), "skipped": result.get("skipped", 0), "errors": result.get("errors", 0)})
        else:
            result = mgr.sync_all(max_per_source=limit, auto_process=False)
            return jsonify({"ok": True, "new": result.get("new", 0), "skipped": result.get("skipped", 0), "errors": result.get("errors", 0)})
    except Exception as e:
        logger.error(f"RSS sync failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Knowledge associations ───────────────────────────────────────

@app.route("/api/associations", methods=["GET", "POST"])
def knowledge_associations():
    try:
        report_path = KB_DIR / "reports" / "knowledge-associations-latest.json"
        if request.method == "POST" or not report_path.exists():
            from association_report import build_report
            report = build_report(KB_DIR)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        return jsonify(report)
    except Exception as e:
        logger.error(f"Knowledge associations failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ── Candidate management ─────────────────────────────────────────

def _get_candidate_manager():
    from candidate_manager import CandidateManager
    return CandidateManager(KB_DIR)


@app.route("/api/candidates", methods=["GET"])
def list_candidates():
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    include_imported = request.args.get("include_imported", "false").lower() == "true"
    include_skipped = request.args.get("include_skipped", "false").lower() == "true"
    min_score = int(request.args.get("min_score", "0") or 0)
    tier = request.args.get("tier", "")
    candidate_type = request.args.get("type", "")
    sort = request.args.get("sort", "quality")
    cm = _get_candidate_manager()
    items = cm.list_candidates(
        include_imported=include_imported,
        include_skipped=include_skipped,
        min_score=min_score,
        tier=tier,
        candidate_type=candidate_type,
        sort=sort,
    )
    try:
        from candidate_manager import summarize_candidates
        summary = summarize_candidates(items)
    except Exception:
        summary = {"total": len(items)}
    return jsonify({"total": len(items), "summary": summary, "candidates": items})


@app.route("/api/candidates/<cid>", methods=["GET"])
def get_candidate(cid: str):
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    cm = _get_candidate_manager()
    item = cm.get_candidate(cid)
    if not item:
        return jsonify({"error": "Candidate not found"}), 404
    return jsonify(item)


@app.route("/api/candidates/<cid>/metadata", methods=["PATCH", "POST"])
def update_candidate_metadata(cid: str):
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    data = request.get_json(silent=True) or {}
    try:
        cm = _get_candidate_manager()
        result = cm.update_candidate_metadata(
            cid,
            title=data.get("title", ""),
            category=data.get("category", ""),
            tags=data.get("tags", []),
            notes=data.get("notes", ""),
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"Update candidate metadata failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/candidates/batch-skip", methods=["POST"])
def batch_skip_candidates():
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    data = request.get_json(silent=True) or {}
    try:
        cm = _get_candidate_manager()
        result = cm.batch_skip(
            tier=data.get("tier", "C,D"),
            candidate_type=data.get("type", ""),
            reason=data.get("reason", "批量跳过低质量候选"),
            confirm=data.get("confirm", ""),
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"Batch skip candidates failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 400


@app.route("/api/candidates/<cid>/translate", methods=["POST"])
def translate_candidate(cid: str):
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force", False))
    preview = bool(data.get("preview", False))
    try:
        cm = _get_candidate_manager()
        result = cm.translate_candidate(cid, force=force, preview=preview)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Translate candidate failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/candidates/translate-preview", methods=["POST"])
def translate_candidates_preview():
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    data = request.get_json(silent=True) or {}
    raw_limit = data.get("limit", 20)
    limit = int(raw_limit if raw_limit is not None else 20)
    tier = data.get("tier", "")
    candidate_type = data.get("type", "")
    force = bool(data.get("force", False))
    cm = _get_candidate_manager()
    items = cm.list_candidates(include_imported=False, include_skipped=False, tier=tier, candidate_type=candidate_type, sort="quality")
    done, failed = [], []
    for item in items:
        if len(done) >= limit:
            break
        if not force and item.get("translated_summary"):
            continue
        try:
            result = cm.translate_candidate(item["id"], force=force, preview=True)
            done.append({"id": item["id"], "translated_title": result.get("translated_title")})
        except Exception as e:
            failed.append({"id": item.get("id"), "error": str(e)})
    return jsonify({"translated": len(done), "failed": failed, "items": done})


@app.route("/api/candidates/<cid>/import", methods=["POST"])
def import_candidate(cid: str):
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    data = request.get_json(silent=True) or {}
    process = data.get("process", True)
    run_maintenance = data.get("run_maintenance", True)
    translate = data.get("translate", True)
    try:
        cm = _get_candidate_manager()
        result = cm.import_candidate(cid, process=bool(process), run_maintenance=bool(run_maintenance), translate=bool(translate))
        global _searcher, _embedder, _graph, _qa_system
        _searcher = _embedder = _graph = _qa_system = None
        return jsonify(result)
    except Exception as e:
        logger.error(f"Import candidate failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def _run_batch_import_job(data: dict) -> None:
    """Run configurable queue import outside the request thread with per-item retries."""
    global _searcher, _embedder, _graph, _qa_system
    with _batch_import_lock:
        _batch_import_job.update({
            "running": True,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "result": None,
            "error": None,
            "items": [],
            "error_items": [],
            "maintenance": None,
            "processed": 0,
            "imported": 0,
            "failed": 0,
            "current": None,
        })
        try:
            tier = str(data.get("tier", "A") or "A")
            limit = max(1, min(int(data.get("limit", 20)), 200))
            max_retries = max(0, min(int(data.get("max_retries", 2)), 5))
            retry_delay_sec = max(0, min(int(data.get("retry_delay_sec", 10)), 120))
            run_maintenance_after_batch = bool(data.get("run_maintenance", True))
            update_embeddings = bool(data.get("update_embeddings", False))

            cm = _get_candidate_manager()
            candidates = cm.list_candidates(include_imported=False, include_skipped=False, tier=tier, sort="quality")
            queue = [i for i in candidates if i.get("status") not in ("imported",)][:limit]
            imported = []
            errors = []
            _batch_import_job.update({
                "tier": tier,
                "limit": limit,
                "max_retries": max_retries,
                "retry_delay_sec": retry_delay_sec,
                "total": len(queue),
            })

            for idx, item in enumerate(queue, start=1):
                cid = item.get("id")
                title = item.get("translated_title") or item.get("title", "")
                _batch_import_job.update({"current": {"index": idx, "id": cid, "title": title, "attempt": 0}})
                last_error = None
                for attempt in range(1, max_retries + 2):
                    _batch_import_job["current"] = {"index": idx, "id": cid, "title": title, "attempt": attempt}
                    try:
                        result = cm.import_candidate(cid, process=True, run_maintenance=False, translate=True)
                        ok_item = {
                            "id": cid,
                            "title": title,
                            "wiki_path": result.get("wiki_path"),
                            "attempts": attempt,
                            "translation": result.get("translation"),
                            "llm": (result.get("processed") or {}).get("llm"),
                        }
                        imported.append(ok_item)
                        _batch_import_job.update({"imported": len(imported), "items": imported})
                        last_error = None
                        break
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"Batch import item failed id={cid} attempt={attempt}/{max_retries + 1}: {e}")
                        if attempt <= max_retries:
                            time.sleep(retry_delay_sec * attempt)
                if last_error:
                    err_item = {"id": cid, "title": title, "error": last_error, "attempts": max_retries + 1}
                    errors.append(err_item)
                    _batch_import_job.update({"failed": len(errors), "error_items": errors})
                _batch_import_job.update({"processed": len(imported) + len(errors)})

            maintenance_result = None
            if imported and run_maintenance_after_batch:
                _batch_import_job.update({"status": "maintaining", "current": {"title": "批后轻量维护"}})
                try:
                    from maintenance import KBMaintenance
                    maint = KBMaintenance(KB_DIR, update_embeddings=update_embeddings)
                    report = maint.run()
                    maintenance_result = {"status": report.get("status"), "summary": report.get("summary", {}), "report_path": report.get("report_path")}
                except Exception as e:
                    logger.error(f"Batch import maintenance failed: {e}", exc_info=True)
                    maintenance_result = {"status": "error", "error": str(e)}
                _batch_import_job["maintenance"] = maintenance_result

            _searcher = _embedder = _graph = _qa_system = None
            result = {"imported": len(imported), "errors": len(errors), "items": imported, "error_items": errors, "maintenance": maintenance_result, "limit": limit, "total": len(queue), "max_retries": max_retries}
            _batch_import_job.update({"status": "done", "result": result, "current": None})
        except Exception as e:
            logger.error(f"Batch import job failed: {e}", exc_info=True)
            _batch_import_job.update({"status": "error", "error": str(e)})
        finally:
            _batch_import_job.update({"running": False, "finished_at": datetime.now(timezone.utc).isoformat()})


@app.route("/api/candidates/batch-import", methods=["POST"])
def batch_import_candidates():
    """Start an async configurable queue import job."""
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    if _batch_import_job.get("running") or _batch_import_lock.locked():
        return jsonify({"error": "已有批量导入任务正在执行，请等待当前任务结束后再试", "job": _batch_import_job}), 409
    data = request.get_json(silent=True) or {}
    thread = threading.Thread(target=_run_batch_import_job, args=(data,), daemon=True)
    thread.start()
    return jsonify({"status": "started", "job": _batch_import_job}), 202


@app.route("/api/candidates/batch-import/status", methods=["GET"])
def batch_import_status():
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    return jsonify(_batch_import_job)


@app.route("/api/candidates/<cid>/skip", methods=["POST"])
def skip_candidate(cid: str):
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "")
    try:
        cm = _get_candidate_manager()
        return jsonify(cm.skip_candidate(cid, reason=reason))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/candidates/<cid>/restore", methods=["POST"])
def restore_candidate(cid: str):
    if not _feature_enabled("candidates"):
        return _feature_disabled_response("candidates")
    try:
        cm = _get_candidate_manager()
        return jsonify(cm.restore_candidate(cid))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Categories ───────────────────────────────────────────────────

@app.route("/api/categories", methods=["GET"])
def categories():
    wiki_dir = KB_DIR / "wiki"
    cats = {}
    for f in wiki_dir.rglob("*.md"):
        rel = f.relative_to(wiki_dir)
        cat = str(rel.parent) if str(rel.parent) != "." else "root"
        cats[cat] = cats.get(cat, 0) + 1
    return jsonify({"categories": [{"name": k, "count": v} for k, v in sorted(cats.items())]})


@app.route("/api/maintenance", methods=["POST"])
def run_maintenance():
    """Run the wiki-as-code maintenance pipeline: link → lint → reindex → embeddings."""
    data = request.get_json(silent=True) or {}
    update_embeddings = data.get("update_embeddings", False)
    try:
        from maintenance import KBMaintenance
        maint = KBMaintenance(KB_DIR, update_embeddings=bool(update_embeddings))
        report = maint.run()
        # Invalidate long-lived in-process caches after maintenance.
        global _searcher, _embedder, _graph, _qa_system
        _searcher = _embedder = _graph = _qa_system = None
        return jsonify(report), 200 if report.get("status") == "ok" else 207
    except Exception as e:
        logger.error(f"Maintenance failed: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════
#  HTML templates
# ═══════════════════════════════════════════════════════════════════

WEBUI_TEMPLATE_DIR = Path(__file__).resolve().parent / "webui" / "templates"
WEBUI_STATIC_DIR = Path(__file__).resolve().parent / "webui" / "static"
INDEX_TEMPLATE = WEBUI_TEMPLATE_DIR / "index.html"


def _load_index_html() -> str:
    return INDEX_TEMPLATE.read_text(encoding="utf-8")



@app.route("/")
def index():
    return _load_index_html(), 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route("/static/<path:filename>")
def static_files(filename: str):
    return send_file(str(KB_DIR / "static" / filename))


@app.route("/webui/static/<path:filename>")
def webui_static_files(filename: str):
    return send_from_directory(WEBUI_STATIC_DIR, filename)



@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════

def _configure_console_output():
    """Avoid startup crashes on Windows consoles using legacy encodings."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


def main():
    _configure_console_output()

    parser = argparse.ArgumentParser(description="Sunoxi知识库 Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=5080, help="Listen port")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    args = parser.parse_args()

    print()
    app_name = WEBUI_CONFIG_DEFAULTS["app"]["name"]
    try:
        app_name = _webui_config_payload()["app"].get("name") or app_name
    except Exception:
        pass
    print(f"{app_name} Web UI")
    print(f"URL: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop")
    print()
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
