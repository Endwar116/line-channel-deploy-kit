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


class Vocabulary(unittest.TestCase):
    """專有名詞表＋簡轉繁（2026-09-29：「臼井靈氣」兩次被聽成「究竟靈氣」、逐字稿冒出簡體「推广」）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_load_vocab_skips_comments_and_blanks(self):
        p = os.path.join(self.tmp, "v.txt")
        open(p, "w", encoding="utf-8").write("# 說明\n臼井靈氣\n\n  宇宙靈氣  \n")
        self.assertEqual(vd.load_vocab(p), ["臼井靈氣", "宇宙靈氣"])

    def test_missing_vocab_file_is_empty(self):
        self.assertEqual(vd.load_vocab(os.path.join(self.tmp, "none.txt")), [])

    def test_prompt_lists_terms_after_traditional_hint(self):
        p = vd.whisper_prompt(["臼井靈氣", "宇宙靈氣"])
        self.assertTrue(p.startswith("以下是繁體中文的逐字稿"))
        self.assertIn("臼井靈氣、宇宙靈氣", p)

    def test_prompt_is_capped_without_cutting_a_term(self):
        terms = [f"詞彙{i:03d}" for i in range(200)]
        p = vd.whisper_prompt(terms)
        self.assertLessEqual(len(p), vd.MAX_PROMPT_CHARS)
        self.assertTrue(p.endswith("。"))
        self.assertIn("詞彙000", p)

    def test_correction_lines_are_not_prompt_terms(self):
        p = os.path.join(self.tmp, "v.txt")
        open(p, "w", encoding="utf-8").write("臼井靈氣\n究竟靈氣 => 臼井靈氣\n")
        self.assertEqual(vd.load_vocab(p), ["臼井靈氣"])
        self.assertEqual(vd.load_fixes(p), [("究竟靈氣", "臼井靈氣")])

    def test_clean_applies_fixes(self):
        # 9/29 實測：加了提示詞，「臼井」仍被聽成「究竟」
        self.assertEqual(vd.clean_transcript("我們常見的究竟靈氣", [("究竟靈氣", "臼井靈氣")]),
                         "我們常見的臼井靈氣")

    def test_clean_drops_known_hallucinations(self):
        # 9/29 實測：影片片尾冒出「優優獨播劇場——YoYo Television Series Exclusive」
        txt = "希望這個可以回答到它。\n優優獨播劇場——YoYo Television Series Exclusive\n"
        self.assertEqual(vd.clean_transcript(txt, []).strip(), "希望這個可以回答到它。")
        for junk in ("字幕由Amara.org社區提供", "請不吝點讚 訂閱 轉發 打賞支持明鏡與點點欄目"):
            self.assertEqual(vd.clean_transcript(junk, []).strip(), "")

    def test_clean_keeps_srt_timing_lines(self):
        srt = "1\n00:00:00,000 --> 00:00:02,000\n究竟靈氣\n\n2\n00:00:02,000 --> 00:00:04,000\n優優獨播劇場——YoYo Television Series Exclusive\n"
        out = vd.clean_transcript(srt, [("究竟靈氣", "臼井靈氣")])
        self.assertIn("00:00:00,000 --> 00:00:02,000\n臼井靈氣", out)
        self.assertNotIn("優優獨播劇場", out)

    def test_whisper_args_carry_the_prompt(self):
        args = vd.whisper_args("m.bin", "a.wav", "auto", "/o/transcript", "以下是繁體中文的逐字稿，可能提到：臼井靈氣。")
        self.assertEqual(args[args.index("--prompt") + 1], "以下是繁體中文的逐字稿，可能提到：臼井靈氣。")

    def test_to_traditional_with_opencc(self):
        import shutil as sh
        if not sh.which("opencc"):
            self.skipTest("本機沒有 opencc")
        self.assertEqual(vd.to_traditional("推广 里面"), "推廣 裡面")

    def test_to_traditional_without_opencc_is_unchanged(self):
        self.assertEqual(vd.to_traditional("推广", opencc=os.path.join(self.tmp, "nope")), "推广")

    def test_finalize_converts_txt_and_srt(self):
        import shutil as sh
        if not sh.which("opencc"):
            self.skipTest("本機沒有 opencc")
        base = os.path.join(self.tmp, "transcript")
        open(base + ".txt", "w", encoding="utf-8").write("推广")
        open(base + ".srt", "w", encoding="utf-8").write("1\n00:00:00,000 --> 00:00:01,000\n推广\n")
        self.assertEqual(vd.finalize_transcript(base), "推廣")
        self.assertIn("推廣", open(base + ".srt", encoding="utf-8").read())


class Paths(unittest.TestCase):
    def test_no_owner_paths(self):
        for mod in ("video_digest.py", "read_doc.py"):
            with open(os.path.join(os.path.dirname(vd.__file__), mod), encoding="utf-8") as f:
                src = f.read()
            from tests.leak_rules import leaks
            self.assertEqual(leaks(src), [])


if __name__ == "__main__":
    unittest.main()
