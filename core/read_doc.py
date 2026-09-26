#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""read_doc.py — 通用文件讀取（本體側工具）

支援 LINE 附件常見的格式，讓「傳一份檔進來叫我讀」不用每次臨時處理。

  .docx / .pptx / .xlsx   標準庫（zipfile + XML），零依賴
  .pdf                    pdftotext（brew install poppler）
  .txt / .md / .csv       直接讀
  影片 / 音檔             video_digest.py：whisper 逐字稿＋關鍵畫格（首次較久，之後讀快取）
  .doc（舊版）             不支援，會明確告訴你為什麼

用法：
  python3 tools/read_doc.py <檔案>              # 印出純文字
  python3 tools/read_doc.py <檔案> --head 3000  # 只印前 N 字元
  python3 tools/read_doc.py --incoming          # 列出 media/incoming 所有檔案與可讀性
"""
import html
import os
import re
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from video_digest import MEDIA_EXT, read_media  # noqa: E402

ROOM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCOMING = os.path.join(ROOM, "media", "incoming")


def _xml_text(xml, cell_sep=" | "):
    xml = xml.replace("</w:p>", "\n").replace("</a:p>", "\n")
    xml = xml.replace("<w:br/>", "\n").replace("<w:tab/>", "\t")
    xml = xml.replace("</w:tc>", cell_sep)
    t = html.unescape(re.sub(r"<[^>]+>", "", xml))
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def read_docx(p):
    with zipfile.ZipFile(p) as z:
        return _xml_text(z.read("word/document.xml").decode("utf-8", "ignore"))


def read_pptx(p):
    out = []
    with zipfile.ZipFile(p) as z:
        slides = sorted(n for n in z.namelist()
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
        for i, n in enumerate(slides, 1):
            out.append(f"── 第 {i} 頁 ──")
            out.append(_xml_text(z.read(n).decode("utf-8", "ignore")))
    return "\n".join(out).strip()


def read_xlsx(p):
    """xlsx 的字串放在 sharedStrings.xml，儲存格只存索引，要對回去。"""
    with zipfile.ZipFile(p) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
            shared = [html.unescape(re.sub(r"<[^>]+>", "", m))
                      for m in re.findall(r"<si>(.*?)</si>", ss, re.S)]
        out = []
        sheets = sorted(n for n in z.namelist()
                        if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        for n in sheets:
            out.append(f"── {os.path.basename(n)} ──")
            xml = z.read(n).decode("utf-8", "ignore")
            for row in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S):
                cells = []
                for attrs, body in re.findall(r"<c\b([^>]*)>(.*?)</c>", row, re.S):
                    tm = re.search(r'\bt="([^"]+)"', attrs)
                    typ = tm.group(1) if tm else ""
                    if typ == "inlineStr":
                        it = re.search(r"<is>(.*?)</is>", body, re.S)
                        cells.append(html.unescape(re.sub(r"<[^>]+>", "", it.group(1))) if it else "")
                        continue
                    v = re.search(r"<v>(.*?)</v>", body, re.S)
                    if not v:
                        cells.append("")
                        continue
                    val = html.unescape(v.group(1))
                    if typ == "s":
                        try:
                            val = shared[int(val)]
                        except (ValueError, IndexError):
                            pass
                    cells.append(val)
                if any(x.strip() for x in cells):
                    out.append(" | ".join(cells))
        return "\n".join(out).strip()


def read_pdf(p):
    exe = None
    for cand in ("/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext", "pdftotext"):
        try:
            subprocess.run([cand, "-v"], capture_output=True, timeout=10)
            exe = cand
            break
        except (OSError, subprocess.SubprocessError):
            continue
    if not exe:
        return "[無法讀取] 沒有 pdftotext。安裝：brew install poppler"
    r = subprocess.run([exe, "-layout", "-enc", "UTF-8", p, "-"],
                       capture_output=True, text=True, timeout=120)
    t = (r.stdout or "").strip()
    if len(t) > 30:
        return re.sub(r"\n{3,}", "\n\n", t)
    # 沒有文字層＝掃描影像，改用 macOS Vision OCR
    ocr = run_ocr(p)
    if ocr:
        return "[本檔無文字層，以下為 OCR 辨識結果]\n\n" + ocr
    return "[讀不到文字] 沒有文字層，OCR 也沒有辨識出內容。"


OCR_BIN = os.path.join(ROOM, "tools", "bin", "ocr")


def run_ocr(path, timeout=300):
    """macOS Vision OCR（tools/bin/ocr，Swift 編譯，零第三方依賴）。"""
    if not os.path.exists(OCR_BIN):
        return ""
    try:
        r = subprocess.run([OCR_BIN, path], capture_output=True, text=True, timeout=timeout)
        return re.sub(r"\n{3,}", "\n\n", (r.stdout or "").strip())
    except Exception:
        return ""


def read_image(p):
    t = run_ocr(p)
    if t:
        return "[圖片 OCR 辨識結果]\n\n" + t
    return "[讀不到] 圖片 OCR 沒有辨識出文字，可能是純圖像或解析度不足。"


READERS = {".docx": read_docx, ".pptx": read_pptx, ".xlsx": read_xlsx, ".pdf": read_pdf,
           ".jpg": read_image, ".jpeg": read_image, ".png": read_image,
           ".heic": read_image, ".tiff": read_image, ".webp": read_image}
PLAIN = {".txt", ".md", ".csv", ".json", ".log"}
UNSUPPORTED = {
    ".doc": "舊版 Word 二進位格式，標準庫解不開。請客戶另存成 .docx。",
    ".xls": "舊版 Excel 二進位格式，同上，請另存成 .xlsx。",
    ".ppt": "舊版 PowerPoint，同上。",
    ".gif": "動圖不處理，請截圖成 png 或 jpg。",
}


def read_any(p):
    ext = os.path.splitext(p)[1].lower()
    if ext in MEDIA_EXT:
        return read_media(p)
    if ext in READERS:
        return READERS[ext](p)
    if ext in PLAIN:
        return open(p, encoding="utf-8", errors="ignore").read().strip()
    if ext in UNSUPPORTED:
        return f"[不支援 {ext}] {UNSUPPORTED[ext]}"
    return f"[未知格式 {ext}] 不確定怎麼讀，請告知這是什麼檔。"


def list_incoming():
    if not os.path.isdir(INCOMING):
        print("（media/incoming 不存在）")
        return
    files = sorted(os.listdir(INCOMING))
    if not files:
        print("（沒有檔案）")
        return
    print(f"media/incoming — {len(files)} 個檔案\n")
    for f in files:
        p = os.path.join(INCOMING, f)
        ext = os.path.splitext(f)[1].lower()
        mark = "✅ 可讀" if (ext in READERS or ext in PLAIN or ext in MEDIA_EXT) else \
               ("❌ " + UNSUPPORTED.get(ext, "未知格式")[:20] if ext in UNSUPPORTED else "⚠️ 未知")
        print(f"  {mark:<12} {os.path.getsize(p):>9,}B  {f}")


def main():
    if "--incoming" in sys.argv:
        list_incoming()
        return
    argv = sys.argv[1:]
    head = None
    if "--head" in argv:
        i = argv.index("--head")
        if i + 1 < len(argv) and argv[i + 1].isdigit():
            head = int(argv[i + 1])
            del argv[i:i + 2]          # 連同數值一起移除，否則會被當成檔名
        else:
            head = 3000
            del argv[i]
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    for p in args:
        if not os.path.isabs(p) and not os.path.exists(p):
            cand = os.path.join(INCOMING, p)
            if os.path.exists(cand):
                p = cand
        if not os.path.exists(p):
            print(f"[找不到] {p}")
            continue
        t = read_any(p)
        print(f"═══ {os.path.basename(p)}　{os.path.getsize(p):,}B　抽出 {len(t):,} 字元 ═══")
        print(t[:head] if head else t)
        print()


if __name__ == "__main__":
    main()
