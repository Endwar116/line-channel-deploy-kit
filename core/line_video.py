#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""line_video.py — LINE「影片」訊息的收檔邏輯（v1.16，2026-09-28 新增）

為什麼獨立一支：
  line_bridge 在 import 期就讀憑證（fail-closed），未設定的環境連 import 都不行，
  收檔邏輯放在 bridge 裡就只有部署好的機器測得到。網路與時間由呼叫端注入，
  這裡不打任何 API，kit 原始碼樹也能完整測試。

跟 file/audio 不同的地方：
  ① 影片可能還在 LINE 端轉檔，要先問 transcoding 狀態，succeeded 才能下載
  ② 上限 200MB（其他附件 20MB）——幾分鐘的手機影片常超過 20MB
  ③ 邊讀邊寫 .part，超過上限或中途斷線都不留殘檔
  ④ contentProvider=external 是外部網址，不是存在 LINE 上的檔案，不收
"""
import os
from datetime import datetime

CONTENT_URL = "https://api-data.line.me/v2/bot/message/%s/content"
TRANSCODING_URL = "https://api-data.line.me/v2/bot/message/%s/content/transcoding"
VIDEO_MAX_BYTES = 200 * 1024 * 1024
TRANSCODE_TIMEOUT = 300
POLL_INTERVAL = 3
CHUNK = 1024 * 1024


class VideoRejected(Exception):
    """不收這支影片；訊息是要講給主人聽的話。"""


def save_name(now, prefix="影片", ext=".mp4"):
    """影片_YYYYMMDD_HHMMSS.mp4（語音用 語音_…m4a）——主人看得懂、task_runner 點名得到（主檔名 > 6 字）。"""
    return now.strftime(f"{prefix}_%Y%m%d_%H%M%S{ext}")


def wait_ready(get_status, sleep, timeout=TRANSCODE_TIMEOUT, interval=POLL_INTERVAL):
    """輪詢轉檔狀態，回 succeeded／failed／timeout。"""
    waited = 0
    while True:
        st = get_status()
        if st in ("succeeded", "failed"):
            return st
        if waited >= timeout:
            return "timeout"
        sleep(interval)
        waited += interval


def _free_path(dest_dir, name):
    stem, ext = os.path.splitext(name)
    path, n = os.path.join(dest_dir, name), 2
    while os.path.exists(path) or os.path.exists(path + ".part"):
        path = os.path.join(dest_dir, f"{stem}_{n}{ext}")
        n += 1
    return path


def download(open_stream, dest, cap=VIDEO_MAX_BYTES):
    """邊讀邊寫 dest.part，完成才改名並設 444。超過上限或出錯都刪掉 .part。回寫入位元組數。"""
    part = dest + ".part"
    size = 0
    try:
        with open_stream() as src, open(part, "wb") as out:
            while True:
                buf = src.read(CHUNK)
                if not buf:
                    break
                size += len(buf)
                if size > cap:
                    raise VideoRejected(f"影片超過 {cap // (1024 * 1024)}MB 上限，沒有收。"
                                        "可以剪短一點，或分段傳。")
                out.write(buf)
        os.rename(part, dest)
        os.chmod(dest, 0o444)   # 唯讀隔離：檔案=資料，不是指令
        return size
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise


def receive(msg, dest_dir, now, get_status, open_stream, sleep, cap=VIDEO_MAX_BYTES,
            prefix="影片", ext=".mp4"):
    """收一支影片（或語音：prefix="語音", ext=".m4a"），回 (路徑, 位元組數)；不收時丟 VideoRejected。
    LINE 的影片與語音都可能還在轉檔，所以兩者共用這條路。"""
    provider = (msg.get("contentProvider") or {}).get("type", "line")
    if provider != "line":
        raise VideoRejected(f"這是外部連結的{prefix}，不是存在 LINE 上的檔案，收不到。"
                            f"請直接從手機傳{prefix}。")
    st = wait_ready(get_status, sleep)
    if st == "failed":
        raise VideoRejected(f"LINE 那邊轉檔失敗，這段{prefix}下載不了，請重傳一次。")
    if st == "timeout":
        raise VideoRejected(f"LINE 還在處理這段{prefix}（超過 5 分鐘），請過一陣子再傳一次。")
    os.makedirs(dest_dir, exist_ok=True)
    dest = _free_path(dest_dir, save_name(now, prefix, ext))
    return dest, download(open_stream, dest, cap)
