#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video_link.py — 任務裡的影片連結 → 下載成檔案（v1.17，2026-09-28 新增）

主人傳「任務：看這支影片 https://...」時，task_runner（Python，不是 agent）先用 yt-dlp
把影片抓下來，再交給 video_digest 轉逐字稿與畫格；agent 仍然只有讀取工具。

邊界（主人 2026-09-28 決定）：
  ・只抓公開影片——不讀瀏覽器 cookie、不登入。要登入的影片如實說，請主人自己下載後用 LINE 傳
  ・最高 720p、200MB、60 分鐘（太長的影片轉逐字稿會拖垮任務）
  ・網址前放 --，就算網址被偽造成 "-o /某處" 也只會被當成網址
  ・只認得下列影片網站的網域（含子網域），長得像的假網域不算

用法：
  python3 tools/video_link.py <網址>     # 手動下載並印出路徑
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys

ROOM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINKS_DIR = os.path.join(ROOM, "media", "links")

SUPPORTED_HOSTS = ("youtube.com", "youtu.be", "facebook.com", "fb.watch", "instagram.com",
                   "threads.net", "threads.com", "tiktok.com", "xiaohongshu.com", "xhslink.com",
                   "vimeo.com", "bilibili.com", "b23.tv", "x.com", "twitter.com")
MAX_LINKS = 2
MAX_MB = 200
MAX_SECONDS = 3600
FETCH_TIMEOUT = 900
INSTALL_HINT = "brew install yt-dlp"

URL_RE = re.compile(r"https?://[^\s\"'<>（）「」【】、，。！？]+")


class LinkRejected(Exception):
    """抓不到這支影片；訊息是要講給主人聽的話。"""


def _host_ok(url):
    host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].lower()
    return any(host == h or host.endswith("." + h) for h in SUPPORTED_HOSTS)


def find_video_links(text, limit=MAX_LINKS):
    out = []
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,;:!?)]}")
        if _host_ok(u) and u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


def _explain(stderr):
    s = stderr.lower()
    if any(k in s for k in ("login", "log in", "sign in", "private", "cookies", "registered users",
                            "members-only", "not available")):
        return "這支影片要登入才看得到（或已設為不公開），我只抓公開影片。可以請你下載後直接用 LINE 傳影片給我。"
    if "max-filesize" in s:
        return f"這支影片超過 {MAX_MB}MB，沒有抓。"
    if "does not pass filter" in s:
        return f"這支影片超過 {MAX_SECONDS // 60} 分鐘，沒有抓（太長轉逐字稿會拖太久）。可以給我片段或時間點。"
    if "unsupported url" in s:
        return "這個網址不支援下載影片（可能不是影片頁，或是網站格式變了）。"
    return "這支影片抓不到（平台可能擋了下載），可以請你下載後直接用 LINE 傳影片給我。"


def fetch(url, dest_dir=LINKS_DIR, run=subprocess.run, ytdlp=None):
    """下載一支連結影片，回檔案路徑；抓不到丟 LinkRejected。同一個網址只下載一次。"""
    ytdlp = ytdlp or shutil.which("yt-dlp") or "/opt/homebrew/bin/yt-dlp"
    if not os.path.exists(ytdlp):
        raise LinkRejected(f"這台電腦沒裝影片下載工具，連結影片看不了（安裝：{INSTALL_HINT}）。")
    os.makedirs(dest_dir, exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    stem = f"連結影片_{key}"
    for f in sorted(os.listdir(dest_dir)):
        if f.startswith(stem + ".") and not f.endswith((".part", ".ytdl")):
            return os.path.join(dest_dir, f)
    args = [ytdlp, "--no-playlist", "--no-progress", "--no-warnings",
            "-f", "bv*[height<=720]+ba/b[height<=720]/b",
            "--max-filesize", f"{MAX_MB}M",
            "--match-filter", f"duration <= {MAX_SECONDS}",
            "--merge-output-format", "mp4", "--socket-timeout", "30",
            "-o", os.path.join(dest_dir, stem + ".%(ext)s"),
            "--print", "after_move:filepath", "--", url]
    try:
        r = run(args, capture_output=True, text=True, timeout=FETCH_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        _cleanup(dest_dir, stem)
        raise LinkRejected(f"下載超過 {FETCH_TIMEOUT // 60} 分鐘還沒完成，放棄了。")
    path = (r.stdout or "").strip().splitlines()[-1:] if r.returncode == 0 else []
    if not path or not os.path.exists(path[0]):
        _cleanup(dest_dir, stem)
        # 被 match-filter 跳過時 yt-dlp 回 0 但沒有檔案
        raise LinkRejected(_explain((r.stderr or "") + (r.stdout or "")))
    return path[0]


def _cleanup(dest_dir, stem):
    for f in os.listdir(dest_dir):
        if f.startswith(stem):
            os.remove(os.path.join(dest_dir, f))


def main():
    for u in sys.argv[1:]:
        try:
            print(fetch(u))
        except LinkRejected as e:
            print(f"[抓不到] {u}：{e}")


if __name__ == "__main__":
    main()
