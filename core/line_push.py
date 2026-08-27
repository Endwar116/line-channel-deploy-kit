#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""line_push.py — 本體對主人的 LINE 主動推送工具（任務回報回程）

用法：python3 tools/line_push.py "訊息文字"
     echo "多行訊息" | python3 tools/line_push.py -
     python3 tools/line_push.py --to <userId/groupId> "訊息"

注意：push 吃免費額度（台灣輕用量 200 則/月）——任務回報用，不閒聊；
平時回報優先用 relay_say.py（免費搭 reply 便車）。
排版慣例：不用 markdown、句號後換行。
收件人＝line_owner.txt 第一行（認主檔）。secrets 同 line_bridge。
"""
import json
import os
import sys
import urllib.request

ROOM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 去硬編碼：以自身位置定位（<base>/tools/ 下）
CFG_P = os.path.join(ROOM, "config", "kit_config.json")


def kit_config():
    try:
        with open(CFG_P, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def find(rel):
    p = os.path.join(ROOM, rel)
    if os.path.exists(p):
        return p
    raise SystemExit(f"找不到 {rel}（基準目錄：{ROOM}）")


def log_to_history(target_id, text, body_label):
    """本體推送同步落通道 history——值台注入對話紀錄時才看得到本體回了什麼
    （語義斷裂修復：不落地的話，值台會不知道本體已在該通道回覆過、自行發揮）。
    失敗不擋推送但要出聲。"""
    try:
        ctype = "dm" if target_id.startswith("U") else ("group" if target_id.startswith("C") else "room")
        d = os.path.join(ROOM, "chats", f"{ctype}_{target_id[:20]}")
        if not os.path.isdir(d):
            print(f"⚠️ history 未落（通道目錄不存在：{d}）")
            return
        import datetime
        ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        with open(os.path.join(d, "history.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ts, "uid": "body", "who": body_label.strip("【】"), "text": text},
                               ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"⚠️ history 落地失敗（推送本身成功）：{e}")


def main():
    cfg = kit_config()
    body_label = cfg.get("body_label", "【本體】")
    args = sys.argv[1:]
    target = None
    if "--to" in args:
        i = args.index("--to")
        try:
            target = args[i + 1]
        except IndexError:
            sys.exit("--to 需要帶目標 id（userId/groupId/roomId）")
        args = args[:i] + args[i + 2:]
    if not args:
        print(__doc__)
        sys.exit(64)
    # 防呆（--help 誤發事故）：「-」開頭的未知參數當打錯指令，印用法退出，不當內文推
    if args[0].startswith("-") and args[0] != "-":
        print(__doc__)
        sys.exit(64)
    text = sys.stdin.read() if args[0] == "-" else args[0]
    text = text.strip()
    if not text:
        sys.exit("空訊息不發")
    # 角色註記：本體出聲必標身分；已帶【】標頭者（如代轉他人）不重複加
    if not text.startswith("【"):
        text = body_label + "\n" + text
    env = {}
    with open(find("config/secrets/line_secrets.env"), encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k] = v
    # 預設推主人私訊；--to 指定通道（教訓：群組任務的回報不該跑進私訊——從哪來回哪去）
    uid = target or open(find("config/secrets/line_owner.txt"), encoding="utf-8").readline().strip()
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=json.dumps({"to": uid, "messages": [{"type": "text", "text": text[:4900]}]}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {env['LINE_CHANNEL_ACCESS_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        print(f"pushed status={r.status} len={len(text)}")
    log_to_history(uid, text, body_label)


if __name__ == "__main__":
    main()
