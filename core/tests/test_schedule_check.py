# -*- coding: utf-8 -*-
"""schedule_check：有人約某天某時，撞到主人的行程就讓值台回「已有安排，請約改天」（2026-09-30 新增）。

主人決定：時段撞到才算沒空；只講日期就告訴對方哪些時段有安排；一律不講行程內容。
忙碌時段取自主人真實課表（2026-10-06 週二）。
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import schedule_check as sc  # noqa: E402

TODAY = date(2026, 9, 30)            # 週三
BUSY = {"2026-10-06": [["15:30", "16:30"], ["18:30", "20:15"], ["20:20", "22:05"]],
        "2026-10-02": [["12:30", "13:30"]]}


class Dates(unittest.TestCase):
    def d(self, text):
        return sc.find_dates(text, TODAY)

    def test_month_day(self):
        self.assertEqual(self.d("10/6 可以嗎"), [date(2026, 10, 6)])
        self.assertEqual(self.d("10月6日碰面"), [date(2026, 10, 6)])

    def test_relative_days(self):
        self.assertEqual(self.d("明天有空嗎"), [date(2026, 10, 1)])
        self.assertEqual(self.d("後天"), [date(2026, 10, 2)])
        self.assertEqual(self.d("大後天"), [date(2026, 10, 3)])

    def test_weekdays(self):
        self.assertEqual(self.d("週五方便嗎"), [date(2026, 10, 2)])        # 本週還沒過
        self.assertEqual(self.d("星期二"), [date(2026, 10, 6)])            # 本週已過→下一個
        self.assertEqual(self.d("下週二"), [date(2026, 10, 6)])
        self.assertEqual(self.d("下禮拜三"), [date(2026, 10, 7)])

    def test_day_only(self):
        self.assertEqual(self.d("6號可以嗎"), [date(2026, 10, 6)])        # 這個月的 6 號已過→下個月

    def test_year_rollover(self):
        self.assertEqual(sc.find_dates("1/5 見面", date(2026, 12, 20)), [date(2027, 1, 5)])


class Times(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(sc.find_time_range("15:00"), (900, 960))

    def test_chinese_with_period(self):
        self.assertEqual(sc.find_time_range("晚上七點"), (1140, 1200))
        self.assertEqual(sc.find_time_range("下午三點半"), (930, 990))
        self.assertEqual(sc.find_time_range("早上10點"), (600, 660))

    def test_period_only(self):
        self.assertEqual(sc.find_time_range("下午"), (780, 1080))
        self.assertEqual(sc.find_time_range("晚上"), (1080, 1320))

    def test_yidian_as_degree_is_not_a_clock(self):
        # 「早一點／晚一點／快一點」是程度，不是一點鐘
        for t in ("明天早一點可以約嗎", "晚一點碰面", "快一點", "一點點時間"):
            self.assertIsNone(sc.find_time_range(t), t)

    def test_no_time(self):
        self.assertIsNone(sc.find_time_range("10/6 可以嗎"))


class Check(unittest.TestCase):
    def note(self, text):
        return sc.check(text, TODAY, BUSY)

    def test_real_case_next_tuesday_7pm_is_busy(self):
        n = self.note("下週二晚上七點可以碰面嗎？")
        self.assertIn("已有安排", n)
        self.assertIn("請約改天", n)

    def test_free_slot_is_not_promised(self):
        n = self.note("下週二早上10點可以約嗎")
        self.assertIn("目前空著", n)
        self.assertNotIn("已有安排", n)

    def test_date_only_lists_busy_slots_without_content(self):
        n = self.note("10/6 有空嗎")
        self.assertIn("18:30–20:15", n)
        self.assertIn("其餘時段目前空著", n)

    def test_empty_day(self):
        self.assertIn("整天目前空著", self.note("10/8 可以約嗎"))

    def test_no_intent_no_note(self):
        self.assertEqual(self.note("10/6 那天的簡報我放雲端了"), "")

    def test_no_date_no_note(self):
        self.assertEqual(self.note("有空再約"), "")

    def test_no_busy_index_no_note(self):
        self.assertEqual(sc.check("明天可以約嗎", TODAY, None), "")

    def test_beyond_index_range_says_unknown(self):
        self.assertIn("查不到", sc.check("2027/5/1 可以約嗎", TODAY, BUSY, horizon_days=90))

    def test_note_warns_not_to_leak(self):
        self.assertIn("不要", self.note("明天可以約嗎"))


class LoadIndex(unittest.TestCase):
    def test_missing_file(self):
        self.assertIsNone(sc.load_busy("/nonexistent/busy.json"))


if __name__ == "__main__":
    unittest.main()
