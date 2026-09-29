#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docx_out.py — 任務要求 Word 時，把結果存成 .docx 放進指定資料夾（v1.21，2026-09-30 新增）

LINE 機器人傳不了 Word 檔，本體（agent）又是唯讀的，所以由 task_runner（Python）在 agent
回完之後把結果做成 .docx。主人決定不開下載連結、直接存進指定資料夾：
kit_config.json 的 "output_dir"（可用 ~），沒設就存 <安裝目錄>/output/。
雲端資料夾在排程環境可能沒有寫入權限（macOS 對 CloudStorage 另有管制），寫不進去就退回本機並照實說。

只用標準庫（zipfile 組最小合法 docx），不需要 python-docx。
"""
import os
import re
import zipfile
from xml.sax.saxutils import escape

WORD_RE = re.compile(r"(?<![a-z])(word|docx)(?![a-z])", re.I)

_CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                  '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                  '<Default Extension="xml" ContentType="application/xml"/>'
                  '<Override PartName="/word/document.xml" '
                  'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                  '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" '
         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
         'Target="word/document.xml"/></Relationships>')
_FONT = '<w:rFonts w:ascii="PingFang TC" w:hAnsi="PingFang TC" w:eastAsia="PingFang TC"/>'


def wants_word(text):
    """任務有沒有要 Word。word／docx 前後不能緊接英文字母（「password」不算）。"""
    return bool(WORD_RE.search(text or ""))


def _para(line):
    heading = re.match(r"^\s*#{1,6}\s*(.*)$", line)
    if heading:
        line = heading.group(1)
    if re.fullmatch(r"\s*([-*_])\1{2,}\s*", line):       # 分隔線 --- *** ___
        return "<w:p/>"
    line = re.sub(r"^\s*>\s?", "", line)                    # 引用 >
    line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)            # 粗體
    line = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", line)   # 斜體（條列的「* 」不動）
    line = line.replace("`", "")
    rpr = f"<w:rPr>{_FONT}" + ("<w:b/><w:sz w:val=\"32\"/>" if heading else "") + "</w:rPr>"
    if not line.strip():
        return "<w:p/>"
    return f'<w:p><w:r>{rpr}<w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'


def to_docx(text, path):
    body = "".join(_para(l) for l in (text or "").splitlines())
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}<w:sectPr/></w:body></w:document>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", doc)


def _slug(task_text):
    t = re.sub(r"https?://\S+", " ", task_text or "")
    t = re.sub(r"^\s*任務[:：]?", "", t)
    t = re.sub(r"[\\/:*?\"<>|\s，。、！？「」（）()]+", "_", t).strip("_")
    return t[:20] or "輸出"


def save_output(text, task_text, out_dir, now, fallback_dir=None):
    """存成 .docx，回 (路徑, 是否退回本機)。"""
    name = f"{now.strftime('%Y%m%d_%H%M')}_{_slug(task_text)}.docx"
    for d, fell_back in ((out_dir, False), (fallback_dir, True)):
        if not d:
            continue
        try:
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, name)
            to_docx(text, path)
            return path, fell_back
        except OSError:
            continue
    raise OSError("輸出資料夾與備用資料夾都寫不進去")
