#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task_verify.py — 任務封包驗章器（本體側；外部安全審查發現的落地：task_queue=不可信 IPC 邊界）

本體收到 Monitor 事件後、動手前，先跑本工具驗最後 N 筆封包：
  python3 tools/task_verify.py            # 驗最後 5 筆
  python3 tools/task_verify.py --all      # 驗全佇列

驗證失敗＝拒絕執行該任務＋警報主人（fail-closed）。
誠實界線：同 UID 惡意程序可讀鍵檔；本工具防的是「只改佇列檔」的偽造，
不是全面淪陷防護（那要靠 OS 層隔離）。
無 sig 欄的舊封包標 LEGACY，不算失敗但提示人工判斷。
"""
import hashlib
import hmac
import json
import os
import sys

ROOM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 去硬編碼：以自身位置定位（<base>/tools/ 下）
QUEUE = os.path.join(ROOM, "LOG", "task_queue.jsonl")
KEY_FILE = os.path.join(ROOM, "config", "secrets", "queue_hmac.key")


def verify(entry: dict) -> str:
    sig = entry.pop("sig", None)
    if sig is None:
        return "LEGACY"
    key = open(KEY_FILE, encoding="utf-8").read().strip().encode()
    canonical = json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    good = hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()
    return "OK" if hmac.compare_digest(good, sig) else "FAIL"


def main():
    n = None if "--all" in sys.argv else 5
    lines = [l for l in open(QUEUE, encoding="utf-8") if l.strip()]
    if n:
        lines = lines[-n:]
    bad = 0
    for i, l in enumerate(lines):
        try:
            e = json.loads(l)
        except json.JSONDecodeError:
            print(f"🔴 #{i} 非法JSON"); bad += 1; continue
        v = verify(dict(e))
        mark = {"OK": "✅", "LEGACY": "⚪", "FAIL": "🔴"}[v]
        print(f"{mark} {v} {e.get('ts','?')} {e.get('channel','?')} {e.get('text','')[:40]!r}")
        if v == "FAIL":
            bad += 1
    if bad:
        print(f"🛑 {bad} 筆驗章失敗——該任務不得執行，立刻警報主人")
        sys.exit(1)
    print("封包鏈驗畢")
    sys.exit(0)


if __name__ == "__main__":
    main()
