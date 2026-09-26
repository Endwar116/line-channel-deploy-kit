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


class NoOwnerSpecifics(unittest.TestCase):
    def test_source_has_no_hardcoded_deployment(self):
        src = open(hc.__file__, encoding="utf-8").read().lower()
        hits = [bad for bad in ("com.ownerkit", "8700/", "owner", "example") if bad in src]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
