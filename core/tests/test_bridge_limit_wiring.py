# -*- coding: utf-8 -*-
"""整合測試：額度用完時 ask_claude 要回額度話術，不是通用失敗話術。

證明 line_bridge 有把 claude_failure.classify_failure 接進失敗出口。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# line_bridge 在 import 期就跑 load_secrets()，未設定時會擋下來（fail-closed，設計如此）：
#   kit 原始碼樹 → 根本沒有 config/  → FileNotFoundError
#   剛裝好未填憑證 → 檔在但值空       → SystemExit
# 兩種都是「還沒設定」，要 skip 而不是 error——否則客戶跑 unittest 看到的是
# 「secrets 缺 LINE_CHANNEL_SECRET」的 ImportError，像 kit 壞掉，其實只是還沒設定。
# 只接這兩種：line_bridge 真有語法或邏輯錯誤時仍要炸開，否則本測試就失去意義。
try:
    import line_bridge as lb  # noqa: E402
    IMPORT_ERR = None
except (SystemExit, OSError) as e:
    lb, IMPORT_ERR = None, f"{type(e).__name__}: {e}"

LIMIT_TEXT = "You've hit your limit · resets Sep 13 at 3pm (Asia/Taipei)"


def _fake_run_limit(*a, **k):
    payload = {"type": "result", "subtype": "success", "is_error": True,
               "result": LIMIT_TEXT, "usage": {}}
    return mock.Mock(returncode=1, stdout=json.dumps(payload), stderr="")


@unittest.skipIf(IMPORT_ERR is not None,
                 "line_bridge 尚未可載入（填完 config/secrets/line_secrets.env 再跑本測試）")
class BridgeLimitWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_ask_claude_returns_limit_reply_on_quota_exhaustion(self):
        with mock.patch.object(lb.subprocess, "run", _fake_run_limit), \
             mock.patch.object(lb, "chat_dir_for", return_value=self.tmp), \
             mock.patch.object(lb, "_meter_append", lambda *a, **k: None):
            out = lb.ask_claude("在嗎？", "dm", "TESTCID")
        self.assertIn("額度", out)
        self.assertIn("Sep 13 at 3pm", out)


if __name__ == "__main__":
    unittest.main()
