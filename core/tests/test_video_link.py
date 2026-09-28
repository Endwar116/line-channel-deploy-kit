# -*- coding: utf-8 -*-
"""video_link：任務裡的影片連結 → 下載成檔案（2026-09-28 新增）。

只抓公開影片（不讀瀏覽器 cookie、不登入）；yt-dlp 由呼叫端注入，這裡不連網。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import video_link as vl  # noqa: E402

FB = "https://www.facebook.com/someone/videos/1234567890"


class FindLinks(unittest.TestCase):
    def test_supported_sites_only(self):
        text = f"任務：看 {FB} 跟 https://youtu.be/abc 還有 https://example.com/x.html"
        self.assertEqual(vl.find_video_links(text), [FB, "https://youtu.be/abc"])

    def test_trailing_chinese_punctuation_is_stripped(self):
        self.assertEqual(vl.find_video_links(f"任務：看這支（{FB}）。"), [FB])

    def test_dedup_and_limit(self):
        text = " ".join([FB, FB, "https://youtu.be/a", "https://youtu.be/b"])
        self.assertEqual(vl.find_video_links(text), [FB, "https://youtu.be/a"])

    def test_subdomains_and_short_hosts(self):
        for u in ("https://m.facebook.com/watch/?v=1", "https://fb.watch/abc/", "https://www.instagram.com/reel/x/",
                  "https://www.threads.net/@a/post/b", "https://vt.tiktok.com/x/", "http://xhslink.com/a/b"):
            self.assertEqual(vl.find_video_links(u), [u], u)

    def test_lookalike_host_is_not_supported(self):
        self.assertEqual(vl.find_video_links("https://facebook.com.evil.io/v"), [])


class FakeYtDlp:
    """記錄呼叫；成功時照 -o 樣板寫出檔案並印出路徑（模仿 --print after_move:filepath）。"""

    def __init__(self, rc=0, stderr="", raise_timeout=False):
        self.calls, self.rc, self.stderr, self.raise_timeout = [], rc, stderr, raise_timeout

    def __call__(self, args, **kw):
        self.calls.append(args)
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(args, kw.get("timeout"))
        out = ""
        if self.rc == 0:
            tmpl = args[args.index("-o") + 1]
            out = tmpl.replace("%(ext)s", "mp4")
            open(out, "wb").write(b"mp4")
        return subprocess.CompletedProcess(args, self.rc, out + "\n", self.stderr)


class Fetch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fetch(self, fake, url=FB):
        return vl.fetch(url, self.tmp, run=fake, ytdlp="/bin/echo")

    def test_success_returns_file(self):
        path = self.fetch(FakeYtDlp())
        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.basename(path).startswith("連結影片_"))

    def test_second_fetch_uses_cache(self):
        fake = FakeYtDlp()
        self.assertEqual(self.fetch(fake), self.fetch(fake))
        self.assertEqual(len(fake.calls), 1)

    def test_args_are_safe_and_public_only(self):
        fake = FakeYtDlp()
        self.fetch(fake)
        a = fake.calls[0]
        self.assertEqual(a[-2:], ["--", FB])            # 網址前有 --，偽造成選項也沒用
        joined = " ".join(a)
        for must in ("--no-playlist", "--max-filesize", "duration <= 3600"):
            self.assertIn(must, joined)
        self.assertNotIn("cookies", joined)

    def rejected(self, stderr):
        with self.assertRaises(vl.LinkRejected) as cm:
            self.fetch(FakeYtDlp(rc=1, stderr=stderr))
        self.assertEqual(os.listdir(self.tmp), [])
        return str(cm.exception)

    def test_login_required(self):
        self.assertIn("登入", self.rejected("ERROR: [facebook] 123: Cannot parse data; please report... login required"))
        self.assertIn("登入", self.rejected("ERROR: This video is private"))

    def test_too_large(self):
        self.assertIn("200MB", self.rejected("File is larger than max-filesize (300.00MiB > 200.00MiB). Aborting."))

    def test_too_long(self):
        self.assertIn("60 分鐘", self.rejected("[youtube] x: video does not pass filter (duration <= 3600), skipping .."))

    def test_unsupported(self):
        self.assertIn("不支援", self.rejected("ERROR: Unsupported URL: https://www.facebook.com/x"))

    def test_other_error_is_generic_not_raw(self):
        msg = self.rejected("ERROR: something weird happened")
        self.assertIn("抓不到", msg)

    def test_timeout(self):
        with self.assertRaises(vl.LinkRejected):
            self.fetch(FakeYtDlp(raise_timeout=True))

    def test_missing_ytdlp(self):
        with self.assertRaises(vl.LinkRejected) as cm:
            vl.fetch(FB, self.tmp, run=FakeYtDlp(), ytdlp=os.path.join(self.tmp, "nope"))
        self.assertIn("brew install yt-dlp", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
