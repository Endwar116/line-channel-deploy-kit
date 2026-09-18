# -*- coding: utf-8 -*-
"""claude_failure：把 `claude -p` 的失敗分類成值台講得出口的話。

背景（2026-09-10 → 09-13 實故障）：訂閱額度用完時 CLI 以 rc=1 結束、stderr 空白，
原因只寫在 stdout JSON 的 result 欄（"You've hit your limit · resets …"）。
bridge 只記 stderr，所以 log 上看不出來，LINE 上只回「本體呼叫失敗」。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_failure import classify_failure, is_limit_text, GENERIC_REPLY  # noqa: E402

LIMIT_TEXT = "You've hit your limit · resets Sep 13 at 3pm (Asia/Taipei)"


class LimitDetection(unittest.TestCase):
    def test_limit_text_is_recognised(self):
        self.assertTrue(is_limit_text(LIMIT_TEXT))

    def test_normal_reply_is_not_a_limit(self):
        self.assertFalse(is_limit_text("好，我記下來了"))

    def test_empty_text_is_not_a_limit(self):
        self.assertFalse(is_limit_text(""))


class ClassifyFailure(unittest.TestCase):
    def test_limit_failure_is_kind_limit(self):
        kind, _ = classify_failure(1, LIMIT_TEXT, "")
        self.assertEqual(kind, "limit")

    def test_limit_reply_mentions_quota_and_reset_time(self):
        _, reply = classify_failure(1, LIMIT_TEXT, "")
        self.assertIn("額度", reply)
        self.assertIn("Sep 13 at 3pm", reply)

    def test_limit_reply_fits_line_six_line_rule(self):
        _, reply = classify_failure(1, LIMIT_TEXT, "")
        self.assertLessEqual(len(reply.strip().splitlines()), 6)

    def test_limit_reply_uses_the_deploy_owner_name(self):
        """主人名要由呼叫端傳入——kit 是要出貨給客戶的，不能寫死任何一個人的名字。"""
        _, reply = classify_failure(1, LIMIT_TEXT, "", owner="小明")
        self.assertIn("小明", reply)

    def test_limit_reply_has_no_hardcoded_person_name(self):
        _, reply = classify_failure(1, LIMIT_TEXT, "")
        self.assertNotIn("昱捷", reply)
        self.assertIn("主人", reply)

    def test_is_error_with_zero_returncode_is_still_limit(self):
        kind, _ = classify_failure(0, LIMIT_TEXT, "", is_error=True)
        self.assertEqual(kind, "limit")

    def test_unknown_failure_keeps_generic_reply(self):
        kind, reply = classify_failure(1, "", "")
        self.assertEqual(kind, "unknown")
        self.assertEqual(reply, GENERIC_REPLY)

    def test_unknown_failure_with_other_text_is_not_limit(self):
        kind, reply = classify_failure(1, "Error: something else broke", "")
        self.assertEqual(kind, "unknown")
        self.assertEqual(reply, GENERIC_REPLY)


if __name__ == "__main__":
    unittest.main()
