# -*- coding: utf-8 -*-
"""video_digest：客戶機器沒裝 ffmpeg／whisper 模型時，傳影片進來不能讓任務執行 crash。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import video_digest as vd  # noqa: E402


class MissingDependencies(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = (vd._bin, vd.DIGEST)
        vd._bin = lambda name: os.path.join(self.tmp, "no-such-bin", name)
        vd.DIGEST = os.path.join(self.tmp, "digest")
        self.video = os.path.join(self.tmp, "clip.mp4")
        open(self.video, "wb").write(b"\x00" * 128)

    def tearDown(self):
        vd._bin, vd.DIGEST = self.orig
        shutil.rmtree(self.tmp)

    def test_missing_tools_lists_ffmpeg(self):
        self.assertIn("ffmpeg", vd.missing_tools())

    def test_missing_ffmpeg_does_not_crash(self):
        out_dir, meta = vd.digest(self.video)
        self.assertTrue(any("ffmpeg" in e for e in meta["errors"]))
        index = open(os.path.join(out_dir, "INDEX.md"), encoding="utf-8").read()
        self.assertIn("brew install ffmpeg", index)

    def test_missing_tools_result_is_not_cached(self):
        # 裝好 ffmpeg 之後，同一支影片要重新處理，不能永遠回「沒裝」
        vd.digest(self.video)
        calls = []
        vd._bin = lambda name: calls.append(name) or os.path.join(self.tmp, "no-such-bin", name)
        vd.digest(self.video)
        self.assertIn("ffmpeg", calls)

    def test_read_media_returns_text(self):
        self.assertIn("ffmpeg", vd.read_media(self.video))


class WhisperMissing(unittest.TestCase):
    """有 ffmpeg，但缺 whisper-cli 或模型——最常見的半安裝狀態。"""

    def setUp(self):
        import shutil as sh
        import subprocess
        self.ffmpeg = sh.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
        if not os.path.exists(self.ffmpeg):
            self.skipTest("本機沒有 ffmpeg")
        self.tmp = tempfile.mkdtemp()
        self.orig = (vd._bin, vd.DIGEST, vd.MODEL)
        vd.DIGEST = os.path.join(self.tmp, "digest")
        vd.MODEL = os.path.join(self.tmp, "model.bin")
        self.video = os.path.join(self.tmp, "clip.mp4")
        subprocess.run([self.ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x48:d=1",
                        "-f", "lavfi", "-i", "sine=d=1", "-shortest", "-y", self.video], check=True)

    def tearDown(self):
        vd._bin, vd.DIGEST, vd.MODEL = self.orig
        shutil.rmtree(self.tmp)

    def test_missing_whisper_cli_does_not_crash(self):
        open(vd.MODEL, "wb").close()
        real = self.orig[0]
        vd._bin = lambda n: os.path.join(self.tmp, "nope", n) if n == "whisper-cli" else real(n)
        out_dir, meta = vd.digest(self.video)
        self.assertTrue(any("whisper-cli" in e for e in meta["errors"]), meta["errors"])
        self.assertTrue(os.path.exists(os.path.join(out_dir, "INDEX.md")))

    def test_model_installed_later_is_picked_up(self):
        _, meta = vd.digest(self.video)
        self.assertTrue(any("找不到 whisper 模型" in e for e in meta["errors"]))
        open(vd.MODEL, "wb").close()          # 補裝模型（假檔，whisper 會失敗，但不能再回「找不到模型」）
        _, meta = vd.digest(self.video)
        self.assertFalse(any("找不到 whisper 模型" in e for e in meta["errors"]), meta["errors"])


class Paths(unittest.TestCase):
    def test_no_owner_paths(self):
        for mod in ("video_digest.py", "read_doc.py"):
            with open(os.path.join(os.path.dirname(vd.__file__), mod), encoding="utf-8") as f:
                src = f.read()
            from tests.leak_rules import leaks
            self.assertEqual(leaks(src), [])


if __name__ == "__main__":
    unittest.main()
