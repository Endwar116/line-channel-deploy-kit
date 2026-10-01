# -*- coding: utf-8 -*-
"""bridge 接上 schedule_check：約時間的訊息，把「那個時段有沒有安排」交給值台（2026-09-30）。"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import line_bridge as lb  # noqa: E402
    IMPORT_ERR = None
except (SystemExit, OSError) as e:
    lb, IMPORT_ERR = None, f"{type(e).__name__}: {e}"

OWNER = "Uowner000000000000000000000000000"
BUSY = {"generated_at": "2026-09-30T00:00:00+08:00",
        "days": {"2026-10-06": [["15:30", "16:30"], ["18:30", "20:15"], ["20:20", "22:05"]]}}


@unittest.skipIf(IMPORT_ERR is not None,
                 "line_bridge 尚未可載入（填完 config/secrets/line_secrets.env 再跑本測試）")
class BridgeScheduleWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        busy = os.path.join(self.tmp, "busy.json")
        json.dump(BUSY, open(busy, "w"))
        self.prompts = []
        for name, value in (("BUSY_INDEX", busy), ("LOG_FILE", os.path.join(self.tmp, "t.log"))):
            p = mock.patch.object(lb, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(lb.schedule_check, "today_tw", lambda: date(2026, 9, 30))
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def test_booking_message_gets_busy_note(self):
        n = lb.schedule_note("下週二晚上七點可以碰面嗎？", [])
        self.assertIn("已有安排", n)

    def test_request_in_recent_context_counts(self):
        # 群組裡約時間的話常在前一則，@值台 的那則只寫「可以嗎」
        n = lb.schedule_note("@值台 可以嗎", ["[成員] 下週二晚上七點碰面？"])
        self.assertIn("已有安排", n)

    def test_bot_own_reply_in_context_does_not_trigger(self):
        # 2026-09-30 實故障：值台前一則回「這週空檔很少，今天已滿。週四、週五上午看起來有一些」，
        # 之後主人在私訊打打卡規則的工作筆記，也被附上行程查詢
        ctx = ["[昱捷助理] 【昱捷助理】這週空檔很少，今天已滿。\n\n週四、週五上午看起來有空，要約可以先排那兩天"]
        self.assertEqual(lb.schedule_note("超過10分鐘不能補打卡\n超過第三次扣全勤", ctx), "")

    def test_current_message_must_carry_date_or_intent(self):
        ctx = ["[成員] 下週二晚上七點碰面？"]
        self.assertEqual(lb.schedule_note("好喔收到", ctx), "")

    def test_plain_chat_gets_nothing(self):
        self.assertEqual(lb.schedule_note("今天天氣不錯", []), "")

    def test_missing_index_gets_nothing(self):
        with mock.patch.object(lb, "BUSY_INDEX", os.path.join(self.tmp, "none.json")):
            self.assertEqual(lb.schedule_note("下週二晚上七點可以碰面嗎", []), "")

    def test_note_reaches_the_agent_prompt(self):
        captured = []
        patches = {"owner_ids": lambda: {OWNER}, "send_reply": lambda *a, **k: None,
                   "start_loading": lambda *a, **k: None, "take_pending_relay": lambda ch: "",
                   "take_unread": lambda *a, **k: [], "log_history": lambda *a, **k: None,
                   "ask_claude": lambda prompt, *a, **k: captured.append(prompt) or "好"}
        for name, value in patches.items():
            p = mock.patch.object(lb, name, value)
            p.start()
            self.addCleanup(p.stop)
        ev = {"type": "message", "replyToken": "rt", "webhookEventId": "w1",
              "source": {"type": "user", "userId": OWNER},
              "message": {"type": "text", "id": "t1", "text": "下週二晚上七點可以碰面嗎？"}}
        lb.handle_event(ev)
        self.assertEqual(len(captured), 1, "值台沒有被呼叫")
        self.assertIn("【行程查詢·系統】", captured[0])
        self.assertIn("已有安排", captured[0])


if __name__ == "__main__":
    unittest.main()
