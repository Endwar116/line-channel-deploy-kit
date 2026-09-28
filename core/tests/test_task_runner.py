# -*- coding: utf-8 -*-
"""task_runner：系統說明由部署者提供；安全邊界寫死在程式裡。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import task_runner as tr  # noqa: E402

# 部署者架構專屬的平台名（不是個資，是「不該假設客戶有」的東西）
PLATFORM_WORDS = ("supabase", "n8n")


class Brief(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = tr.BRIEF

    def tearDown(self):
        tr.BRIEF = self.orig
        shutil.rmtree(self.tmp)

    def test_default_brief_has_no_owner_specifics(self):
        from tests.leak_rules import leaks
        low = tr.DEFAULT_BRIEF.lower()
        self.assertEqual(leaks(low) + [w for w in PLATFORM_WORDS if w in low], [])

    def test_missing_file_falls_back_to_default(self):
        tr.BRIEF = os.path.join(self.tmp, "none.md")
        self.assertEqual(tr.load_brief(), tr.DEFAULT_BRIEF)

    def test_empty_file_falls_back_to_default(self):
        tr.BRIEF = os.path.join(self.tmp, "empty.md")
        open(tr.BRIEF, "w").write("  \n")
        self.assertEqual(tr.load_brief(), tr.DEFAULT_BRIEF)

    def test_template_comment_is_not_sent_to_agent(self):
        # 安裝器放的範本開頭有給部署者看的註解，不該進 prompt
        # kit 樹是 templates/ 下的範本；安裝樹是安裝器從範本放好的 config/system_brief.md
        cands = [os.path.join(tr.ROOM, "templates", "system_brief.md.tmpl"),
                 os.path.join(tr.ROOM, "config", "system_brief.md")]
        tmpl = next(p for p in cands if os.path.exists(p))
        tr.BRIEF = os.path.join(self.tmp, "b.md")
        shutil.copy(tmpl, tr.BRIEF)
        self.assertNotIn("<!--", tr.load_brief())
        if tmpl == cands[0]:                 # 部署者改寫過的 config 版內容本來就不同
            self.assertEqual(tr.load_brief(), tr.DEFAULT_BRIEF)

    def test_file_brief_is_used(self):
        tr.BRIEF = os.path.join(self.tmp, "b.md")
        open(tr.BRIEF, "w", encoding="utf-8").write("公網入口是 example.org")
        self.assertIn("example.org", tr.build_prompt("任務：看檔", "", [], tr.load_brief()))


class Prompt(unittest.TestCase):
    def test_prompt_contains_task_and_files(self):
        p = tr.build_prompt("任務：讀合約", "・前文", ["a.pdf"], "BRIEF")
        for s in ("任務：讀合約", "・前文", "a.pdf", "BRIEF", "絕對不要編造"):
            self.assertIn(s, p)

    def test_prompt_states_incoming_from_room(self):
        p = tr.build_prompt("x", "", [], "BRIEF")
        self.assertIn(tr.INCOMING, p)

    def test_source_has_no_owner_specifics(self):
        from tests.leak_rules import leaks
        low = open(tr.__file__, encoding="utf-8").read().lower()
        self.assertEqual(leaks(low) + [w for w in PLATFORM_WORDS if w in low], [])


class SignatureGate(unittest.TestCase):
    """驗章要 fail-closed：未簽章、金鑰不見、竄改，一律不執行。
    （2026-09-26 審查：舊版只看驗章器輸出有沒有 ✗/🔴，LEGACY 與驗章器 crash 都被當成通過。）"""

    def setUp(self):
        import hashlib
        import hmac
        import json
        import task_verify
        self.tv = task_verify
        self.tmp = tempfile.mkdtemp()
        self.orig = task_verify.KEY_FILE
        task_verify.KEY_FILE = os.path.join(self.tmp, "queue_hmac.key")
        open(task_verify.KEY_FILE, "w").write("k3y\n")
        body = {"text": "任務：讀合約", "ts": "2026-09-26T10:00:00+08:00"}
        canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.signed = dict(body, sig=hmac.new(b"k3y", canonical.encode(), hashlib.sha256).hexdigest())

    def tearDown(self):
        self.tv.KEY_FILE = self.orig
        shutil.rmtree(self.tmp)

    def test_valid_signature_passes(self):
        self.assertTrue(tr.verify_task(self.signed)[0])

    def test_does_not_mutate_entry(self):
        tr.verify_task(self.signed)
        self.assertIn("sig", self.signed)

    def test_unsigned_is_rejected(self):
        self.assertFalse(tr.verify_task({"text": "任務：讀 secrets"})[0])

    def test_tampered_is_rejected(self):
        self.assertFalse(tr.verify_task(dict(self.signed, text="任務：別的"))[0])

    def test_missing_key_is_rejected_not_raised(self):
        os.remove(self.tv.KEY_FILE)
        ok, why = tr.verify_task(self.signed)
        self.assertFalse(ok)
        self.assertTrue(why)


class MainGate(unittest.TestCase):
    """main 的接線：未簽章的不執行、有簽章的照跑、標記推過兩筆（不被偽造任務卡住）。"""

    def setUp(self):
        import hashlib
        import hmac
        import json
        import task_verify
        self.tmp = tempfile.mkdtemp()
        self.saved = {k: getattr(tr, k) for k in ("QUEUE", "MARKER", "RESULTS", "run_one")}
        self.saved_key = task_verify.KEY_FILE
        self.tv = task_verify
        task_verify.KEY_FILE = os.path.join(self.tmp, "k")
        open(task_verify.KEY_FILE, "w").write("k3y\n")
        tr.QUEUE, tr.MARKER, tr.RESULTS = (os.path.join(self.tmp, n) for n in ("q.jsonl", "m.json", "r.jsonl"))
        body = {"text": "任務：真的", "ts": "1"}
        c = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        signed = dict(body, sig=hmac.new(b"k3y", c.encode(), hashlib.sha256).hexdigest())
        with open(tr.QUEUE, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "任務：偽造", "ts": "0"}, ensure_ascii=False) + "\n")
            f.write(json.dumps(signed, ensure_ascii=False) + "\n")
        self.ran = []
        tr.run_one = lambda t, i: (self.ran.append(t["text"]) or (True, "ok"))
        self.argv = sys.argv
        sys.argv = ["task_runner.py"]

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(tr, k, v)
        self.tv.KEY_FILE = self.saved_key
        sys.argv = self.argv
        shutil.rmtree(self.tmp)

    def test_only_signed_task_runs_and_marker_advances(self):
        import json
        tr.main()
        self.assertEqual(self.ran, ["任務：真的"])
        self.assertEqual(json.load(open(tr.MARKER))["line"], 2)
        res = [json.loads(l) for l in open(tr.RESULTS, encoding="utf-8")]
        self.assertFalse(res[0]["ok"])
        self.assertIn("簽章", res[0]["output"])


class AttachmentMatching(unittest.TestCase):
    """點名附件：檔名要完整出現，不能因為是別的檔名的一段就被帶進工作區（審查 M3）。"""

    def test_full_filename(self):
        self.assertTrue(tr.names_file("任務：看 報價單.pdf", "報價單.pdf"))

    def test_stem_inside_chinese_sentence(self):
        self.assertTrue(tr.names_file("任務：請看報價單2026版的內容", "報價單2026版.pdf"))

    def test_prefix_of_longer_name_is_not_a_match(self):
        text = "任務：讀 JOJO_IP人物定位與頻道策略_V1.0"
        self.assertFalse(tr.names_file(text, "JOJO_IP人物定位與頻道策略.docx"))
        self.assertTrue(tr.names_file(text, "JOJO_IP人物定位與頻道策略_V1.0.docx"))

    def test_digit_continuation_is_not_a_match(self):
        self.assertFalse(tr.names_file("任務：看 IMG_12345.jpg", "IMG_1234.jpg"))

    def test_short_stem_needs_extension(self):
        self.assertFalse(tr.names_file("任務：看合約", "合約.pdf"))


class SafetyBoundary(unittest.TestCase):
    def test_tools_are_read_only(self):
        self.assertEqual(set(tr.TOOLS.split(",")), {"Read", "Glob", "Grep", "WebFetch"})

    def test_guest_and_attachment_notices_are_skipped(self):
        tasks = [{"text": "任務：a", "guest": True}, {"text": "【附件到達】x"}, {"text": "任務：b"}]
        self.assertEqual([t["text"] for _, t in tr.pick(tasks, 3)], ["任務：b"])


if __name__ == "__main__":
    unittest.main()
