# -*- coding: utf-8 -*-
"""群組附件安靜存著、@ 才讀；主人的圖片也收（2026-09-30 主人決定）。

背景：主人在群組貼賀圖被記成「拒收」；群組每份檔案都回「已收下」並排進本體佇列，
本體要讀的資料太多。私訊行為不變（收下、回覆、排佇列）。
"""
import io
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

OWNER = "Uowner000000000000000000000000000"
GROUP = "Cgroup000000000000000000000000000"


def event(mtype, where="group", uid=OWNER, **msg):
    src = {"type": "user", "userId": uid} if where == "dm" else {"type": "group", "groupId": GROUP, "userId": uid}
    m = {"type": mtype, "id": "m1", "contentProvider": {"type": "line"}}
    m.update(msg)
    return {"type": "message", "replyToken": "rt", "source": src, "message": m}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@unittest.skipIf(IMPORT_ERR is not None,
                 "line_bridge 尚未可載入（填完 config/secrets/line_secrets.env 再跑本測試）")
class GroupSilence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replies = []
        for name, value in (
                ("LOG_FILE", os.path.join(self.tmp, "t.log")),
                ("MEDIA_INCOMING", os.path.join(self.tmp, "incoming")),
                ("PENDING_RELAY", os.path.join(self.tmp, "relay.jsonl")),
                ("TASK_QUEUE", os.path.join(self.tmp, "queue.jsonl")),
                ("ATTACH_INDEX", os.path.join(self.tmp, "attachments.jsonl")),
                ("S_TIER_ATTACH_OK", set()), ("ATTACH_OPEN", set()), ("ATTACH_OPEN_ALL_FOR_OWNER", True),
                ("send_reply", lambda tok, text: self.replies.append(text)),
                ("owner_ids", lambda: {OWNER}),
                ("load_secrets", lambda: {"LINE_CHANNEL_ACCESS_TOKEN": "t"}),
                ("_video_status", lambda mid, tok: "succeeded"),
                ("_video_stream", lambda mid, tok: _Resp(b"data"))):
            p = mock.patch.object(lb, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(lb.urllib.request, "urlopen", lambda *a, **k: _Resp(b"filedata"))
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

    def saved(self):
        d = os.path.join(self.tmp, "incoming")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_owner_image_in_dm_is_saved_and_named(self):
        lb.handle_event(event("image", where="dm"))
        self.assertEqual(len(self.saved()), 1)
        self.assertTrue(self.saved()[0].startswith("圖片_") and self.saved()[0].endswith(".jpg"))
        self.assertEqual(len(self.replies), 1)
        self.assertIn(os.path.splitext(self.saved()[0])[0], self.replies[0])
        self.assertEqual(len(self.rows("queue.jsonl")), 1)
        self.assertEqual(len(self.rows("attachments.jsonl")), 1)

    def assert_silent_but_indexed(self):
        self.assertEqual(len(self.saved()), 1)
        self.assertEqual(self.replies, [])
        self.assertEqual(self.rows("queue.jsonl"), [])
        self.assertEqual(self.rows("relay.jsonl"), [])
        idx = self.rows("attachments.jsonl")
        self.assertEqual(len(idx), 1)
        self.assertEqual(idx[0]["channel"], f"group:{GROUP}")
        self.assertTrue(os.path.exists(idx[0]["path"]))

    def test_owner_image_in_group_is_silent(self):
        lb.handle_event(event("image"))
        self.assert_silent_but_indexed()

    def test_owner_file_in_group_is_silent(self):
        lb.handle_event(event("file", fileName="JOJO_準備手冊_V22.pdf"))
        self.assert_silent_but_indexed()

    def test_owner_video_in_group_is_silent(self):
        lb.handle_event(event("video"))
        self.assert_silent_but_indexed()


if __name__ == "__main__":
    unittest.main()
