# -*- coding: utf-8 -*-
"""line_video：LINE「影片」訊息的收檔邏輯（2026-09-28 新增）。

網路與時間都由呼叫端注入，這裡不打真的 LINE API。
"""
import io
import os
import shutil
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import line_video as lv  # noqa: E402

NOW = datetime(2026, 9, 28, 15, 30, 12, tzinfo=timezone(timedelta(hours=8)))
LINE_MSG = {"type": "video", "id": "m1", "contentProvider": {"type": "line"}}


class Naming(unittest.TestCase):
    def test_save_name_is_readable_timestamp(self):
        self.assertEqual(lv.save_name(NOW), "影片_20260928_153012.mp4")

    def test_stem_is_long_enough_for_task_matching(self):
        # task_runner 點名附件要主檔名 > 6 字
        self.assertGreater(len(os.path.splitext(lv.save_name(NOW))[0]), 6)


class WaitReady(unittest.TestCase):
    def test_polls_until_succeeded(self):
        seq = iter(["processing", "processing", "succeeded"])
        slept = []
        self.assertEqual(lv.wait_ready(lambda: next(seq), slept.append, timeout=60, interval=3), "succeeded")
        self.assertEqual(slept, [3, 3])

    def test_failed_stops_immediately(self):
        self.assertEqual(lv.wait_ready(lambda: "failed", lambda s: None), "failed")

    def test_gives_up_after_timeout(self):
        slept = []
        self.assertEqual(lv.wait_ready(lambda: "processing", slept.append, timeout=9, interval=3), "timeout")
        self.assertEqual(sum(slept), 9)


class Receive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        for root, dirs, files in os.walk(self.tmp):
            for f in files:
                os.chmod(os.path.join(root, f), 0o644)
        shutil.rmtree(self.tmp)

    def receive(self, data=b"x" * 10, msg=LINE_MSG, status="succeeded", cap=lv.VIDEO_MAX_BYTES):
        return lv.receive(msg, self.tmp, NOW, get_status=lambda: status,
                          open_stream=lambda: io.BytesIO(data), sleep=lambda s: None, cap=cap)

    def test_saves_readonly_file(self):
        path, size = self.receive(b"abc")
        self.assertEqual(os.path.basename(path), "影片_20260928_153012.mp4")
        self.assertEqual(open(path, "rb").read(), b"abc")
        self.assertEqual(size, 3)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o444)

    def test_same_second_gets_suffix(self):
        first, _ = self.receive(b"a")
        second, _ = self.receive(b"b")
        self.assertNotEqual(first, second)
        self.assertEqual(os.path.basename(second), "影片_20260928_153012_2.mp4")

    def test_over_cap_is_rejected_and_leaves_nothing(self):
        with self.assertRaises(lv.VideoRejected) as cm:
            self.receive(b"x" * 11, cap=10)
        self.assertIn("MB", str(cm.exception))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_external_video_is_rejected(self):
        msg = dict(LINE_MSG, contentProvider={"type": "external", "originalContentUrl": "https://x/y.mp4"})
        with self.assertRaises(lv.VideoRejected):
            self.receive(msg=msg)

    def test_transcoding_failed_is_rejected(self):
        with self.assertRaises(lv.VideoRejected):
            self.receive(status="failed")

    def test_broken_download_leaves_nothing(self):
        class Boom(io.BytesIO):
            def read(self, n=-1):
                raise OSError("connection reset")
        with self.assertRaises(OSError):
            lv.receive(LINE_MSG, self.tmp, NOW, get_status=lambda: "succeeded",
                       open_stream=lambda: Boom(), sleep=lambda s: None)
        self.assertEqual(os.listdir(self.tmp), [])


if __name__ == "__main__":
    unittest.main()
