# -*- coding: utf-8 -*-
"""帳號 failover：max-a 撞額度時自動改用 max-b。

背景（2026-09-16→18 實故障）：值台被釘在單一帳號（launchd 的 PATH 不含 ~/.cmax/bin，
所以走 /usr/local/bin/claude ＋ 預設 profile）。該帳號連三天撞額度，11 次呼叫成功 0 次。
CMax 的 shim 在非互動環境會回 "Not logged in"，所以不能靠它自動切換——
只能由 bridge 自己在 subprocess 上設 CLAUDE_CONFIG_DIR。

黏性冷卻的理由：一次 limit 失敗要約 33 秒。沒有冷卻的話，被限流那幾小時內每則訊息
都要先付 33 秒才輪到下一個帳號；兩個都掛就是 66 秒，超過 LINE reply token 的 60 秒。
冷卻時間用固定值而非 CLI 回報的 reset 時間——2026-09-19 實測確認那個時間不可信
（log 說隔天 15:00 恢復，實際當天凌晨就好了）。
"""
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

SKIP = unittest.skipIf(IMPORT_ERR is not None,
                       "line_bridge 尚未可載入（填完 config/secrets/line_secrets.env 再跑）")

NOW = 1_000_000.0
P = ["", "~/.claude-max/profiles/max-b"]


@SKIP
class AvailableProfiles(unittest.TestCase):
    """純函式：依冷卻狀態挑出還能用的 profile，順序保持設定的順序。"""

    def test_no_cooldown_returns_all_in_order(self):
        self.assertEqual(lb.available_profiles(P, {}, NOW), P)

    def test_first_cooling_is_skipped(self):
        cd = {"": NOW + 600}
        self.assertEqual(lb.available_profiles(P, cd, NOW), [P[1]])

    def test_all_cooling_returns_empty(self):
        cd = {"": NOW + 600, "~/.claude-max/profiles/max-b": NOW + 600}
        self.assertEqual(lb.available_profiles(P, cd, NOW), [])

    def test_expired_cooldown_is_available_again(self):
        cd = {"": NOW - 1}
        self.assertEqual(lb.available_profiles(P, cd, NOW), P)

    def test_unknown_profile_in_cooldown_is_ignored(self):
        cd = {"~/.someone-elses-profile": NOW + 600}
        self.assertEqual(lb.available_profiles(P, cd, NOW), P)

    def test_empty_profile_list_means_one_inherited_env_run(self):
        """kit 預設 claude_profiles=[]＝不 failover，行為與改動前完全相同。"""
        self.assertEqual(lb.available_profiles([], {}, NOW), [None])


@SKIP
class ProfileEnv(unittest.TestCase):
    """None＝沿用環境不動；"" ＝移除該變數回到預設帳號；其他＝設成該目錄。"""

    def test_none_profile_inherits_environment_untouched(self):
        """None＝沒設定 failover：一個位元組都不能改，否則就不是「行為與改動前相同」。"""
        self.assertEqual(lb.profile_env(None), dict(os.environ))

    def test_empty_string_profile_removes_inherited_config_dir(self):
        """清單裡的 "" ＝預設帳號：主動**移除** CLAUDE_CONFIG_DIR，不是設成某個路徑。

        兩個都要滿足：
        ① 不能沿用繼承值——若外層（例如 CMax）已把它指向 max-b，清單 ["", "…max-b"]
           會指到同一個帳號，failover 空轉卻從 log 看不出來。
        ② 不能設成 ~/.claude——2026-09-20 實測：CLI 在這個變數沒設時讀 ~/.claude.json
           ＋Keychain，一旦明確指向 ~/.claude 就改找 ~/.claude/.claude.json（不存在），
           直接變成 "Not logged in"。預設帳號無法用一個路徑表達。
        """
        os.environ["CLAUDE_CONFIG_DIR"] = "/somewhere/else"
        try:
            self.assertNotIn("CLAUDE_CONFIG_DIR", lb.profile_env(""))
        finally:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def test_listed_profiles_are_distinct_even_under_inherited_config_dir(self):
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.expanduser("~/.claude-max/profiles/max-b")
        try:
            a = lb.profile_env("").get("CLAUDE_CONFIG_DIR")
            b = lb.profile_env("~/.claude-max/profiles/max-b").get("CLAUDE_CONFIG_DIR")
            self.assertIsNone(a)
            self.assertNotEqual(a, b)
        finally:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def test_named_profile_sets_expanded_config_dir(self):
        env = lb.profile_env("~/.claude-max/profiles/max-b")
        self.assertEqual(env["CLAUDE_CONFIG_DIR"],
                         os.path.expanduser("~/.claude-max/profiles/max-b"))

    def test_profile_env_does_not_mutate_os_environ(self):
        before = dict(os.environ)
        lb.profile_env("~/.claude-max/profiles/max-b")
        self.assertEqual(dict(os.environ), before)



LIMIT_TEXT = "You've hit your limit · resets Sep 20 at 3pm (Asia/Taipei)"


def _res(returncode, result_text, is_error=False):
    payload = {"type": "result", "subtype": "success",
               "is_error": is_error, "result": result_text, "usage": {}}
    return mock.Mock(returncode=returncode, stdout=json.dumps(payload), stderr="")


@SKIP
class AskClaudeFailover(unittest.TestCase):
    """ask_claude 撞額度時要換帳號重試，而不是把額度話術丟回 LINE。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calls = []          # [(有無 -c, CLAUDE_CONFIG_DIR)]
        self.cooled = []         # 被標記冷卻的 profile
        self.profiles = ["", "~/.claude-max/profiles/max-b"]
        self.patches = [
            mock.patch.object(lb, "CLAUDE_PROFILES", self.profiles),
            mock.patch.object(lb, "chat_dir_for", lambda *a, **k: self.tmp),
            mock.patch.object(lb, "_meter_append", lambda *a, **k: None),
            mock.patch.object(lb, "load_profile_cooldown", lambda: {}),
            mock.patch.object(lb, "mark_profile_cooldown",
                              lambda p, **k: self.cooled.append(p)),
            mock.patch.object(lb, "PROFILE_COOLDOWN_PATH",
                              os.path.join(self.tmp, "cooldown.json")),
            # LOG_FILE 也要隔離：ask_claude 內的 log() 會寫進正式 line_bridge.log，
            # 讓營運 log 混進測試產生的 PROFILE_LIMITED，日後查故障會被誤導。
            mock.patch.object(lb, "LOG_FILE", os.path.join(self.tmp, "test.log")),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def _runner(self, outcome_by_profile):
        """outcome_by_profile: {CLAUDE_CONFIG_DIR 尾段: (rc, text)}"""
        def run(cmd, **kw):
            cfg = (kw.get("env") or {}).get("CLAUDE_CONFIG_DIR", "")
            key = "max-b" if cfg.endswith("max-b") else "default"
            self.calls.append(("-c" in cmd, key))
            rc, text = outcome_by_profile[key]
            return _res(rc, text, is_error=(rc != 0))
        return run

    def test_falls_over_to_second_profile_and_returns_its_answer(self):
        run = self._runner({"default": (1, LIMIT_TEXT), "max-b": (0, "在的")})
        with mock.patch.object(lb.subprocess, "run", run):
            out = lb.ask_claude("在嗎？", "dm", "C1")
        self.assertEqual(out, "在的")
        self.assertIn("", self.cooled)                      # 預設 profile 被標冷卻
        self.assertIn(("max-b"), [k for _, k in self.calls])

    def test_limit_does_not_retry_without_c_on_same_profile(self):
        """同帳號重跑必然同樣撞額度，白花約 33 秒——不該重跑。"""
        run = self._runner({"default": (1, LIMIT_TEXT), "max-b": (0, "在的")})
        with mock.patch.object(lb.subprocess, "run", run):
            lb.ask_claude("在嗎？", "dm", "C1")
        default_calls = [c for c in self.calls if c[1] == "default"]
        self.assertEqual(len(default_calls), 1, f"預設 profile 應只跑一次，實際 {default_calls}")

    def test_non_limit_failure_still_retries_without_c_on_same_profile(self):
        """CONTINUE_MISS（沒有可接續的對話）的既有行為不能被改掉。"""
        seen = []

        def run(cmd, **kw):
            seen.append("-c" in cmd)
            return _res(0, "新對話回覆") if "-c" not in cmd else _res(1, "")
        with mock.patch.object(lb.subprocess, "run", run):
            out = lb.ask_claude("在嗎？", "dm", "C1")
        self.assertEqual(out, "新對話回覆")
        self.assertEqual(seen, [True, False])
        self.assertEqual(self.cooled, [])

    def test_all_profiles_limited_returns_limit_reply(self):
        run = self._runner({"default": (1, LIMIT_TEXT), "max-b": (1, LIMIT_TEXT)})
        with mock.patch.object(lb.subprocess, "run", run):
            out = lb.ask_claude("在嗎？", "dm", "C1")
        self.assertIn("額度", out)
        self.assertIn("Sep 20 at 3pm", out)
        self.assertEqual(len(self.cooled), 2)

if __name__ == "__main__":
    unittest.main()
