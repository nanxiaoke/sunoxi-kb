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
from flask import Flask, request, jsonify, send_from_directory, send_file, render_template_string, Response
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


def _translate_wiki_document(wiki_text: str, *, provider_name: str, model: str) -> Dict[str, Any]:
    from llm_service import LLMService

    source_file = _source_file_for_wiki(wiki_text)
    raw_text = source_file.read_text(encoding="utf-8", errors="ignore") if source_file else wiki_text
    old_title = _parse_frontmatter_value(wiki_text, "title")
    if not old_title:
        m = re.search(r"(?m)^#\s+(.+?)\s*$", wiki_text)
        old_title = m.group(1).strip() if m else "Untitled"
    original_title = _original_title_from_raw(raw_text, old_title)
    llm = LLMService()
    resolved_provider = _resolve_translation_provider(provider_name)
    provider_cfg = llm.config.provider(resolved_provider)
    if model and model != provider_cfg.model:
        raise ValueError("model override is not supported yet; choose a configured provider instead")
    flow = llm.config.flow("retranslation")
    options = {"temperature": 0.1, "think": False, "max_tokens": 2500, "num_predict": 1800}
    system = "你是专业的 AI/软件工程技术翻译。标题必须保留原文，不翻译标题。输出忠实、准确、自然、可检索的中文。"
    guide = _term_guide()

    summary_prompt = f"""请为下面英文技术文档生成中文知识库元数据。标题必须保留原文，不要翻译标题。

{guide}

原文标题：{original_title}
原文内容：
{raw_text[:12000]}

只输出 JSON，不要 Markdown 代码块。字段：
- summary_zh: 150-300字中文摘要
- keypoints_zh: 3-5条中文关键点数组
- category_zh: 技术/学术论文/笔记/代码/教程/新闻/其他 之一
- entities_zh: 核心实体和术语数组，术语尽量中英并列
"""
    meta_result = llm.chat("retranslation", [
        {"role": "system", "content": system + " 只输出严格 JSON。"},
        {"role": "user", "content": summary_prompt},
    ], provider_name=resolved_provider, options=options)
    if meta_result.status != "ok":
        raise RuntimeError(meta_result.error or "translation metadata generation failed")
    meta_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (meta_result.content or "").strip(), flags=re.S).strip()
    meta = json.loads(meta_text)

    translated_parts = []
    chunk_meta = []
    chunks = _chunks(raw_text, flow.chunk_chars)
    for i, chunk in enumerate(chunks, 1):
        prompt = f"""请把下面英文技术内容翻译成中文。标题、项目名、产品名、模型名、代码、命令、URL 不要翻译；技术术语首次出现中英并列。

{guide}

原文标题：{original_title}
分片：{i}

待翻译内容：
{chunk}

只输出中文译文，不要解释。"""
        result = llm.chat("retranslation", [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ], provider_name=resolved_provider, options=options)
        if result.status != "ok":
            raise RuntimeError(result.error or f"translation chunk {i} failed")
        translated_parts.append(result.content.strip())
        item = result.to_dict()
        item["chunk_index"] = i
        item["chunk_chars"] = len(chunk)
        item.pop("content", None)
        chunk_meta.append(item)

    return {
        "title": original_title,
        "summary": (meta.get("summary_zh") or "").strip(),
        "keypoints": "\n".join(f"{idx}. {x}" for idx, x in enumerate(meta.get("keypoints_zh") or [], 1)),
        "category": (meta.get("category_zh") or "").strip(),
        "entities": "，".join(meta.get("entities_zh") or []),
        "translation": "\n\n".join(x for x in translated_parts if x),
        "model": meta_result.model,
        "provider": meta_result.provider,
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
        if result.get("translation"):
            new_text = _replace_section(new_text, "🌐 中文翻译", result["translation"])
        stamp = f"> **翻译模型**: {result['provider']} / {result['model'] or 'default'}\n> **重新翻译时间**: {datetime.now(timezone.utc).isoformat()}"
        if "## 🌐 中文翻译" in new_text:
            new_text = re.sub(r"(## 🌐 中文翻译\s*\n)", r"\1\n" + stamp + "\n\n", new_text, count=1)
        new_text = _upsert_frontmatter_mapping(new_text, "llm_retranslation", {
            "flow": "retranslation",
            "provider": result.get("provider", ""),
            "model": result.get("model", ""),
            "status": result.get("llm_result", {}).get("status", "ok"),
            "duration_sec": result.get("llm_result", {}).get("duration_sec"),
            "chunk_count": result.get("chunk_count", len(result.get("llm_chunks", []))),
            "chunks": result.get("llm_chunks", []),
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

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Sunoxi Knowledge Base</title>
    <!-- Vue 3 -->
    <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
    <!-- Tailwind & DaisyUI -->
    <link href="https://cdn.jsdelivr.net/npm/daisyui@3.9.0/dist/full.css" rel="stylesheet" type="text/css" />
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: { primary: "#3b82f6", secondary: "#10b981", accent: "#8b5cf6" },
                    fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] }
                }
            }
        }
    </script>
    <!-- ECharts for Graph -->
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <!-- Marked & DOMPurify & Highlight (pinned versions) -->
    <script src="https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>
    <link rel="icon" type="image/svg+xml" href="/static/favicon.svg?v=4">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    
    <style>
        /* Responsive scrollbars & mobile fixes */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #4b5563; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #6b7280; }
        .markdown-body { font-size: 0.95rem; line-height: 1.6; }
        .markdown-body h1, .markdown-body h2, .markdown-body h3 { font-weight: 600; margin-top: 1.5em; margin-bottom: 0.5em; }
        .markdown-body p { margin-bottom: 1em; }
        .markdown-body pre { background: #1e1e1e; padding: 1em; border-radius: 0.5rem; overflow-x: auto; margin-bottom: 1em; }
        .markdown-body code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
        .markdown-body ul { list-style-type: disc; padding-left: 1.5em; margin-bottom: 1em; }
        .markdown-body a { color: #3b82f6; text-decoration: none; }
        .markdown-body a:hover { text-decoration: underline; }
        
        /* Mobile height fix for iOS Safari */
        .h-screen-dvh { height: 100vh; height: 100dvh; }
        
        /* Transition for layout */
        .fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
        .fade-enter-from, .fade-leave-to { opacity: 0; }
        
        .chat-bubble-ai { background-color: #2a303c; color: #a6adbb; }
        [data-theme="light"] .chat-bubble-ai { background-color: #f3f4f6; color: #1f2937; }
    </style>
</head>
<body class="bg-base-100 text-base-content overflow-hidden">
    <div id="app" class="flex flex-col md:flex-row h-screen-dvh w-full">
        
        <!-- Mobile Header (Visible only on small screens) -->
        <div class="md:hidden navbar bg-base-200 border-b border-base-300 z-50 px-4">
            <div class="flex-none">
                <button class="btn btn-square btn-ghost" @click="mobileMenuOpen = !mobileMenuOpen">
                    <svg v-if="!mobileMenuOpen" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" class="inline-block w-5 h-5 stroke-current"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path></svg>
                    <svg v-else xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" class="inline-block w-5 h-5 stroke-current"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                </button>
            </div>
            <div class="flex-1 px-2">
                <span class="font-bold text-lg tracking-tight">{{ webuiApp.name }}</span>
            </div>
            <div class="flex-none">
                <button class="btn btn-ghost btn-circle" @click="toggleTheme">
                    <span v-if="theme==='dark'">☀️</span><span v-else>🌙</span>
                </button>
            </div>
        </div>

        <!-- Sidebar Navigation -->
        <div :class="['fixed md:relative top-16 md:top-auto bottom-0 md:bottom-auto left-0 w-[82vw] max-w-xs md:w-64 md:max-w-none bg-base-200 border-r border-base-300 flex flex-col transition-transform duration-300 z-40 h-[calc(100dvh-4rem)] md:h-full shadow-2xl md:shadow-none', mobileMenuOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0']">
            <div class="p-4 hidden md:flex items-center justify-between border-b border-base-300">
                <div class="flex items-center gap-2">
                    <img :src="webuiApp.logo" :alt="webuiApp.name" class="w-8 h-8 rounded-xl shadow-sm">
                    <h1 class="font-bold text-lg tracking-tight truncate">{{ webuiApp.name }}</h1>
                </div>
            </div>
            
            <div class="flex-1 overflow-y-auto p-4 space-y-2">
                <!-- Nav Items -->
                <button v-if="featureEnabled('chat')" @click="switchTab('chat')" :class="['w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-colors', activeTab === 'chat' ? 'bg-primary text-primary-content shadow-lg shadow-primary/20' : 'hover:bg-base-300']">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"></path></svg>
                    <span class="font-medium">{{ t('nav.chat') }}</span>
                </button>
                <button v-if="featureEnabled('graph')" @click="switchTab('graph')" :class="['w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-colors', activeTab === 'graph' ? 'bg-primary text-primary-content shadow-lg shadow-primary/20' : 'hover:bg-base-300']">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                    <span class="font-medium">{{ t('nav.graph') }}</span>
                </button>
                <button v-if="featureEnabled('documents')" @click="switchTab('docs')" :class="['w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-colors', activeTab === 'docs' ? 'bg-primary text-primary-content shadow-lg shadow-primary/20' : 'hover:bg-base-300']">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path></svg>
                    <span class="font-medium">{{ t('nav.docs') }}</span>
                    <span class="ml-auto badge badge-sm" v-if="stats && stats.wiki_documents">{{stats.wiki_documents}}</span>
                </button>
                <button v-if="featureEnabled('candidates')" @click="switchTab('candidates')" :class="['w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-colors', activeTab === 'candidates' ? 'bg-primary text-primary-content shadow-lg shadow-primary/20' : 'hover:bg-base-300']">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    <span class="font-medium">{{ t('nav.candidates') }}</span>
                    <span class="ml-auto badge badge-sm" v-if="candidates.length">{{candidates.length}}</span>
                </button>
                <button v-if="featureEnabled('wechat')" @click="switchTab('wechat')" :class="['w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-colors', activeTab === 'wechat' ? 'bg-primary text-primary-content shadow-lg shadow-primary/20' : 'hover:bg-base-300']">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 20H5a2 2 0 01-2-2V7a2 2 0 012-2h3l2-2h4l2 2h3a2 2 0 012 2v11a2 2 0 01-2 2z"></path></svg>
                    <span class="font-medium">{{ t('nav.wechat') }}</span>
                    <span class="ml-auto badge badge-sm" v-if="wechatSources.length">{{wechatSources.length}}</span>
                </button>
                <button v-if="featureEnabled('rss')" @click="switchTab('rss')" :class="['w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-colors', activeTab === 'rss' ? 'bg-primary text-primary-content shadow-lg shadow-primary/20' : 'hover:bg-base-300']">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 5c7.18 0 13 5.82 13 13M6 11a7 7 0 017 7m-6 0a1 1 0 110-2 1 1 0 010 2z"></path></svg>
                    <span class="font-medium">{{ t('nav.rss') }}</span>
                    <span class="ml-auto badge badge-sm" v-if="rssFeeds.length">{{rssFeeds.length}}</span>
                </button>
                <button @click="switchTab('settings')" :class="['w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-colors', activeTab === 'settings' ? 'bg-primary text-primary-content shadow-lg shadow-primary/20' : 'hover:bg-base-300']">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.607 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                    <span class="font-medium">{{ t('nav.settings') }}</span>
                </button>
            </div>
            
            <div class="p-4 border-t border-base-300 hidden md:flex items-center justify-between">
                <button class="btn btn-ghost btn-circle btn-sm" @click="toggleTheme" title="切换主题">
                    <span v-if="theme==='dark'">☀️</span><span v-else>🌙</span>
                </button>
                <select v-model="uiLang" class="select select-xs select-bordered w-20" title="Language">
                    <option value="zh">中文</option>
                    <option value="en">EN</option>
                </select>
                <span class="text-xs opacity-50">v1.1</span>
            </div>
        </div>

        <!-- Main Content Area -->
        <div class="flex-1 min-w-0 min-h-0 h-[calc(100dvh-4rem)] md:h-auto flex relative overflow-hidden bg-base-100">
            
            <!-- Tab: Chat -->
            <transition name="fade">
                <div v-show="activeTab === 'chat'" class="absolute inset-0 flex flex-col">
                    <!-- Chat History -->
                    <div class="flex-1 overflow-y-auto p-4 md:p-8 space-y-6 scroll-smooth" id="chat-container">
                        <div v-if="chatHistory.length === 0" class="flex flex-col items-center justify-center h-full text-center opacity-50 space-y-4">
                            <span class="text-6xl">🤖</span>
                            <h2 class="text-2xl font-bold">{{ t('chat.emptyTitle') }}</h2>
                            <p class="max-w-md">{{ t('chat.emptyBody') }}</p>
                            <div class="flex flex-wrap gap-2 justify-center mt-4">
                                <button class="btn btn-outline btn-sm rounded-full" @click="ask('什么是横纵分析法？')">什么是横纵分析法？</button>
                                <button class="btn btn-outline btn-sm rounded-full" @click="ask('大语言模型发展史')">大语言模型发展史</button>
                                <button class="btn btn-outline btn-sm rounded-full" @click="ask('CC Switch 是什么？它如何解决模型切换问题？')">CC Switch 是什么？</button>
                                <button class="btn btn-outline btn-sm rounded-full" @click="ask('为什么说 Hermes 多 Agent 不是技术活而是管理活？')">Hermes 多 Agent 管理</button>
                            </div>
                        </div>
                        
                        <div v-for="(msg, i) in chatHistory" :key="i" :class="['chat', msg.role === 'user' ? 'chat-end' : 'chat-start']">
                            <div class="chat-image avatar hidden sm:block">
                                <div class="w-10 rounded-full bg-base-300 flex items-center justify-center text-xl">
                                    {{ msg.role === 'user' ? '👤' : '🐾' }}
                                </div>
                            </div>
                            <div class="chat-header mb-1 opacity-50 text-xs">
                                {{ msg.role === 'user' ? 'You' : webuiApp.name }}
                                <time v-if="msg.time" class="ml-1">{{ msg.time }}</time>
                            </div>
                            <div :class="['chat-bubble shadow-sm', msg.role === 'user' ? 'chat-bubble-primary' : 'chat-bubble-ai']">
                                <div v-if="msg.role === 'user'" class="whitespace-pre-wrap">{{ msg.content }}</div>
                                <div v-else class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
                                <div v-if="msg.role === 'ai' && (msg.latency || msg.cache_hit || msg.citations?.length || msg.diagnostics?.query_tokens?.length || msg.llm?.status)" class="mt-3 flex flex-wrap gap-2 text-xs opacity-70">
                                    <span v-if="msg.latency" class="badge badge-ghost badge-sm">⏱ {{ msg.latency }}s</span>
                                    <span v-if="msg.cache_hit" class="badge badge-success badge-sm">缓存命中</span>
                                    <span v-if="msg.citations?.length" class="badge badge-info badge-sm">{{ msg.citations.length }} 个引用</span>
                                    <span v-if="msg.answer_mode" class="badge badge-outline badge-sm">{{ msg.answer_mode === 'extractive' ? '极速答案' : '模型生成' }}</span>
                                    <span v-if="msg.llm?.provider" :class="['badge badge-sm', msg.llm.status === 'error' ? 'badge-error' : 'badge-outline']">{{ msg.llm.provider }} / {{ msg.llm.model }}</span>
                                    <span v-if="msg.llm?.fallback_from" class="badge badge-warning badge-sm">fallback {{ msg.llm.fallback_from }} → {{ msg.llm.fallback_to }}</span>
                                    <span v-if="msg.diagnostics?.query_tokens?.length" class="badge badge-outline badge-sm">{{ msg.diagnostics.query_tokens.slice(0, 4).join(' · ') }}</span>
                                </div>
                                <div v-if="msg.llm?.status === 'error' && msg.llm?.error" class="alert alert-warning py-2 px-3 mt-3 text-xs">
                                    <span class="break-all">模型调用失败：{{ msg.llm.error }}</span>
                                </div>
                                
                                <!-- Sources Cards -->
                                <div v-if="msg.sources && msg.sources.length > 0" class="mt-4 pt-3 border-t border-base-content/10 flex flex-col gap-2">
                                    <div class="text-xs opacity-70 font-semibold mb-1">📚 参考来源</div>
                                    <div class="flex flex-wrap gap-2">
                                        <div v-for="src in msg.sources" :key="src.path" @click="previewDoc(src.path)" class="bg-base-100/50 hover:bg-base-100 rounded-lg p-2 text-sm cursor-pointer border border-base-content/10 transition-colors flex items-start gap-2 w-full sm:w-auto max-w-full">
                                            <span class="text-lg">📄</span>
                                            <div class="truncate flex-1">
                                                <div class="truncate font-medium">{{ src.title }}</div>
                                                <div class="text-xs opacity-60 flex gap-2">
                                                    <span class="text-primary">{{ src.score ? src.score.toFixed(1) : '' }}</span>
                                                </div>
                                                <div v-if="src.matched_snippets?.length" class="text-xs opacity-70 mt-1 max-h-10 overflow-hidden whitespace-normal">{{ src.matched_snippets[0] }}</div>
                                                <div class="mt-2 flex flex-wrap gap-1">
                                                    <button class="btn btn-[10px] btn-outline min-h-0 h-6 px-2" @click.stop="previewDoc(src.path)">预览</button>
                                                    <button class="btn btn-[10px] btn-ghost min-h-0 h-6 px-2" @click.stop="focusDocInList(src.path)">列表定位</button>
                                                    <button class="btn btn-[10px] btn-ghost min-h-0 h-6 px-2" @click.stop="openDocAudit(src.path)">审计</button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div v-if="isWaiting" class="chat chat-start">
                            <div class="chat-image avatar hidden sm:block">
                                <div class="w-10 rounded-full bg-base-300 flex items-center justify-center">🐾</div>
                            </div>
                            <div class="chat-bubble chat-bubble-ai opacity-70 flex items-center gap-2">
                                <span class="loading loading-dots loading-sm"></span>
                                <span class="text-sm">
                                    {{ chatAnswerMode === 'llm' ? '正在调用模型生成，可能需要几十秒...' : '正在检索并生成极速答案...' }}
                                    <span v-if="chatAnswerMode === 'llm' && qaProviderChain" class="block text-xs opacity-70 mt-1">qa: {{ qaProviderChain }}</span>
                                </span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Chat Input -->
                    <div class="p-4 bg-base-200 border-t border-base-300">
                        <form @submit.prevent="submitChat" class="max-w-4xl mx-auto relative flex items-end gap-2">
                            <div class="relative flex-1">
                                <textarea 
                                    v-model="chatInput" 
                                    @keydown.enter.exact.prevent="submitChat"
                                    rows="1"
                                    class="textarea textarea-bordered w-full resize-none pr-12 rounded-2xl bg-base-100 leading-normal min-h-[3rem] py-3 shadow-sm focus:border-primary transition-colors" 
                                    placeholder="提问或搜索知识库... (Enter 发送，Shift+Enter 换行)"
                                    :disabled="isWaiting"
                                ></textarea>
                                <button type="submit" class="absolute right-2 bottom-2 btn btn-sm btn-circle btn-primary shadow-md" :disabled="!chatInput.trim() || isWaiting">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path></svg>
                                </button>
                            </div>
                            <div class="hidden sm:flex items-center gap-2 mb-2">
                                <label class="cursor-pointer label gap-2" title="极速答案约0.5秒；模型生成更自然但可能需要几十秒">
                                    <span class="label-text text-xs opacity-70">{{ chatAnswerMode === 'llm' ? '模型生成' : '极速答案' }}</span> 
                                    <input type="checkbox" :checked="chatAnswerMode === 'llm'" @change="chatAnswerMode = $event.target.checked ? 'llm' : 'extractive'" class="toggle toggle-primary toggle-sm" />
                                </label>
                                <span v-if="chatAnswerMode === 'llm' && qaProviderChain" class="text-[11px] opacity-50 max-w-44 truncate" :title="qaProviderChain">qa: {{ qaProviderChain }}</span>
                            </div>
                        </form>
                    </div>
                </div>
            </transition>

            <!-- Tab: Graph -->
            <transition name="fade">
                <div v-show="activeTab === 'graph'" class="absolute inset-0 flex flex-col">
                    <div class="p-4 border-b border-base-300 flex items-center justify-between bg-base-100 z-10">
                        <div class="font-medium flex items-center gap-2">
                            <span>🕸️</span> 
                            <select v-model="graphLayout" @change="initGraph" class="select select-ghost select-sm font-bold text-base focus:bg-transparent">
                                <option value="sankey">层级桑基图 (Sankey)</option>
                                <option value="tree">树状图 (Tree)</option>
                                <option value="chord">弦图 (Chord)</option>
                                <option value="force">力导向图 (Force)</option>
                                <option value="circular">环形布局 (Circular)</option>
                            </select>
                        </div>
                        <div class="flex gap-2 items-center">
                            <input v-model="graphSearchText" @keyup.enter="initGraph" placeholder="搜索实体..." class="input input-sm input-bordered rounded-full w-36 bg-base-200" />
                            <button v-if="graphSearchText" class="btn btn-sm btn-ghost btn-circle" @click="graphSearchText=''; initGraph()" title="清除搜索">✕</button>
                            <button class="btn btn-sm btn-outline" @click="initGraph"><svg class="w-4 h-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> 刷新</button>
                        </div>
                    </div>
                    <div v-if="associationReport" class="border-b border-base-300 bg-base-200/70 p-3 text-sm">
                        <div class="flex flex-wrap items-center justify-between gap-3">
                            <div class="flex flex-wrap gap-2 items-center">
                                <span class="font-semibold">知识关联报告</span>
                                <span class="badge badge-sm">文档 {{ associationReport.summary?.docs ?? 0 }}</span>
                                <span class="badge badge-sm" :class="associationReport.summary?.orphans ? 'badge-warning' : 'badge-success'">孤立 {{ associationReport.summary?.orphans ?? 0 }}</span>
                                <span class="badge badge-sm" :class="associationReport.summary?.duplicate_groups ? 'badge-warning' : 'badge-success'">重复 {{ associationReport.summary?.duplicate_groups ?? 0 }}</span>
                                <span class="badge badge-sm" :class="associationReport.summary?.broken_links ? 'badge-error' : 'badge-success'">坏链 {{ associationReport.summary?.broken_links ?? 0 }}</span>
                                <span class="badge badge-sm">实体 {{ associationReport.summary?.entities ?? 0 }}</span>
                                <span class="badge badge-sm" :class="associationReport.summary?.auto_link_candidates ? 'badge-warning' : 'badge-success'">可自动补 {{ associationReport.summary?.auto_link_candidates ?? 0 }}</span>
                                <span class="badge badge-sm" :class="associationReport.summary?.recommendation_only_links ? 'badge-info' : 'badge-success'">推荐展示 {{ associationReport.summary?.recommendation_only_links ?? 0 }}</span>
                                <span class="badge badge-sm opacity-70">低置信 {{ associationReport.summary?.low_confidence_links ?? 0 }}</span>
                            </div>
                            <button class="btn btn-xs btn-outline" @click="loadAssociations(true)" :disabled="loadingAssociations">
                                <span v-if="loadingAssociations" class="loading loading-spinner loading-xs mr-1"></span>重建关联报告
                            </button>
                        </div>
                        <div v-if="associationReport.orphans?.length" class="mt-2 text-xs opacity-80">
                            <span class="font-semibold text-warning">孤立文档：</span>
                            <span v-for="o in associationReport.orphans.slice(0,3)" :key="o.path" class="mr-2">{{ o.title || o.path }}</span>
                        </div>
                        <div v-if="associationReport.duplicate_groups?.length" class="mt-3 text-xs opacity-90 space-y-2">
                            <span class="font-semibold text-warning">疑似重复：</span>
                            <div v-for="g in associationReport.duplicate_groups.slice(0,3)" :key="g.type + ':' + g.key" class="rounded-xl border border-warning/30 bg-warning/5 p-2">
                                <div class="mb-1">{{ g.reason }} · {{ g.doc_count }}篇 · 建议保留 {{ g.keep_suggestion }}</div>
                                <div class="flex flex-wrap gap-1">
                                    <button v-for="d in g.docs" :key="g.key + d.path"
                                        :class="['btn btn-xs', d.path === g.keep_suggestion ? 'btn-success' : 'btn-outline']"
                                        @click="previewDoc(d.path)"
                                        :title="d.path">
                                        {{ d.path === g.keep_suggestion ? '建议保留' : '审查' }} · {{ d.title || d.path }}
                                    </button>
                                </div>
                            </div>
                        </div>
                        <div v-if="associationReport.auto_link_candidates?.length" class="mt-2 text-xs opacity-80">
                            <span class="font-semibold text-warning">可自动补链：</span>
                            <span v-for="s in associationReport.auto_link_candidates.slice(0,3)" :key="s.source_path + '→' + s.target_path" class="mr-2">{{ s.source_title }} → {{ s.target_title }}({{ s.score }})</span>
                        </div>
                        <div v-else-if="associationReport.recommendation_only_links?.length" class="mt-2 text-xs opacity-80">
                            <span class="font-semibold text-info">仅推荐展示：</span>
                            <span v-for="s in associationReport.recommendation_only_links.slice(0,3)" :key="s.source_path + '→' + s.target_path" class="mr-2">{{ s.source_title }} → {{ s.target_title }}({{ s.score }})</span>
                        </div>
                        <div v-else-if="associationReport.docs?.length" class="mt-2 text-xs opacity-70">
                            示例关联：{{ associationReport.docs[0].title }} →
                            <span v-for="r in (associationReport.docs[0].related || []).slice(0,3)" :key="r.path" class="mr-2">{{ r.title }}({{ r.score }})</span>
                        </div>
                    </div>
                    <div class="flex-1 relative bg-base-100" id="graph-container">
                        <!-- ECharts Mount Point -->
                    </div>
                </div>
            </transition>

            <!-- Tab: Docs -->
            <transition name="fade">
                <div v-show="activeTab === 'docs'" class="absolute inset-0 flex flex-col overflow-y-auto bg-base-100 p-4 md:p-8">
                    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
                        <div>
                            <h2 class="text-2xl font-bold tracking-tight">{{ t('docs.title') }}</h2>
                            <p class="opacity-60 text-sm mt-1">{{ t('docs.subtitle') }}</p>
                        </div>
                        <div class="flex gap-2 flex-wrap">
                            <input type="text" v-model="docSearchText" :placeholder="t('docs.filter')" class="input input-sm input-bordered rounded-full w-48 bg-base-200" />
                            <button class="btn btn-sm btn-outline rounded-full" @click="runMaintenance" :disabled="isMaintaining" title="按当前 LLM 模式维护知识库、检查坏链并重建索引">
                                <span v-if="isMaintaining" class="loading loading-spinner loading-xs mr-1"></span>
                                <span v-else class="mr-1">🧹</span>
                                {{ isMaintaining ? t('docs.maintaining') : t('docs.maintenance') }}
                            </button>
                            <button v-if="featureEnabled('url_import')" class="btn btn-sm btn-outline rounded-full" @click="showUrlInput = !showUrlInput">
                                <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"></path></svg>
                                {{ t('docs.fetchUrl') }}
                            </button>
                            <label v-if="featureEnabled('upload')" class="btn btn-sm btn-primary rounded-full cursor-pointer shadow-md">
                                <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
                                {{ t('docs.upload') }}
                                <input type="file" multiple class="hidden" @change="handleFileUpload">
                            </label>
                        </div>
                    </div>

                    <div v-if="featureEnabled('upload') && fileImportProviderChain" class="alert border border-info/30 bg-info/10 text-xs mb-4">
                        <div>
                            <div class="font-semibold">文件上传处理链路</div>
                            <div class="font-mono break-all mt-1">file_import_structure: {{ fileImportProviderChain }}</div>
                            <div class="opacity-70 mt-1">当前模式：{{ llmModeLabel }} · fallback {{ fileImportFlow?.allow_fallback ? 'on' : 'off' }}</div>
                        </div>
                    </div>

                    <!-- Upload Area Dropzone -->
                    <div v-if="featureEnabled('upload')"
                        @dragover.prevent="dragOver = true" 
                        @dragleave.prevent="dragOver = false" 
                        @drop.prevent="handleDrop"
                        :class="['border-2 border-dashed rounded-2xl p-8 text-center transition-all duration-300 mb-8', dragOver ? 'border-primary bg-primary/10 scale-[1.02]' : 'border-base-300 hover:border-primary/50']"
                    >
                        <div class="text-4xl mb-2">📥</div>
                        <h3 class="text-lg font-medium">{{ t('docs.dropTitle') }}</h3>
                        <p class="text-sm opacity-60 mt-1">{{ t('docs.dropBody') }}</p>
                    </div>

                    <!-- URL Fetch Input Card -->
                    <transition name="fade">
                        <div v-show="showUrlInput && featureEnabled('url_import')" class="card bg-base-200 border border-base-300 rounded-2xl p-6 mb-8 shadow-sm">
                            <h3 class="font-semibold flex items-center gap-2 mb-3">🔗 {{ t('docs.fetchTitle') }}</h3>
                            <form @submit.prevent="fetchUrl" class="flex flex-col md:flex-row gap-3">
                                <input 
                                    v-model="fetchUrlInput" 
                                    type="url" 
                                    :placeholder="t('docs.fetchPlaceholder')"
                                    class="input input-bordered flex-1 bg-base-100 rounded-xl"
                                    :disabled="isFetchingUrl"
                                />
                                <button 
                                    type="submit"
                                    class="btn btn-primary rounded-xl shadow-md"
                                    :disabled="!fetchUrlInput.trim() || isFetchingUrl"
                                >
                                    <span v-if="isFetchingUrl" class="loading loading-spinner loading-sm"></span>
                                    <svg v-else class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                                    {{ isFetchingUrl ? t('docs.fetching') : t('docs.fetchImport') }}
                                </button>
                            </form>
                            <p v-if="fetchUrlError" class="text-error text-sm mt-2">{{ fetchUrlError }}</p>
                            <p v-if="fetchUrlSuccess" class="text-success text-sm mt-2">✅ {{ t('docs.fetchSuccess') }}</p>
                        </div>
                    </transition>

                    <div v-if="failedImports.length" class="alert border border-warning/40 bg-warning/10 text-sm mb-4">
                        <div class="w-full">
                            <div class="font-semibold">待重试导入</div>
                            <div class="mt-2 space-y-2">
                                <div v-for="item in failedImports" :key="item.raw_path" class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-xl bg-base-100/70 border border-base-300 p-3">
                                    <div class="min-w-0">
                                        <div class="font-mono text-xs break-all">{{ item.raw_path }}</div>
                                        <div class="text-xs opacity-70 mt-1">{{ item.error || item.message || item.recovery?.hint || '处理失败，可重试' }}</div>
                                    </div>
                                    <div class="flex gap-2 shrink-0">
                                        <button class="btn btn-xs btn-warning" @click="retryFailedImport(item)" :disabled="item.retrying">
                                            <span v-if="item.retrying" class="loading loading-spinner loading-xs"></span>重试处理
                                        </button>
                                        <button class="btn btn-xs btn-ghost" @click="failedImports = failedImports.filter(x => x !== item)">忽略</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Hierarchical Document Browser -->
                    <div v-if="loadingDocs" class="flex justify-center py-12"><span class="loading loading-spinner loading-lg text-primary"></span></div>
                    <div v-if="!loadingDocs && qualityBadCount" class="alert border border-warning/30 bg-warning/10 text-sm mb-4">
                        <div class="w-full">
                            <div class="flex flex-wrap items-center justify-between gap-2">
                                <div>
                                    <div class="font-semibold">质量待修复文档 {{ qualityBadCount }} 篇</div>
                                    <div class="opacity-75 mt-1">主要问题：{{ qualityIssueSummary || '摘要、关键点或实体信息不完整' }}</div>
                                </div>
                                <div class="flex gap-2">
                                    <button class="btn btn-xs btn-outline" @click="qualityOnly = !qualityOnly">{{ qualityOnly ? '查看全部' : '只看待修复' }}</button>
                                    <button class="btn btn-xs btn-warning" @click="repairAllQuality" :disabled="repairingQuality">
                                        <span v-if="repairingQuality" class="loading loading-spinner loading-xs"></span>一键修复
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div v-if="!loadingDocs" class="grid grid-cols-1 lg:grid-cols-[18rem_1fr] gap-4 min-h-[26rem]">
                        <!-- Folder Tree -->
                        <aside class="card bg-base-200 border border-base-300 rounded-2xl overflow-hidden">
                            <div class="px-4 py-3 border-b border-base-300 flex items-center justify-between">
                                <div class="font-semibold text-sm">{{ t('docs.folders') }}</div>
                                <div class="badge badge-sm">{{ docs.length }}</div>
                            </div>
                            <div class="p-2 overflow-y-auto max-h-[calc(100dvh-18rem)]">
                                <button v-for="folder in folderRows" :key="folder.path || '__all__'"
                                    @click="selectedDocFolder = folder.path"
                                    :class="['w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-left transition-colors', selectedDocFolder === folder.path ? 'bg-primary text-primary-content' : 'hover:bg-base-300']"
                                    :style="{ paddingLeft: (12 + folder.depth * 18) + 'px' }">
                                    <span>{{ folder.path === '' ? '📚' : '📁' }}</span>
                                    <span class="truncate flex-1" :title="folder.path || '全部文档'">{{ folder.label }}</span>
                                    <span :class="['badge badge-xs', selectedDocFolder === folder.path ? 'badge-primary-content' : 'badge-ghost']">{{ folder.count }}</span>
                                </button>
                            </div>
                        </aside>

                        <!-- Document List -->
                        <section class="card bg-base-200 border border-base-300 rounded-2xl overflow-hidden">
                            <div class="px-4 py-3 border-b border-base-300 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                                <div>
                                    <div class="font-semibold text-sm">{{ selectedDocFolder || '全部文档' }}</div>
                                    <div class="text-xs opacity-60">{{ visibleDocs.length }} {{ t('docs.items') }} · {{ t('docs.sorted') }}</div>
                                </div>
                                <div class="flex gap-2 items-center">
                                    <span v-if="qualityBadCount" class="badge badge-warning badge-sm">{{ qualityBadCount }} 待修复</span>
                                    <button v-if="qualityBadCount" class="btn btn-xs btn-outline" @click="qualityOnly = !qualityOnly">{{ qualityOnly ? '全部文档' : '只看待修复' }}</button>
                                    <button v-if="qualityBadCount" class="btn btn-xs btn-warning" @click="repairAllQuality" :disabled="repairingQuality">
                                        <span v-if="repairingQuality" class="loading loading-spinner loading-xs"></span>一键修复质量
                                    </button>
                                    <button v-if="selectedDocFolder" class="btn btn-xs btn-ghost" @click="selectedDocFolder = ''">{{ t('docs.viewAll') }}</button>
                                </div>
                            </div>

                            <div v-if="visibleDocs.length === 0" class="p-12 text-center opacity-50">
                                <div class="text-4xl mb-2">🗂️</div>
                                <div>{{ t('docs.empty') }}</div>
                            </div>

                            <div v-else class="divide-y divide-base-300 max-h-[calc(100dvh-22rem)] overflow-y-auto">
                                <div v-for="doc in pagedVisibleDocs" :key="doc.relpath"
                                    class="group flex flex-wrap sm:flex-nowrap items-center gap-3 px-4 py-3 hover:bg-base-300/60 cursor-pointer transition-colors"
                                    @click="previewDoc(doc.relpath)">
                                    <div class="text-2xl shrink-0">📄</div>
                                    <div class="min-w-0 flex-1">
                                        <div class="font-medium truncate" :title="doc.name">{{ doc.name }}</div>
                                        <div class="text-xs opacity-60 truncate break-all">{{ doc.relpath }}</div>
                                    </div>
                                    <div class="hidden md:flex items-center gap-2 text-xs opacity-50 shrink-0">
                                        <span class="badge badge-sm badge-outline">{{ doc.type }}</span>
                                        <span v-if="doc.quality && !doc.quality.ok" class="badge badge-warning badge-sm" :title="issueText(doc.quality.issues)">质量待修复</span>
                                        <span v-else class="badge badge-success badge-sm">质量OK</span>
                                        <span>{{ formatBytes(doc.size) }}</span>
                                        <span>{{ formatDate(doc.mtime) }}</span>
                                    </div>
                                    <div v-if="doc.quality && !doc.quality.ok" class="hidden lg:flex flex-wrap gap-1 shrink-0 max-w-xs">
                                        <span v-for="issue in doc.quality.issues" :key="doc.relpath + issue" class="badge badge-xs badge-outline badge-warning">{{ issueLabel(issue) }}</span>
                                    </div>
                                    <div class="flex items-center gap-1 shrink-0 ml-auto opacity-90 md:opacity-0 group-hover:opacity-100 transition-opacity">
                                        <button @click.stop="previewDoc(doc.relpath)" class="btn btn-xs btn-outline" title="打开预览">预览</button>
                                        <button v-if="doc.quality && !doc.quality.ok" @click.stop="repairDocQuality(doc.relpath)" class="btn btn-xs btn-warning" title="修复摘要/关键点/实体">修复</button>
                                        <button @click.stop="openDocAudit(doc.relpath)" class="btn btn-xs btn-ghost" title="查看 LLM 审计">审计</button>
                                    </div>
                                    <button @click.stop="deleteDoc(doc.relpath)" class="btn btn-xs btn-ghost btn-circle text-error opacity-60 md:opacity-0 group-hover:opacity-100 transition-opacity" title="删除">
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                    </button>
                                </div>
                            </div>
                            <div v-if="visibleDocs.length > docsPageSize" class="px-4 py-3 border-t border-base-300 flex items-center justify-between gap-3 text-sm">
                                <div class="opacity-60">{{ t('docs.page') }} {{ docsPage }} / {{ docsTotalPages }} · {{ t('docs.total') }} {{ visibleDocs.length }} {{ t('docs.items') }}</div>
                                <div class="join">
                                    <button class="btn btn-xs join-item" @click="docsPage = Math.max(1, docsPage - 1)" :disabled="docsPage <= 1">{{ t('docs.prev') }}</button>
                                    <button class="btn btn-xs join-item" @click="docsPage = Math.min(docsTotalPages, docsPage + 1)" :disabled="docsPage >= docsTotalPages">{{ t('docs.next') }}</button>
                                </div>
                            </div>
                        </section>
                    </div>
                </div>
            </transition>

            <!-- Tab: RSS Subscriptions -->
            <transition name="fade">
                <div v-show="activeTab === 'rss'" class="absolute inset-0 flex flex-col overflow-y-auto bg-base-100 px-4 pt-5 pb-24 md:p-8">
                    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                        <div>
                            <h2 class="text-2xl font-bold tracking-tight">RSS订阅</h2>
                            <p class="opacity-60 text-sm mt-1">管理RSS订阅源，同步文章先进入候选池审查</p>
                        </div>
                        <div class="flex gap-2">
                            <button class="btn btn-sm btn-outline rounded-full" @click="syncRss()" :disabled="syncingRss">
                                <span v-if="syncingRss" class="loading loading-spinner loading-xs mr-1"></span>同步全部
                            </button>
                            <button class="btn btn-sm btn-outline rounded-full" @click="loadRssFeeds" :disabled="loadingRssFeeds">
                                <span v-if="loadingRssFeeds" class="loading loading-spinner loading-xs mr-1"></span>刷新
                            </button>
                        </div>
                    </div>
                    <div class="alert border border-info/30 bg-info/10 text-sm mb-5">
                        <div>
                            <div class="font-semibold">环境说明</div>
                            <div class="opacity-80 mt-1">RSS同步需要服务器能访问订阅源URL；同步结果先进入候选池，不会直接写入知识库。网络受限、Feed格式异常或超时会记录为错误，可稍后重试。</div>
                        </div>
                    </div>
                    <div v-if="rssSyncResult" class="alert alert-info mb-5 text-sm">
                        <div v-if="!syncingRss">
                            RSS同步: {{rssSyncResult.new}} 新 / {{rssSyncResult.skipped}} 跳过 / {{rssSyncResult.errors}} 错误
                        </div>
                        <span v-else class="loading loading-spinner loading-xs"></span>
                    </div>
                    <div class="card bg-base-200 border border-base-300 rounded-2xl mb-5">
                        <div class="card-body p-4 grid md:grid-cols-5 gap-3">
                            <input v-model="rssNewForm.url" class="input input-bordered input-sm md:col-span-2" placeholder="RSS/Atom URL *">
                            <input v-model="rssNewForm.name" class="input input-bordered input-sm" placeholder="名称">
                            <select v-model="rssNewForm.category" class="select select-bordered select-sm">
                                <option value="articles">articles</option><option value="ai_lab">ai_lab</option><option value="news">news</option><option value="tech">tech</option>
                            </select>
                            <div class="flex gap-2">
                                <select v-model="rssNewForm.priority" class="select select-bordered select-sm">
                                    <option value="high">high</option><option value="medium">medium</option><option value="low">low</option>
                                </select>
                                <button class="btn btn-sm btn-primary" @click="saveRssFeed" :disabled="!rssNewForm.url.trim()">保存</button>
                            </div>
                        </div>
                    </div>
                    <div v-if="loadingRssFeeds" class="flex justify-center py-12"><span class="loading loading-spinner loading-lg text-primary"></span></div>
                    <div v-else class="space-y-3">
                        <div v-for="feed in rssFeeds" :key="feed.key || feed.url" class="card bg-base-200 border border-base-300 rounded-2xl">
                            <div class="card-body p-5">
                                <div class="flex justify-between gap-4">
                                    <div class="min-w-0">
                                        <div class="flex flex-wrap items-center gap-2 mb-2">
                                            <h3 class="font-semibold text-lg">{{feed.name || feed.key}}</h3>
                                            <span class="badge badge-sm" :class="feed.enabled ? 'badge-success' : 'badge-ghost'">{{feed.enabled ? '启用' : '禁用'}}</span>
                                            <span class="badge badge-sm badge-outline">{{feed.priority || 'medium'}}</span>
                                            <span class="badge badge-sm">{{feed.language || 'en'}}</span>
                                        </div>
                                        <p class="text-xs opacity-60 break-all">{{feed.url}}</p>
                                        <div class="flex flex-wrap gap-2 mt-2">
                                            <span class="badge badge-info badge-xs" v-if="feed.tags && feed.tags.length">{{feed.tags.join(', ')}}</span>
                                            <span class="text-xs opacity-60 ml-1">{{feed.category}} · 间隔{{feed.interval_minutes}}min · 最多{{feed.max_articles}}篇</span>
                                        </div>
                                        <p v-if="feed.notes" class="text-xs opacity-50 mt-1">{{feed.notes}}</p>
                                    </div>
                                    <div class="flex gap-2 shrink-0">
                                        <button class="btn btn-sm btn-outline" @click="syncRss(feed.key)" :disabled="syncingRss">同步</button>
                                        <label class="swap swap-rotate btn btn-sm btn-ghost" :title="feed.enabled ? '禁用' : '启用'" @click.prevent="toggleRssFeed(feed.key)">
                                            <input type="checkbox" :checked="feed.enabled" class="hidden">
                                            <svg v-if="feed.enabled" class="w-4 h-4 text-success fill-current" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
                                            <svg v-else class="w-4 h-4 text-error fill-current" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12 19 6.41z"/></svg>
                                        </label>
                                        <button class="btn btn-sm btn-ghost text-error" @click="deleteRssFeed(feed.key)" :disabled="syncingRss">删除</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </transition>

            <!-- Tab: WeChat Sources -->
            <transition name="fade">
                <div v-show="activeTab === 'wechat'" class="absolute inset-0 flex flex-col overflow-y-auto bg-base-100 px-4 pt-5 pb-24 md:p-8">
                    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                        <div>
                            <h2 class="text-2xl font-bold tracking-tight">公众号订阅</h2>
                            <p class="opacity-60 text-sm mt-1">管理公众号作者；通过搜索发现候选文章，先审查再导入</p>
                        </div>
                        <button class="btn btn-sm btn-outline rounded-full" @click="loadWechatSources" :disabled="loadingWechatSources">
                            <span v-if="loadingWechatSources" class="loading loading-spinner loading-xs mr-1"></span>刷新订阅
                        </button>
                    </div>
                    <div class="alert border border-warning/30 bg-warning/10 text-sm mb-5">
                        <div>
                            <div class="font-semibold">环境说明</div>
                            <div class="opacity-80 mt-1">公众号历史发现依赖公开搜索/跳转页，受验证页和反爬影响较大；指定文章URL通常更稳定。发现结果会进入候选池，需要人工确认后再导入。</div>
                        </div>
                    </div>
                    <div class="card bg-base-200 border border-base-300 rounded-2xl mb-5">
                        <div class="card-body p-4 grid md:grid-cols-4 gap-3">
                            <input v-model="newWechatSource.name" class="input input-bordered input-sm" placeholder="公众号/作者名">
                            <input v-model="newWechatSource.sample_url" class="input input-bordered input-sm md:col-span-2" placeholder="样例文章 URL（推荐）">
                            <div class="flex gap-2">
                                <input v-model="newWechatSource.tags" class="input input-bordered input-sm flex-1" placeholder="标签,逗号分隔">
                                <button class="btn btn-sm btn-primary" @click="saveWechatSource" :disabled="savingWechatSource || !newWechatSource.name.trim()">
                                    <span v-if="savingWechatSource" class="loading loading-spinner loading-xs"></span>保存
                                </button>
                            </div>
                        </div>
                    </div>
                    <div class="card bg-base-200 border border-base-300 rounded-2xl mb-5">
                        <div class="card-body p-4 grid md:grid-cols-5 gap-3 items-end">
                            <label class="form-control">
                                <div class="label py-0"><span class="label-text text-xs">订阅源</span></div>
                                <select v-model="discoverForm.source" class="select select-bordered select-sm">
                                    <option value="">全部</option>
                                    <option v-for="s in wechatSources" :key="s.name" :value="s.name">{{s.name}}</option>
                                </select>
                            </label>
                            <label class="form-control">
                                <div class="label py-0"><span class="label-text text-xs">since</span></div>
                                <input v-model="discoverForm.since" class="input input-bordered input-sm" placeholder="YYYY-MM-DD">
                            </label>
                            <label class="form-control">
                                <div class="label py-0"><span class="label-text text-xs">limit</span></div>
                                <input v-model.number="discoverForm.limit" type="number" min="1" max="50" class="input input-bordered input-sm">
                            </label>
                            <label class="form-control md:col-span-2">
                                <div class="label py-0"><span class="label-text text-xs">指定文章 URL（可选）</span></div>
                                <div class="flex gap-2">
                                    <input v-model="discoverForm.url" class="input input-bordered input-sm flex-1" placeholder="https://mp.weixin.qq.com/s/...">
                                    <button class="btn btn-sm btn-secondary" @click="discoverWechat()" :disabled="discoveringWechat">
                                        <span v-if="discoveringWechat" class="loading loading-spinner loading-xs"></span>搜索发现候选
                                    </button>
                                </div>
                            </label>
                        </div>
                    </div>
                    <div v-if="wechatDiscoveryResult" class="alert mb-5" :class="wechatDiscoveryResult.ok ? 'alert-info' : 'alert-error'">
                        <div class="text-sm">
                            <div class="font-semibold">发现结果：{{ wechatDiscoveryResult.ok ? '完成' : '失败' }}</div>
                            <div v-if="wechatDiscoveryResult.results">处理订阅源 {{wechatDiscoveryResult.total_sources}} 个。说明：微信历史页常返回验证页；这里使用搜索发现候选，结果可能是微信跳转/转载页，需要人工确认。</div>
                            <div v-if="wechatDiscoveryResult.error">{{wechatDiscoveryResult.error}}</div>
                        </div>
                    </div>
                    <div v-if="loadingWechatSources" class="flex justify-center py-12"><span class="loading loading-spinner loading-lg text-primary"></span></div>
                    <div v-else class="space-y-3">
                        <div v-for="s in wechatSources" :key="s.name" class="card bg-base-200 border border-base-300 rounded-2xl">
                            <div class="card-body p-5">
                                <div class="flex justify-between gap-4">
                                    <div class="min-w-0">
                                        <h3 class="font-semibold text-lg">{{s.name}}</h3>
                                        <div class="flex flex-wrap gap-2 mt-2">
                                            <span class="badge badge-sm badge-outline" v-for="t in (s.tags || [])" :key="t">{{t}}</span>
                                            <span class="badge badge-sm">{{s.priority || 'normal'}}</span>
                                            <span class="badge badge-sm" :class="s.profile_ext_status && s.profile_ext_status.is_verify ? 'badge-warning' : 'badge-success'">profile: {{s.profile_ext_status && s.profile_ext_status.is_verify ? '验证页' : '可探测'}}</span>
                                        </div>
                                        <p class="text-xs opacity-60 mt-2 break-all">biz: {{s.biz || '未知'}} · user_name: {{s.user_name || '未知'}}</p>
                                        <p class="text-xs opacity-60 mt-1 break-all">{{s.sample_url}}</p>
                                    </div>
                                    <button class="btn btn-sm btn-outline shrink-0" @click="discoverWechat(s.name)">发现</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </transition>

            <!-- Tab: Candidates -->
            <transition name="fade">
                <div v-show="activeTab === 'candidates'" class="absolute inset-0 flex flex-col overflow-y-auto bg-base-100 px-4 pt-5 pb-24 md:p-8">
                    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
                        <div>
                            <h2 class="text-2xl font-bold tracking-tight">候选池</h2>
                            <p class="opacity-60 text-sm mt-1">微信公众号/RSS 候选内容先审核，再导入知识库</p>
                        </div>
                        <div class="flex gap-2 flex-wrap items-center">
                            <select v-model="candidateTierFilter" @change="loadCandidates" class="select select-sm select-bordered rounded-full bg-base-200">
                                <option value="">全部等级（按 A/B/C/D 分组）</option>
                                <option value="A,B">A/B 优先</option>
                                <option value="A">仅 A · 优先导入</option>
                                <option value="B">仅 B · 值得审核</option>
                                <option value="C,D">C/D 低优先级</option>
                            </select>
                            <select v-model="candidateTypeFilter" @change="loadCandidates" class="select select-sm select-bordered rounded-full bg-base-200">
                                <option value="">全部来源</option>
                                <option value="wechat">微信</option>
                                <option value="rss">RSS</option>
                                <option value="other">其他</option>
                            </select>
                            <label class="label cursor-pointer gap-2 rounded-full border border-base-300 bg-base-200 px-3 py-1">
                                <input type="checkbox" v-model="candidateIncludeSkipped" @change="loadCandidates" class="checkbox checkbox-xs" />
                                <span class="label-text text-xs">显示已跳过</span>
                            </label>
                            <button class="btn btn-sm btn-outline rounded-full" @click="batchTranslatePreview" :disabled="batchTranslatingPreview || loadingCandidates">
                                <span v-if="batchTranslatingPreview" class="loading loading-spinner loading-xs mr-1"></span>
                                批量补中文预览
                            </button>
                            <button class="btn btn-sm btn-error btn-outline rounded-full" @click="batchSkipLowQuality" :disabled="batchSkippingCandidates || loadingCandidates">
                                <span v-if="batchSkippingCandidates" class="loading loading-spinner loading-xs mr-1"></span>
                                批量跳过C/D
                            </button>
                            <label class="input input-sm input-bordered rounded-full flex items-center gap-1 bg-base-200 w-28">
                                <span class="text-xs opacity-60">导入</span>
                                <input v-model.number="batchImportLimit" type="number" min="1" max="200" class="w-12" />
                            </label>
                            <label class="input input-sm input-bordered rounded-full flex items-center gap-1 bg-base-200 w-28">
                                <span class="text-xs opacity-60">重试</span>
                                <input v-model.number="batchImportRetries" type="number" min="0" max="5" class="w-12" />
                            </label>
                            <button class="btn btn-sm btn-success rounded-full" @click="batchImportA" :disabled="batchImportingA || loadingCandidates">
                                <span v-if="batchImportingA" class="loading loading-spinner loading-xs mr-1"></span>
                                队列导入A级
                            </button>
                            <button class="btn btn-sm btn-outline rounded-full" @click="loadCandidates" :disabled="loadingCandidates">
                                <span v-if="loadingCandidates" class="loading loading-spinner loading-xs mr-1"></span>
                                刷新候选
                            </button>
                        </div>
                    </div>
                    <div v-if="loadingCandidates" class="flex justify-center py-12"><span class="loading loading-spinner loading-lg text-primary"></span></div>
                    <div v-else-if="candidates.length === 0" class="p-12 text-center opacity-50 card bg-base-200 border border-base-300 rounded-2xl">
                        <div class="text-5xl mb-3">📭</div>
                        <div class="font-medium">暂无待审核候选</div>
                    </div>
                    <div v-else class="space-y-3">
                        <div v-if="candidateSummary" class="stats stats-vertical md:stats-horizontal shadow bg-base-200 border border-base-300 rounded-2xl w-full mb-3">
                            <div class="stat py-3"><div class="stat-title">候选总数</div><div class="stat-value text-lg">{{ candidateSummary.total || candidates.length }}</div></div>
                            <div class="stat py-3"><div class="stat-title">平均分</div><div class="stat-value text-lg">{{ candidateSummary.avg_score || 0 }}</div></div>
                            <div class="stat py-3"><div class="stat-title">等级</div><div class="stat-value text-sm">A {{candidateSummary.by_tier?.A || 0}} / B {{candidateSummary.by_tier?.B || 0}} / C {{candidateSummary.by_tier?.C || 0}} / D {{candidateSummary.by_tier?.D || 0}}</div></div>
                        </div>
                        <div v-if="batchImportJob && batchImportJob.status !== 'idle'" class="alert border border-info/40 bg-info/10 rounded-2xl text-sm shadow-sm">
                            <div class="w-full">
                                <div class="flex flex-wrap items-center justify-between gap-3">
                                    <div>
                                        <div class="font-bold text-info">📥 队列导入：{{ batchImportJob.status }}</div>
                                        <div class="text-xs opacity-70 mt-1">
                                            进度 {{ batchImportJob.processed || 0 }} / {{ batchImportJob.total || 0 }} · 成功 {{ batchImportJob.imported || 0 }} · 失败 {{ batchImportJob.failed || 0 }} · 重试 {{ batchImportJob.max_retries || 0 }}
                                        </div>
                                        <div v-if="batchImportJob.current" class="text-xs opacity-60 mt-1 break-all">
                                            当前：{{ batchImportJob.current.index || '' }} {{ batchImportJob.current.title || '' }} <span v-if="batchImportJob.current.attempt">· 第 {{ batchImportJob.current.attempt }} 次</span>
                                        </div>
                                        <div v-if="batchImportJob.maintenance" class="text-xs opacity-60 mt-1">维护：{{ batchImportJob.maintenance.status }}</div>
                                    </div>
                                    <button class="btn btn-xs btn-outline" @click="loadBatchImportStatus">刷新状态</button>
                                </div>
                            </div>
                        </div>
                        <div v-if="lastImportResult" class="alert border border-success/40 bg-success/10 rounded-2xl text-sm shadow-sm">
                            <div class="w-full">
                                <div class="flex flex-wrap items-start justify-between gap-3">
                                    <div>
                                        <div class="font-bold text-success">✅ 已完成导入闭环</div>
                                        <div class="text-xs opacity-70 mt-1">
                                            处理 {{ lastImportResult.processed?.ok ? '成功' : '未知' }} ·
                                            维护 {{ lastImportResult.maintenance?.status || '未运行' }} ·
                                            验证 {{ lastImportResult.validation?.ok ? '通过' : '需检查' }}
                                        </div>
                                        <div class="text-xs opacity-60 mt-1 break-all">原始文件：{{ lastImportResult.imported_to }}</div>
                                        <div v-if="lastImportResult.wiki_path" class="text-xs opacity-60 mt-1 break-all">Wiki：{{ lastImportResult.wiki_path }}</div>
                                        <div v-if="lastImportResult.translation" class="mt-2 rounded-xl border border-base-300 bg-base-100/70 p-3 text-xs">
                                            <div class="font-semibold mb-1">模型链路</div>
                                            <div>
                                                翻译决策：{{ lastImportResult.translation.decision || '-' }} ·
                                                请求翻译 {{ lastImportResult.translation.requested ? '是' : '否' }} ·
                                                全文 {{ lastImportResult.translation.full ? '是' : '否' }}
                                            </div>
                                            <div v-if="lastImportResult.translation.preview?.provider" class="mt-1">
                                                预览：{{ lastImportResult.translation.preview.flow || 'candidate_preview' }} ·
                                                {{ lastImportResult.translation.preview.provider }} / {{ lastImportResult.translation.preview.model || '-' }}
                                                <span v-if="lastImportResult.translation.preview.fallback_from"> · fallback {{ lastImportResult.translation.preview.fallback_from }} → {{ lastImportResult.translation.preview.fallback_to }}</span>
                                            </div>
                                            <div v-if="lastImportResult.translation.full_translation?.provider" class="mt-1">
                                                全文：{{ lastImportResult.translation.full_translation.flow || 'full_translation' }} ·
                                                {{ lastImportResult.translation.full_translation.provider }} / {{ lastImportResult.translation.full_translation.model || '-' }} ·
                                                chunks {{ lastImportResult.translation.full_translation.chunk_count || 0 }}
                                            </div>
                                            <div v-if="lastImportResult.processed?.llm?.provider" class="mt-1">
                                                入库处理：{{ lastImportResult.processed.llm.flow || '-' }} ·
                                                {{ lastImportResult.processed.llm.provider }} / {{ lastImportResult.processed.llm.model || '-' }}
                                            </div>
                                        </div>
                                        <div v-if="lastImportResult.validation?.checks" class="flex flex-wrap gap-1 mt-2">
                                            <span v-for="(ok, name) in lastImportResult.validation.checks" :key="name" :class="['badge badge-xs', ok ? 'badge-success' : 'badge-warning']">{{ name }} {{ ok ? '✓' : '!' }}</span>
                                        </div>
                                        <div v-if="lastImportResult.maintenance?.summary?.lint" class="text-xs opacity-70 mt-2">
                                            Lint：坏链 {{ lastImportResult.maintenance.summary.lint.broken_links ?? '?' }} · 孤立 {{ lastImportResult.maintenance.summary.lint.orphans ?? '?' }} · 内链 {{ lastImportResult.maintenance.summary.lint.internal_links ?? '?' }}
                                        </div>
                                        <div v-if="lastImportResult.maintenance?.summary?.associations" class="text-xs opacity-70 mt-1">
                                            关联：重复 {{ lastImportResult.maintenance.summary.associations.duplicate_groups ?? 0 }} · 可补链 {{ lastImportResult.maintenance.summary.associations.auto_link_candidates ?? 0 }} · 推荐 {{ lastImportResult.maintenance.summary.associations.recommendation_only_links ?? 0 }}
                                        </div>
                                    </div>
                                    <div class="flex flex-wrap gap-2">
                                        <button v-if="lastImportResult.wiki_path" class="btn btn-xs btn-success" @click="openLastImportedDoc">查看文档</button>
                                        <button v-if="lastImportResult.search_query" class="btn btn-xs btn-outline" @click="searchLastImported">搜索验证</button>
                                        <button class="btn btn-xs btn-outline" @click="runMaintenance" :disabled="isMaintaining">重新维护</button>
                                        <button class="btn btn-xs btn-ghost" @click="lastImportResult = null">关闭</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="alert bg-base-200 border border-base-300 rounded-2xl text-sm">
                            <div class="w-full">
                                <div class="font-semibold mb-2">质量等级说明（规则评分，非模型黑盒）</div>
                                <div class="grid md:grid-cols-4 gap-2">
                                    <div class="rounded-xl border border-success/30 bg-success/5 p-3"><span class="badge badge-success mb-1">A · 80-100</span><div class="text-xs opacity-70">优先导入：来源/主题/内容长度/新鲜度综合较好</div></div>
                                    <div class="rounded-xl border border-info/30 bg-info/5 p-3"><span class="badge badge-info mb-1">B · 65-79</span><div class="text-xs opacity-70">值得审核：相关但需要人工判断价值</div></div>
                                    <div class="rounded-xl border border-warning/30 bg-warning/5 p-3"><span class="badge badge-warning mb-1">C · 45-64</span><div class="text-xs opacity-70">低优先级：信息量、来源或主题相关性不足</div></div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3"><span class="badge badge-ghost mb-1">D · 0-44</span><div class="text-xs opacity-70">建议跳过：低相关/过短/重复/泛新闻风险</div></div>
                                </div>
                                <div class="text-xs opacity-60 mt-2">判断依据：候选类型、来源 priority/tags、正文长度、中文预览主题命中、标题质量、新鲜度、重复风险；已入库/已审核内容固定为 A。</div>
                            </div>
                        </div>
                        <div v-for="group in candidateGroups" :key="group.tier" class="space-y-3">
                            <div :class="['sticky top-0 z-10 rounded-2xl border p-4 shadow-sm backdrop-blur bg-base-100/95', group.borderClass]">
                                <div class="flex flex-wrap items-center justify-between gap-3">
                                    <div class="flex items-center gap-3">
                                        <span :class="['badge badge-lg text-base font-bold px-4 py-4', group.badgeClass]">{{ group.tier }}级</span>
                                        <div>
                                            <div class="font-bold text-lg">{{ group.title }}</div>
                                            <div class="text-xs opacity-60">组内按发布时间/更新时间倒序排列</div>
                                        </div>
                                    </div>
                                    <div class="text-sm opacity-70">{{ group.items.length }} 篇</div>
                                </div>
                            </div>
                            <div v-for="item in group.items" :key="item.id" :class="['card border rounded-2xl', tierCardClass(item.quality_tier), item.status === 'skipped' ? 'opacity-65 grayscale' : '']">
                                <div class="card-body p-5">
                                    <div class="flex flex-col md:flex-row md:items-start gap-4 justify-between">
                                        <div class="min-w-0 flex-1">
                                            <div class="flex flex-wrap items-center gap-2 mb-3">
                                                <span :class="['badge badge-lg font-bold px-4', tierBadgeClass(item.quality_tier)]">{{ item.quality_tier || '?' }} · {{ item.quality_score ?? 0 }}分</span>
                                                <span class="text-sm font-medium opacity-80">{{ tierLabel(item.quality_tier) }}</span>
                                                <span class="badge badge-outline badge-sm">{{ item.source_name || '未知来源' }}</span>
                                                <span class="badge badge-sm">{{ item.author || '未知作者' }}</span>
                                                <span class="badge badge-ghost badge-sm">{{ formatCandidateDate(item) }}</span>
                                                <span v-if="item.status === 'skipped'" class="badge badge-error badge-sm">已跳过</span>
                                            </div>
                                            <h3 class="font-semibold text-lg leading-tight" :title="item.title">{{ item.translated_title || item.title }}</h3>
                                            <p v-if="item.translated_title && item.translated_title !== item.title" class="text-xs opacity-50 mt-1">原文：{{ item.title }}</p>
                                            <p v-if="item.translated_summary" class="text-sm opacity-80 mt-2 leading-relaxed line-clamp-3">{{ item.translated_summary }}</p>
                                            <div v-if="item.translated_topics?.length" class="mt-2 flex flex-wrap gap-1">
                                                <span v-for="t in item.translated_topics.slice(0,5)" :key="t" class="badge badge-xs badge-info badge-outline">{{ t }}</span>
                                            </div>
                                            <div v-if="item.review_category || item.review_tags?.length || item.review_title" class="mt-2 rounded-xl border border-primary/30 bg-primary/5 p-2 text-xs">
                                                <div class="font-semibold mb-1">审核编辑</div>
                                                <div v-if="item.review_title">标题：{{ item.review_title }}</div>
                                                <div v-if="item.review_category">分类：{{ item.review_category }}</div>
                                                <div v-if="item.review_tags?.length">标签：{{ item.review_tags.join(' / ') }}</div>
                                            </div>
                                            <p class="text-xs opacity-60 mt-2 break-all">{{ item.path }}</p>
                                            <div class="text-xs opacity-60 mt-2">正文约 {{ item.content_length }} 字 · {{ item.translated_summary ? '已生成中文预览' : '未生成中文预览' }} · {{ item.quality?.recommendation || '' }}</div>
                                            <div v-if="item.quality" class="mt-3 rounded-xl border border-base-300 bg-base-100/70 p-3">
                                                <div class="flex flex-wrap items-center gap-2 mb-2">
                                                    <span class="text-xs font-semibold opacity-70">质量构成</span>
                                                    <span class="badge badge-xs badge-outline">来源权重: {{ item.quality.source_priority || 'unknown' }}</span>
                                                    <span v-if="item.quality.duplicate_risk && item.quality.duplicate_risk !== 'none'" class="badge badge-xs badge-warning">重复风险: {{ item.quality.duplicate_risk }}</span>
                                                </div>
                                                <div v-if="item.quality.factors?.length" class="mb-2 grid grid-cols-2 gap-1">
                                                    <div v-for="f in item.quality.factors" :key="f.name" class="flex items-center gap-1 text-xs">
                                                        <span class="w-20 truncate opacity-70">{{ f.name }}</span>
                                                        <div class="flex-1 h-2 rounded-full bg-base-300 overflow-hidden">
                                                            <div :style="{ width: Math.min(100, Math.max(0, ((f.score + Math.abs(f.max)) / (Math.abs(f.max) * 2 || 1)) * 100)) + '%', background: f.score >= 0 ? '#22c55e' : '#ef4444' }" class="h-full rounded-full transition-all"></div>
                                                        </div>
                                                        <span class="w-8 text-right" :class="f.score >= 0 ? 'text-success' : 'text-error'">{{ f.score >= 0 ? '+' : ''}}{{ f.score }}</span>
                                                    </div>
                                                </div>
                                                <div class="flex flex-wrap gap-1">
                                                    <span v-for="r in (item.quality.reasons || [])" :key="r" class="badge badge-sm badge-outline text-success">+ {{ r }}</span>
                                                    <span v-for="p in (item.quality.penalties || [])" :key="p" class="badge badge-sm badge-outline text-warning">- {{ p }}</span>
                                                </div>
                                                <div v-if="item.quality.kb_matches?.length" class="text-xs opacity-70 mt-2">KB实体重叠: {{ item.quality.kb_matches.slice(0, 6).join(' / ') }}</div>
                                                <div v-if="item.quality.topic_hits?.length" class="text-xs opacity-60 mt-2">主题命中: {{ item.quality.topic_hits.join(' / ') }}</div>
                                            </div>
                                        </div>
                                        <div class="flex gap-2 shrink-0">
                                            <button class="btn btn-sm btn-outline" @click="translateCandidate(item.id)" :disabled="translatingCandidateId === item.id">
                                                <span v-if="translatingCandidateId === item.id" class="loading loading-spinner loading-xs mr-1"></span>预翻译
                                            </button>
                                            <button v-if="item.status !== 'skipped'" class="btn btn-sm btn-outline" @click="editCandidate(item)">编辑</button>
                                            <button class="btn btn-sm btn-outline" @click="previewCandidate(item.id)">预览</button>
                                            <button v-if="item.status !== 'skipped'" class="btn btn-sm btn-primary" @click="importCandidate(item.id)" :disabled="importingCandidateId === item.id">
                                                <span v-if="importingCandidateId === item.id" class="loading loading-spinner loading-xs mr-1"></span>
                                                导入
                                            </button>
                                            <button v-if="item.status !== 'skipped'" class="btn btn-sm btn-ghost text-error" @click="skipCandidate(item.id)">跳过</button>
                                            <button v-else class="btn btn-sm btn-success btn-outline" @click="restoreCandidate(item.id)">恢复</button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </transition>

            <!-- Tab: System Settings -->
            <transition name="fade">
                <div v-show="activeTab === 'settings'" class="absolute inset-0 flex flex-col overflow-y-auto bg-base-100 px-4 pt-5 pb-24 md:p-8">
                    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                        <div>
                            <h2 class="text-2xl font-bold tracking-tight">{{ t('settings.title') }}</h2>
                            <p class="opacity-60 text-sm mt-1">{{ t('settings.subtitle') }}</p>
                        </div>
                        <div class="flex gap-2">
                            <button class="btn btn-sm btn-outline rounded-full" @click="refreshAllSettings" :disabled="loadingWebuiConfig || loadingLlmConfig">
                                <span v-if="loadingWebuiConfig || loadingLlmConfig" class="loading loading-spinner loading-xs mr-1"></span>{{ t('settings.refresh') }}
                            </button>
                            <button class="btn btn-sm btn-outline rounded-full" @click="loadLlmBackups" :disabled="loadingLlmConfig">
                                {{ t('settings.backups') }}
                            </button>
                            <button class="btn btn-sm btn-primary rounded-full" @click="saveAllSettings" :disabled="savingWebuiConfig || savingLlmConfig || loadingWebuiConfig || loadingLlmConfig">
                                <span v-if="savingWebuiConfig || savingLlmConfig" class="loading loading-spinner loading-xs mr-1"></span>{{ t('settings.save') }}
                            </button>
                        </div>
                    </div>
                    <div class="grid lg:grid-cols-[1fr_1.2fr] gap-5 mb-5">
                        <section class="card bg-base-200 border border-base-300 rounded-2xl">
                            <div class="card-body p-5">
                                <h3 class="font-semibold mb-3">{{ t('settings.basic') }}</h3>
                                <div class="grid md:grid-cols-2 gap-3">
                                    <label class="form-control">
                                        <div class="label py-1"><span class="label-text text-xs">{{ t('settings.appName') }}</span></div>
                                        <input v-model="webuiConfig.app.name" class="input input-sm input-bordered" />
                                    </label>
                                    <label class="form-control">
                                        <div class="label py-1"><span class="label-text text-xs">{{ t('settings.appTitle') }}</span></div>
                                        <input v-model="webuiConfig.app.title" class="input input-sm input-bordered" />
                                    </label>
                                </div>
                                <label class="form-control mt-2">
                                    <div class="label py-1"><span class="label-text text-xs">{{ t('settings.appSubtitle') }}</span></div>
                                    <input v-model="webuiConfig.app.subtitle" class="input input-sm input-bordered" />
                                </label>
                                <label class="form-control mt-2">
                                    <div class="label py-1"><span class="label-text text-xs">{{ t('settings.appLogo') }}</span></div>
                                    <input v-model="webuiConfig.app.logo" class="input input-sm input-bordered font-mono text-xs" />
                                </label>
                            </div>
                        </section>
                        <section class="card bg-base-200 border border-base-300 rounded-2xl">
                            <div class="card-body p-5">
                                <div class="flex items-start justify-between gap-3 mb-3">
                                    <div>
                                        <h3 class="font-semibold">Translation Policy</h3>
                                        <p class="text-xs opacity-60 mt-1">控制导入和重翻译的双语策略；不会自动启动全量批处理。</p>
                                    </div>
                                    <input v-model="webuiConfig.translation_policy.enabled" type="checkbox" class="toggle toggle-primary toggle-sm" />
                                </div>
                                <div class="grid md:grid-cols-3 gap-3">
                                    <label class="form-control">
                                        <div class="label py-1"><span class="label-text text-xs">Mode</span></div>
                                        <select v-model="webuiConfig.translation_policy.mode" class="select select-sm select-bordered">
                                            <option value="off">off</option>
                                            <option value="preview_only">preview_only</option>
                                            <option value="bilingual_on_import">bilingual_on_import</option>
                                            <option value="bilingual_for_selected">bilingual_for_selected</option>
                                        </select>
                                    </label>
                                    <label class="form-control">
                                        <div class="label py-1"><span class="label-text text-xs">Targets</span></div>
                                        <select v-model="webuiConfig.translation_policy.targets" class="select select-sm select-bordered">
                                            <option value="auto_opposite">auto_opposite</option>
                                            <option value="zh">zh</option>
                                            <option value="en">en</option>
                                            <option value="zh,en">zh,en</option>
                                        </select>
                                    </label>
                                    <label class="form-control">
                                        <div class="label py-1"><span class="label-text text-xs">Fallback</span></div>
                                        <select v-model="webuiConfig.translation_policy.fallback_on_failure" class="select select-sm select-bordered">
                                            <option value="preview_only">preview_only</option>
                                            <option value="skip">skip</option>
                                            <option value="fail_import">fail_import</option>
                                        </select>
                                    </label>
                                </div>
                                <div class="grid md:grid-cols-3 gap-3 mt-3">
                                    <label class="form-control">
                                        <div class="label py-1"><span class="label-text text-xs">Chunk chars</span></div>
                                        <input v-model.number="webuiConfig.translation_policy.max_chunk_chars" type="number" min="500" max="20000" class="input input-sm input-bordered" />
                                    </label>
                                    <label class="label cursor-pointer justify-start gap-2 rounded-xl border border-base-300 bg-base-100 px-3 py-2 mt-6">
                                        <input v-model="webuiConfig.translation_policy.preserve_original_full" type="checkbox" class="checkbox checkbox-sm" />
                                        <span class="label-text text-xs">保留完整原文</span>
                                    </label>
                                    <div class="rounded-xl border border-base-300 bg-base-100 px-3 py-2">
                                        <div class="text-xs opacity-60 mb-2">Candidate tiers</div>
                                        <div class="flex flex-wrap gap-2 text-xs">
                                            <label v-for="tier in ['A','B','C','D']" :key="'tier-'+tier" class="label cursor-pointer gap-1 p-0">
                                                <input v-model="webuiConfig.translation_policy.candidate_tiers" :value="tier" type="checkbox" class="checkbox checkbox-xs" />
                                                <span>{{ tier }}</span>
                                            </label>
                                            <label class="label cursor-pointer gap-1 p-0">
                                                <input v-model="webuiConfig.translation_policy.candidate_tiers" value="all" type="checkbox" class="checkbox checkbox-xs" />
                                                <span>all</span>
                                            </label>
                                        </div>
                                    </div>
                                </div>
                                <div class="grid md:grid-cols-3 gap-2 text-xs mt-3">
                                    <label v-for="key in Object.keys(webuiConfig.translation_policy.full_translate || {})" :key="'full-'+key" class="label cursor-pointer justify-start gap-2 rounded-xl border border-base-300 bg-base-100 px-3 py-2">
                                        <input v-model="webuiConfig.translation_policy.full_translate[key]" type="checkbox" class="checkbox checkbox-xs" />
                                        <span class="font-mono">{{ key }}</span>
                                    </label>
                                    <label class="label cursor-pointer justify-start gap-2 rounded-xl border border-base-300 bg-base-100 px-3 py-2">
                                        <input v-model="webuiConfig.translation_policy.chinese_source.translate_to_english" type="checkbox" class="checkbox checkbox-xs" />
                                        <span>中文源文 → English</span>
                                    </label>
                                    <label class="label cursor-pointer justify-start gap-2 rounded-xl border border-base-300 bg-base-100 px-3 py-2">
                                        <input v-model="webuiConfig.translation_policy.english_source.translate_to_chinese" type="checkbox" class="checkbox checkbox-xs" />
                                        <span>English source → 中文</span>
                                    </label>
                                </div>
                            </div>
                        </section>
                        <section class="card bg-base-200 border border-base-300 rounded-2xl">
                            <div class="card-body p-5">
                                <div class="flex items-start justify-between gap-3 mb-3">
                                    <div>
                                        <h3 class="font-semibold">{{ t('settings.features') }}</h3>
                                        <p class="text-xs opacity-60 mt-1">{{ t('settings.featureHint') }}</p>
                                    </div>
                                </div>
                                <div class="grid grid-cols-2 md:grid-cols-3 gap-2 text-sm">
                                    <label v-for="key in Object.keys(webuiConfig.features)" :key="key" class="label cursor-pointer justify-start gap-2 rounded-xl border border-base-300 bg-base-100 px-3 py-2">
                                        <input v-model="webuiConfig.features[key]" type="checkbox" class="toggle toggle-primary toggle-sm" />
                                        <span class="label-text font-mono text-xs">{{ key }}</span>
                                    </label>
                                </div>
                            </div>
                        </section>
                    </div>
                    <div class="alert border border-info/30 bg-info/10 text-sm mb-6">
                        <div>{{ t('settings.secretNote') }}</div>
                    </div>
                    <div v-if="featureEnabled('llm_settings')" class="card bg-base-200 border border-base-300 rounded-2xl mb-5">
                        <div class="card-body p-4">
                            <div class="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <div class="font-semibold">{{ t('settings.deploymentMode') }}</div>
                                    <div class="text-xs opacity-60 mt-1">{{ t('settings.deploymentModeHint') }}</div>
                                </div>
                                <span class="badge badge-sm badge-outline">{{ llmModeLabel }}</span>
                            </div>
                            <div class="grid md:grid-cols-3 gap-2 mt-3">
                                <button
                                    v-for="mode in llmModeOptions"
                                    :key="mode.id"
                                    class="btn btn-sm justify-start"
                                    :class="llmMode === mode.id ? 'btn-primary' : 'btn-outline'"
                                    @click="setLlmMode(mode.id)"
                                    :disabled="settingLlmMode === mode.id || loadingLlmConfig">
                                    <span v-if="settingLlmMode === mode.id" class="loading loading-spinner loading-xs mr-1"></span>
                                    {{ mode.label }}
                                </button>
                            </div>
                            <div v-if="llmModeDescription" class="mt-3 text-xs opacity-70">{{ llmModeDescription }}</div>
                        </div>
                    </div>
                    <div v-if="featureEnabled('llm_settings') && llmSecretSetup" class="card bg-base-200 border border-base-300 rounded-2xl mb-5">
                        <div class="card-body p-4">
                            <div class="font-semibold mb-3">{{ t('settings.setupCommand') }}</div>
                            <div class="grid lg:grid-cols-2 gap-3 text-xs">
                                <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                    <div class="opacity-60 mb-1">{{ t('settings.secretFile') }}</div>
                                    <div class="font-mono break-all">{{ llmSecretSetup.env_file }}</div>
                                    <div class="mt-2 flex flex-wrap gap-2">
                                        <span class="badge badge-sm" :class="llmSecretSetup.env_file_exists ? 'badge-success' : 'badge-warning'">
                                            {{ llmSecretSetup.env_file_exists ? t('settings.configured') : t('settings.notConfigured') }}
                                        </span>
                                        <span v-if="llmSecretSetup.env_file_mode" class="badge badge-sm badge-outline">{{ t('settings.permissionMode') }} {{ llmSecretSetup.env_file_mode }}</span>
                                    </div>
                                </div>
                                <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                    <div class="opacity-60 mb-1">{{ t('settings.systemdDropin') }}</div>
                                    <div class="font-mono break-all">{{ llmSecretSetup.systemd_dropin }}</div>
                                    <div class="mt-2">
                                        <span class="badge badge-sm" :class="llmSecretSetup.systemd_dropin_exists ? 'badge-success' : 'badge-warning'">
                                            {{ llmSecretSetup.systemd_dropin_exists ? t('settings.configured') : t('settings.notConfigured') }}
                                        </span>
                                    </div>
                                </div>
                            </div>
                            <div class="mt-3 rounded-xl border border-base-300 bg-base-100 px-3 py-2 font-mono text-xs break-all">
                                {{ llmSecretSetup.install_command }}
                            </div>
                        </div>
                    </div>
                    <div v-if="featureEnabled('llm_audit')" class="card bg-base-200 border border-base-300 rounded-2xl mb-5">
                        <div class="card-body p-4">
                            <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
                                <div class="font-semibold">{{ t('settings.audit') }}</div>
                                <div class="flex flex-wrap gap-2">
                                    <button class="btn btn-xs btn-outline" @click="loadLlmAudit" :disabled="loadingLlmAudit">
                                        <span v-if="loadingLlmAudit" class="loading loading-spinner loading-xs mr-1"></span>{{ t('settings.auditRefresh') }}
                                    </button>
                                    <button class="btn btn-xs btn-outline" @click="exportLlmAudit('json')" :disabled="!llmAudit">导出 JSON</button>
                                    <button class="btn btn-xs btn-outline" @click="exportLlmAudit('csv')" :disabled="!llmAudit">导出 CSV</button>
                                </div>
                            </div>
                            <div v-if="llmAudit" class="space-y-4">
                                <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                    <div class="grid md:grid-cols-4 gap-2 text-xs">
                                        <select v-model="llmAuditFilters.flow" class="select select-bordered select-xs">
                                            <option value="">全部 Flow</option>
                                            <option v-for="[name] in objectEntries(llmAudit.by_flow)" :key="name" :value="name">{{ name }}</option>
                                        </select>
                                        <select v-model="llmAuditFilters.provider" class="select select-bordered select-xs">
                                            <option value="">全部 Provider</option>
                                            <option v-for="[name] in objectEntries(llmAudit.by_provider)" :key="name" :value="name">{{ name }}</option>
                                        </select>
                                        <select v-model="llmAuditFilters.model" class="select select-bordered select-xs">
                                            <option value="">全部 Model</option>
                                            <option v-for="[name] in objectEntries(llmAudit.by_model)" :key="name" :value="name">{{ name }}</option>
                                        </select>
                                        <select v-model="llmAuditFilters.status" class="select select-bordered select-xs">
                                            <option value="">全部 Status</option>
                                            <option v-for="[name] in objectEntries(llmAudit.by_status)" :key="name" :value="name">{{ name }}</option>
                                        </select>
                                    </div>
                                    <div class="flex flex-wrap items-center justify-between gap-2 mt-2">
                                        <div class="flex flex-wrap gap-3 text-xs">
                                            <label class="label cursor-pointer gap-1 p-0"><input v-model="llmAuditFilters.missing" type="checkbox" class="checkbox checkbox-xs">缺元数据</label>
                                            <label class="label cursor-pointer gap-1 p-0"><input v-model="llmAuditFilters.fallback" type="checkbox" class="checkbox checkbox-xs">仅 fallback</label>
                                            <label class="label cursor-pointer gap-1 p-0"><input v-model="llmAuditFilters.retranslated" type="checkbox" class="checkbox checkbox-xs">已重翻译</label>
                                        </div>
                                        <div class="flex gap-2">
                                            <button class="btn btn-xs btn-primary" @click="loadLlmAudit" :disabled="loadingLlmAudit">应用筛选</button>
                                            <button class="btn btn-xs btn-ghost" @click="resetLlmAuditFilters">清空</button>
                                        </div>
                                    </div>
                                    <div class="text-xs opacity-60 mt-2">筛选结果 {{ llmAudit.filtered_total ?? (llmAudit.items || []).length }} / {{ llmAudit.total || 0 }}</div>
                                </div>
                                <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2">
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="text-xs opacity-60">{{ t('settings.auditCoverage') }}</div>
                                        <div class="text-xl font-bold">{{ Math.round((llmAudit.coverage || 0) * 100) }}%</div>
                                    </div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="text-xs opacity-60">Total</div>
                                        <div class="text-xl font-bold">{{ llmAudit.total || 0 }}</div>
                                    </div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="text-xs opacity-60">{{ t('settings.auditMissing') }}</div>
                                        <div class="text-xl font-bold">{{ llmAudit.missing_llm || 0 }}</div>
                                    </div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="text-xs opacity-60">{{ t('settings.auditFallback') }}</div>
                                        <div class="text-xl font-bold">{{ llmAudit.fallback_count || 0 }}</div>
                                    </div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="text-xs opacity-60">Full Translation</div>
                                        <div class="text-xl font-bold">{{ llmAudit.full_translation_count || 0 }}</div>
                                    </div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="text-xs opacity-60">{{ t('settings.auditRetranslated') }}</div>
                                        <div class="text-xl font-bold">{{ llmAudit.retranslated_count || 0 }}</div>
                                    </div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="text-xs opacity-60">{{ t('settings.auditLegacyTranslation') }}</div>
                                        <div class="text-xl font-bold">{{ llmAudit.translation_legacy_count || 0 }}</div>
                                    </div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="text-xs opacity-60">Quality Repair</div>
                                        <div class="text-xl font-bold">{{ llmAudit.quality_repair_count || 0 }}</div>
                                    </div>
                                </div>
                                <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                    <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
                                        <div>
                                            <div class="font-semibold">Translation Backfill</div>
                                            <div class="text-xs opacity-60 mt-1">历史文档缺失 opposite-language 全文译文审计；这里只做 dry-run 预览。</div>
                                        </div>
                                        <div class="flex flex-wrap gap-2">
                                            <button class="btn btn-xs btn-outline" @click="loadTranslationBackfillAudit" :disabled="loadingTranslationBackfill">
                                                <span v-if="loadingTranslationBackfill" class="loading loading-spinner loading-xs mr-1"></span>刷新审计
                                            </button>
                                            <button class="btn btn-xs btn-primary" @click="previewTranslationBackfillDryRun" :disabled="loadingTranslationBackfill">
                                                Dry-run 预览
                                            </button>
                                        </div>
                                    </div>
                                    <div v-if="translationBackfillAudit" class="space-y-3">
                                        <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                                            <div class="rounded-lg border border-base-200 p-2">
                                                <div class="opacity-60">Scanned</div>
                                                <div class="text-lg font-bold">{{ translationBackfillAudit.stats?.scanned || 0 }}</div>
                                            </div>
                                            <div class="rounded-lg border border-base-200 p-2">
                                                <div class="opacity-60">Missing</div>
                                                <div class="text-lg font-bold">{{ translationBackfillAudit.stats?.missing || 0 }}</div>
                                            </div>
                                            <div class="rounded-lg border border-base-200 p-2">
                                                <div class="opacity-60">Translated</div>
                                                <div class="text-lg font-bold">{{ translationBackfillAudit.stats?.already_translated || 0 }}</div>
                                            </div>
                                            <div class="rounded-lg border border-base-200 p-2">
                                                <div class="opacity-60">Policy</div>
                                                <div class="font-mono truncate">{{ translationBackfillAudit.policy?.targets || '-' }}</div>
                                            </div>
                                        </div>
                                        <div v-if="translationBackfillDryRun" class="rounded-lg border border-base-200 p-2 text-xs">
                                            Dry-run planned {{ translationBackfillDryRun.planned || 0 }} / applied {{ translationBackfillDryRun.applied || 0 }}
                                        </div>
                                        <div class="overflow-x-auto">
                                            <table class="table table-xs">
                                                <thead><tr><th>Doc</th><th>Source</th><th>Missing</th><th>Action</th></tr></thead>
                                                <tbody>
                                                    <tr v-for="item in (translationBackfillAudit.items || []).slice(0, 8)" :key="item.path">
                                                        <td class="max-w-xs truncate">{{ item.path }}</td>
                                                        <td>{{ item.source_language }}</td>
                                                        <td>{{ (item.missing_targets || []).join(', ') }}</td>
                                                        <td><button class="btn btn-xs btn-ghost" @click="previewDoc(item.path)">打开</button></td>
                                                    </tr>
                                                </tbody>
                                            </table>
                                        </div>
                                    </div>
                                    <div v-else class="text-xs opacity-60">尚未加载 backfill 审计。</div>
                                </div>
                                <div class="grid md:grid-cols-3 gap-3 text-xs">
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="font-semibold mb-2">Flow</div>
                                        <div v-for="[name, count] in objectEntries(llmAudit.by_flow).slice(0,6)" :key="name" class="flex justify-between gap-3 py-1 border-b border-base-200 last:border-0">
                                            <span class="font-mono truncate">{{ name }}</span><span>{{ count }}</span>
                                        </div>
                                    </div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="font-semibold mb-2">Provider</div>
                                        <div v-for="[name, count] in objectEntries(llmAudit.by_provider).slice(0,6)" :key="name" class="flex justify-between gap-3 py-1 border-b border-base-200 last:border-0">
                                            <span class="font-mono truncate">{{ name }}</span><span>{{ count }}</span>
                                        </div>
                                    </div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="font-semibold mb-2">Model</div>
                                        <div v-for="[name, count] in objectEntries(llmAudit.by_model).slice(0,6)" :key="name" class="flex justify-between gap-3 py-1 border-b border-base-200 last:border-0">
                                            <span class="font-mono truncate">{{ name }}</span><span>{{ count }}</span>
                                        </div>
                                    </div>
                                </div>
                                <div v-if="objectEntries(llmAudit.by_translation_model).length" class="grid md:grid-cols-2 gap-3 text-xs">
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="font-semibold mb-2">Translation Provider</div>
                                        <div v-for="[name, count] in objectEntries(llmAudit.by_translation_provider).slice(0,6)" :key="name" class="flex justify-between gap-3 py-1 border-b border-base-200 last:border-0">
                                            <span class="font-mono truncate">{{ name }}</span><span>{{ count }}</span>
                                        </div>
                                    </div>
                                    <div class="rounded-xl border border-base-300 bg-base-100 p-3">
                                        <div class="font-semibold mb-2">Translation Model</div>
                                        <div v-for="[name, count] in objectEntries(llmAudit.by_translation_model).slice(0,6)" :key="name" class="flex justify-between gap-3 py-1 border-b border-base-200 last:border-0">
                                            <span class="font-mono truncate">{{ name }}</span><span>{{ count }}</span>
                                        </div>
                                    </div>
                                </div>
                                <div>
                                    <div class="font-semibold mb-2">{{ t('settings.recentLlmDocs') }}</div>
                                    <div class="overflow-x-auto rounded-xl border border-base-300 bg-base-100">
                                        <table class="table table-xs">
                                            <thead><tr><th>Doc</th><th>Flow</th><th>Provider</th><th>Model</th><th>Status</th><th>Full</th><th>Retrans</th><th>Repair</th><th>Chain</th><th>Action</th></tr></thead>
                                            <tbody>
                                                <tr v-for="item in (llmAudit.items || []).slice(0,10)" :key="item.path" class="hover cursor-pointer" @click="openAuditDoc(item)">
                                                    <td class="max-w-xs truncate">{{ item.title || item.path }}</td>
                                                    <td class="font-mono">{{ item.llm?.flow || '-' }}</td>
                                                    <td class="font-mono">{{ item.llm?.provider || '-' }}</td>
                                                    <td class="font-mono">{{ item.llm?.model || '-' }}</td>
                                                    <td>{{ item.llm?.status || '-' }}</td>
                                                    <td>{{ item.llm_full_translation?.target_language || '-' }}</td>
                                                    <td>{{ item.llm_retranslation?.provider || '-' }}</td>
                                                    <td>{{ item.quality_repair?.method || '-' }}</td>
                                                    <td>
                                                        <span v-for="step in (item.generation_chain || [])" :key="item.path + step.type" class="badge badge-xs badge-outline mr-1">{{ step.type }}</span>
                                                    </td>
                                                    <td><button class="btn btn-xs btn-outline" @click.stop="openAuditDoc(item)">打开</button></td>
                                                </tr>
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </div>
                            <div v-else class="text-sm opacity-60">{{ loadingLlmAudit ? 'Loading...' : 'No audit data loaded.' }}</div>
                        </div>
                    </div>
                    <div v-if="featureEnabled('llm_settings') && llmBackups.length" class="card bg-base-200 border border-base-300 rounded-2xl mb-5">
                        <div class="card-body p-4">
                            <div class="font-semibold mb-2">{{ t('settings.backups') }}</div>
                            <div class="grid md:grid-cols-2 xl:grid-cols-3 gap-2">
                                <div v-for="backup in llmBackups.slice(0,6)" :key="backup.name" class="rounded-xl border border-base-300 bg-base-100 p-3 text-xs">
                                    <div class="font-mono truncate" :title="backup.name">{{ backup.name }}</div>
                                    <div class="opacity-60 mt-1">{{ backup.modified }}</div>
                                    <button class="btn btn-xs btn-outline mt-2" @click="restoreLlmBackup(backup.name)" :disabled="restoringLlmBackup === backup.name">
                                        <span v-if="restoringLlmBackup === backup.name" class="loading loading-spinner loading-xs mr-1"></span>{{ t('settings.restore') }}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div v-if="featureEnabled('llm_settings') && loadingLlmConfig" class="flex justify-center py-16"><span class="loading loading-spinner loading-lg text-primary"></span></div>
                    <div v-else-if="featureEnabled('llm_settings')" class="grid xl:grid-cols-[26rem_1fr] gap-5">
                        <section class="card bg-base-200 border border-base-300 rounded-2xl">
                            <div class="card-body p-5">
                                <div class="flex items-center justify-between mb-2">
                                    <h3 class="font-semibold">{{ t('settings.providers') }}</h3>
                                    <div class="flex items-center gap-2">
                                        <span class="badge badge-sm">{{ llmProviders.length }}</span>
                                        <button class="btn btn-xs btn-primary" @click="addLlmProvider">{{ t('settings.addProvider') }}</button>
                                    </div>
                                </div>
                                <div class="space-y-3">
                                    <div v-for="provider in llmProviders" :key="provider.name" class="rounded-xl border border-base-300 bg-base-100 p-4 space-y-3">
                                        <div class="flex items-center justify-between gap-2">
                                            <label class="form-control flex-1">
                                                <div class="label py-1"><span class="label-text text-xs">ID</span></div>
                                                <input v-model.trim="provider.name" @change="syncProviderName(provider)" class="input input-sm input-bordered font-mono text-xs" />
                                            </label>
                                            <div class="flex flex-col items-end gap-2">
                                                <span class="badge badge-sm" :class="provider.secret_configured ? 'badge-success' : (provider.api_key_env ? 'badge-warning' : 'badge-ghost')">
                                                    {{ provider.api_key_env ? (provider.secret_configured ? t('settings.secretReady') : t('settings.secretMissing')) : t('settings.noSecret') }}
                                                </span>
                                                <button class="btn btn-xs btn-ghost text-error" @click="deleteLlmProvider(provider)">{{ t('settings.deleteProvider') }}</button>
                                            </div>
                                        </div>
                                        <div class="flex items-center gap-2">
                                            <button class="btn btn-xs btn-outline" @click="testLlmProvider(provider)" :disabled="provider.testing">
                                                <span v-if="provider.testing" class="loading loading-spinner loading-xs mr-1"></span>{{ t('settings.test') }}
                                            </button>
                                            <span v-if="provider.test_result" class="text-xs" :class="provider.test_result.ok ? 'text-success' : 'text-error'">
                                                {{ provider.test_result.ok ? 'OK' : provider.test_result.error }}
                                            </span>
                                        </div>
                                        <div class="grid grid-cols-2 gap-2">
                                            <label class="form-control">
                                                <div class="label py-1"><span class="label-text text-xs">{{ t('settings.label') }}</span></div>
                                                <input v-model="provider.label" class="input input-sm input-bordered" />
                                            </label>
                                            <label class="form-control">
                                                <div class="label py-1"><span class="label-text text-xs">{{ t('settings.type') }}</span></div>
                                                <select v-model="provider.type" class="select select-sm select-bordered">
                                                    <option value="ollama">ollama</option>
                                                    <option value="openai_compatible">openai_compatible</option>
                                                </select>
                                            </label>
                                        </div>
                                        <label class="form-control">
                                            <div class="label py-1"><span class="label-text text-xs">{{ t('settings.model') }}</span></div>
                                            <input v-model="provider.model" class="input input-sm input-bordered" />
                                        </label>
                                        <label class="form-control">
                                            <div class="label py-1"><span class="label-text text-xs">{{ t('settings.baseUrl') }}</span></div>
                                            <input v-model="provider.base_url" class="input input-sm input-bordered font-mono text-xs" />
                                        </label>
                                        <div class="grid grid-cols-2 gap-2">
                                            <label class="form-control">
                                                <div class="label py-1"><span class="label-text text-xs">{{ t('settings.keyEnv') }}</span></div>
                                                <input v-model="provider.api_key_env" class="input input-sm input-bordered font-mono text-xs" placeholder="DEEPSEEK_API_KEY" />
                                            </label>
                                            <label class="form-control">
                                                <div class="label py-1"><span class="label-text text-xs">{{ t('settings.timeout') }}</span></div>
                                                <input v-model.number="provider.timeout_sec" type="number" min="1" class="input input-sm input-bordered" />
                                            </label>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </section>
                        <section class="card bg-base-200 border border-base-300 rounded-2xl">
                            <div class="card-body p-5">
                                <div class="flex items-center justify-between mb-2">
                                    <h3 class="font-semibold">{{ t('settings.flows') }}</h3>
                                    <span class="badge badge-sm">{{ llmFlows.length }}</span>
                                </div>
                                <div class="space-y-3">
                                    <div v-for="flow in llmFlows" :key="flow.name" class="rounded-xl border border-base-300 bg-base-100 p-4">
                                        <div class="grid lg:grid-cols-[1fr_16rem] gap-4">
                                            <div class="space-y-3">
                                                <div class="flex flex-wrap items-center gap-2">
                                                    <div class="font-semibold">{{ flow.name }}</div>
                                                    <span class="badge badge-sm badge-outline">{{ flow.intent }}</span>
                                                </div>
                                                <div class="grid md:grid-cols-2 gap-2">
                                                    <label class="form-control">
                                                        <div class="label py-1"><span class="label-text text-xs">{{ t('settings.label') }}</span></div>
                                                        <input v-model="flow.label" class="input input-sm input-bordered" />
                                                    </label>
                                                    <label class="form-control">
                                                        <div class="label py-1"><span class="label-text text-xs">{{ t('settings.intent') }}</span></div>
                                                        <input v-model="flow.intent" class="input input-sm input-bordered" />
                                                    </label>
                                                </div>
                                                <div class="form-control">
                                                    <div class="label py-1"><span class="label-text text-xs">{{ t('settings.providersOrder') }}</span></div>
                                                    <div class="space-y-2">
                                                        <div v-for="(providerName, idx) in flow.providers" :key="providerName + '-' + idx" class="flex items-center gap-2 rounded-lg border border-base-300 bg-base-200/70 px-2 py-2">
                                                            <span class="badge badge-sm badge-outline">{{ idx + 1 }}</span>
                                                            <div class="min-w-0 flex-1">
                                                                <div class="font-mono text-xs truncate">{{ providerName }}</div>
                                                                <div class="text-[11px] opacity-60 truncate">{{ providerLabel(providerName) }}</div>
                                                            </div>
                                                            <button class="btn btn-xs btn-ghost" @click="moveFlowProvider(flow, idx, -1)" :disabled="idx === 0">{{ t('settings.up') }}</button>
                                                            <button class="btn btn-xs btn-ghost" @click="moveFlowProvider(flow, idx, 1)" :disabled="idx === flow.providers.length - 1">{{ t('settings.down') }}</button>
                                                            <button class="btn btn-xs btn-ghost text-error" @click="removeFlowProvider(flow, idx)" :disabled="flow.providers.length <= 1">{{ t('settings.remove') }}</button>
                                                        </div>
                                                        <div class="flex gap-2">
                                                            <select v-model="flow.new_provider" class="select select-sm select-bordered flex-1">
                                                                <option value="">{{ t('settings.selectProvider') }}</option>
                                                                <option v-for="provider in availableProvidersForFlow(flow)" :key="provider.name" :value="provider.name">{{ provider.name }} · {{ provider.model }}</option>
                                                            </select>
                                                            <button class="btn btn-sm btn-outline" @click="addProviderToFlow(flow)" :disabled="!flow.new_provider">{{ t('settings.add') }}</button>
                                                        </div>
                                                    </div>
                                                </div>
                                                <label class="form-control">
                                                    <div class="label py-1"><span class="label-text text-xs">{{ t('settings.notes') }}</span></div>
                                                    <textarea v-model="flow.notes" class="textarea textarea-sm textarea-bordered min-h-16"></textarea>
                                                </label>
                                            </div>
                                            <div class="space-y-3">
                                                <label class="form-control">
                                                    <div class="label py-1"><span class="label-text text-xs">{{ t('settings.chunkChars') }}</span></div>
                                                    <input v-model.number="flow.chunk_chars" type="number" min="1" class="input input-sm input-bordered" />
                                                </label>
                                                <label class="form-control">
                                                    <div class="label py-1"><span class="label-text text-xs">{{ t('settings.fallbackNotice') }}</span></div>
                                                    <select v-model="flow.fallback_notice" class="select select-sm select-bordered">
                                                        <option value="record">record</option>
                                                        <option value="required">required</option>
                                                        <option value="none">none</option>
                                                    </select>
                                                </label>
                                                <label class="label cursor-pointer justify-start gap-3">
                                                    <input v-model="flow.allow_fallback" type="checkbox" class="toggle toggle-primary toggle-sm" />
                                                    <span class="label-text">{{ t('settings.allowFallback') }}</span>
                                                </label>
                                                <label class="label cursor-pointer justify-start gap-3">
                                                    <input v-model="flow.allow_online" type="checkbox" class="toggle toggle-primary toggle-sm" />
                                                    <span class="label-text">{{ t('settings.allowOnline') }}</span>
                                                </label>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </section>
                    </div>
                </div>
            </transition>

        </div>

        <!-- Candidate Edit Drawer Backdrop -->
        <transition name="fade">
            <div v-if="candidateEditOpen" @click="closeCandidateEdit" class="fixed inset-0 bg-black/40 backdrop-blur-[1px] z-40"></div>
        </transition>

        <!-- Candidate Review Edit Drawer -->
        <div :class="['fixed inset-y-0 right-0 w-full md:w-[34rem] bg-base-100 border-l border-base-300 shadow-2xl z-50 transform transition-transform duration-300 flex flex-col', candidateEditOpen ? 'translate-x-0' : 'translate-x-full']">
            <div class="p-4 border-b border-base-300 flex justify-between items-center bg-base-200">
                <div class="min-w-0">
                    <div class="font-semibold text-sm">审核编辑 · 入库前元数据</div>
                    <div class="text-xs opacity-60 truncate max-w-[24rem]">{{ candidateEditOriginalTitle }}</div>
                </div>
                <button class="btn btn-sm btn-circle btn-ghost" @click="closeCandidateEdit">✕</button>
            </div>
            <div class="flex-1 overflow-y-auto p-5 space-y-4">
                <div class="alert bg-primary/5 border border-primary/20 text-sm">
                    <div>这里保存的是审核信息。导入时会优先使用这些标题、分类和标签，并写入 wiki frontmatter。</div>
                </div>
                <label class="form-control w-full">
                    <div class="label"><span class="label-text font-semibold">入库标题</span></div>
                    <input v-model="candidateEditForm.title" class="input input-bordered w-full" placeholder="导入 wiki 时使用的标题" />
                </label>
                <label class="form-control w-full">
                    <div class="label"><span class="label-text font-semibold">分类</span></div>
                    <select v-model="candidateEditForm.category" class="select select-bordered w-full">
                        <option value="技术">技术</option>
                        <option value="教程">教程</option>
                        <option value="文章">文章</option>
                        <option value="学术论文">学术论文</option>
                        <option value="笔记">笔记</option>
                        <option value="新闻">新闻</option>
                        <option value="其他">其他</option>
                    </select>
                </label>
                <label class="form-control w-full">
                    <div class="label"><span class="label-text font-semibold">标签</span><span class="label-text-alt">逗号分隔</span></div>
                    <input v-model="candidateEditForm.tagsText" class="input input-bordered w-full" placeholder="Agent, LLM, RAG" />
                </label>
                <label class="form-control w-full">
                    <div class="label"><span class="label-text font-semibold">审核备注</span><span class="label-text-alt">可选</span></div>
                    <textarea v-model="candidateEditForm.notes" class="textarea textarea-bordered min-h-24" placeholder="为什么导入/暂缓、需要注意什么"></textarea>
                </label>
                <div v-if="candidateEditItem" class="rounded-2xl border border-base-300 bg-base-200 p-4 text-sm space-y-2">
                    <div class="font-semibold">候选参考</div>
                    <div><span class="opacity-60">质量：</span><span :class="['badge badge-sm', tierBadgeClass(candidateEditItem.quality_tier)]">{{ candidateEditItem.quality_tier }} · {{ candidateEditItem.quality_score }}分</span></div>
                    <div v-if="candidateEditItem.translated_summary"><span class="opacity-60">摘要：</span>{{ candidateEditItem.translated_summary }}</div>
                    <div v-if="candidateEditItem.translated_topics?.length"><span class="opacity-60">推荐主题：</span>{{ candidateEditItem.translated_topics.join(' / ') }}</div>
                    <div v-if="candidateEditItem.url" class="break-all"><span class="opacity-60">链接：</span>{{ candidateEditItem.url }}</div>
                </div>
            </div>
            <div class="p-4 border-t border-base-300 bg-base-200 flex justify-end gap-2">
                <button class="btn btn-ghost" @click="closeCandidateEdit">取消</button>
                <button class="btn btn-primary" @click="saveCandidateEdit" :disabled="savingCandidateEdit">
                    <span v-if="savingCandidateEdit" class="loading loading-spinner loading-xs mr-1"></span>
                    保存审核信息
                </button>
            </div>
        </div>

        <!-- Drawer Backdrop: click outside to close preview -->
        <transition name="fade">
            <div v-if="previewOpen" @click="closePreview" class="fixed inset-0 bg-black/40 backdrop-blur-[1px] z-40"></div>
        </transition>

        <!-- Right Side Panel: Document Preview / Edit Drawer -->
        <div :class="['fixed inset-y-0 right-0 w-full md:w-[32rem] bg-base-100 border-l border-base-300 shadow-2xl z-50 transform transition-transform duration-300 flex flex-col', previewOpen ? 'translate-x-0' : 'translate-x-full']">
            <div class="p-4 border-b border-base-300 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-2 bg-base-200">
                <div class="font-medium truncate max-w-full sm:max-w-[70%] text-sm">{{ previewDocName }}</div>
                <div class="flex gap-2 flex-wrap justify-start sm:justify-end">
                    <template v-if="previewMode === 'candidate'">
                        <button class="btn btn-sm btn-outline" @click="translateCandidate(candidateWorkbenchItem?.id, { refreshPreview: true })" :disabled="translatingCandidateId === candidateWorkbenchItem?.id">
                            <span v-if="translatingCandidateId === candidateWorkbenchItem?.id" class="loading loading-spinner loading-xs mr-1"></span>翻译
                        </button>
                        <button class="btn btn-sm btn-outline" @click="saveCandidateReviewInline" :disabled="savingCandidateEdit">
                            <span v-if="savingCandidateEdit" class="loading loading-spinner loading-xs mr-1"></span>保存审核
                        </button>
                        <button class="btn btn-sm btn-primary" @click="importCandidate(candidateWorkbenchItem?.id)" :disabled="importingCandidateId === candidateWorkbenchItem?.id">
                            <span v-if="importingCandidateId === candidateWorkbenchItem?.id" class="loading loading-spinner loading-xs mr-1"></span>导入
                        </button>
                    </template>
                    <template v-else>
                        <select v-if="!isEditingDoc" v-model="translationProvider" class="select select-sm select-bordered max-w-36" title="Translation provider">
                            <option v-for="m in translationModels" :key="m.provider" :value="m.provider" :disabled="!m.available">
                                {{ m.label || m.provider_name || m.provider }} · {{ m.kind || (m.online ? 'online' : 'local') }}{{ m.available ? '' : (m.key_env ? ' · missing ' + m.key_env : ' · unavailable') }}
                            </option>
                        </select>
                        <button class="btn btn-sm btn-outline" v-if="!isEditingDoc" @click="retranslateDoc" :disabled="isRetranslating || !previewDocPath">
                            <span v-if="isRetranslating" class="loading loading-spinner loading-xs mr-1"></span>{{ t('doc.retranslate') }}
                        </button>
                        <button class="btn btn-sm btn-ghost" v-if="!isEditingDoc" @click="isEditingDoc = true">✏️ {{ t('common.edit') }}</button>
                        <button class="btn btn-sm btn-primary" v-if="isEditingDoc" @click="saveDocContent">{{ t('common.save') }}</button>
                    </template>
                    <button class="btn btn-sm btn-circle btn-ghost" @click="closePreview">✕</button>
                </div>
            </div>
            <div class="flex-1 overflow-y-auto relative">
                <div v-if="previewLoading" class="absolute inset-0 flex items-center justify-center bg-base-100 z-10">
                    <span class="loading loading-spinner text-primary"></span>
                </div>
                
                <div v-if="previewMode === 'candidate'" class="border-b border-base-300 bg-base-200/60 p-4 space-y-4">
                    <div class="flex flex-wrap items-center justify-between gap-3">
                        <div>
                            <div class="font-semibold text-sm">候选审核工作台</div>
                            <div class="text-xs opacity-60 mt-1">预览 → 翻译 → 编辑元数据 → 导入 → 维护/验证</div>
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <span :class="['badge badge-sm', tierBadgeClass(candidateWorkbenchItem?.quality_tier)]">{{ candidateWorkbenchItem?.quality_tier || '?' }} · {{ candidateWorkbenchItem?.quality_score ?? 0 }}分</span>
                            <span class="badge badge-sm badge-outline">{{ candidateWorkbenchItem?.source_name || '未知来源' }}</span>
                            <span v-if="candidateWorkbenchItem?.translated_summary" class="badge badge-sm badge-success">已中文预览</span>
                            <span v-else class="badge badge-sm badge-warning">未中文预览</span>
                        </div>
                    </div>
                    <div v-if="candidateWorkbenchItem?.quality" class="grid md:grid-cols-2 gap-3 text-xs">
                        <div class="rounded-xl border border-success/30 bg-success/5 p-3">
                            <div class="font-semibold mb-1">加分原因</div>
                            <div v-if="candidateWorkbenchItem.quality.reasons?.length" class="flex flex-wrap gap-1">
                                <span v-for="r in candidateWorkbenchItem.quality.reasons" :key="r" class="badge badge-xs badge-outline text-success">+ {{ r }}</span>
                            </div>
                            <div v-else class="opacity-60">无</div>
                        </div>
                        <div class="rounded-xl border border-warning/30 bg-warning/5 p-3">
                            <div class="font-semibold mb-1">扣分/风险</div>
                            <div v-if="candidateWorkbenchItem.quality.penalties?.length" class="flex flex-wrap gap-1">
                                <span v-for="r in candidateWorkbenchItem.quality.penalties" :key="r" class="badge badge-xs badge-outline text-warning">- {{ r }}</span>
                            </div>
                            <div v-else class="opacity-60">无明显风险</div>
                        </div>
                    </div>
                    <div class="grid md:grid-cols-2 gap-3">
                        <label class="form-control">
                            <div class="label py-1"><span class="label-text text-xs font-semibold">入库标题</span></div>
                            <input v-model="candidateEditForm.title" class="input input-sm input-bordered" />
                        </label>
                        <label class="form-control">
                            <div class="label py-1"><span class="label-text text-xs font-semibold">分类</span></div>
                            <select v-model="candidateEditForm.category" class="select select-sm select-bordered">
                                <option value="技术">技术</option><option value="教程">教程</option><option value="文章">文章</option><option value="新闻">新闻</option><option value="其他">其他</option>
                            </select>
                        </label>
                        <label class="form-control md:col-span-2">
                            <div class="label py-1"><span class="label-text text-xs font-semibold">标签（逗号分隔）</span></div>
                            <input v-model="candidateEditForm.tagsText" class="input input-sm input-bordered" placeholder="Agent, LLM, RAG" />
                        </label>
                        <label class="form-control md:col-span-2">
                            <div class="label py-1"><span class="label-text text-xs font-semibold">审核备注</span></div>
                            <textarea v-model="candidateEditForm.notes" class="textarea textarea-sm textarea-bordered min-h-16" placeholder="为什么导入/暂缓、需要注意什么"></textarea>
                        </label>
                    </div>
                    <div class="flex flex-wrap gap-2 justify-end">
                        <button class="btn btn-sm btn-outline" @click="saveCandidateReviewInline" :disabled="savingCandidateEdit">保存审核信息</button>
                        <button class="btn btn-sm btn-outline" @click="translateCandidate(candidateWorkbenchItem?.id, { refreshPreview: true })" :disabled="translatingCandidateId === candidateWorkbenchItem?.id">预翻译/刷新中文</button>
                        <button class="btn btn-sm btn-primary" @click="importCandidate(candidateWorkbenchItem?.id)" :disabled="importingCandidateId === candidateWorkbenchItem?.id">导入并维护</button>
                        <button class="btn btn-sm btn-ghost text-error" @click="skipCandidate(candidateWorkbenchItem?.id)">跳过</button>
                    </div>
                </div>

                <textarea v-if="isEditingDoc" v-model="previewContent" class="w-full h-full p-4 bg-base-100 resize-none outline-none font-mono text-sm leading-relaxed" spellcheck="false"></textarea>
                
                <template v-else>
                    <div v-if="previewMode === 'document'" class="border-b border-base-300 bg-base-200/60 p-4 text-xs">
                        <div class="flex flex-wrap items-center gap-2">
                            <span class="badge badge-sm badge-outline">{{ previewMeta.category || '未分类' }}</span>
                            <span :class="['badge badge-sm', previewMeta.quality?.ok ? 'badge-success' : 'badge-warning']">{{ previewMeta.quality?.ok ? '质量OK' : '质量待修复' }}</span>
                            <span v-if="previewMeta.llm?.provider" class="badge badge-sm badge-info">{{ previewMeta.llm.flow || 'llm' }} · {{ previewMeta.llm.provider }} / {{ previewMeta.llm.model || '-' }}</span>
                            <span v-if="previewMeta.llm_full_translation?.provider" class="badge badge-sm badge-primary">全文翻译 · {{ previewMeta.llm_full_translation.target_language || '-' }} · {{ previewMeta.llm_full_translation.provider }} / {{ previewMeta.llm_full_translation.model || '-' }}</span>
                            <span v-if="previewMeta.llm_retranslation?.provider" class="badge badge-sm badge-secondary">重翻译 · {{ previewMeta.llm_retranslation.provider }} / {{ previewMeta.llm_retranslation.model || '-' }}</span>
                            <span v-if="previewMeta.quality_repair?.method" class="badge badge-sm badge-accent">质量修复 · {{ previewMeta.quality_repair.method }}</span>
                        </div>
                        <div v-if="previewMeta.quality && !previewMeta.quality.ok" class="mt-2 opacity-70">问题：{{ issueText(previewMeta.quality.issues || []) }}</div>
                        <div v-if="previewAuditItem" class="mt-3 rounded-xl border border-info/30 bg-info/10 p-3">
                            <div class="flex flex-wrap items-center justify-between gap-2">
                                <div class="font-semibold text-info">LLM 审计链路</div>
                                <div class="opacity-60">{{ previewAuditItem.llm?.status || '-' }} · {{ previewAuditItem.modified || '' }}</div>
                            </div>
                            <div class="mt-2 flex flex-wrap gap-1">
                                <span v-for="step in (previewAuditItem.generation_chain || [])" :key="previewAuditItem.path + step.type" class="badge badge-xs badge-outline">
                                    {{ step.type }}<template v-if="step.provider"> · {{ step.provider }}</template><template v-if="step.model"> / {{ step.model }}</template><template v-if="step.status"> · {{ step.status }}</template>
                                </span>
                            </div>
                            <div v-if="previewAuditItem.llm?.fallback_from" class="mt-2 text-warning">fallback：{{ previewAuditItem.llm.fallback_from }} → {{ previewAuditItem.llm.fallback_to }}</div>
                        </div>
                    </div>
                    <div v-if="previewRelated.length" class="border-b border-base-300 bg-base-200/60 p-4">
                        <div class="flex items-center justify-between gap-2 mb-3">
                            <div class="font-semibold text-sm">🔗 相关文档推荐</div>
                            <div class="text-xs opacity-60">入链 {{ previewAssociation?.incoming_count ?? 0 }} · 出链 {{ previewAssociation?.outgoing_count ?? 0 }} · 推荐 {{ previewRelated.length }}</div>
                        </div>
                        <div v-if="previewAssociation?.link_suggestions?.length" class="mb-3 rounded-xl border border-info/30 bg-info/10 p-3 text-xs">
                            <div class="font-semibold text-info mb-2">补链建议分层</div>
                            <div v-for="s in previewAssociation.link_suggestions.slice(0,3)" :key="s.source_path + '→' + s.target_path" class="mb-1 last:mb-0">
                                <span class="badge badge-xs mr-1" :class="s.action === 'auto_link' ? 'badge-warning' : (s.action === 'recommend_only' ? 'badge-info' : 'badge-ghost')">{{ s.action === 'auto_link' ? '可自动补' : (s.action === 'recommend_only' ? '仅推荐' : '低置信') }}</span>
                                {{ s.target_title }} · {{ s.reason }}
                            </div>
                        </div>
                        <div class="space-y-2">
                            <button v-for="r in previewRelated.slice(0,5)" :key="r.path" @click="previewDoc(r.path)" class="w-full text-left rounded-xl border border-base-300 bg-base-100 hover:bg-base-200 p-3 transition-colors">
                                <div class="flex items-start justify-between gap-2">
                                    <div class="font-medium text-sm line-clamp-2">{{ r.title || r.path }}</div>
                                    <span class="badge badge-sm badge-primary">{{ r.score }}</span>
                                </div>
                                <div class="mt-1 text-xs opacity-70">
                                    <span>{{ r.category || '未分类' }}</span>
                                    <span v-if="r.shared_entities?.length"> · 共享：{{ r.shared_entities.join('、') }}</span>
                                </div>
                            </button>
                        </div>
                    </div>
                    <div class="p-6 markdown-body" v-html="renderMarkdown(previewContent)"></div>
                </template>
            </div>
        </div>
        
        <!-- Toast Notifications -->
        <div class="toast toast-top toast-center z-[100]">
            <div v-for="t in toasts" :key="t.id" :class="['alert', 'alert-'+t.type, 'shadow-lg']">
                <span>{{ t.msg }}</span>
            </div>
        </div>

    </div>

    <!-- Application Logic -->
    <script>
        const { createApp, ref, reactive, onMounted, computed, watch, nextTick } = Vue;

        createApp({
            setup() {
                const activeTab = ref('chat');
                const theme = ref(localStorage.getItem('theme') || 'dark');
                const mobileMenuOpen = ref(false);
                const graphLayout = ref('sankey');
                const graphSearchText = ref('');
                const associationReport = ref(null);
                const loadingAssociations = ref(false);
                const uiLang = ref(localStorage.getItem('kb_ui_lang') || 'zh');
                const defaultTranslationPolicy = () => ({
                    enabled: true,
                    mode: 'bilingual_on_import',
                    targets: 'auto_opposite',
                    fallback_on_failure: 'preview_only',
                    candidate_tiers: ['A', 'B'],
                    preserve_original_full: true,
                    max_chunk_chars: 3500,
                    full_translate: {
                        url_import: true,
                        file_upload: true,
                        candidate_import: true,
                        rss_candidate_preview: false,
                        wechat_candidate_import: true
                    },
                    chinese_source: { translate_to_english: true },
                    english_source: { translate_to_chinese: true }
                });
                const mergeTranslationPolicy = (policy = {}) => {
                    const defaults = defaultTranslationPolicy();
                    const incoming = policy || {};
                    return {
                        ...defaults,
                        ...incoming,
                        candidate_tiers: Array.isArray(incoming.candidate_tiers) ? incoming.candidate_tiers : defaults.candidate_tiers,
                        full_translate: { ...defaults.full_translate, ...(incoming.full_translate || {}) },
                        chinese_source: { ...defaults.chinese_source, ...(incoming.chinese_source || {}) },
                        english_source: { ...defaults.english_source, ...(incoming.english_source || {}) }
                    };
                };
                const webuiConfig = ref({
                    app: { name: 'Sunoxi KB', title: 'Sunoxi 知识库', subtitle: 'Personal Knowledge Base', logo: '/static/favicon.svg?v=4' },
                    features: { chat: true, graph: true, documents: true, upload: true, url_import: true, candidates: true, rss: true, wechat: true, llm_settings: true, llm_audit: true },
                    translation_policy: defaultTranslationPolicy()
                });
                const loadingWebuiConfig = ref(false);
                const savingWebuiConfig = ref(false);
                const webuiApp = computed(() => webuiConfig.value.app || {});
                const webuiFeatures = computed(() => webuiConfig.value.features || {});
                const featureEnabled = (name) => webuiFeatures.value[name] !== false;
                const i18n = {
                    zh: {
                        nav: { chat: '智能问答', graph: '知识图谱', docs: '文档管理', candidates: '候选池', wechat: '公众号订阅', rss: 'RSS订阅', settings: '系统设置' },
                        chat: { emptyTitle: '今天想研究点什么？', emptyBody: '可以直接向我提问，或者输入关键词进行语义搜索。' },
                        docs: {
                            title: '文档管理', subtitle: '支持拖拽文件上传，自动分析摘要与实体', filter: '过滤文档...',
                            maintenance: '维护知识库', maintaining: '维护中...', fetchUrl: '从网址抓取', upload: '上传文件',
                            dropTitle: '将文件拖拽到此处', dropBody: '支持 Markdown, TXT, Python, PDF 等格式',
                            fetchTitle: '从网址抓取文章', fetchPlaceholder: '输入文章网址，例如 https://example.com/article',
                            fetching: '抓取中...', fetchImport: '抓取并导入', fetchSuccess: '抓取成功！文档已导入知识库。',
                            folders: '目录结构', items: '个文档', sorted: '按修改时间排序', viewAll: '查看全部',
                            empty: '当前目录没有匹配文档', page: '第', total: '共', prev: '上一页', next: '下一页'
                        },
                        settings: {
                            title: '系统设置', subtitle: '管理知识库名称、环境功能开关、模型策略与审计信息',
                            basic: '基础设置', features: '功能开关', appName: '知识库名称', appTitle: '页面标题', appSubtitle: '副标题', appLogo: 'Logo 路径',
                            featureHint: '关闭功能会隐藏菜单，并让对应 API 返回 403。',
                            refresh: '刷新', save: '保存配置', secretNote: '这里不会显示或保存 API Key，只显示环境变量名和是否已配置。',
                            deploymentMode: '部署模式', deploymentModeHint: '一键切换全局策略；保存前会自动备份 llm_runtime.yaml。',
                            secretFile: '密钥文件', systemdDropin: 'systemd 配置', setupCommand: '一键配置命令',
                            configured: '已配置', notConfigured: '未配置', permissionMode: '权限',
                            audit: 'LLM 审计', auditRefresh: '刷新审计', auditCoverage: '覆盖率', auditMissing: '缺少元数据',
                            auditFallback: 'Fallback', auditRetranslated: '已重翻译', auditLegacyTranslation: '历史翻译', recentLlmDocs: '最近模型产物',
                            providers: 'Providers', flows: '业务流策略', label: '显示名', type: '类型', model: '模型', baseUrl: 'Base URL',
                            keyEnv: 'Key 环境变量', timeout: '超时秒数', secretReady: '密钥已配置', secretMissing: '缺少密钥', noSecret: '无需密钥',
                            intent: '策略意图', providersOrder: 'Provider 顺序', notes: '备注', chunkChars: '分片字符数',
                            fallbackNotice: 'Fallback 记录', allowFallback: '允许 fallback', allowOnline: '允许在线模型', test: '测试',
                            backups: '配置备份', restore: '恢复', addProvider: '新增', deleteProvider: '删除',
                            selectProvider: '选择 Provider', add: '添加', remove: '移除', up: '上移', down: '下移',
                            missingProvider: 'Provider 不存在'
                        },
                        doc: { retranslate: '重新翻译' },
                        common: { edit: '编辑', save: '保存' }
                    },
                    en: {
                        nav: { chat: 'Chat', graph: 'Knowledge Graph', docs: 'Documents', candidates: 'Candidates', wechat: 'WeChat Sources', rss: 'RSS Feeds', settings: 'System Settings' },
                        chat: { emptyTitle: 'What do you want to research today?', emptyBody: 'Ask a question directly, or enter keywords for semantic search.' },
                        docs: {
                            title: 'Documents', subtitle: 'Drag files here, analyze summaries and entities automatically', filter: 'Filter documents...',
                            maintenance: 'Maintain KB', maintaining: 'Maintaining...', fetchUrl: 'Fetch URL', upload: 'Upload',
                            dropTitle: 'Drop files here', dropBody: 'Supports Markdown, TXT, Python, PDF and more',
                            fetchTitle: 'Fetch Article From URL', fetchPlaceholder: 'Enter article URL, e.g. https://example.com/article',
                            fetching: 'Fetching...', fetchImport: 'Fetch and Import', fetchSuccess: 'Fetched successfully. Document imported.',
                            folders: 'Folders', items: 'documents', sorted: 'sorted by modified time', viewAll: 'View all',
                            empty: 'No matching documents in this folder', page: 'Page', total: 'Total', prev: 'Prev', next: 'Next'
                        },
                        settings: {
                            title: 'System Settings', subtitle: 'Manage branding, environment feature switches, model policies, and audit data.',
                            basic: 'Basic Settings', features: 'Feature Switches', appName: 'Knowledge Base Name', appTitle: 'Page Title', appSubtitle: 'Subtitle', appLogo: 'Logo Path',
                            featureHint: 'Disabled features are hidden from navigation and blocked by API gates.',
                            refresh: 'Refresh', save: 'Save Config', secretNote: 'API keys are never shown or saved here. Only env var names and configured status are displayed.',
                            deploymentMode: 'Deployment Mode', deploymentModeHint: 'Switch global policy presets. llm_runtime.yaml is backed up before changes.',
                            secretFile: 'Secret file', systemdDropin: 'systemd drop-in', setupCommand: 'One-shot setup command',
                            configured: 'Configured', notConfigured: 'Not configured', permissionMode: 'Mode',
                            audit: 'LLM Audit', auditRefresh: 'Refresh Audit', auditCoverage: 'Coverage', auditMissing: 'Missing metadata',
                            auditFallback: 'Fallback', auditRetranslated: 'Retranslated', auditLegacyTranslation: 'Legacy translation', recentLlmDocs: 'Recent LLM outputs',
                            providers: 'Providers', flows: 'Flow Policies', label: 'Label', type: 'Type', model: 'Model', baseUrl: 'Base URL',
                            keyEnv: 'Key Env Var', timeout: 'Timeout Sec', secretReady: 'Secret ready', secretMissing: 'Secret missing', noSecret: 'No secret',
                            intent: 'Intent', providersOrder: 'Provider order', notes: 'Notes', chunkChars: 'Chunk chars',
                            fallbackNotice: 'Fallback notice', allowFallback: 'Allow fallback', allowOnline: 'Allow online', test: 'Test',
                            backups: 'Config Backups', restore: 'Restore', addProvider: 'Add', deleteProvider: 'Delete',
                            selectProvider: 'Select provider', add: 'Add', remove: 'Remove', up: 'Up', down: 'Down',
                            missingProvider: 'Missing provider'
                        },
                        doc: { retranslate: 'Retranslate' },
                        common: { edit: 'Edit', save: 'Save' }
                    }
                };
                const t = (key) => key.split('.').reduce((obj, part) => obj && obj[part], i18n[uiLang.value]) || key;
                watch(uiLang, (v) => {
                    localStorage.setItem('kb_ui_lang', v);
                    document.documentElement.lang = v === 'en' ? 'en' : 'zh';
                }, { immediate: true });
                watch(webuiApp, (app) => {
                    if(app?.title) document.title = app.title;
                }, { immediate: true, deep: true });

                const loadWebuiConfig = async () => {
                    loadingWebuiConfig.value = true;
                    try {
                        const res = await fetch('/api/webui/config');
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        webuiConfig.value = {
                            app: data.app || webuiConfig.value.app,
                            features: data.features || webuiConfig.value.features,
                            translation_policy: mergeTranslationPolicy(data.translation_policy || webuiConfig.value.translation_policy)
                        };
                    } catch(e) {
                        showToast(`加载系统设置失败: ${e.message}`, 'error', 7000);
                    } finally {
                        loadingWebuiConfig.value = false;
                    }
                };

                const saveWebuiConfig = async () => {
                    savingWebuiConfig.value = true;
                    try {
                        const res = await fetch('/api/webui/config', {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(webuiConfig.value)
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        webuiConfig.value = {
                            app: data.app || webuiConfig.value.app,
                            features: data.features || webuiConfig.value.features,
                            translation_policy: mergeTranslationPolicy(data.translation_policy || webuiConfig.value.translation_policy)
                        };
                        showToast('系统设置已保存', 'success');
                    } catch(e) {
                        showToast(`保存系统设置失败: ${e.message}`, 'error', 7000);
                    } finally {
                        savingWebuiConfig.value = false;
                    }
                };

                const saveAllSettings = async () => {
                    await saveWebuiConfig();
                    if(featureEnabled('llm_settings')) await saveLlmConfig();
                };

                const refreshAllSettings = async () => {
                    await loadWebuiConfig();
                    if(featureEnabled('llm_settings')) await loadLlmConfig();
                    if(featureEnabled('llm_audit')) await loadLlmAudit();
                };
                
                // Switch Tab Logic
                const switchTab = (tab) => {
                    if(tab !== 'settings' && !featureEnabled(tab === 'docs' ? 'documents' : tab)) {
                        showToast('该功能已在系统设置中关闭', 'warning');
                        return;
                    }
                    activeTab.value = tab;
                    mobileMenuOpen.value = false;
                    if(previewOpen.value) closePreview();
                    if(tab === 'graph') {
                        loadAssociations(false).catch(()=>{});
                        nextTick(() => initGraph());
                    } else if(tab === 'docs') {
                        loadDocs();
                    } else if(tab === 'candidates') {
                        loadCandidates();
                    } else if(tab === 'wechat') {
                        loadWechatSources();
                    } else if(tab === 'rss') {
                        loadRssFeeds();
                    } else if(tab === 'settings') {
                        loadWebuiConfig();
                        loadLlmConfig();
                        loadLlmAudit();
                    }
                };

                // Theme
                const toggleTheme = () => {
                    theme.value = theme.value === 'dark' ? 'light' : 'dark';
                    document.documentElement.setAttribute('data-theme', theme.value);
                    localStorage.setItem('theme', theme.value);
                    if(activeTab.value === 'graph' && chartInstance) {
                        setTimeout(initGraph, 100); // Re-render graph with new theme colors
                    }
                };
                document.documentElement.setAttribute('data-theme', theme.value);

                // --- Toasts ---
                const toasts = ref([]);
                let toastId = 0;
                const showToast = (msg, type='info', duration=3000) => {
                    const id = toastId++;
                    toasts.value.push({id, msg, type});
                    setTimeout(() => { toasts.value = toasts.value.filter(t => t.id !== id); }, duration);
                };

                // --- Markdown Setup ---
                const renderMarkdown = (() => {
                    try {
                        if (typeof marked === 'undefined') throw new Error('marked not loaded');
                        marked.setOptions({
                            highlight: function(code, lang) {
                                try {
                                    if (lang && hljs.getLanguage(lang)) {
                                        return hljs.highlight(code, { language: lang }).value;
                                    }
                                    return hljs.highlightAuto(code).value;
                                } catch(e) { return code; }
                            },
                            breaks: true
                        });
                        return (text) => {
                            try {
                                const html = marked.parse(text || '');
                                return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
                            } catch(e) { return '<pre>' + (text || '') + '</pre>'; }
                        };
                    } catch(e) {
                        console.warn('Markdown init failed:', e);
                        return (text) => '<pre>' + (text || '') + '</pre>';
                    }
                })();

                // --- Chat System ---
                const chatInput = ref('');
                const chatHistory = ref([]);
                const isWaiting = ref(false);
                const chatAnswerMode = ref(localStorage.getItem('kb_chat_answer_mode') || 'extractive');
                watch(chatAnswerMode, (v) => localStorage.setItem('kb_chat_answer_mode', v));
                
                const scrollToBottom = () => {
                    nextTick(() => {
                        const container = document.getElementById('chat-container');
                        if (container) container.scrollTop = container.scrollHeight;
                    });
                };

                const ask = (text) => { chatInput.value = text; submitChat(); };
                
                const submitChat = async () => {
                    const q = chatInput.value.trim();
                    if(!q) return;
                    
                    chatHistory.value.push({ role: 'user', content: q, time: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) });
                    chatInput.value = '';
                    isWaiting.value = true;
                    scrollToBottom();
                    
                    try {
                        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&qa=true&answer_mode=${encodeURIComponent(chatAnswerMode.value)}`);
                        const data = await res.json();
                        
                        chatHistory.value.push({
                            role: 'ai',
                            content: data.answer || "未能生成答案。",
                            sources: data.documents || [],
                            citations: data.citations || [],
                            latency: data.latency,
                            cache_hit: data.cache_hit,
                            context_preview: data.context_preview,
                            diagnostics: data.diagnostics || {},
                            answer_mode: data.answer_mode,
                            llm: data.llm,
                            time: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
                        });
                    } catch (e) {
                        showToast("问答请求失败", "error");
                        chatHistory.value.push({ role: 'ai', content: "系统内部错误，无法连接到模型。" });
                    } finally {
                        isWaiting.value = false;
                        scrollToBottom();
                    }
                };

                // --- Document Preview Drawer ---
                const previewOpen = ref(false);
                const previewLoading = ref(false);
                const previewContent = ref('');
                const previewDocName = ref('');
                const previewDocPath = ref('');
                const previewRelated = ref([]);
                const previewAssociation = ref(null);
                const previewMeta = ref({});
                const previewAuditItem = ref(null);
                const previewMode = ref('document');
                const candidateWorkbenchItem = ref(null);
                const isEditingDoc = ref(false);
                const translationModels = ref([]);
                const translationProvider = ref('local_gemma4');
                const isRetranslating = ref(false);
                const llmProviders = ref([]);
                const llmFlows = ref([]);
                const llmBackups = ref([]);
                const llmSecretSetup = ref(null);
                const llmMode = ref('hybrid');
                const llmModeOptions = ref([]);
                const settingLlmMode = ref('');
                const llmAudit = ref(null);
                const llmAuditFilters = reactive({ flow: '', provider: '', model: '', status: '', missing: false, fallback: false, retranslated: false });
                const loadingLlmAudit = ref(false);
                const translationBackfillAudit = ref(null);
                const translationBackfillDryRun = ref(null);
                const loadingTranslationBackfill = ref(false);
                const loadingLlmConfig = ref(false);
                const savingLlmConfig = ref(false);
                const restoringLlmBackup = ref('');
                const objectEntries = (obj) => Object.entries(obj || {});
                const selectedTranslationModel = computed(() => translationModels.value.find(m => m.provider === translationProvider.value || m.provider_name === translationProvider.value || m.id === translationProvider.value) || null);
                const translationProviderLabel = (model) => {
                    if(!model) return translationProvider.value || '-';
                    const kind = model.kind === 'online' ? '在线' : '本地';
                    return `${model.label || model.provider_name || model.provider || kind} · ${model.model || '-'}`;
                };
                const llmModeLabel = computed(() => (llmModeOptions.value.find(m => m.id === llmMode.value)?.label) || llmMode.value || 'custom');
                const llmModeDescription = computed(() => (llmModeOptions.value.find(m => m.id === llmMode.value)?.description) || '');
                const fileImportFlow = computed(() => llmFlows.value.find(f => f.name === 'file_import_structure') || null);
                const fileImportProviderChain = computed(() => (fileImportFlow.value?.providers || []).map(name => {
                    const p = llmProviders.value.find(item => item.name === name);
                    return p ? `${name} / ${p.model}` : name;
                }).join(' -> '));
                const qaFlow = computed(() => llmFlows.value.find(f => f.name === 'qa') || null);
                const qaProviderChain = computed(() => (qaFlow.value?.providers || []).map(name => {
                    const p = llmProviders.value.find(item => item.name === name);
                    return p ? `${name} / ${p.model}` : name;
                }).join(' -> '));

                const normalizeLlmProviders = (items) => (items || []).map(p => ({
                    ...p,
                    name: String(p.name || '').trim(),
                    _original_name: String(p.name || '').trim()
                }));

                const normalizeLlmFlows = (items) => (items || []).map(f => ({
                    ...f,
                    providers: Array.isArray(f.providers) ? f.providers.filter(Boolean) : [],
                    new_provider: ''
                }));

                const providerLabel = (name) => {
                    const p = llmProviders.value.find(item => item.name === name);
                    if(!p) return t('settings.missingProvider') || 'Missing provider';
                    return [p.label, p.model].filter(Boolean).join(' · ');
                };

                const nextProviderName = () => {
                    const used = new Set(llmProviders.value.map(p => p.name));
                    let idx = 1;
                    let name = 'new_provider';
                    while(used.has(name)) {
                        idx += 1;
                        name = `new_provider_${idx}`;
                    }
                    return name;
                };

                const addLlmProvider = () => {
                    const name = nextProviderName();
                    llmProviders.value.push({
                        name,
                        _original_name: name,
                        type: 'ollama',
                        label: 'New Provider',
                        model: 'gemma4:e4b',
                        base_url: 'http://127.0.0.1:11434',
                        api_key_env: '',
                        timeout_sec: 60,
                        options: {},
                        online: false,
                        secret_configured: false
                    });
                    showToast(`已新增 Provider：${name}`, 'info', 4000);
                };

                const syncProviderName = (provider) => {
                    const oldName = provider._original_name || '';
                    const newName = String(provider.name || '').trim();
                    if(!/^[A-Za-z0-9_-]+$/.test(newName)) {
                        provider.name = oldName;
                        showToast('Provider ID 只能包含字母、数字、下划线和短横线', 'error', 6000);
                        return;
                    }
                    const duplicate = llmProviders.value.some(p => p !== provider && p.name === newName);
                    if(duplicate) {
                        provider.name = oldName;
                        showToast(`Provider ID 已存在：${newName}`, 'error', 6000);
                        return;
                    }
                    if(oldName && oldName !== newName) {
                        llmFlows.value.forEach(flow => {
                            flow.providers = (flow.providers || []).map(name => name === oldName ? newName : name);
                        });
                    }
                    provider._original_name = newName;
                };

                const deleteLlmProvider = (provider) => {
                    if(!provider?.name) return;
                    const refs = llmFlows.value.filter(flow => (flow.providers || []).includes(provider.name)).map(flow => flow.name);
                    const message = refs.length
                        ? `确认删除 Provider ${provider.name}？它会同时从这些业务流移除：${refs.join(', ')}`
                        : `确认删除 Provider ${provider.name}？`;
                    if(!confirm(message)) return;
                    llmProviders.value = llmProviders.value.filter(p => p !== provider);
                    const fallback = llmProviders.value[0]?.name || '';
                    llmFlows.value.forEach(flow => {
                        flow.providers = (flow.providers || []).filter(name => name !== provider.name);
                        if(!flow.providers.length && fallback) flow.providers = [fallback];
                    });
                    showToast(`已删除 Provider：${provider.name}`, 'info', 4000);
                };

                const availableProvidersForFlow = (flow) => {
                    const selected = new Set(flow.providers || []);
                    return llmProviders.value.filter(provider => !selected.has(provider.name));
                };

                const addProviderToFlow = (flow) => {
                    if(!flow.new_provider) return;
                    flow.providers = flow.providers || [];
                    if(!flow.providers.includes(flow.new_provider)) {
                        flow.providers.push(flow.new_provider);
                    }
                    flow.new_provider = '';
                };

                const removeFlowProvider = (flow, idx) => {
                    if(!flow.providers || flow.providers.length <= 1) return;
                    flow.providers.splice(idx, 1);
                };

                const moveFlowProvider = (flow, idx, delta) => {
                    const providers = flow.providers || [];
                    const target = idx + delta;
                    if(target < 0 || target >= providers.length) return;
                    const [item] = providers.splice(idx, 1);
                    providers.splice(target, 0, item);
                };

                const closePreview = () => {
                    previewOpen.value = false;
                    isEditingDoc.value = false;
                    previewRelated.value = [];
                    previewAssociation.value = null;
                    previewMeta.value = {};
                    previewAuditItem.value = null;
                    previewMode.value = 'document';
                    candidateWorkbenchItem.value = null;
                };

                const previewDoc = async (path, options = {}) => {
                    previewDocPath.value = path;
                    previewDocName.value = path.split('/').pop();
                    previewOpen.value = true;
                    previewLoading.value = true;
                    isEditingDoc.value = false;
                    previewContent.value = '';
                    previewRelated.value = [];
                    previewAssociation.value = null;
                    previewMeta.value = {};
                    previewAuditItem.value = options.auditItem || null;
                    previewMode.value = 'document';
                    candidateWorkbenchItem.value = null;
                    
                    try {
                        const res = await fetch(`/api/documents/${encodeURIComponent(path)}`);
                        if(res.ok) {
                            const data = await res.json();
                            previewContent.value = data.content || '';
                            previewRelated.value = data.related || [];
                            previewAssociation.value = data.association || null;
                            previewMeta.value = data.meta || {};
                        } else {
                            previewContent.value = "无法加载文档内容。";
                        }
                    } catch(e) {
                        showToast("加载失败", "error");
                    } finally {
                        previewLoading.value = false;
                    }
                };

                const focusDocInList = async (path) => {
                    if(!path) return;
                    activeTab.value = 'docs';
                    const parts = path.split('/');
                    selectedDocFolder.value = parts.length > 1 ? parts.slice(0, -1).join('/') : '';
                    docSearchText.value = parts[parts.length - 1] || path;
                    docsPage.value = 1;
                    await nextTick();
                    previewDoc(path);
                };

                const openAuditDoc = async (item) => {
                    if(!item?.path) return;
                    await previewDoc(item.path, { auditItem: item });
                };

                const openDocAudit = async (path) => {
                    if(!path) return;
                    activeTab.value = 'settings';
                    if(!llmAudit.value && !loadingLlmAudit.value) await loadLlmAudit();
                    const item = (llmAudit.value?.items || []).find(x => x.path === path);
                    if(item) {
                        await previewDoc(path, { auditItem: item });
                    } else {
                        await previewDoc(path);
                        showToast('已打开文档；当前审计筛选中未找到对应条目', 'info', 5000);
                    }
                };

                const saveDocContent = async () => {
                    try {
                        const res = await fetch(`/api/documents/${encodeURIComponent(previewDocPath.value)}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ content: previewContent.value })
                        });
                        if(res.ok) {
                            showToast("保存成功", "success");
                            isEditingDoc.value = false;
                        } else {
                            throw new Error("保存失败");
                        }
                    } catch(e) {
                        showToast("保存出错: " + e.message, "error");
                    }
                };

                const loadTranslationModels = async () => {
                    try {
                        const res = await fetch('/api/translation/models');
                        const data = await res.json();
                        translationModels.value = data.models || [];
                        const current = selectedTranslationModel.value;
                        if(!current || current.available === false) {
                            const firstAvailable = translationModels.value.find(m => m.available);
                            translationProvider.value = firstAvailable?.provider || translationModels.value[0]?.provider || 'local_gemma4';
                        }
                    } catch(e) {
                        translationModels.value = [
                            { id: 'deepseek_pro', provider: 'deepseek_pro', provider_name: 'deepseek_pro', kind: 'online', label: 'DeepSeek Pro', model: 'deepseek-v4-pro', available: false, key_env: 'DEEPSEEK_API_KEY' },
                            { id: 'local_gemma4', provider: 'local_gemma4', provider_name: 'local_gemma4', kind: 'local', label: 'Local Gemma4', model: 'gemma4:e4b', available: true }
                        ];
                        translationProvider.value = 'local_gemma4';
                    }
                };

                const retranslateDoc = async () => {
                    if(!previewDocPath.value || isRetranslating.value) return;
                    const selected = selectedTranslationModel.value || {};
                    if(selected.available === false) {
                        showToast(`${translationProviderLabel(selected)} 不可用${selected.key_env ? `：缺少 ${selected.key_env}` : ''}`, 'warning', 6000);
                        return;
                    }
                    isRetranslating.value = true;
                    showToast(`正在使用 ${translationProviderLabel(selected)} 生成重翻译预览...`, 'info', 6000);
                    try {
                        const previewRes = await fetch(`/api/documents/${encodeURIComponent(previewDocPath.value)}/translate`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ provider: translationProvider.value, model: selected.model || '', dry_run: true })
                        });
                        const preview = await previewRes.json();
                        if(!previewRes.ok) throw new Error(preview.error || `HTTP ${previewRes.status}`);
                        const translationPreview = (preview.preview?.translation || preview.preview?.summary || '').slice(0, 220);
                        const confirmMsg = `确认应用重新翻译？\n模型：${preview.provider || translationProvider.value} / ${preview.model || selected.model || '-'}\nchunks：${preview.chunk_count || 0}\n预览：${translationPreview}\n\n确认后会再次调用模型并写入文档。`;
                        if(!confirm(confirmMsg)) {
                            showToast('已取消重新翻译写入', 'info');
                            return;
                        }
                        showToast('正在应用重新翻译...', 'info', 6000);
                        const res = await fetch(`/api/documents/${encodeURIComponent(previewDocPath.value)}/translate`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ provider: translationProvider.value, model: selected.model || '', dry_run: false })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        showToast('重新翻译完成', 'success', 5000);
                        await previewDoc(previewDocPath.value);
                        await loadDocs();
                    } catch(e) {
                        showToast(`重新翻译失败: ${e.message}`, 'error', 8000);
                    } finally {
                        isRetranslating.value = false;
                    }
                };

                const loadLlmConfig = async () => {
                    loadingLlmConfig.value = true;
                    try {
                        const res = await fetch('/api/llm/config');
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        llmProviders.value = normalizeLlmProviders(data.providers);
                        llmFlows.value = normalizeLlmFlows(data.flows);
                        llmSecretSetup.value = data.secret_setup || null;
                        llmMode.value = data.mode || 'hybrid';
                        llmModeOptions.value = data.mode_options || llmModeOptions.value || [];
                        llmBackups.value = data.backups || llmBackups.value || [];
                    } catch(e) {
                        showToast(`加载模型配置失败: ${e.message}`, 'error', 7000);
                    } finally {
                        loadingLlmConfig.value = false;
                    }
                };

                const saveLlmConfig = async () => {
                    savingLlmConfig.value = true;
                    try {
                        const payload = {
                            providers: llmProviders.value.map(p => ({
                                name: p.name,
                                type: p.type,
                                label: p.label,
                                model: p.model,
                                base_url: p.base_url,
                                api_key_env: p.api_key_env,
                                timeout_sec: p.timeout_sec,
                                options: p.options || {}
                            })),
                            flows: llmFlows.value.map(f => ({
                                name: f.name,
                                label: f.label,
                                providers: f.providers || [],
                                allow_fallback: !!f.allow_fallback,
                                allow_online: !!f.allow_online,
                                fallback_notice: f.fallback_notice,
                                chunk_chars: f.chunk_chars,
                                intent: f.intent,
                                notes: f.notes,
                                options: f.options || {}
                            }))
                        };
                        const res = await fetch('/api/llm/config', {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        llmProviders.value = normalizeLlmProviders(data.providers);
                        llmFlows.value = normalizeLlmFlows(data.flows);
                        llmSecretSetup.value = data.secret_setup || llmSecretSetup.value;
                        llmMode.value = data.mode || llmMode.value;
                        llmModeOptions.value = data.mode_options || llmModeOptions.value;
                        llmBackups.value = data.backups || [];
                        await loadTranslationModels();
                        showToast(`模型配置已保存${data.backup ? '，已自动备份' : ''}`, 'success', 5000);
                    } catch(e) {
                        showToast(`保存模型配置失败: ${e.message}`, 'error', 8000);
                    } finally {
                        savingLlmConfig.value = false;
                    }
                };

                const applyLlmConfigPayload = async (data) => {
                    llmProviders.value = normalizeLlmProviders(data.providers);
                    llmFlows.value = normalizeLlmFlows(data.flows);
                    llmSecretSetup.value = data.secret_setup || llmSecretSetup.value;
                    llmMode.value = data.mode || llmMode.value;
                    llmModeOptions.value = data.mode_options || llmModeOptions.value;
                    llmBackups.value = data.backups || [];
                    await loadTranslationModels();
                };

                const setLlmMode = async (mode) => {
                    if(!mode || settingLlmMode.value) return;
                    settingLlmMode.value = mode;
                    try {
                        const res = await fetch('/api/llm/mode', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ mode })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        await applyLlmConfigPayload(data);
                        showToast(`已切换部署模式：${llmModeLabel.value}${data.backup ? '，已自动备份' : ''}`, 'success', 5000);
                    } catch(e) {
                        showToast(`切换部署模式失败: ${e.message}`, 'error', 8000);
                    } finally {
                        settingLlmMode.value = '';
                    }
                };

                const loadLlmBackups = async () => {
                    try {
                        const res = await fetch('/api/llm/config/backups');
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        llmBackups.value = data.backups || [];
                    } catch(e) {
                        showToast(`加载配置备份失败: ${e.message}`, 'error', 7000);
                    }
                };

                const loadLlmAudit = async () => {
                    loadingLlmAudit.value = true;
                    try {
                        const params = new URLSearchParams();
                        Object.entries(llmAuditFilters).forEach(([key, value]) => {
                            if(value) params.set(key, value === true ? 'true' : value);
                        });
                        const url = `/api/llm/audit${params.toString() ? `?${params}` : ''}`;
                        const res = await fetch(url);
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        llmAudit.value = data;
                    } catch(e) {
                        showToast(`加载 LLM 审计失败: ${e.message}`, 'error', 7000);
                    } finally {
                        loadingLlmAudit.value = false;
                    }
                };

                const resetLlmAuditFilters = async () => {
                    Object.assign(llmAuditFilters, { flow: '', provider: '', model: '', status: '', missing: false, fallback: false, retranslated: false });
                    await loadLlmAudit();
                };

                const llmAuditExportUrl = (format) => {
                    const params = new URLSearchParams();
                    Object.entries(llmAuditFilters).forEach(([key, value]) => {
                        if(value) params.set(key, value === true ? 'true' : value);
                    });
                    params.set('format', format);
                    return `/api/llm/audit?${params.toString()}`;
                };

                const exportLlmAudit = (format) => {
                    window.open(llmAuditExportUrl(format), '_blank');
                };

                const loadTranslationBackfillAudit = async () => {
                    loadingTranslationBackfill.value = true;
                    try {
                        const res = await fetch('/api/translation/backfill?limit=8');
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        translationBackfillAudit.value = data;
                    } catch(e) {
                        showToast(`加载补译审计失败: ${e.message}`, 'error', 7000);
                    } finally {
                        loadingTranslationBackfill.value = false;
                    }
                };

                const previewTranslationBackfillDryRun = async () => {
                    loadingTranslationBackfill.value = true;
                    try {
                        const res = await fetch('/api/translation/backfill', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ limit: 8, dry_run: true })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        translationBackfillDryRun.value = data;
                        translationBackfillAudit.value = data.audit || translationBackfillAudit.value;
                        showToast(`补译 dry-run：计划 ${data.planned || 0} 篇，已写入 ${data.applied || 0} 篇`, 'info', 5000);
                    } catch(e) {
                        showToast(`补译 dry-run 失败: ${e.message}`, 'error', 7000);
                    } finally {
                        loadingTranslationBackfill.value = false;
                    }
                };

                const restoreLlmBackup = async (name) => {
                    if(!name || !confirm(`确认恢复配置备份 ${name}？当前配置会先自动备份。`)) return;
                    restoringLlmBackup.value = name;
                    try {
                        const res = await fetch(`/api/llm/config/backups/${encodeURIComponent(name)}/restore`, { method: 'POST' });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        llmProviders.value = normalizeLlmProviders(data.providers);
                        llmFlows.value = normalizeLlmFlows(data.flows);
                        llmSecretSetup.value = data.secret_setup || llmSecretSetup.value;
                        llmMode.value = data.mode || llmMode.value;
                        llmModeOptions.value = data.mode_options || llmModeOptions.value;
                        llmBackups.value = data.backups || [];
                        await loadTranslationModels();
                        showToast(`已恢复配置：${data.restored_from || name}`, 'success', 6000);
                    } catch(e) {
                        showToast(`恢复配置失败: ${e.message}`, 'error', 8000);
                    } finally {
                        restoringLlmBackup.value = '';
                    }
                };

                const testLlmProvider = async (provider) => {
                    if(!provider?.name) return;
                    provider.testing = true;
                    provider.test_result = null;
                    try {
                        const res = await fetch(`/api/llm/providers/${encodeURIComponent(provider.name)}/test`, { method: 'POST' });
                        const data = await res.json();
                        provider.test_result = data;
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        showToast(`${provider.name} 测试通过`, 'success', 4000);
                    } catch(e) {
                        provider.test_result = provider.test_result || { ok: false, error: e.message };
                        showToast(`${provider.name} 测试失败: ${e.message}`, 'error', 7000);
                    } finally {
                        provider.testing = false;
                    }
                };

                // --- Document Management ---
                const docs = ref([]);
                const loadingDocs = ref(false);
                const docSearchText = ref('');
                const selectedDocFolder = ref('');
                const docsPage = ref(1);
                const docsPageSize = ref(80);
                const isMaintaining = ref(false);
                const maintenanceReport = ref(null);
                const repairingQuality = ref(false);
                const candidates = ref([]);
                const candidateSummary = ref(null);
                const candidateTierFilter = ref('');
                const candidateTypeFilter = ref('');
                const candidateIncludeSkipped = ref(false);
                const loadingCandidates = ref(false);
                const importingCandidateId = ref('');
                const translatingCandidateId = ref('');
                const batchTranslatingPreview = ref(false);
                const batchSkippingCandidates = ref(false);
                const batchImportingA = ref(false);
                const batchImportLimit = ref(20);
                const batchImportRetries = ref(2);
                const batchImportJob = ref(null);
                let batchImportPollTimer = null;
                const candidateEditOpen = ref(false);
                const savingCandidateEdit = ref(false);
                const candidateEditItem = ref(null);
                const candidateEditOriginalTitle = ref('');
                const candidateEditForm = reactive({ id: '', title: '', category: '技术', tagsText: '', notes: '' });
                const lastImportResult = ref(null);
                const tierMeta = {
                    A: { title: 'A · 优先导入', badgeClass: 'badge-success', borderClass: 'border-success/40', order: 0 },
                    B: { title: 'B · 值得审核', badgeClass: 'badge-info', borderClass: 'border-info/40', order: 1 },
                    C: { title: 'C · 低优先级', badgeClass: 'badge-warning', borderClass: 'border-warning/40', order: 2 },
                    D: { title: 'D · 建议跳过', badgeClass: 'badge-ghost', borderClass: 'border-base-300', order: 3 },
                    '?': { title: '未评级', badgeClass: 'badge-ghost', borderClass: 'border-base-300', order: 4 },
                };
                const candidateTime = (item) => {
                    const raw = item.publish_time || item.modified || '';
                    const t = Date.parse(raw);
                    return Number.isFinite(t) ? t : 0;
                };
                const candidateGroups = computed(() => {
                    const map = {};
                    for(const item of candidates.value || []) {
                        const tier = item.quality_tier || '?';
                        if(!map[tier]) map[tier] = [];
                        map[tier].push(item);
                    }
                    return Object.entries(map)
                        .map(([tier, items]) => {
                            items.sort((a,b) => candidateTime(b) - candidateTime(a));
                            const meta = tierMeta[tier] || tierMeta['?'];
                            return { tier, items, ...meta };
                        })
                        .sort((a,b) => (a.order ?? 9) - (b.order ?? 9));
                });
                const tierBadgeClass = (tier) => (tierMeta[tier] || tierMeta['?']).badgeClass;
                const tierLabel = (tier) => (tierMeta[tier] || tierMeta['?']).title.replace(/^. · /, '');
                const tierCardClass = (tier) => {
                    if(tier === 'A') return 'bg-success/5 border-success/30';
                    if(tier === 'B') return 'bg-info/5 border-info/30';
                    if(tier === 'C') return 'bg-warning/5 border-warning/30';
                    return 'bg-base-200 border-base-300';
                };
                const formatCandidateDate = (item) => {
                    const raw = item.publish_time || item.modified || '';
                    const d = new Date(raw);
                    if(Number.isNaN(d.getTime())) return raw || '无日期';
                    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
                };
                const wechatSources = ref([]);
                const loadingWechatSources = ref(false);
                const savingWechatSource = ref(false);
                const discoveringWechat = ref(false);
                const wechatDiscoveryResult = ref(null);
                const newWechatSource = ref({ name: '', sample_url: '', tags: '', priority: 'normal' });
                const discoverForm = ref({ source: '', since: '', limit: 10, url: '' });
                const rssFeeds = ref([]);
                const loadingRssFeeds = ref(false);
                const syncingRss = ref(false);
                const rssSyncResult = ref(null);
                const rssNewForm = ref({ url: '', name: '', category: 'articles', priority: 'medium', tags: '', notes: '', language: 'en', interval_minutes: 360, max_articles: 10, enabled: true });
                const dragOver = ref(false);
                const stats = ref({});
                const showUrlInput = ref(false);
                const fetchUrlInput = ref('');
                const isFetchingUrl = ref(false);
                const fetchUrlError = ref('');
                const fetchUrlSuccess = ref(false);
                const failedImports = ref([]);
                const qualityOnly = ref(false);
                const qualityIssueLabels = {
                    summary_placeholder: '摘要缺失',
                    keypoints_placeholder: '关键点缺失',
                    entities_placeholder: '实体缺失',
                    quality_scan_failed: '扫描失败',
                };
                const issueLabel = (issue) => qualityIssueLabels[issue] || issue;
                const issueText = (issues) => (issues || []).map(issueLabel).join(' / ');

                const loadDocs = async () => {
                    loadingDocs.value = true;
                    try {
                        const [docRes, statRes] = await Promise.all([
                            fetch('/api/documents'), fetch('/api/stats')
                        ]);
                        const rawDocs = (await docRes.json()).documents || [];
                        // Normalize API fields to UI fields
                        docs.value = rawDocs.map(d => {
                            const relpath = d.path || d.relpath;
                            const parts = relpath.split('/');
                            const folder = parts.length > 1 ? parts.slice(0, -1).join('/') : 'root';
                            return {
                                relpath,
                                name: d.name,
                                type: d.category || d.type || folder || 'root',
                                folder,
                                generated: !!d.generated,
                                quality: d.quality || { ok: true, issues: [], score: 100 },
                                size: d.size_bytes || d.size || 0,
                                mtime: new Date(d.modified || d.mtime || Date.now()).getTime() / 1000
                            };
                        });
                        stats.value = await statRes.json();
                    } catch(e) {
                        showToast("获取文档列表失败", "error");
                    } finally {
                        loadingDocs.value = false;
                    }
                };

                const filteredDocs = computed(() => {
                    const q = docSearchText.value.trim().toLowerCase();
                    let list = docs.value.slice().sort((a, b) => b.mtime - a.mtime);
                    if(qualityOnly.value) list = list.filter(d => d.quality && !d.quality.ok);
                    if(!q) return list;
                    return list.filter(d => d.name.toLowerCase().includes(q) || d.relpath.toLowerCase().includes(q) || (d.type || '').toLowerCase().includes(q));
                });

                watch([docSearchText, selectedDocFolder, qualityOnly], () => { docsPage.value = 1; });

                const folderRows = computed(() => {
                    const dirs = new Map();
                    const addDir = (path) => {
                        if(!dirs.has(path)) dirs.set(path, { path, label: path ? path.split('/').pop() : '全部文档', depth: path ? path.split('/').length - 1 : 0, count: 0 });
                    };
                    addDir('');
                    docs.value.forEach(doc => {
                        const parts = doc.relpath.split('/');
                        if(parts.length > 1) {
                            for(let i = 1; i < parts.length; i++) addDir(parts.slice(0, i).join('/'));
                        }
                    });
                    dirs.forEach(folder => {
                        folder.count = folder.path === ''
                            ? docs.value.length
                            : docs.value.filter(d => d.relpath.startsWith(folder.path + '/')).length;
                    });
                    return Array.from(dirs.values()).sort((a, b) => {
                        if(a.path === '') return -1;
                        if(b.path === '') return 1;
                        return a.path.localeCompare(b.path, 'zh-Hans-CN');
                    });
                });

                const visibleDocs = computed(() => {
                    const folder = selectedDocFolder.value;
                    const list = !folder ? filteredDocs.value : filteredDocs.value.filter(d => d.relpath.startsWith(folder + '/'));
                    return list;
                });
                const docsTotalPages = computed(() => Math.max(1, Math.ceil(visibleDocs.value.length / docsPageSize.value)));
                const pagedVisibleDocs = computed(() => {
                    const start = (docsPage.value - 1) * docsPageSize.value;
                    return visibleDocs.value.slice(start, start + docsPageSize.value);
                });

                const qualityBadCount = computed(() => docs.value.filter(d => d.quality && !d.quality.ok).length);
                const qualityIssueSummary = computed(() => {
                    const counts = {};
                    docs.value.forEach(d => (d.quality?.issues || []).forEach(i => { counts[i] = (counts[i] || 0) + 1; }));
                    return Object.entries(counts)
                        .sort((a, b) => b[1] - a[1])
                        .map(([issue, count]) => `${issueLabel(issue)} ${count}`)
                        .join('，');
                });

                const repairDocQuality = async (path) => {
                    repairingQuality.value = true;
                    try {
                        const previewRes = await fetch(`/api/documents/${encodeURIComponent(path)}/repair-quality`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ dry_run: true })
                        });
                        const preview = await previewRes.json();
                        if(!previewRes.ok) throw new Error(preview.error || `HTTP ${previewRes.status}`);
                        if(!preview.changed) {
                            showToast('文档无需修复', 'info');
                            return;
                        }
                        const planned = issueText(preview.before?.issues || []);
                        const summaryPreview = (preview.sections?.summary || '').slice(0, 160);
                        if(!confirm(`确认应用质量修复？\n文档：${path}\n问题：${planned || '未知'}\n摘要预览：${summaryPreview}`)) return;
                        const res = await fetch(`/api/documents/${encodeURIComponent(path)}/repair-quality`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ dry_run: false })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        showToast(data.changed ? '文档质量已修复' : '文档无需修复', data.changed ? 'success' : 'info');
                        await loadDocs();
                        if(previewDocPath.value === path) await previewDoc(path);
                    } catch(e) {
                        showToast(`质量修复失败: ${e.message}`, 'error');
                    } finally { repairingQuality.value = false; }
                };

                const repairAllQuality = async () => {
                    if(!qualityBadCount.value) return;
                    repairingQuality.value = true;
                    try {
                        const previewRes = await fetch('/api/quality/repair', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ limit: 50, dry_run: true })
                        });
                        const preview = await previewRes.json();
                        if(!previewRes.ok) throw new Error(preview.error || `HTTP ${previewRes.status}`);
                        const sample = (preview.results || []).slice(0, 5).map(x => `${x.path}: ${issueText(x.before?.issues || [])}`).join('\n');
                        if(!preview.planned) {
                            showToast('没有需要修复的文档', 'info');
                            return;
                        }
                        if(!confirm(`确认批量应用质量修复？\n计划修复：${preview.planned} 篇\n\n${sample}`)) return;
                        const res = await fetch('/api/quality/repair', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ limit: 50, dry_run: false })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        showToast(`已修复 ${data.repaired || 0} 个文档`, 'success');
                        await loadDocs();
                    } catch(e) {
                        showToast(`批量修复失败: ${e.message}`, 'error');
                    } finally { repairingQuality.value = false; }
                };

                const loadRssFeeds = async () => {
                    loadingRssFeeds.value = true;
                    try {
                        const res = await fetch('/api/rss/feeds');
                        const data = await res.json();
                        rssFeeds.value = data.feeds || [];
                    } catch(e) { showToast('加载RSS订阅失败', 'error'); }
                    finally { loadingRssFeeds.value = false; }
                };

                const saveRssFeed = async () => {
                    const payload = { ...rssNewForm.value };
                    if(typeof payload.tags === 'string') payload.tags = payload.tags.split(',').map(t=>t.trim()).filter(Boolean);
                    try {
                        const res = await fetch('/api/rss/feeds', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        if(!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
                        showToast('RSS订阅已保存', 'success');
                        rssNewForm.value = { url: '', name: '', category: 'articles', priority: 'medium', tags: '', notes: '', language: 'en', interval_minutes: 360, max_articles: 10, enabled: true };
                        await loadRssFeeds();
                    } catch(e) { showToast(`保存失败: ${e.message}`, 'error'); }
                };

                const deleteRssFeed = async (key) => {
                    if(!confirm(`确认删除订阅源 "${key}"？`)) return;
                    try {
                        const res = await fetch(`/api/rss/feeds/${encodeURIComponent(key)}`, { method: 'DELETE' });
                        if(!res.ok) throw new Error(`HTTP ${res.status}`);
                        showToast('已删除', 'success');
                        await loadRssFeeds();
                    } catch(e) { showToast(`删除失败: ${e.message}`, 'error'); }
                };

                const toggleRssFeed = async (key) => {
                    try {
                        const feed = rssFeeds.value.find(f => f.key === key);
                        if(!feed) return;
                        const res = await fetch(`/api/rss/feeds/${encodeURIComponent(key)}`, {
                            method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ enabled: !feed.enabled })
                        });
                        if(!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
                        feed.enabled = !feed.enabled;
                        showToast(`已${feed.enabled ? '启用' : '禁用'} ${feed.name || key}`, 'success');
                    } catch(e) { showToast(`操作失败: ${e.message}`, 'error'); }
                };

                const syncRss = async (feedKey=null) => {
                    if(typeof feedKey !== 'string') feedKey = null;
                    syncingRss.value = true;
                    rssSyncResult.value = null;
                    try {
                        const payload = { limit: 5 };
                        if(feedKey) payload.feed_key = feedKey;
                        const res = await fetch('/api/rss/sync', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        const data = await res.json();
                        rssSyncResult.value = data;
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        showToast(`RSS同步完成: ${data.new} 新, ${data.skipped} 跳过, ${data.errors} 错误`, data.new > 0 ? 'success' : 'info', 6000);
                        await loadRssFeeds();
                        await loadCandidates();
                    } catch(e) { showToast(`RSS同步失败: ${e.message}`, 'error', 8000); }
                    finally { syncingRss.value = false; }
                };

                const loadWechatSources = async () => {
                    loadingWechatSources.value = true;
                    try {
                        const res = await fetch('/api/wechat/sources');
                        const data = await res.json();
                        wechatSources.value = data.sources || [];
                    } catch(e) { showToast('加载公众号订阅失败', 'error'); }
                    finally { loadingWechatSources.value = false; }
                };

                const saveWechatSource = async () => {
                    savingWechatSource.value = true;
                    try {
                        const res = await fetch('/api/wechat/sources', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(newWechatSource.value)
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        showToast('公众号订阅已保存', 'success');
                        newWechatSource.value = { name: '', sample_url: '', tags: '', priority: 'normal' };
                        await loadWechatSources();
                    } catch(e) { showToast(`保存失败: ${e.message}`, 'error'); }
                    finally { savingWechatSource.value = false; }
                };

                const discoverWechat = async (sourceName=null) => {
                    if(sourceName && typeof sourceName !== 'string') sourceName = null;
                    discoveringWechat.value = true;
                    wechatDiscoveryResult.value = null;
                    try {
                        const payload = { ...discoverForm.value };
                        if(sourceName) payload.source = sourceName;
                        const res = await fetch('/api/wechat/discover', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        const data = await res.json();
                        wechatDiscoveryResult.value = data;
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        showToast('搜索发现完成，候选已进入候选池', 'success', 6000);
                        await loadWechatSources();
                        await loadCandidates();
                    } catch(e) { showToast(`发现失败: ${e.message}`, 'error', 8000); }
                    finally { discoveringWechat.value = false; }
                };

                const loadCandidates = async () => {
                    loadingCandidates.value = true;
                    try {
                        const params = new URLSearchParams({ sort: 'quality' });
                        if(candidateTierFilter.value) params.set('tier', candidateTierFilter.value);
                        if(candidateTypeFilter.value) params.set('type', candidateTypeFilter.value);
                        if(candidateIncludeSkipped.value) params.set('include_skipped', 'true');
                        const res = await fetch(`/api/candidates?${params.toString()}`);
                        const data = await res.json();
                        candidates.value = data.candidates || [];
                        candidateSummary.value = data.summary || null;
                    } catch(e) {
                        showToast('加载候选池失败', 'error');
                    } finally {
                        loadingCandidates.value = false;
                    }
                };

                const previewCandidate = async (id) => {
                    previewLoading.value = true;
                    previewOpen.value = true;
                    isEditingDoc.value = false;
                    previewRelated.value = [];
                    previewAssociation.value = null;
                    previewMeta.value = {};
                    previewAuditItem.value = null;
                    try {
                        const res = await fetch(`/api/candidates/${encodeURIComponent(id)}`);
                        const data = await res.json();
                        previewMode.value = 'candidate';
                        candidateWorkbenchItem.value = data;
                        candidateEditItem.value = data;
                        candidateEditOriginalTitle.value = data.title || '';
                        candidateEditForm.id = data.id;
                        candidateEditForm.title = data.review_title || data.translated_title || data.title || '';
                        candidateEditForm.category = data.review_category || '技术';
                        candidateEditForm.tagsText = (data.review_tags?.length ? data.review_tags : (data.translated_topics || data.translation?.topics || [])).join(', ');
                        candidateEditForm.notes = data.edited_metadata?.notes || '';
                        previewDocName.value = data.translated_title || data.title || '候选文章';
                        const trans = data.translation || {};
                        const zhTitle = data.translated_title || trans.translated_title || '';
                        const zhSummary = data.translated_summary || trans.translated_summary || '';
                        const zhContent = data.translated_content || trans.translated_content || '';
                        const topics = data.translated_topics || trans.topics || [];
                        const keyTerms = data.key_terms || trans.key_terms || [];
                        const quality = data.quality || {};
                        const parts = [];
                        if(zhTitle || zhSummary || zhContent) {
                            parts.push(`# ${zhTitle || data.title || '候选文章'}`);
                            parts.push(`> 质量等级：${data.quality_tier || '?'} · ${data.quality_score ?? 0}分 · ${quality.recommendation || ''}`);
                            if(data.title && zhTitle && data.title !== zhTitle) parts.push(`> 原文标题：${data.title}`);
                            if(data.source_name) parts.push(`> 来源：${data.source_name}`);
                            if(data.publish_time) parts.push(`> 发布时间：${data.publish_time}`);
                            if(data.url) parts.push(`> 链接：${data.url}`);
                            if(topics.length) parts.push(`> 中文主题：${topics.join(' / ')}`);
                            if(keyTerms.length) parts.push(`> 关键术语：${keyTerms.join(' / ')}`);
                            parts.push('');
                            parts.push('## 中文预览');
                            parts.push(zhContent || zhSummary || '（暂无中文正文，仅有标题翻译）');
                            if(quality.reasons?.length || quality.penalties?.length) {
                                parts.push('');
                                parts.push('## 质量判断理由');
                                for(const r of (quality.reasons || [])) parts.push(`- + ${r}`);
                                for(const p of (quality.penalties || [])) parts.push(`- - ${p}`);
                            }
                            parts.push('');
                            parts.push('---');
                            parts.push('');
                            parts.push('## 英文原文');
                            parts.push(data.content || '');
                            previewContent.value = parts.join('\n');
                        } else {
                            previewContent.value = data.content || '';
                        }
                        previewDocPath.value = '';
                    } catch(e) {
                        showToast('加载候选预览失败', 'error');
                    } finally {
                        previewLoading.value = false;
                    }
                };

                const translateCandidate = async (id, options={}) => {
                    if(!id) return;
                    translatingCandidateId.value = id;
                    showToast('正在生成候选池中文预览...', 'info', 5000);
                    try {
                        const res = await fetch(`/api/candidates/${encodeURIComponent(id)}/translate`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ force: false, preview: true })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || '预翻译失败');
                        showToast('中文预览已生成，质量评分会优先使用中文内容', 'success', 5000);
                        await loadCandidates();
                        if(options.refreshPreview) await previewCandidate(id);
                    } catch(e) {
                        showToast(`预翻译失败: ${e.message}`, 'error', 6000);
                    } finally {
                        translatingCandidateId.value = '';
                    }
                };

                const batchTranslatePreview = async () => {
                    if(!confirm('批量补齐当前筛选条件下最多20篇候选的中文预览？')) return;
                    batchTranslatingPreview.value = true;
                    showToast('正在批量生成中文预览...', 'info', 6000);
                    try {
                        const res = await fetch('/api/candidates/translate-preview', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ limit: 20, tier: candidateTierFilter.value, type: candidateTypeFilter.value, force: false })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || '批量预翻译失败');
                        showToast(`批量预翻译完成：${data.translated || 0} 篇，失败 ${data.failed?.length || 0} 篇`, 'success', 7000);
                        await loadCandidates();
                    } catch(e) {
                        showToast(`批量预翻译失败: ${e.message}`, 'error', 8000);
                    } finally {
                        batchTranslatingPreview.value = false;
                    }
                };

                const editCandidate = (item) => {
                    candidateEditItem.value = item;
                    candidateEditOriginalTitle.value = item.title || '';
                    candidateEditForm.id = item.id;
                    candidateEditForm.title = item.review_title || item.translated_title || item.title || '';
                    candidateEditForm.category = item.review_category || '技术';
                    candidateEditForm.tagsText = (item.review_tags?.length ? item.review_tags : (item.translated_topics || [])).join(', ');
                    candidateEditForm.notes = item.edited_metadata?.notes || '';
                    candidateEditOpen.value = true;
                };

                const closeCandidateEdit = () => {
                    candidateEditOpen.value = false;
                    savingCandidateEdit.value = false;
                    candidateEditItem.value = null;
                };

                const saveCandidateEdit = async () => {
                    if(!candidateEditForm.id) return;
                    savingCandidateEdit.value = true;
                    try {
                        const res = await fetch(`/api/candidates/${encodeURIComponent(candidateEditForm.id)}/metadata`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                title: candidateEditForm.title,
                                category: candidateEditForm.category,
                                tags: candidateEditForm.tagsText,
                                notes: candidateEditForm.notes,
                            })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || '保存失败');
                        showToast('审核信息已保存，导入时会优先使用', 'success', 5000);
                        closeCandidateEdit();
                        await loadCandidates();
                    } catch(e) {
                        showToast(`保存审核信息失败: ${e.message}`, 'error', 7000);
                    } finally {
                        savingCandidateEdit.value = false;
                    }
                };

                const saveCandidateReviewInline = async () => {
                    if(!candidateEditForm.id) return;
                    savingCandidateEdit.value = true;
                    try {
                        const res = await fetch(`/api/candidates/${encodeURIComponent(candidateEditForm.id)}/metadata`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                title: candidateEditForm.title,
                                category: candidateEditForm.category,
                                tags: candidateEditForm.tagsText,
                                notes: candidateEditForm.notes,
                            })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || '保存失败');
                        showToast('审核信息已保存，导入时会优先使用', 'success', 5000);
                        await loadCandidates();
                        await previewCandidate(candidateEditForm.id);
                    } catch(e) {
                        showToast(`保存审核信息失败: ${e.message}`, 'error', 7000);
                    } finally {
                        savingCandidateEdit.value = false;
                    }
                };

                const loadBatchImportStatus = async () => {
                    const res = await fetch('/api/candidates/batch-import/status');
                    const job = await res.json();
                    batchImportJob.value = job;
                    batchImportingA.value = !!job.running;
                    return job;
                };

                const startBatchImportPolling = () => {
                    if(batchImportPollTimer) clearInterval(batchImportPollTimer);
                    batchImportPollTimer = setInterval(async () => {
                        try {
                            const job = await loadBatchImportStatus();
                            if(!job.running) {
                                clearInterval(batchImportPollTimer);
                                batchImportPollTimer = null;
                                if(job.status === 'done') {
                                    const result = job.result || {};
                                    const maint = result.maintenance?.status ? `，维护状态：${result.maintenance.status}` : '';
                                    showToast(`队列导入完成: ${result.imported || 0}/${result.total || 0} 成功，失败 ${result.errors || 0}${maint}`, 'success', 10000);
                                    await loadCandidates();
                                } else if(job.status === 'error') {
                                    showToast(`队列导入失败: ${job.error || '未知错误'}`, 'error', 10000);
                                }
                            }
                        } catch(e) {}
                    }, 5000);
                };

                const batchImportA = async () => {
                    const limit = Math.max(1, Math.min(Number(batchImportLimit.value) || 20, 200));
                    const maxRetries = Math.max(0, Math.min(Number(batchImportRetries.value) || 0, 5));
                    if(!confirm(`确认启动 A 级候选队列导入？\n数量：${limit} 篇\n失败自动重试：${maxRetries} 次\n完成后统一跑轻量维护（不重建语义向量）。`)) return;
                    batchImportingA.value = true;
                    showToast('队列导入任务已提交，后台串行处理，可在进度卡片查看状态。', 'info', 10000);
                    try {
                        const res = await fetch('/api/candidates/batch-import', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ tier: 'A', limit, max_retries: maxRetries, retry_delay_sec: 10, run_maintenance: true, update_embeddings: false })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        batchImportJob.value = data.job || { status: 'started', running: true };
                        startBatchImportPolling();
                    } catch(e) {
                        batchImportingA.value = false;
                        showToast(`队列导入启动失败: ${e.message}`, 'error', 9000);
                    }
                };

                const batchSkipLowQuality = async () => {
                    const tier = candidateTierFilter.value || 'C,D';
                    if(!confirm(`将批量跳过当前来源过滤下的 ${tier || 'C,D'} 候选。此操作可在 candidate_state.json 中追溯，但会从默认候选池隐藏。继续？`)) return;
                    const code = prompt('二次确认：请输入 SKIP_LOW_QUALITY');
                    if(code !== 'SKIP_LOW_QUALITY') {
                        showToast('确认码不匹配，已取消', 'info');
                        return;
                    }
                    batchSkippingCandidates.value = true;
                    try {
                        const res = await fetch('/api/candidates/batch-skip', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ tier, type: candidateTypeFilter.value, confirm: code, reason: 'WebUI批量跳过低质量候选' })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || '批量跳过失败');
                        showToast(`已批量跳过 ${data.skipped || 0} 篇候选`, 'success', 7000);
                        await loadCandidates();
                    } catch(e) {
                        showToast(`批量跳过失败: ${e.message}`, 'error', 8000);
                    } finally {
                        batchSkippingCandidates.value = false;
                    }
                };

                const importCandidate = async (id) => {
                    if(!confirm('确认导入这篇候选文章？A/B候选会复用/生成中文译文，并自动维护知识库。')) return;
                    importingCandidateId.value = id;
                    showToast('正在导入候选文章，可能会生成全文译文并维护知识库...', 'info', 6000);
                    try {
                        const res = await fetch(`/api/candidates/${encodeURIComponent(id)}/import`, {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ process: true, run_maintenance: true, translate: true })
                        });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        const wikiPath = data.wiki_path || data.processed?.wiki_path || '';
                        const searchQuery = (data.validation?.checks?.edited_title_applied && data.validation?.path) ? data.validation.path : (wikiPath ? wikiPath.split('/').pop().replace(/_[a-f0-9]{8}\.md$/, '').replace(/\.md$/, '') : '');
                        lastImportResult.value = { ...data, wiki_path: wikiPath, search_query: searchQuery };
                        if(previewMode.value === 'candidate') closePreview();
                        showToast('候选文章已导入知识库，可继续查看文档/搜索验证', 'success', 8000);
                        await loadCandidates();
                        await loadDocs();
                        stats.value = await fetch('/api/stats').then(r=>r.json());
                    } catch(e) {
                        showToast(`导入失败: ${e.message}`, 'error', 8000);
                    } finally {
                        importingCandidateId.value = '';
                    }
                };

                const skipCandidate = async (id) => {
                    const reason = prompt('跳过原因（可选）', '不导入');
                    if(reason === null) return;
                    try {
                        const res = await fetch(`/api/candidates/${encodeURIComponent(id)}/skip`, {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ reason })
                        });
                        if(!res.ok) throw new Error(`HTTP ${res.status}`);
                        showToast('已跳过候选', 'success');
                        if(previewMode.value === 'candidate') closePreview();
                        await loadCandidates();
                    } catch(e) {
                        showToast(`跳过失败: ${e.message}`, 'error');
                    }
                };

                const restoreCandidate = async (id) => {
                    if(!confirm('恢复这个已跳过候选？恢复后会重新出现在默认候选池。')) return;
                    try {
                        const res = await fetch(`/api/candidates/${encodeURIComponent(id)}/restore`, { method: 'POST' });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        showToast(data.restored ? '已恢复候选' : (data.message || '候选无需恢复'), data.restored ? 'success' : 'info');
                        await loadCandidates();
                    } catch(e) {
                        showToast(`恢复失败: ${e.message}`, 'error');
                    }
                };

                const openLastImportedDoc = async () => {
                    if(!lastImportResult.value?.wiki_path) return;
                    switchTab('docs');
                    await nextTick();
                    previewDoc(lastImportResult.value.wiki_path);
                };

                const searchLastImported = async () => {
                    const q = lastImportResult.value?.search_query || lastImportResult.value?.wiki_path || '';
                    if(!q) return;
                    docSearchText.value = q;
                    switchTab('docs');
                    await loadDocs();
                    showToast(`已按导入内容过滤文档：${q}`, 'info', 5000);
                };

                const runMaintenance = async () => {
                    if(isMaintaining.value) return;
                    isMaintaining.value = true;
                    maintenanceReport.value = null;
                    showToast('正在维护知识库：按当前 LLM 模式检查 / 重建链接 / lint / 索引...', 'info', 5000);
                    try {
                        const res = await fetch('/api/maintenance', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ update_embeddings: false })
                        });
                        const report = await res.json();
                        maintenanceReport.value = report;
                        const lint = report.summary?.lint || {};
                        const model = report.summary?.model || {};
                        const assoc = report.summary?.associations || {};
                        const msg = `维护完成：模型 ${model.model || 'local'} ${model.status || ''}，坏链 ${lint.broken_links ?? '?'}，孤立页 ${lint.orphans ?? '?'}，重复组 ${assoc.duplicate_groups ?? '?'}，真实文档 ${report.summary?.real_wiki_docs ?? '?'}`;
                        showToast(msg, report.status === 'ok' ? 'success' : 'warning', 6000);
                        await loadDocs();
                        if(activeTab.value === 'graph') await nextTick(() => initGraph());
                    } catch(e) {
                        showToast(`维护失败: ${e.message}`, 'error', 6000);
                    } finally {
                        isMaintaining.value = false;
                    }
                };

                const deleteDoc = async (path) => {
                    if(!confirm(`确定删除 ${path} 及其处理产生的Wiki文件吗？`)) return;
                    try {
                        const res = await fetch(`/api/documents/${encodeURIComponent(path)}`, { method: 'DELETE' });
                        if(res.ok) {
                            showToast("删除成功", "success");
                            docs.value = docs.value.filter(d => d.relpath !== path);
                            stats.value.wiki_documents = Math.max(0, (stats.value.wiki_documents || 1) - 1);
                        }
                    } catch(e) { showToast("删除失败", "error"); }
                };

                const fetchUrl = async () => {
                    const url = fetchUrlInput.value.trim();
                    if(!url) return;
                    // Validate URL client-side first
                    try {
                        const u = new URL(url);
                        if(!['http:', 'https:'].includes(u.protocol)) throw new Error('仅支持 http/https');
                    } catch(e) {
                        fetchUrlError.value = `URL 不合法: ${e.message}`;
                        showToast(`URL 不合法: ${e.message}`, 'error');
                        return;
                    }
                    isFetchingUrl.value = true;
                    fetchUrlError.value = '';
                    fetchUrlSuccess.value = false;
                    showToast(`正在抓取: ${url}`, 'info', 5000);
                    try {
                        const res = await fetch('/api/documents/url', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ url: url, auto_process: true })
                        });
                        const data = await res.json();
                        if(!res.ok) {
                            throw new Error(data.error || `HTTP ${res.status}`);
                        }
                        if(data.processed) {
                            fetchUrlSuccess.value = true;
                            showToast('✅ 抓取并导入成功！', 'success');
                            loadDocs();
                        } else {
                            if(data.recovery?.can_retry) {
                                failedImports.value.unshift({
                                    raw_path: data.recovery.raw_path || data.raw_path,
                                    error: data.message || data.recovery.error,
                                    recovery: data.recovery,
                                    retrying: false
                                });
                            }
                            showToast(`❌ 抓取成功但处理失败: ${data.message || '未知错误'}`, 'warning');
                        }
                    } catch(e) {
                        fetchUrlError.value = e.message;
                        showToast(`抓取失败: ${e.message}`, 'error');
                    } finally {
                        isFetchingUrl.value = false;
                    }
                };

                const handleFileUpload = async (e) => {
                    const files = e.target.files;
                    if(!files.length) return;
                    await uploadFiles(files);
                };
                const handleDrop = async (e) => {
                    dragOver.value = false;
                    const files = e.dataTransfer.files;
                    if(!files.length) return;
                    await uploadFiles(files);
                };
                const uploadFiles = async (files) => {
                    showToast(`正在上传 ${files.length} 个文件...`, "info");
                    const summaries = [];
                    for(let i=0; i<files.length; i++) {
                        const fd = new FormData();
                        fd.append('files', files[i]);
                        try {
                            const res = await fetch('/api/documents', { method: 'POST', body: fd });
                            const data = await res.json();
                            if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                            const processed = data.processed || [];
                            for(const item of processed) {
                                summaries.push(item);
                                if(item.processed) {
                                    const model = item.llm?.provider ? ` · ${item.llm.provider} / ${item.llm.model || '-'}` : '';
                                    showToast(`已处理 ${item.filename}${model}`, 'success', 7000);
                                } else {
                                    if(item.recovery?.can_retry) {
                                        failedImports.value.unshift({
                                            raw_path: item.recovery.raw_path || item.raw_path,
                                            filename: item.filename,
                                            error: item.error || item.message,
                                            recovery: item.recovery,
                                            retrying: false
                                        });
                                    }
                                    showToast(`上传成功但处理失败 ${item.filename}: ${item.error || item.message || '未知错误'}`, 'warning', 9000);
                                }
                            }
                        } catch(e) {
                            console.error("Upload error", e);
                            showToast(`上传失败 ${files[i].name}: ${e.message}`, 'error', 9000);
                        }
                    }
                    if(!summaries.length) showToast("上传请求已发送", "success");
                    loadDocs();
                };

                const retryFailedImport = async (item) => {
                    if(!item?.raw_path || item.retrying) return;
                    item.retrying = true;
                    try {
                        const res = await fetch('/api/documents/retry-import', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ raw_path: item.raw_path })
                        });
                        const data = await res.json();
                        if(!res.ok || !data.processed) throw new Error(data.error || data.message || `HTTP ${res.status}`);
                        failedImports.value = failedImports.value.filter(x => x !== item);
                        showToast(`重试处理成功: ${data.wiki_path || item.raw_path}`, 'success', 7000);
                        loadDocs();
                    } catch(e) {
                        item.error = e.message;
                        showToast(`重试处理失败: ${e.message}`, 'error', 9000);
                    } finally {
                        item.retrying = false;
                    }
                };

                const formatBytes = (bytes) => {
                    if(bytes === 0) return '0 B';
                    const k = 1024, sizes = ['B', 'KB', 'MB', 'GB'];
                    const i = Math.floor(Math.log(bytes) / Math.log(k));
                    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
                };
                const formatDate = (ts) => new Date(ts*1000).toLocaleDateString();


                const loadAssociations = async (rebuild=false) => {
                    loadingAssociations.value = true;
                    try {
                        const res = await fetch('/api/associations', { method: rebuild ? 'POST' : 'GET' });
                        const data = await res.json();
                        if(!res.ok) throw new Error(data.error || '加载关联报告失败');
                        associationReport.value = data;
                        if(rebuild) showToast('知识关联报告已重建', 'success');
                    } catch(e) {
                        showToast(`知识关联报告失败: ${e.message}`, 'error', 7000);
                    } finally {
                        loadingAssociations.value = false;
                    }
                };

                // --- Knowledge Graph (ECharts) ---
                let chartInstance = null;
                const initGraph = async () => {
                    const container = document.getElementById('graph-container');
                    if(!container) return;
                    
                    if(chartInstance) { chartInstance.dispose(); }
                    
                    chartInstance = echarts.init(container, theme.value === 'dark' ? 'dark' : null);
                    chartInstance.showLoading({ color: '#3b82f6', maskColor: theme.value==='dark'?'rgba(29,35,42,0.8)':'rgba(255,255,255,0.8)'});

                    try {
                        let apiUrl = '/api/graph?limit=50';
                        const q = graphSearchText.value.trim();
                        if (q) apiUrl += '&entity=' + encodeURIComponent(q) + '&mode=neighbors';
                        const res = await fetch(apiUrl);
                        const data = await res.json();
                        
                        if(!data.nodes || data.nodes.length === 0) {
                            chartInstance.hideLoading();
                            return;
                        }

                        const isDark = theme.value === 'dark';
                        const textColor = isDark ? '#a6adbb' : '#1f2937';
                        const lineColor = isDark ? '#4b5563' : '#d1d5db';

                        if (graphLayout.value === 'sankey') {
                            renderSankey(data, isDark);
                        } else if (graphLayout.value === 'tree') {
                            renderTree(data, isDark);
                        } else if (graphLayout.value === 'chord') {
                            renderChord(data, isDark, textColor);
                        } else {
                            renderForceOrCircular(data, isDark, textColor, lineColor);
                        }
                    } catch(e) {
                        console.error("Graph error:", e);
                        chartInstance.hideLoading();
                        showToast("加载图谱失败", "error");
                    }
                };

                const renderForceOrCircular = (data, isDark, textColor, lineColor) => {
                    const totalNodes = data.nodes.length;
                    const nodes = data.nodes.map(n => {
                        let size = n.type === 'document' ? 35 : 18;
                        if (n.freq) size += Math.min(n.freq * 3, 28);
                        return {
                            id: n.id,
                            name: n.name || n.id,
                            symbolSize: size,
                            draggable: true,
                            itemStyle: {
                                color: n.type === 'document' ? '#3b82f6' : '#10b981',
                                borderColor: isDark ? '#1d232a' : '#fff',
                                borderWidth: 2,
                                shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)'
                            },
                            label: {
                                show: graphLayout.value === 'circular' || totalNodes < 60,
                                position: graphLayout.value === 'circular' ? 'right' : 'bottom',
                                rotate: graphLayout.value === 'circular' ? 0 : 0,
                                formatter: '{b}',
                                color: textColor,
                                fontSize: 12,
                                backgroundColor: isDark ? 'rgba(0,0,0,0.5)' : 'rgba(255,255,255,0.7)',
                                padding: [2, 4], borderRadius: 4
                            },
                            type: n.type, categories: n.categories || [n.category || '其他'], path: n.path
                        };
                    });

                    const option = {
                        backgroundColor: 'transparent',
                        tooltip: { trigger: 'item' },
                        series: [{
                            type: 'graph',
                            layout: graphLayout.value,
                            data: nodes,
                            links: data.links.map(l => ({
                                source: l.source, target: l.target,
                                lineStyle: { width: 1.5, opacity: 0.4, curveness: 0.1 }
                            })),
                            roam: true,
                            focusNodeAdjacency: true,
                            force: {
                                repulsion: 1000, gravity: 0.05, edgeLength: [80, 200], friction: 0.8
                            },
                            circular: { rotateLabel: true },
                            lineStyle: { color: lineColor, curveness: 0.3 },
                            emphasis: { lineStyle: { width: 4, opacity: 1 }, label: { show: true } }
                        }]
                    };
                    chartInstance.hideLoading();
                    chartInstance.setOption(option);
                    
                    chartInstance.on('click', (p) => {
                        if(p.dataType === 'node' && p.data.path) previewDoc(p.data.path);
                        else if (p.dataType === 'node') { ask(p.data.name); switchTab('chat'); }
                    });
                };

                const graphDocCategory = (docNode) => {
                    if(docNode.path && docNode.path.includes('/')) return docNode.path.split('/').slice(0, -1).join('/');
                    const cats = Array.isArray(docNode.categories) ? docNode.categories : (docNode.category ? [docNode.category] : []);
                    return (cats[0] && cats[0] !== '文档') ? cats[0] : 'root';
                };

                const renderTree = (data, isDark) => {
                    const docNodes = data.nodes.filter(n => n.type === 'document');
                    const nodeById = new Map(data.nodes.map(n => [n.id, n]));
                    const entitiesByDoc = new Map();
                    data.links.forEach(l => {
                        const src = nodeById.get(l.source);
                        const tgt = nodeById.get(l.target);
                        if(src && tgt && src.type === 'document' && tgt.type !== 'document') {
                            if(!entitiesByDoc.has(src.id)) entitiesByDoc.set(src.id, []);
                            entitiesByDoc.get(src.id).push(tgt);
                        } else if(src && tgt && tgt.type === 'document' && src.type !== 'document') {
                            if(!entitiesByDoc.has(tgt.id)) entitiesByDoc.set(tgt.id, []);
                            entitiesByDoc.get(tgt.id).push(src);
                        }
                    });

                    const root = { name: webuiApp.value.name || 'Knowledge Base', children: [] };
                    const folders = new Map();
                    const ensureFolder = (path) => {
                        if(!path || path === 'root') {
                            if(!folders.has('root')) {
                                const node = { name: 'root', children: [] };
                                folders.set('root', node);
                                root.children.push(node);
                            }
                            return folders.get('root');
                        }
                        const parts = path.split('/');
                        let currentPath = '';
                        let parent = root;
                        parts.forEach(part => {
                            currentPath = currentPath ? currentPath + '/' + part : part;
                            if(!folders.has(currentPath)) {
                                const node = { name: part, children: [] };
                                folders.set(currentPath, node);
                                parent.children.push(node);
                            }
                            parent = folders.get(currentPath);
                        });
                        return parent;
                    };

                    docNodes.forEach(doc => {
                        const folder = ensureFolder(graphDocCategory(doc));
                        const seen = new Set();
                        const children = (entitiesByDoc.get(doc.id) || [])
                            .filter(e => { const name = e.name || e.label || e.id; if(seen.has(name)) return false; seen.add(name); return true; })
                            .slice(0, 12)
                            .map(e => ({ name: e.name || e.label || e.id, value: e.freq || 1 }));
                        folder.children.push({ name: doc.name || doc.id, path: doc.path, children });
                    });

                    const option = {
                        backgroundColor: 'transparent',
                        tooltip: { trigger: 'item', triggerOn: 'mousemove' },
                        series: [{
                            type: 'tree',
                            data: [root],
                            top: '4%', left: '8%', bottom: '4%', right: '22%',
                            orient: 'LR',
                            symbol: 'emptyCircle',
                            symbolSize: 8,
                            expandAndCollapse: true,
                            initialTreeDepth: 3,
                            roam: true,
                            label: {
                                position: 'left', verticalAlign: 'middle', align: 'right',
                                color: isDark ? '#ccc' : '#333', fontSize: 12
                            },
                            leaves: {
                                label: { position: 'right', verticalAlign: 'middle', align: 'left', color: isDark ? '#ddd' : '#333' }
                            },
                            emphasis: { focus: 'descendant' },
                            lineStyle: { color: isDark ? '#4b5563' : '#d1d5db', width: 1.5, curveness: 0.5 }
                        }]
                    };
                    chartInstance.hideLoading();
                    chartInstance.setOption(option);
                    chartInstance.on('click', (p) => {
                        if(p.data && p.data.path) previewDoc(p.data.path);
                    });
                };

                const renderChord = (data, isDark, textColor) => {
                    const docNodes = data.nodes.filter(n => n.type === 'document');
                    const nodeById = new Map(data.nodes.map(n => [n.id, n]));
                    const categoryNodes = new Map();
                    const entityNodes = new Map();
                    const links = [];

                    docNodes.forEach(doc => {
                        const cat = graphDocCategory(doc);
                        if(!categoryNodes.has(cat)) {
                            categoryNodes.set(cat, { id: 'cat_' + cat, name: cat, type: 'category', symbolSize: 34, itemStyle: { color: '#8b5cf6' } });
                        }
                        links.push({ source: 'cat_' + cat, target: doc.id, value: 2 });
                    });

                    data.links.forEach(l => {
                        const src = nodeById.get(l.source);
                        const tgt = nodeById.get(l.target);
                        const doc = src?.type === 'document' ? src : (tgt?.type === 'document' ? tgt : null);
                        const ent = src?.type === 'document' ? tgt : (tgt?.type === 'document' ? src : null);
                        if(!doc || !ent || ent.type === 'document') return;
                        const entName = ent.name || ent.label || ent.id;
                        if(!entityNodes.has(ent.id)) {
                            entityNodes.set(ent.id, { id: ent.id, name: entName, type: 'entity', symbolSize: 18 + Math.min((ent.freq || 1) * 2, 18), itemStyle: { color: '#10b981' } });
                        }
                        links.push({ source: doc.id, target: ent.id, value: 1 });
                    });

                    const nodes = [
                        ...Array.from(categoryNodes.values()),
                        ...docNodes.map(d => ({
                            id: d.id, name: d.name || d.id, type: 'document', path: d.path, symbolSize: 26,
                            itemStyle: { color: '#3b82f6' }
                        })),
                        ...Array.from(entityNodes.values())
                    ];

                    const option = {
                        backgroundColor: 'transparent',
                        tooltip: { trigger: 'item' },
                        legend: [{ data: ['category', 'document', 'entity'], bottom: 8, textStyle: { color: textColor } }],
                        series: [{
                            name: '知识弦图',
                            type: 'graph',
                            layout: 'circular',
                            circular: { rotateLabel: true },
                            roam: true,
                            focusNodeAdjacency: true,
                            data: nodes.map(n => ({...n, category: n.type})),
                            categories: [
                                { name: 'category' },
                                { name: 'document' },
                                { name: 'entity' }
                            ],
                            links: links.map(l => ({
                                source: l.source, target: l.target, value: l.value,
                                lineStyle: { width: Math.max(1, l.value), opacity: 0.38, curveness: 0.35 }
                            })),
                            lineStyle: { color: 'source', curveness: 0.35 },
                            label: { show: true, position: 'right', formatter: '{b}', color: textColor, fontSize: 11 },
                            emphasis: { focus: 'adjacency', lineStyle: { width: 4, opacity: 0.9 } }
                        }]
                    };
                    chartInstance.hideLoading();
                    chartInstance.setOption(option);
                    chartInstance.on('click', (p) => {
                        if(p.dataType === 'node' && p.data.path) previewDoc(p.data.path);
                        else if(p.dataType === 'node' && p.data.type === 'entity') { ask(p.data.name); switchTab('chat'); }
                    });
                };

                const renderSankey = (data, isDark) => {
                    // Transform Graph to Sankey: Category -> Doc -> Entity
                    const nodes = [];
                    const links = [];
                    const nodeSet = new Set();

                    const addNode = (name, depth) => {
                        if(!nodeSet.has(name)) {
                            nodes.push({ name: name, itemStyle: { color: depth === 0 ? '#8b5cf6' : (depth === 1 ? '#3b82f6' : '#10b981') } });
                            nodeSet.add(name);
                        }
                    };

                    data.nodes.forEach(n => {
                        if(n.type === 'document') {
                            const cats = Array.isArray(n.categories) ? n.categories : (n.category ? [n.category] : ['未分类']);
                            const cat = graphDocCategory(n);
                            addNode(cat, 0);
                            addNode(n.name, 1);
                            links.push({ source: cat, target: n.name, value: 2 });
                        }
                    });

                    data.links.forEach(l => {
                        const src = data.nodes.find(n => n.id === l.source);
                        const tgt = data.nodes.find(n => n.id === l.target);
                        if(src && tgt && src.type === 'document' && tgt.type === 'entity') {
                            addNode(src.name, 1);
                            addNode(tgt.name, 2);
                            links.push({ source: src.name, target: tgt.name, value: 1 });
                        }
                    });

                    const option = {
                        tooltip: { trigger: 'item', triggerOn: 'mousemove' },
                        series: [{
                            type: 'sankey',
                            data: nodes,
                            links: links,
                            emphasis: { focus: 'adjacency' },
                            lineStyle: { color: 'gradient', curveness: 0.5 },
                            label: { color: isDark ? '#ccc' : '#333', fontSize: 12 },
                            nodeAlign: 'left',
                            layoutIterations: 32
                        }]
                    };
                    chartInstance.hideLoading();
                    chartInstance.setOption(option);
                };

                // Resize observer for graph
                onMounted(async () => {
                    window.addEventListener('resize', () => {
                        if(activeTab.value === 'graph' && chartInstance) chartInstance.resize();
                    });
                    
                    // Initial load stats & sidebar counts
                    await loadWebuiConfig().catch(()=>{});
                    fetch('/api/stats').then(r=>r.json()).then(s => stats.value = s).catch(()=>{});
                    if(featureEnabled('candidates')) {
                        loadCandidates().catch(()=>{});
                        loadBatchImportStatus().then(job => { if(job.running) startBatchImportPolling(); }).catch(()=>{});
                    }
                    if(featureEnabled('wechat')) loadWechatSources().catch(()=>{});
                    if(featureEnabled('rss')) loadRssFeeds().catch(()=>{});
                    loadTranslationModels().catch(()=>{});
                    if(featureEnabled('llm_settings')) {
                        loadLlmConfig().catch(()=>{});
                        loadLlmBackups().catch(()=>{});
                    }
                    if(featureEnabled('llm_audit')) {
                        loadLlmAudit().catch(()=>{});
                        loadTranslationBackfillAudit().catch(()=>{});
                    }
                });

                return {
                    activeTab, switchTab, theme, toggleTheme, uiLang, t, mobileMenuOpen, graphLayout, graphSearchText, associationReport, loadingAssociations, loadAssociations,
                    webuiConfig, webuiApp, webuiFeatures, featureEnabled, loadingWebuiConfig, savingWebuiConfig, loadWebuiConfig, saveWebuiConfig, saveAllSettings, refreshAllSettings,
                    toasts, 
                    chatInput, chatHistory, isWaiting, submitChat, chatAnswerMode, renderMarkdown, ask,
                    qaProviderChain,
                    docs, filteredDocs, folderRows, visibleDocs, pagedVisibleDocs, docsPage, docsPageSize, docsTotalPages, selectedDocFolder, loadingDocs, docSearchText, loadDocs, qualityBadCount, qualityIssueSummary, qualityOnly, issueLabel, issueText, repairingQuality, repairDocQuality, repairAllQuality, deleteDoc,
                    isMaintaining, maintenanceReport, runMaintenance,
                    candidates, candidateGroups, candidateSummary, candidateTierFilter, candidateTypeFilter, candidateIncludeSkipped, loadingCandidates, importingCandidateId, translatingCandidateId, batchTranslatingPreview, batchImportingA, batchImportLimit, batchImportRetries, batchImportJob, loadBatchImportStatus, batchSkippingCandidates, candidateEditOpen, savingCandidateEdit, candidateEditItem, candidateEditOriginalTitle, candidateEditForm, lastImportResult, openLastImportedDoc, searchLastImported, tierBadgeClass, tierLabel, tierCardClass, formatCandidateDate, loadCandidates, previewCandidate, translateCandidate, batchTranslatePreview, batchImportA, editCandidate, closeCandidateEdit, saveCandidateEdit, batchSkipLowQuality, importCandidate, skipCandidate, restoreCandidate,
                    wechatSources, loadingWechatSources, savingWechatSource, discoveringWechat, wechatDiscoveryResult, newWechatSource, discoverForm, loadWechatSources, saveWechatSource, discoverWechat,
                    rssFeeds, loadingRssFeeds, syncingRss, rssSyncResult, rssNewForm, loadRssFeeds, saveRssFeed, deleteRssFeed, syncRss, toggleRssFeed,
                    dragOver, handleDrop, handleFileUpload, formatBytes, formatDate, stats,
                    initGraph,
                    previewOpen, previewLoading, previewContent, previewDocName, previewRelated, previewAssociation, previewMeta, previewAuditItem, previewMode, candidateWorkbenchItem, previewDoc, focusDocInList, openAuditDoc, openDocAudit, closePreview, isEditingDoc, saveDocContent, saveCandidateReviewInline,
                    translationModels, translationProvider, selectedTranslationModel, isRetranslating, retranslateDoc,
                    llmProviders, llmFlows, llmBackups, llmSecretSetup, llmMode, llmModeOptions, llmModeLabel, llmModeDescription, settingLlmMode,
                    fileImportFlow, fileImportProviderChain,
                    llmAudit, llmAuditFilters, loadingLlmAudit, translationBackfillAudit, translationBackfillDryRun, loadingTranslationBackfill, loadingLlmConfig, savingLlmConfig, restoringLlmBackup,
                    loadLlmConfig, saveLlmConfig, setLlmMode, loadLlmBackups, loadLlmAudit, resetLlmAuditFilters, exportLlmAudit, loadTranslationBackfillAudit, previewTranslationBackfillDryRun, restoreLlmBackup, testLlmProvider, objectEntries,
                    addLlmProvider, deleteLlmProvider, syncProviderName, providerLabel,
                    availableProvidersForFlow, addProviderToFlow, removeFlowProvider, moveFlowProvider,
                    showUrlInput, fetchUrlInput, isFetchingUrl, fetchUrlError, fetchUrlSuccess, fetchUrl, failedImports, retryFailedImport
                };
            }
        }).mount('#app');
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return INDEX_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route("/static/<path:filename>")
def static_files(filename: str):
    return send_file(str(KB_DIR / "static" / filename))



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
