#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""relay_say.py — 本體對主人說話的**免費**路徑（v1.11 機制）

用法：python3 tools/relay_say.py "訊息"        # 預設主人私訊通道
     echo "多行" | python3 tools/relay_say.py -
     python3 tools/relay_say.py --to <channel> "訊息"   # 例：group:Cxxxx
     python3 tools/relay_say.py --any "訊息"            # 任何通道下次出聲時帶出

原理：不打 push API（免費額度 200 則/月），改把話掛進 pending_relay.jsonl；
bridge 在下一次「本來就要發的 reply」（值台回話／任務 ack）時原樣帶出——reply 免費無限。
代價：**不是即時**，要等主人下次傳訊息。急件仍用 line_push.py（吃額度）。
排版慣例：不用 markdown、逗號句號後換行。
"""
import base64
import json
import os
import sys
from datetime import datetime, timezone, timedelta

ROOM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 去硬編碼：以自身位置定位（<base>/tools/ 下）
PENDING = os.path.join(ROOM, "LOG", "pending_relay.jsonl")
OWNER = os.path.join(ROOM, "config", "secrets", "line_owner.txt")
CFG_P = os.path.join(ROOM, "config", "kit_config.json")


def kit_config():
    try:
        with open(CFG_P, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    cfg = kit_config()
    args = sys.argv[1:]
    channel = None
    if args and args[0] == "--to":
        channel, args = args[1], args[2:]
    elif args and args[0] == "--any":
        channel, args = "*", args[1:]
    if not args:
        print(__doc__)
        sys.exit(64)
    text = sys.stdin.read() if args[0] == "-" else args[0]
    text = text.strip()
    if not text:
        sys.exit("空訊息不掛")
    if not text.startswith("【"):
        text = cfg.get("body_label", "【本體】") + "\n" + text   # 角色註記：每個聲音標身分
    if channel is None:
        uid = open(OWNER, encoding="utf-8").readline().strip()
        channel = f"dm:{uid}"
    # 高信任通道防呆（硬擋）：待轉達會把本體的話**原樣**送進通道——
    # 掛到最高規格通道（如主人的職場群）等於把內部回報送到外人面前。
    # 要在那裡發言，必須經由該通道值台、走它自己的紀律。
    s_tier = set(cfg.get("s_tier_channels", []))
    if any(t in channel for t in s_tier):
        sys.exit("✗ 拒絕：目標是高信任職場通道。\n"
                 "  待轉達會原樣送出本體的話——內部回報不得進入該通道。\n"
                 "  要在那裡發言請走該通道值台（它讀該通道的專屬紀律），或請主人親自轉述。")

    rec = {"id": base64.b16encode(os.urandom(6)).decode().lower(),
           "channel": channel, "text": text,
           "ts": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")}
    os.makedirs(os.path.dirname(PENDING), exist_ok=True)
    with open(PENDING, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"✓ 已掛待轉達 id={rec['id']} channel={channel} len={len(text)}（主人下次出聲時免費帶出）")


if __name__ == "__main__":
    main()
