# -*- coding: utf-8 -*-
"""docx_out：任務要求 Word 時，把結果存成 .docx 放進指定資料夾（2026-09-30）。
主人決定：不做下載連結，直接存進指定資料夾（線上＝Google 雲端 2024goclub／昱捷助理輸出）。"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import docx_out as dx  # noqa: E402
import read_doc  # noqa: E402

NOW = datetime(2026, 9, 30, 10, 15)


class WantsWord(unittest.TestCase):
    def test_detects(self):
        for t in ("任務：把字提出來貼成word檔", "任務：整理成 Word", "任務：輸出 docx", "做成Word檔傳上來"):
            self.assertTrue(dx.wants_word(t), t)

    def test_ignores(self):
        for t in ("任務：讀這份 PDF", "任務：password 是什麼"):
            self.assertFalse(dx.wants_word(t), t)


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    TEXT = "# 提示詞整理\n\n**第一段** 內容 <特殊&符號>\n- 項目一\n第二行"

    def test_roundtrip_with_our_reader(self):
        p = os.path.join(self.tmp, "a.docx")
        dx.to_docx(self.TEXT, p)
        got = read_doc.read_docx(p)
        for s in ("提示詞整理", "第一段 內容 <特殊&符號>", "項目一", "第二行"):
            self.assertIn(s, got)
        self.assertNotIn("**", got)
        self.assertNotIn("# ", got)

    def test_markdown_decorations_are_cleaned(self):
        # 2026-09-30 實測：agent 回覆的 ---、> 引用、*斜體* 原樣進了 Word
        p = os.path.join(self.tmp, "b.docx")
        dx.to_docx("---\n> 你是資深行銷顧問。\n*文件由系統產出*\n- 條列保留", p)
        got = read_doc.read_docx(p)
        self.assertNotIn("---", got)
        self.assertNotIn(">", got)
        self.assertNotIn("*", got)
        self.assertIn("你是資深行銷顧問。", got)
        self.assertIn("- 條列保留", got)

    def test_macos_textutil_accepts_it(self):
        if not shutil.which("textutil"):
            self.skipTest("沒有 textutil")
        p = os.path.join(self.tmp, "a.docx")
        dx.to_docx(self.TEXT, p)
        r = subprocess.run(["textutil", "-convert", "txt", "-stdout", p], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("提示詞整理", r.stdout)

    def test_save_names_file_from_task(self):
        path, fell_back = dx.save_output("內容", "任務：https://xhslink.cn/o/x 把提示詞/貼成word檔", self.tmp, NOW)
        self.assertFalse(fell_back)
        name = os.path.basename(path)
        self.assertTrue(name.startswith("20260930_1015_") and name.endswith(".docx"), name)
        self.assertNotIn("http", name)
        self.assertNotIn("/", name)

    def test_unwritable_folder_falls_back(self):
        locked = os.path.join(self.tmp, "locked")
        os.makedirs(locked)
        os.chmod(locked, 0o500)
        try:
            fb = os.path.join(self.tmp, "fallback")
            path, fell_back = dx.save_output("內容", "任務：做成 word", locked, NOW, fallback_dir=fb)
            self.assertTrue(fell_back)
            self.assertTrue(path.startswith(fb) and os.path.exists(path))
        finally:
            os.chmod(locked, 0o700)


if __name__ == "__main__":
    unittest.main()
