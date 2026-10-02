# -*- coding: utf-8 -*-
"""說話者顯示名：沒登記的成員改用 LINE 顯示名稱，不再只給 UID 代號（2026-10-03 主人交辦）。

背景：主人看到日曆通知「與成員Ud5293 約定會面…」，要求改用 LINE 顯示名稱。
LINE 名稱是對方自己取的暱稱，不等於核實過的身分——所以保留「身分未登記，不要假設他是誰」。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import line_bridge as lb  # noqa: E402
    IMPORT_ERR = None
except (SystemExit, OSError) as e:
    lb, IMPORT_ERR = None, f"{type(e).__name__}: {e}"

UID = "Ud5293aaaaaaaaaaaaaaaaaaaaaaaaaaa"
GROUP = "Cgroup000000000000000000000000000"


@unittest.skipIf(IMPORT_ERR is not None,
                 "line_bridge 尚未可載入（填完 config/secrets/line_secrets.env 再跑本測試）")
class DisplayName(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.alias = os.path.join(self.tmp, "alias.json")
        json.dump({"Uknown": "何玲玲（高世貿）"}, open(self.alias, "w", encoding="utf-8"), ensure_ascii=False)
        self.calls = []
        for name, value in (("MEMBER_ALIAS", self.alias),
                            ("LINE_NAMES", os.path.join(self.tmp, "line_names.json")),
                            ("LOG_FILE", os.path.join(self.tmp, "t.log")),
                            ("_fetch_line_name", lambda uid, ctype, cid: self.calls.append(uid) or "王小明")):
            p = mock.patch.object(lb, name, value)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def test_alias_wins(self):
        self.assertEqual(lb.display_name("Uknown", False, "group", GROUP), "何玲玲（高世貿）")
        self.assertEqual(self.calls, [])

    def test_unregistered_member_gets_line_name_with_caution(self):
        n = lb.display_name(UID, False, "group", GROUP)
        self.assertTrue(n.startswith("王小明"), n)
        self.assertIn("身分未登記", n)
        self.assertNotIn(UID[:6], n)

    def test_line_name_is_cached(self):
        lb.display_name(UID, False, "group", GROUP)
        lb.display_name(UID, False, "group", GROUP)
        self.assertEqual(self.calls, [UID])

    def test_lookup_failure_falls_back_to_code(self):
        with mock.patch.object(lb, "_fetch_line_name", lambda *a: None):
            n = lb.display_name(UID, False, "group", GROUP)
        self.assertIn("成員Ud5293", n)

    def test_owner_is_owner(self):
        self.assertEqual(lb.display_name(UID, True, "group", GROUP), lb.OWNER_NAME)


if __name__ == "__main__":
    unittest.main()
