# -*- coding: utf-8 -*-
"""bridge 接上 line_video：LINE「影片」訊息從進來到落盤、排佇列、回報的整條路（2026-09-28）。

不打 LINE API：轉檔狀態與下載串流由 _video_status／_video_stream 提供，測試時換掉。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 跟 test_bridge_limit_wiring 一樣：未設定憑證＝skip，真有錯仍要炸開
try:
    import line_bridge as lb  # noqa: E402
    IMPORT_ERR = None
except (SystemExit, OSError) as e:
    lb, IMPORT_ERR = None, f"{type(e).__name__}: {e}"

OWNER = "Uowner000000000000000000000000000"


def video_event(uid=OWNER, src_type="user", extra_src=None, mtype="video"):
    src = {"type": src_type, "userId": uid}
    src.update(extra_src or {})
    return {"type": "message", "replyToken": "rt", "source": src,
            "message": {"type": mtype, "id": "m1", "contentProvider": {"type": "line"}}}


@unittest.skipIf(IMPORT_ERR is not None,
                 "line_bridge 尚未可載入（填完 config/secrets/line_secrets.env 再跑本測試）")
class BridgeVideoWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replies = []
        patches = [
            ("LOG_FILE", os.path.join(self.tmp, "test.log")),
            ("MEDIA_INCOMING", os.path.join(self.tmp, "incoming")),
            ("PENDING_RELAY", os.path.join(self.tmp, "relay.jsonl")),
            ("TASK_QUEUE", os.path.join(self.tmp, "queue.jsonl")),
            ("S_TIER_ATTACH_OK", set()), ("ATTACH_OPEN", set()),
            ("ATTACH_OPEN_ALL_FOR_OWNER", True),
            ("send_reply", lambda tok, text: self.replies.append(text)),
            ("owner_ids", lambda: {OWNER}),
            ("load_secrets", lambda: {"LINE_CHANNEL_ACCESS_TOKEN": "t"}),
            ("_video_status", lambda mid, tok: "succeeded"),
            ("_video_stream", lambda mid, tok: io.BytesIO(b"fake-mp4")),
        ]
        for name, value in patches:
            p = mock.patch.object(lb, name, value)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        for root, _, files in os.walk(self.tmp):
            for f in files:
                os.chmod(os.path.join(root, f), 0o644)
        import shutil
        shutil.rmtree(self.tmp)

    def rows(self, name):
        p = os.path.join(self.tmp, name)
        return [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []

    def test_owner_video_is_saved_queued_and_reported(self):
        lb.handle_event(video_event())
        saved = os.listdir(os.path.join(self.tmp, "incoming"))
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].startswith("影片_") and saved[0].endswith(".mp4"))
        self.assertEqual(len(self.replies), 1)                 # 先回「收到，下載中」
        self.assertIn("下載中", self.replies[0])
        q = self.rows("queue.jsonl")
        self.assertEqual(len(q), 1)
        self.assertIn("sig", q[0])                             # 驗章過得了 task_runner
        self.assertIn(saved[0], q[0]["text"])
        relay = self.rows("relay.jsonl")
        self.assertEqual(relay[0]["channel"], f"dm:{OWNER}")
        self.assertIn(os.path.splitext(saved[0])[0], relay[0]["text"])   # 告訴主人怎麼點名

    def test_oversized_video_is_reported_not_queued(self):
        with mock.patch.object(lb, "VIDEO_MAX_BYTES", 3):
            lb.handle_event(video_event())
        self.assertEqual(self.rows("queue.jsonl"), [])
        self.assertIn("上限", self.rows("relay.jsonl")[0]["text"])

    def test_download_error_is_reported(self):
        def boom(mid, tok):
            raise OSError("reset")
        with mock.patch.object(lb, "_video_stream", boom):
            lb.handle_event(video_event())
        self.assertEqual(self.rows("queue.jsonl"), [])
        self.assertIn("下載失敗", self.rows("relay.jsonl")[0]["text"])

    def test_owner_voice_message_is_saved_and_named_in_reply(self):
        # 2026-09-29 實故障：主人私訊的語音被路由擋掉（只放行 S 級通道），三段語音無聲消失
        lb.handle_event(video_event(mtype="audio"))
        saved = os.listdir(os.path.join(self.tmp, "incoming"))
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].startswith("語音_") and saved[0].endswith(".m4a"), saved)
        self.assertEqual(len(self.replies), 1)
        self.assertIn(os.path.splitext(saved[0])[0], self.replies[0])   # 回覆就附上檔名
        q = self.rows("queue.jsonl")
        self.assertEqual(len(q), 1)
        self.assertIn("sig", q[0])

    def test_ignored_media_is_logged_not_silent(self):
        lb.handle_event(video_event(uid="Ustranger0000000000000000000000000", mtype="audio"))
        self.assertIn("MEDIA_IGNORED", open(os.path.join(self.tmp, "test.log"), encoding="utf-8").read())

    def test_stranger_video_is_ignored(self):
        lb.handle_event(video_event(uid="Ustranger0000000000000000000000000"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "incoming")))
        self.assertEqual(self.replies, [])


if __name__ == "__main__":
    unittest.main()
