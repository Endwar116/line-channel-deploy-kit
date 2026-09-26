# -*- coding: utf-8 -*-
"""task_runner：系統說明由部署者提供；安全邊界寫死在程式裡。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import task_runner as tr  # noqa: E402

OWNER_WORDS = ("ownerkit", "主人", "owner", "example", "supabase", "n8n")


class Brief(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = tr.BRIEF

    def tearDown(self):
        tr.BRIEF = self.orig
        shutil.rmtree(self.tmp)

    def test_default_brief_has_no_owner_specifics(self):
        low = tr.DEFAULT_BRIEF.lower()
        for w in OWNER_WORDS:
            self.assertNotIn(w, low)

    def test_missing_file_falls_back_to_default(self):
        tr.BRIEF = os.path.join(self.tmp, "none.md")
        self.assertEqual(tr.load_brief(), tr.DEFAULT_BRIEF)

    def test_empty_file_falls_back_to_default(self):
        tr.BRIEF = os.path.join(self.tmp, "empty.md")
        open(tr.BRIEF, "w").write("  \n")
        self.assertEqual(tr.load_brief(), tr.DEFAULT_BRIEF)

    def test_template_comment_is_not_sent_to_agent(self):
        # 安裝器放的範本開頭有給部署者看的註解，不該進 prompt
        tmpl = os.path.join(os.path.dirname(os.path.dirname(tr.__file__)), "templates", "system_brief.md.tmpl")
        tr.BRIEF = os.path.join(self.tmp, "b.md")
        shutil.copy(tmpl, tr.BRIEF)
        self.assertNotIn("<!--", tr.load_brief())
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
        low = open(tr.__file__, encoding="utf-8").read().lower()
        self.assertEqual([w for w in OWNER_WORDS if w in low], [])


class SafetyBoundary(unittest.TestCase):
    def test_tools_are_read_only(self):
        self.assertEqual(set(tr.TOOLS.split(",")), {"Read", "Glob", "Grep", "WebFetch"})

    def test_guest_and_attachment_notices_are_skipped(self):
        tasks = [{"text": "任務：a", "guest": True}, {"text": "【附件到達】x"}, {"text": "任務：b"}]
        self.assertEqual([t["text"] for _, t in tr.pick(tasks, 3)], ["任務：b"])


if __name__ == "__main__":
    unittest.main()
