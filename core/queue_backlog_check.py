#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""queue_backlog_check.py — LINE 任務佇列積壓偵測器

唯讀設計：只讀 task_queue.jsonl 與收割標記檔，不碰 bridge、不發訊。
「積壓」定義：佇列裡 ts 晚於收割標記、且已滯留超過寬限期（預設 10 分鐘）的任務。

用法：
  check          列出積壓任務（有積壓 exit 1，乾淨 exit 0）——排程每拍跑
  mark           處理完佇列後把收割標記設為現在——收尾跑
  mark <ISO時刻>  把標記設到指定時刻（首跑驗證/回溯用）

設計依據：實戰事故「排程鐘死了沒人發現」——
本工具讓「佇列有任務但沒人動」變成可機器判定的事實，而非靠回憶。
"""
import json
import os
import sys
import datetime

ROOM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 去硬編碼：以自身位置定位（<base>/tools/ 下）
QUEUE = os.path.join(ROOM, "LOG", "task_queue.jsonl")
MARKER = os.path.join(ROOM, "LOG", "queue_harvest_marker.json")
GRACE_MIN = 10
TZ = datetime.timezone(datetime.timedelta(hours=8))   # 預設台灣時區；跨時區部署改這裡


def now_tz():
    return datetime.datetime.now(TZ)


def read_marker():
    if not os.path.exists(MARKER):
        return None
    with open(MARKER, encoding="utf-8") as f:
        return datetime.datetime.fromisoformat(json.load(f)["harvested_until"])


def cmd_mark(ts=None):
    val = ts or now_tz().isoformat(timespec="seconds")
    datetime.datetime.fromisoformat(val)  # 壞格式直接炸，不寫壞標記
    with open(MARKER, "w", encoding="utf-8") as f:
        json.dump({"harvested_until": val, "written_at": now_tz().isoformat(timespec="seconds")}, f, ensure_ascii=False)
    print(f"marker={val}")


def cmd_check():
    marker = read_marker()
    if marker is None:
        sys.exit("無收割標記——先跑 mark 初始化（否則整條佇列都算積壓）")
    grace = now_tz() - datetime.timedelta(minutes=GRACE_MIN)
    backlog = []
    with open(QUEUE, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            ts = datetime.datetime.fromisoformat(e["ts"])
            if ts > marker and ts < grace:
                backlog.append((e["ts"], e.get("channel", "?"), e.get("text", "")[:40]))
    if backlog:
        print(f"🔴 積壓 {len(backlog)} 筆（標記後滯留 >{GRACE_MIN} 分鐘）：")
        for ts, ch, txt in backlog:
            print(f"  {ts} {ch} {txt!r}")
        sys.exit(1)
    print(f"✅ 無積壓（標記 {marker.isoformat(timespec='seconds')}，寬限 {GRACE_MIN} 分）")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "mark"):
        print(__doc__)
        sys.exit(64)
    if sys.argv[1] == "mark":
        cmd_mark(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        cmd_check()


if __name__ == "__main__":
    main()
