# -*- coding: utf-8 -*-
"""relay_say：S 級硬擋不能擋到主人自己的私訊。

背景（2026-09-04 線上實故障）：主人把自己的私訊設成 S 級以放行附件後，
本體所有回報都被 relay_say 的「高信任職場通道禁止發言」擋下。
kit v1.13 已在 bridge 端把附件通道與 S 級拆開，這裡是第二道防護。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNER = "Uowner0000000000000000000000000000"


class RelaySayOwnerDm(unittest.TestCase):
    def setUp(self):
        self.room = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.room, "tools"))
        os.makedirs(os.path.join(self.room, "config", "secrets"))
        shutil.copy(os.path.join(CORE, "relay_say.py"), os.path.join(self.room, "tools"))
        with open(os.path.join(self.room, "config", "secrets", "line_owner.txt"), "w") as f:
            f.write(OWNER + "\n")
        cfg = {"s_tier_channels": [f"dm:{OWNER}", "group:Cwork"]}
        with open(os.path.join(self.room, "config", "kit_config.json"), "w") as f:
            json.dump(cfg, f)

    def tearDown(self):
        shutil.rmtree(self.room)

    def run_say(self, *args):
        return subprocess.run([sys.executable, os.path.join(self.room, "tools", "relay_say.py"), *args],
                              capture_output=True, text=True)

    def pending(self):
        p = os.path.join(self.room, "LOG", "pending_relay.jsonl")
        return [json.loads(l) for l in open(p)] if os.path.exists(p) else []

    def test_owner_dm_in_s_tier_is_allowed(self):
        r = self.run_say("測試")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.pending()[0]["channel"], f"dm:{OWNER}")

    def test_s_tier_group_is_still_blocked(self):
        r = self.run_say("--to", "group:Cwork", "測試")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.pending(), [])

    def test_other_dm_in_s_tier_is_blocked(self):
        with open(os.path.join(self.room, "config", "kit_config.json"), "w") as f:
            json.dump({"s_tier_channels": ["dm:Uother"]}, f)
        r = self.run_say("--to", "dm:Uother", "測試")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
