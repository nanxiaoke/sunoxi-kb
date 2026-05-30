#!/usr/bin/env python3
"""Shared cleanup helpers for raw import paths."""

from __future__ import annotations

import re
from typing import Any


TITLE_SUFFIXES = [
    "微信公众平台",
    "微信公众号",
    "知乎专栏",
    "知乎",
    "掘金",
    "CSDN博客",
    "CSDN",
    "博客园",
    "InfoQ",
]


def clean_import_title(raw: Any, fallback: str = "未命名文档", max_len: int = 120) -> str:
    title = str(raw or "").strip()
    title = re.sub(r"^```(?:\w+)?|```$", "", title).strip()
    title = re.sub(r"^\s*#*\s*(标题|title)\s*[:：]\s*", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" \t\r\n\"'`")
    for suffix in TITLE_SUFFIXES:
        title = re.sub(rf"\s*[-|_—–]\s*{re.escape(suffix)}\s*$", "", title, flags=re.I).strip()
    if not title:
        title = fallback
    return title[:max_len].strip() or fallback


def safe_import_stem(title: Any, fallback: str = "untitled", max_len: int = 60) -> str:
    clean = clean_import_title(title, fallback=fallback, max_len=max_len)
    stem = re.sub(r"[^\w\u4e00-\u9fff\-_ —]", "", clean).strip()
    stem = re.sub(r"\s+", "_", stem)
    return stem[:max_len].strip("_") or fallback
