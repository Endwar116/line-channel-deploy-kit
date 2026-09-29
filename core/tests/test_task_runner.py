# -*- coding: utf-8 -*-
"""task_runner：系統說明由部署者提供；安全邊界寫死在程式裡。"""
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import task_runner as tr  # noqa: E402

# 部署者架構專屬的平台名（不是個資，是「不該假設客戶有」的東西）
PLATFORM_WORDS = ("supabase", "n8n")


class Brief(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = tr.BRIEF

    def tearDown(self):
        tr.BRIEF = self.orig
        shutil.rmtree(self.tmp)

    def test_default_brief_has_no_owner_specifics(self):
        from tests.leak_rules import leaks
        low = tr.DEFAULT_BRIEF.lower()
        self.assertEqual(leaks(low) + [w for w in PLATFORM_WORDS if w in low], [])

    def test_missing_file_falls_back_to_default(self):
        tr.BRIEF = os.path.join(self.tmp, "none.md")
        self.assertEqual(tr.load_brief(), tr.DEFAULT_BRIEF)

    def test_empty_file_falls_back_to_default(self):
        tr.BRIEF = os.path.join(self.tmp, "empty.md")
        open(tr.BRIEF, "w").write("  \n")
        self.assertEqual(tr.load_brief(), tr.DEFAULT_BRIEF)

    def test_template_comment_is_not_sent_to_agent(self):
        # 安裝器放的範本開頭有給部署者看的註解，不該進 prompt
        # kit 樹是 templates/ 下的範本；安裝樹是安裝器從範本放好的 config/system_brief.md
        cands = [os.path.join(tr.ROOM, "templates", "system_brief.md.tmpl"),
                 os.path.join(tr.ROOM, "config", "system_brief.md")]
        tmpl = next(p for p in cands if os.path.exists(p))
        tr.BRIEF = os.path.join(self.tmp, "b.md")
        shutil.copy(tmpl, tr.BRIEF)
        self.assertNotIn("<!--", tr.load_brief())
        if tmpl == cands[0]:                 # 部署者改寫過的 config 版內容本來就不同
            self.assertEqual(tr.load_brief(), tr.DEFAULT_BRIEF)

    def test_file_brief_is_used(self):
        tr.BRIEF = os.path.join(self.tmp, "b.md")
        open(tr.BRIEF, "w", encoding="utf-8").write("公網入口是 example.org")
        self.assertIn("example.org", tr.build_prompt("任務：看檔", "", [], tr.load_brief()))


class Prompt(unittest.TestCase):
    def test_prompt_contains_task_and_files(self):
        p = tr.build_prompt("任務：讀合約", "・前文", ["a.pdf"], "BRIEF")
        for s in ("任務：讀合約", "・前文", "a.pdf", "BRIEF", "絕對不要編造"):
            self.assertIn(s, p)

    def test_prompt_states_incoming_from_room(self):
        p = tr.build_prompt("x", "", [], "BRIEF")
        self.assertIn(tr.INCOMING, p)

    def test_source_has_no_owner_specifics(self):
        from tests.leak_rules import leaks
        low = open(tr.__file__, encoding="utf-8").read().lower()
        self.assertEqual(leaks(low) + [w for w in PLATFORM_WORDS if w in low], [])


class SignatureGate(unittest.TestCase):
    """驗章要 fail-closed：未簽章、金鑰不見、竄改，一律不執行。
    （2026-09-26 審查：舊版只看驗章器輸出有沒有 ✗/🔴，LEGACY 與驗章器 crash 都被當成通過。）"""

    def setUp(self):
        import hashlib
        import hmac
        import json
        import task_verify
        self.tv = task_verify
        self.tmp = tempfile.mkdtemp()
        self.orig = task_verify.KEY_FILE
        task_verify.KEY_FILE = os.path.join(self.tmp, "queue_hmac.key")
        open(task_verify.KEY_FILE, "w").write("k3y\n")
        body = {"text": "任務：讀合約", "ts": "2026-09-26T10:00:00+08:00"}
        canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.signed = dict(body, sig=hmac.new(b"k3y", canonical.encode(), hashlib.sha256).hexdigest())

    def tearDown(self):
        self.tv.KEY_FILE = self.orig
        shutil.rmtree(self.tmp)

    def test_valid_signature_passes(self):
        self.assertTrue(tr.verify_task(self.signed)[0])

    def test_does_not_mutate_entry(self):
        tr.verify_task(self.signed)
        self.assertIn("sig", self.signed)

    def test_unsigned_is_rejected(self):
        self.assertFalse(tr.verify_task({"text": "任務：讀 secrets"})[0])

    def test_tampered_is_rejected(self):
        self.assertFalse(tr.verify_task(dict(self.signed, text="任務：別的"))[0])

    def test_missing_key_is_rejected_not_raised(self):
        os.remove(self.tv.KEY_FILE)
        ok, why = tr.verify_task(self.signed)
        self.assertFalse(ok)
        self.assertTrue(why)


class MainGate(unittest.TestCase):
    """main 的接線：未簽章的不執行、有簽章的照跑、標記推過兩筆（不被偽造任務卡住）。"""

    def setUp(self):
        import hashlib
        import hmac
        import json
        import task_verify
        self.tmp = tempfile.mkdtemp()
        # report 一定要攔：不攔的話，在部署好的機器上跑測試會把「任務：偽造」真的送到主人 LINE
        # （2026-09-29 實際發生過 5 次）
        self.saved = {k: getattr(tr, k) for k in ("QUEUE", "MARKER", "RESULTS", "run_one", "report")}
        self.reported = []
        tr.report = self.reported.append
        self.saved_key = task_verify.KEY_FILE
        self.tv = task_verify
        task_verify.KEY_FILE = os.path.join(self.tmp, "k")
        open(task_verify.KEY_FILE, "w").write("k3y\n")
        tr.QUEUE, tr.MARKER, tr.RESULTS = (os.path.join(self.tmp, n) for n in ("q.jsonl", "m.json", "r.jsonl"))
        body = {"text": "任務：真的", "ts": "1"}
        c = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        signed = dict(body, sig=hmac.new(b"k3y", c.encode(), hashlib.sha256).hexdigest())
        with open(tr.QUEUE, "w", encoding="utf-8") as f:
            f.write(json.dumps({"text": "任務：偽造", "ts": "0"}, ensure_ascii=False) + "\n")
            f.write(json.dumps(signed, ensure_ascii=False) + "\n")
        self.ran = []
        tr.run_one = lambda t, i, extra=(): (self.ran.append(t["text"]) or (True, "ok"))
        self.argv = sys.argv
        sys.argv = ["task_runner.py"]

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(tr, k, v)
        self.tv.KEY_FILE = self.saved_key
        sys.argv = self.argv
        shutil.rmtree(self.tmp)

    def test_only_signed_task_runs_and_marker_advances(self):
        import json
        tr.main()
        self.assertEqual(self.ran, ["任務：真的"])
        self.assertEqual(json.load(open(tr.MARKER))["line"], 2)
        res = [json.loads(l) for l in open(tr.RESULTS, encoding="utf-8")]
        self.assertFalse(res[0]["ok"])
        self.assertIn("簽章", res[0]["output"])
        self.assertEqual(len(self.reported), 1)
        self.assertIn("任務：偽造", self.reported[0])


class AttachmentMatching(unittest.TestCase):
    """點名附件：檔名要完整出現，不能因為是別的檔名的一段就被帶進工作區（審查 M3）。"""

    def test_full_filename(self):
        self.assertTrue(tr.names_file("任務：看 報價單.pdf", "報價單.pdf"))

    def test_stem_inside_chinese_sentence(self):
        self.assertTrue(tr.names_file("任務：請看報價單2026版的內容", "報價單2026版.pdf"))

    def test_prefix_of_longer_name_is_not_a_match(self):
        text = "任務：讀 JOJO_IP人物定位與頻道策略_V1.0"
        self.assertFalse(tr.names_file(text, "JOJO_IP人物定位與頻道策略.docx"))
        self.assertTrue(tr.names_file(text, "JOJO_IP人物定位與頻道策略_V1.0.docx"))

    def test_digit_continuation_is_not_a_match(self):
        self.assertFalse(tr.names_file("任務：看 IMG_12345.jpg", "IMG_1234.jpg"))

    def test_short_stem_needs_extension(self):
        self.assertFalse(tr.names_file("任務：看合約", "合約.pdf"))


class VideoLinks(unittest.TestCase):
    """任務帶影片連結：Python 先下載、轉逐字稿，放進工作區；抓不到就把原因交給 agent 照實講。"""

    def setUp(self):
        import video_link
        self.vl = video_link
        self.tmp = tempfile.mkdtemp()
        self.saved = {k: getattr(tr, k) for k in ("WORKSPACE", "INCOMING", "fetch_link", "digest")}
        tr.WORKSPACE = os.path.join(self.tmp, "ws")
        tr.INCOMING = os.path.join(self.tmp, "incoming")
        digest_dir = os.path.join(self.tmp, "digest", "連結影片_abc")
        os.makedirs(digest_dir)
        open(os.path.join(digest_dir, "INDEX.md"), "w").write("# 逐字稿")
        tr.digest = lambda path: (digest_dir, {})

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(tr, k, v)
        shutil.rmtree(self.tmp)

    def test_link_is_downloaded_and_digested_into_workspace(self):
        got = []
        tr.fetch_link = lambda url: got.append(url) or os.path.join(self.tmp, "連結影片_abc.mp4")
        ws, copied = tr.prepare_workspace("t1", "任務：看這支 https://fb.watch/abc/ 講重點")
        self.assertEqual(got, ["https://fb.watch/abc/"])
        self.assertTrue(os.path.exists(os.path.join(ws, "連結影片_abc_digest", "INDEX.md")))
        self.assertTrue(any("INDEX.md" in c for c in copied))

    def test_rejected_link_reason_reaches_agent(self):
        def nope(url):
            raise self.vl.LinkRejected("這支影片要登入才看得到")
        tr.fetch_link = nope
        _, copied = tr.prepare_workspace("t2", "任務：看 https://www.facebook.com/x/videos/1")
        self.assertTrue(any("要登入" in c for c in copied), copied)

    def test_no_links_no_download(self):
        tr.fetch_link = lambda url: self.fail("不該下載")
        tr.prepare_workspace("t3", "任務：幫我看 https://example.com/page")


class ImplicitAttachments(unittest.TestCase):
    """任務沒寫檔名但提到影片／語音：帶入同對話前後 30 分鐘內到的附件。
    （2026-09-29 實故障：影片 02:04 收下，「任務：將影片轉文字」沒寫檔名，本體看不到影片。）"""

    DM = "dm:Uowner"

    def setUp(self):
        # 正式附件清單不能影響這組測試
        self.saved_index = tr.ATTACH_INDEX
        tr.ATTACH_INDEX = os.path.join(tempfile.gettempdir(), "no-such-attachments.jsonl")

    def tearDown(self):
        tr.ATTACH_INDEX = self.saved_index

    def notice(self, name, ts, channel=DM):
        return {"ts": ts, "channel": channel, "text": f"【附件到達·影片】{name} 已收進",
                "attachment": {"path": f"/in/{name}", "name": name}}

    def task(self, text, ts="2026-09-29T02:04:32+08:00", channel=DM):
        return {"ts": ts, "channel": channel, "text": text}

    def test_real_case_video_same_second(self):
        rows = [self.notice("影片_20260929_020418.mp4", "2026-09-29T02:04:32+08:00"),
                self.task("任務：將影片轉文字")]
        self.assertEqual(tr.implicit_attachments(rows, 1), ["/in/影片_20260929_020418.mp4"])

    def test_attachment_arriving_after_task_counts(self):
        # 大影片下載完才排佇列，可能比任務晚
        rows = [self.task("任務：把語音轉成文字"), self.notice("語音_1.m4a", "2026-09-29T02:10:00+08:00")]
        self.assertEqual(tr.implicit_attachments(rows, 0), ["/in/語音_1.m4a"])

    def test_other_channel_and_old_attachments_are_ignored(self):
        rows = [self.notice("a.mp4", "2026-09-29T00:00:00+08:00"),
                self.notice("b.mp4", "2026-09-29T02:00:00+08:00", channel="group:Cx"),
                self.task("任務：將影片轉文字")]
        self.assertEqual(tr.implicit_attachments(rows, 2), [])

    def test_task_that_names_a_file_gets_nothing_extra(self):
        rows = [self.notice("影片_20260929_020418.mp4", "2026-09-29T02:04:00+08:00"),
                self.task("任務：看 報價單.pdf")]
        self.assertEqual(tr.implicit_attachments(rows, 1), [])

    def test_task_without_media_words_gets_nothing(self):
        rows = [self.notice("影片_1.mp4", "2026-09-29T02:04:00+08:00"), self.task("任務：查明天天氣")]
        self.assertEqual(tr.implicit_attachments(rows, 1), [])

    def test_prepare_workspace_copies_extra_files(self):
        tmp = tempfile.mkdtemp()
        saved = (tr.WORKSPACE, tr.INCOMING)
        try:
            tr.WORKSPACE, tr.INCOMING = os.path.join(tmp, "ws"), os.path.join(tmp, "in")
            src = os.path.join(tmp, "語音_1.txt")
            open(src, "w").write("x")
            ws, copied = tr.prepare_workspace("t9", "任務：把語音轉成文字", extra=[src])
            self.assertTrue(os.path.exists(os.path.join(ws, "語音_1.txt")))
            self.assertTrue(any("自動帶入" in c for c in copied), copied)
        finally:
            tr.WORKSPACE, tr.INCOMING = saved
            shutil.rmtree(tmp)


class SilentGroupAttachments(unittest.TestCase):
    """群組附件安靜存著，不進任務佇列；@ 助理下任務時才從附件清單帶進來（2026-09-30 主人決定）。"""

    def setUp(self):
        import json
        self.tmp = tempfile.mkdtemp()
        self.saved = tr.ATTACH_INDEX
        tr.ATTACH_INDEX = os.path.join(self.tmp, "attachments.jsonl")
        with open(tr.ATTACH_INDEX, "w", encoding="utf-8") as f:
            for name, ts, ch in (("JOJO_準備手冊_V22.pdf", "2026-09-30T10:00:00+08:00", "group:Cjojo"),
                                 ("圖片_20260930_100500.jpg", "2026-09-30T10:05:00+08:00", "group:Cjojo"),
                                 ("別群.pdf", "2026-09-30T10:05:00+08:00", "group:Cother")):
                f.write(json.dumps({"ts": ts, "channel": ch, "path": f"/in/{name}", "name": name},
                                   ensure_ascii=False) + "\n")

    def tearDown(self):
        tr.ATTACH_INDEX = self.saved
        shutil.rmtree(self.tmp)

    def test_group_task_picks_silent_attachments_from_same_group(self):
        rows = [{"ts": "2026-09-30T10:10:00+08:00", "channel": "group:Cjojo",
                 "text": "@昱捷助理 任務：讀剛剛那份 PDF 跟截圖"}]
        self.assertEqual(tr.implicit_attachments(rows, 0),
                         ["/in/JOJO_準備手冊_V22.pdf", "/in/圖片_20260930_100500.jpg"])

    def test_picture_words_count(self):
        rows = [{"ts": "2026-09-30T10:10:00+08:00", "channel": "group:Cjojo", "text": "任務：把圖片的字抄出來"}]
        self.assertIn("/in/圖片_20260930_100500.jpg", tr.implicit_attachments(rows, 0))


class WordOutput(unittest.TestCase):
    """任務要 Word：本體照樣只產文字，task_runner 存成 .docx 放進指定資料夾，回覆附檔名。"""

    def setUp(self):
        import json
        self.tmp = tempfile.mkdtemp()
        self.saved = {k: getattr(tr, k) for k in ("output_dir", "FALLBACK_OUTPUT", "WORKSPACE", "INCOMING")}
        tr.output_dir = lambda: (os.path.join(self.tmp, "drive"), "Google 雲端／昱捷助理輸出")
        tr.FALLBACK_OUTPUT = os.path.join(self.tmp, "local")
        tr.WORKSPACE = os.path.join(self.tmp, "ws")
        tr.INCOMING = os.path.join(self.tmp, "in")
        fake = json.dumps({"result": "# 提示詞\n第一條", "permission_denials": []})
        p = unittest.mock.patch.object(tr.subprocess, "run",
                                       return_value=unittest.mock.Mock(returncode=0, stdout=fake, stderr=""))
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(tr, k, v)
        shutil.rmtree(self.tmp)

    def test_prompt_tells_agent_word_is_handled(self):
        p = tr.build_prompt("任務：貼成word檔", "", [], "BRIEF", word=True)
        self.assertIn("Word", p)
        self.assertIn("不要說做不到", p)

    def test_word_task_saves_docx_and_reports_name(self):
        ok, out = tr.run_one({"text": "任務：把提示詞貼成word檔", "ts": "t"}, 1)
        self.assertTrue(ok)
        files = os.listdir(os.path.join(self.tmp, "drive"))
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith(".docx"))
        self.assertIn(files[0], out)
        self.assertIn("Google 雲端／昱捷助理輸出", out)

    def test_line_summary_keeps_word_note_after_truncation(self):
        out = "字" * 2000 + "\n\n📄 已存成 Word：a.docx\n位置：Google 雲端"
        summ = tr.line_summary(out)
        self.assertLess(len(summ), 500)
        self.assertIn("a.docx", summ)
        self.assertIn("Google 雲端", summ)

    def test_plain_task_saves_nothing(self):
        tr.run_one({"text": "任務：講重點", "ts": "t"}, 2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "drive")))


class NoInventedCommands(unittest.TestCase):
    def test_prompt_forbids_suggesting_commands_not_in_brief(self):
        # 2026-09-29：本體建議主人跑不存在的 `line_bridge.py --process-media`
        self.assertIn("不要建議", tr.build_prompt("x", "", [], "BRIEF"))


class SafetyBoundary(unittest.TestCase):
    def test_tools_are_read_only(self):
        self.assertEqual(set(tr.TOOLS.split(",")), {"Read", "Glob", "Grep", "WebFetch"})

    def test_guest_and_attachment_notices_are_skipped(self):
        tasks = [{"text": "任務：a", "guest": True}, {"text": "【附件到達】x"}, {"text": "任務：b"}]
        self.assertEqual([t["text"] for _, t in tr.pick(tasks, 3)], ["任務：b"])


if __name__ == "__main__":
    unittest.main()
