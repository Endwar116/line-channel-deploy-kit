#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video_digest.py — 影片／音檔消化（本體側工具）

把一支影片或一段錄音拆成「讀得懂的東西」，讓只有讀取工具的本體也能分析影片：

  逐字稿    ffmpeg 抽音軌（16kHz 單聲道）→ whisper.cpp（Metal 加速）→ .txt + .srt
  關鍵畫格  ffmpeg 場景偵測抓換鏡頭的畫面，不夠就等距補，最多 MAX_FRAMES 張 jpg
  基本資訊  長度、解析度、fps、有沒有音軌 → meta.json

產出在 media/digest/<檔名>/，同一支檔案只處理一次（依大小+修改時間判斷），
第二次直接讀快取。原始檔不動（incoming 是 444 唯讀）。

用法：
  python3 tools/video_digest.py <檔案>            # 處理並印出摘要
  python3 tools/video_digest.py <檔案> --force    # 忽略快取重做
  python3 tools/video_digest.py <檔案> --no-frames
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCOMING = os.path.join(ROOM, "media", "incoming")
DIGEST = os.path.join(ROOM, "media", "digest")
MODEL = os.path.join(ROOM, "models", "ggml-large-v3-turbo-q5_0.bin")

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".3gp"}
AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus", ".flac", ".aiff", ".amr"}
MEDIA_EXT = VIDEO_EXT | AUDIO_EXT

MAX_FRAMES = 12
SCENE_THRESHOLD = 0.3
WHISPER_TIMEOUT = 3600


def _bin(name):
    return shutil.which(name) or f"/opt/homebrew/bin/{name}"


INSTALL_HINT = "brew install ffmpeg whisper-cpp；模型放 models/ggml-large-v3-turbo-q5_0.bin"


def missing_tools():
    """缺少的外部指令（ffmpeg、ffprobe、whisper-cli）。"""
    return [n for n in ("ffmpeg", "ffprobe", "whisper-cli") if not os.path.exists(_bin(n))]


def probe(path):
    r = subprocess.run([_bin("ffprobe"), "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", path],
                       capture_output=True, text=True, timeout=60)
    d = json.loads(r.stdout or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"
              and s.get("disposition", {}).get("attached_pic") != 1), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = None
    if v and v.get("avg_frame_rate", "0/0") != "0/0":
        n, dnm = v["avg_frame_rate"].split("/")
        fps = round(int(n) / int(dnm), 2) if int(dnm) else None
    return {"duration": round(float(d.get("format", {}).get("duration", 0) or 0), 2),
            "has_video": bool(v), "has_audio": bool(a),
            "width": v.get("width") if v else None, "height": v.get("height") if v else None,
            "fps": fps}


def transcribe(path, out_dir, lang="auto"):
    """回傳 (純文字, 錯誤訊息)。"""
    if not os.path.exists(MODEL):
        return "", f"找不到 whisper 模型 {MODEL}（安裝：{INSTALL_HINT}）"
    if not os.path.exists(_bin("whisper-cli")):
        return "", f"這台電腦沒裝 whisper-cli，沒有逐字稿（安裝：{INSTALL_HINT}）"
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "a.wav")
        r = subprocess.run([_bin("ffmpeg"), "-y", "-v", "error", "-i", path, "-vn",
                            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return "", f"抽音軌失敗：{r.stderr[:200]}"
        base = os.path.join(out_dir, "transcript")
        # --prompt 用繁體開頭，whisper 輸出中文時會跟著用繁體
        r = subprocess.run([_bin("whisper-cli"), "-m", MODEL, "-f", wav, "-l", lang,
                            "--prompt", "以下是繁體中文的逐字稿。",
                            "-otxt", "-osrt", "-of", base, "-np"],
                           capture_output=True, text=True, timeout=WHISPER_TIMEOUT)
        if r.returncode != 0:
            return "", f"whisper 失敗 rc={r.returncode}：{r.stderr[-300:]}"
    txt = open(base + ".txt", encoding="utf-8", errors="ignore").read().strip()
    return txt, ""


def extract_frames(path, out_dir, duration):
    fdir = os.path.join(out_dir, "frames")
    os.makedirs(fdir, exist_ok=True)
    # 先用場景偵測抓換鏡頭的畫面，showinfo 印出時間點
    r = subprocess.run([_bin("ffmpeg"), "-v", "info", "-i", path, "-an",
                        "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',scale=960:-2,showinfo",
                        "-fps_mode", "vfr", "-frames:v", str(MAX_FRAMES), "-q:v", "4",
                        os.path.join(fdir, "scene_%02d.jpg")],
                       capture_output=True, text=True, timeout=900)
    times = [float(t) for t in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    frames = sorted(f for f in os.listdir(fdir) if f.endswith(".jpg"))
    out = [{"file": f"frames/{f}", "t": round(times[i], 1) if i < len(times) else None}
           for i, f in enumerate(frames)]
    # 換鏡頭太少（講課錄影常見）→ 等距補齊，確保至少有開頭到結尾的樣本
    need = min(MAX_FRAMES, max(4, int(duration // 60) + 1)) - len(out)
    if need > 0 and duration > 0:
        for k in range(need):
            t = duration * (k + 0.5) / need
            name = f"even_{k:02d}.jpg"
            subprocess.run([_bin("ffmpeg"), "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", path,
                            "-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "4",
                            os.path.join(fdir, name)], capture_output=True, timeout=120)
            if os.path.exists(os.path.join(fdir, name)):
                out.append({"file": f"frames/{name}", "t": round(t, 1)})
    return sorted(out, key=lambda x: (x["t"] is None, x["t"] or 0))


def _fmt(sec):
    sec = int(sec or 0)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def digest(path, force=False, frames=True):
    """處理一個檔案，回傳 (輸出資料夾, meta dict)。"""
    st = os.stat(path)
    stem = re.sub(r"[^\w一-鿿.-]+", "_", os.path.splitext(os.path.basename(path))[0])
    out_dir = os.path.join(DIGEST, stem)
    meta_p = os.path.join(out_dir, "meta.json")
    sig = f"{st.st_size}:{int(st.st_mtime)}"
    if not force and os.path.exists(meta_p):
        meta = json.load(open(meta_p, encoding="utf-8"))
        # missing：當時缺 ffmpeg 的結果不算數，補裝後要重做
        if meta.get("sig") == sig and not meta.get("missing") and \
                (meta.get("frames") or not frames or not meta.get("has_video")):
            return out_dir, meta
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    miss = [n for n in missing_tools() if n in ("ffmpeg", "ffprobe")]
    if miss:
        # 沒有 ffmpeg 什麼都做不了；照樣寫 INDEX.md，讓 agent 能如實告訴主人缺什麼
        meta = {"duration": 0, "has_video": False, "has_audio": False,
                "width": None, "height": None, "fps": None,
                "source": os.path.abspath(path), "sig": sig, "frames": [], "missing": miss,
                "errors": [f"這台電腦沒裝 {'、'.join(miss)}，無法處理影音（安裝：{INSTALL_HINT}）"]}
        json.dump(meta, open(meta_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        write_index(out_dir, meta)
        return out_dir, meta
    meta = probe(path)
    meta.update({"source": os.path.abspath(path), "sig": sig, "frames": [], "errors": []})
    if meta["has_audio"]:
        # 缺模型或 whisper-cli 的結果不能進快取，否則補裝後同一支影片永遠沒有逐字稿
        skipped = [n for n, bad in (("whisper 模型", not os.path.exists(MODEL)),
                                    ("whisper-cli", not os.path.exists(_bin("whisper-cli")))) if bad]
        if skipped:
            meta["missing"] = skipped
        txt, err = transcribe(path, out_dir)
        meta["transcript_chars"] = len(txt)
        if err:
            meta["errors"].append(err)
    if frames and meta["has_video"]:
        meta["frames"] = extract_frames(path, out_dir, meta["duration"])
    json.dump(meta, open(meta_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    write_index(out_dir, meta)
    return out_dir, meta


def write_index(out_dir, meta):
    lines = [f"# {os.path.basename(meta['source'])}", "",
             f"- 長度：{_fmt(meta['duration'])}（{meta['duration']} 秒）"]
    if meta["has_video"]:
        lines.append(f"- 畫面：{meta['width']}×{meta['height']}，{meta['fps']} fps")
    lines.append(f"- 音軌：{'有' if meta['has_audio'] else '無'}")
    for e in meta["errors"]:
        lines.append(f"- ⚠️ {e}")
    if meta["frames"]:
        lines += ["", "## 關鍵畫格（用 Read 開 jpg 看畫面）"]
        lines += [f"- {_fmt(f['t']) if f['t'] is not None else '??:??'}　{f['file']}"
                  for f in meta["frames"]]
    tp = os.path.join(out_dir, "transcript.txt")
    if os.path.exists(tp):
        lines += ["", "## 逐字稿（含時間碼版本見 transcript.srt）", "",
                  open(tp, encoding="utf-8").read().strip()]
    open(os.path.join(out_dir, "INDEX.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


def read_media(p):
    """給 read_doc.py 用：回傳可讀的純文字摘要。"""
    out_dir, _ = digest(p)
    return open(os.path.join(out_dir, "INDEX.md"), encoding="utf-8").read().strip() + \
        f"\n\n（產出資料夾：{out_dir}）"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    for p in args:
        if not os.path.exists(p) and os.path.exists(os.path.join(INCOMING, p)):
            p = os.path.join(INCOMING, p)
        if not os.path.exists(p):
            print(f"[找不到] {p}")
            continue
        out_dir, _ = digest(p, force="--force" in sys.argv, frames="--no-frames" not in sys.argv)
        print(open(os.path.join(out_dir, "INDEX.md"), encoding="utf-8").read())
        print(f"→ {out_dir}")


if __name__ == "__main__":
    main()
