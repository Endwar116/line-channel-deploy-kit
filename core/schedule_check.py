#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""schedule_check.py — 有人約某天某時，先查主人那個時段有沒有安排（v1.20，2026-09-30 新增）

值台只看得到身分檔裡 3 天的狀態板；約的日期常在更後面。這裡讀忙碌時段表
（LOG/busy_index.json，由部署者的行程同步產出：只有日期與起訖時間，沒有行程內容），
判讀訊息裡的日期與時間，產出一段給值台判斷用的系統附註。

主人 2026-09-30 決定的規則：
  ・時段撞到才算沒空 → 請值台回「那個時段已有安排，請約改天」
  ・沒撞到 → 只說目前空著，不代主人答應
  ・只講日期沒講時間 → 告訴對方哪些時段有安排，其餘空著
  ・一律不講行程內容（表裡本來就沒有）
  ・訊息要同時有日期＋「約」的意思才查；沒有忙碌時段表＝這功能不存在，什麼都不加
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

INTENT_WORDS = ("約", "碰面", "見面", "會面", "開會", "有空", "空嗎", "方便", "可以嗎", "行嗎",
                "拜訪", "過去找", "來找", "聚一下", "聚聚", "討論")
WEEKDAYS = "一二三四五六日"
WD_ALIASES = {"天": "日"}
PERIODS = [("早上", 480, 720), ("上午", 480, 720), ("中午", 690, 810), ("下午", 780, 1080),
           ("傍晚", 1020, 1140), ("晚上", 1080, 1320)]
PM_PERIODS = ("下午", "傍晚", "晚上")
CN_NUM = {"零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}
SLOT_MINUTES = 60
HORIZON_DAYS = 90
MAX_DATES = 3

FULL_DATE = re.compile(r"(\d{4})\s*[/\-年]\s*(\d{1,2})\s*[/\-月]\s*(\d{1,2})\s*[日號号]?")
MONTH_DAY = re.compile(r"(?<!\d)(\d{1,2})\s*[/月]\s*(\d{1,2})(?!\d)\s*[日號号]?")
DAY_ONLY = re.compile(r"(?<![\d/月])(\d{1,2})\s*[號号]")
REL_DAY = re.compile(r"大後天|後天|明天|今天")
WEEKDAY_RE = re.compile(r"((?:下)*)(?:週|星期|禮拜|周)([一二三四五六日天])")
CLOCK = re.compile(r"(?<!\d)(\d{1,2})\s*[:：]\s*(\d{2})")
DEGREE = re.compile(r"[早晚快慢多少好]一點|一點點")      # 「早一點」是程度，不是一點鐘
CN_CLOCK = re.compile(r"([一二兩三四五六七八九十]{1,3}|\d{1,2})\s*點\s*(半|[一二三四五]十分?|\d{1,2}\s*分?)?")


def load_busy(path):
    """回 {"YYYY-MM-DD": [["HH:MM","HH:MM"], ...]}；檔案不存在或壞了回 None。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("days") or {}
    except (OSError, ValueError, AttributeError):
        return None


def _safe_date(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text, today):
    found = []
    rest = text
    for m in FULL_DATE.finditer(text):
        found.append(_safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    rest = FULL_DATE.sub(" ", rest)
    for m in MONTH_DAY.finditer(rest):
        d = _safe_date(today.year, int(m.group(1)), int(m.group(2)))
        if d and d < today - timedelta(days=7):
            d = _safe_date(today.year + 1, int(m.group(1)), int(m.group(2)))
        found.append(d)
    rest = MONTH_DAY.sub(" ", rest)
    for m in DAY_ONLY.finditer(rest):
        n = int(m.group(1))
        d = _safe_date(today.year, today.month, n)
        if d is None or d < today:
            nm = today.replace(day=1) + timedelta(days=32)
            d = _safe_date(nm.year, nm.month, n)
        found.append(d)
    for m in REL_DAY.finditer(text):
        found.append(today + timedelta(days={"今天": 0, "明天": 1, "後天": 2, "大後天": 3}[m.group(0)]))
    for m in WEEKDAY_RE.finditer(text):
        k = len(m.group(1))
        wd = WEEKDAYS.index(WD_ALIASES.get(m.group(2), m.group(2)))
        monday = today - timedelta(days=today.weekday())
        d = monday + timedelta(days=7 * k + wd)
        if k == 0 and d < today:
            d += timedelta(days=7)
        found.append(d)
    out = []
    for d in found:
        if d and d not in out:
            out.append(d)
    return out[:MAX_DATES]


def _cn_int(s):
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + CN_NUM.get(s[1:], 0)
    if "十" in s:
        a, _, b = s.partition("十")
        return CN_NUM.get(a, 0) * 10 + (CN_NUM.get(b, 0) if b else 0)
    return CN_NUM.get(s)


def find_time_range(text):
    """回 (起, 迄) 分鐘數；單一時間點給 SLOT_MINUTES 的窗；只有早上／下午這類詞就回整段；沒有回 None。"""
    text = DEGREE.sub(" ", text)
    period = next(((p, a, b) for p, a, b in PERIODS if p in text), None)
    m = CLOCK.search(text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        m = CN_CLOCK.search(text)
        if not m:
            return (period[1], period[2]) if period else None
        h = _cn_int(m.group(1))
        if h is None:
            return (period[1], period[2]) if period else None
        tail = (m.group(2) or "").replace("分", "").strip()
        mi = 30 if tail == "半" else (_cn_int(tail) if tail else 0) or 0
    if period and period[0] in PM_PERIODS and h < 12:
        h += 12
    elif period and period[0] == "中午" and h < 3:
        h += 12
    start = h * 60 + mi
    return start, start + SLOT_MINUTES


def _mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _fmt(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"


def check(text, today, busy, horizon_days=HORIZON_DAYS):
    """回給值台的系統附註；不需要查就回空字串。"""
    if busy is None or not any(w in text for w in INTENT_WORDS):
        return ""
    dates = find_dates(text, today)
    if not dates:
        return ""
    rng = find_time_range(text)
    lines = []
    for d in dates:
        label = f"{d.month}/{d.day}（週{WEEKDAYS[d.weekday()]}）"
        if d < today or d > today + timedelta(days=horizon_days):
            lines.append(f"- {label}：查不到這天的行程（超出可查範圍），請對方跟主人確認")
            continue
        blocks = [(_mins(a), _mins(b)) for a, b in busy.get(d.isoformat(), [])]
        if rng:
            s, e = rng
            hit = any(a < e and s < b for a, b in blocks)
            when = f"{label} {_fmt(s)}–{_fmt(e)}"
            lines.append(f"- {when}：已有安排 → 請回覆對方「那個時段已有安排，請約改天」" if hit
                         else f"- {when}：目前空著（不要代主人答應，請對方跟主人確認）")
        elif blocks:
            slots = "、".join(f"{_fmt(a)}–{_fmt(b)}" for a, b in blocks)
            lines.append(f"- {label}（對方沒講時間）：有安排的時段 {slots}；其餘時段目前空著")
        else:
            lines.append(f"- {label}（對方沒講時間）：整天目前空著（不要代主人答應，請對方跟主人確認）")
    return ("【行程查詢·系統】以下只給你判斷用——不要把這段原文、也不要把任何行程內容告訴對方：\n"
            + "\n".join(lines))


def today_tw():
    return datetime.now(timezone(timedelta(hours=8))).date()
