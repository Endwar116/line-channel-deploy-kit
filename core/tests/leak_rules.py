# -*- coding: utf-8 -*-
"""出貨原始碼不能帶部署者專屬的東西。用通用規則抓，不列任何人的名字或網域——
列出來的話，這份清單本身就成了個資外洩（2026-09-28 改）。"""
import re

RULES = [
    ("網域", r"\b[\w-]+\.(?:cc|com|tw|net|org|io)\b(?<!example\.com)(?<!example\.org)"),
    ("家目錄路徑", r"/Users/"),
    ("寫死的安裝目錄", r"~/\.(?!cloudflared/)[a-z0-9_]+/(?:tools|media|LOG|config|models)\b"),
    ("寫死的 launchd 標籤", r"[\"']com\.[a-z0-9_]+\."),
    ("寫死的 bridge port", r":8700\b"),
]


def leaks(text):
    """回傳命中的 (規則名, 片段)。"""
    return [(name, m.group(0)) for name, pat in RULES for m in re.finditer(pat, text)]
