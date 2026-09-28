# -*- coding: utf-8 -*-
"""health_check：自檢要跟著部署者的 slug／port／實際服務走，且不把關機時間算成停擺。"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import health_check as hc  # noqa: E402

HOUR = 3600


class EffectiveLogAge(unittest.TestCase):
    """2026-09-24 重開機實測：自檢 RunAtLoad 先跑，其他排程還沒輪到，五項全被誤判停擺。"""

    def test_right_after_boot_old_log_is_not_stale(self):
        boot = 100 * HOUR
        self.assertEqual(hc.effective_log_age(boot - 8 * HOUR, boot + 60, boot), 60)

    def test_log_written_after_boot_uses_mtime(self):
        boot = 100 * HOUR
        self.assertEqual(hc.effective_log_age(boot + 600, boot + 900, boot), 300)

    def test_job_dead_since_boot_still_goes_stale(self):
        boot = 100 * HOUR
        self.assertEqual(hc.effective_log_age(boot - 8 * HOUR, boot + 2 * HOUR, boot), 2 * HOUR)

    def test_unknown_boot_time_falls_back_to_mtime(self):
        self.assertEqual(hc.effective_log_age(1000, 1600, None), 600)

    def test_boot_time_is_in_the_past(self):
        import time
        bt = hc.boot_time()
        self.assertIsNotNone(bt)
        self.assertLess(bt, time.time())


class LogState(unittest.TestCase):
    """排程型服務：剛安裝還沒輪到第一輪（log 不存在）不算故障。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "x.log")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_new_install_without_log_is_pending(self):
        now = 1000 * HOUR
        self.assertEqual(hc.log_state(self.log, 900, now - 300, now, None)[0], "pending")

    def test_old_install_without_log_is_missing(self):
        now = 1000 * HOUR
        self.assertEqual(hc.log_state(self.log, 900, now - 48 * HOUR, now, None)[0], "missing")

    def test_fresh_and_stale_log(self):
        open(self.log, "w").close()
        m = os.path.getmtime(self.log)
        self.assertEqual(hc.log_state(self.log, 900, m, m + 60, None)[0], "ok")
        self.assertEqual(hc.log_state(self.log, 900, m, m + 3 * HOUR, None)[0], "stale")


class Deployment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_slug_from_room(self):
        self.assertEqual(hc.slug_from_room("/Users/x/.acme"), "acme")
        self.assertEqual(hc.slug_from_room("/Users/x/.acme/"), "acme")

    def test_discovers_only_existing_plists(self):
        for n in ("com.acme.linebridge.plist", "com.acme.healthcheck.plist",
                  "com.acme.mystery.plist", "com.other.linebridge.plist", "notes.txt"):
            open(os.path.join(self.tmp, n), "w").close()
        got = hc.discover_services(self.tmp, "acme")
        self.assertEqual(got, {"com.acme.linebridge": "接收站",
                               "com.acme.healthcheck": "自檢",
                               "com.acme.mystery": "mystery"})

    def test_nosleep_has_a_name(self):
        open(os.path.join(self.tmp, "com.acme.nosleep.plist"), "w").close()
        self.assertEqual(hc.discover_services(self.tmp, "acme")["com.acme.nosleep"], "防睡眠")

    def test_discover_missing_dir_is_empty(self):
        self.assertEqual(hc.discover_services(os.path.join(self.tmp, "nope"), "acme"), {})

    def test_local_port_from_config(self):
        p = os.path.join(self.tmp, "kit_config.json")
        json.dump({"port": 8811}, open(p, "w"))
        orig = hc.CFG_P
        try:
            hc.CFG_P = p
            self.assertEqual(hc.local_port(), 8811)
            hc.CFG_P = os.path.join(self.tmp, "missing.json")
            self.assertEqual(hc.local_port(), 8700)
        finally:
            hc.CFG_P = orig


class Backlog(unittest.TestCase):
    """任務執行沒啟用時，本體用 queue_backlog_check mark 收割；兩種標記任一涵蓋就算收過（審查 M1）。"""

    ROWS = [{"text": "任務：a", "ts": "2026-09-20T10:00:00+08:00"},
            {"text": "【附件到達】x.pdf", "ts": "2026-09-20T11:00:00+08:00"},
            {"text": "任務：b", "ts": "2026-09-21T10:00:00+08:00", "guest": True}]

    def test_nothing_harvested_counts_tasks_not_notices(self):
        self.assertEqual(hc.unharvested(self.ROWS, 0, None), 2)

    def test_runner_marker_covers_by_line(self):
        self.assertEqual(hc.unharvested(self.ROWS, 1, None), 1)

    def test_queue_marker_covers_by_time(self):
        from datetime import datetime
        m = datetime.fromisoformat("2026-09-21T00:00:00+08:00")
        self.assertEqual(hc.unharvested(self.ROWS, 0, m), 1)

    def test_bad_timestamp_counts_as_pending(self):
        from datetime import datetime
        m = datetime.fromisoformat("2026-09-30T00:00:00+08:00")
        self.assertEqual(hc.unharvested([{"text": "任務：x", "ts": "壞"}], 0, m), 1)


class PublicHost(unittest.TestCase):
    """公網主機名：只認真的轉到本機 bridge port 的那一個（審查 M2）。"""

    CF = """tunnel: abc
ingress:
  - hostname: other.example.com
    service: http://localhost:3000
  - hostname: bot.example.com
    service: http://localhost:8700
  - service: http_status:404
"""

    def test_config_wins(self):
        self.assertEqual(hc.resolve_public_host({"public_host": "a.b"}, 8700, self.CF, None, ""), "a.b")

    def test_cloudflared_picks_host_for_our_port(self):
        self.assertEqual(hc.resolve_public_host({}, 8700, self.CF, None, ""), "bot.example.com")

    def test_cloudflared_unrelated_tunnel_is_ignored(self):
        self.assertIsNone(hc.resolve_public_host({}, 8799, self.CF, None, ""))

    def test_tailscale_funnel_to_our_port(self):
        ts = {"Self": {"DNSName": "mac.tail1234.ts.net."}}
        funnel = "https://mac.tail1234.ts.net (Funnel on)\n|-- / proxy http://127.0.0.1:8700\n"
        self.assertEqual(hc.resolve_public_host({}, 8700, "", ts, funnel), "mac.tail1234.ts.net")

    def test_tailscale_without_funnel_is_ignored(self):
        ts = {"Self": {"DNSName": "mac.tail1234.ts.net."}}
        self.assertIsNone(hc.resolve_public_host({}, 8700, "", ts, "No serve config"))


class SetupPhase(unittest.TestCase):
    """剛安裝、還沒認主：憑證空白是待辦不是故障，也不發通知（反正送不出去）（審查 I5）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = (hc.SEC, list(hc.results))
        hc.SEC = self.tmp
        del hc.results[:]
        with open(os.path.join(self.tmp, "line_secrets.env"), "w") as f:
            f.write("LINE_CHANNEL_SECRET=\nLINE_CHANNEL_ACCESS_TOKEN=\n")

    def tearDown(self):
        hc.SEC = self.orig[0]
        hc.results[:] = self.orig[1]
        shutil.rmtree(self.tmp)

    def levels(self):
        hc.check_line_secrets()
        return {r[0] for r in hc.results}

    def test_empty_secrets_before_registration_is_warn(self):
        self.assertEqual(self.levels(), {hc.WARN})
        self.assertFalse(hc.owner_registered())

    def test_empty_secrets_after_registration_is_fail(self):
        open(os.path.join(self.tmp, "line_owner.txt"), "w").write("Uowner\n")
        self.assertIn(hc.FAIL, self.levels())
        self.assertTrue(hc.owner_registered())


class NoOwnerSpecifics(unittest.TestCase):
    def test_source_has_no_hardcoded_deployment(self):
        src = open(hc.__file__, encoding="utf-8").read().lower()
        hits = [bad for bad in ("com.ownerkit", "8700/", "owner", "example") if bad in src]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
