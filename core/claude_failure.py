# -*- coding: utf-8 -*-
"""claude_failure.py — 把 `claude -p` 的失敗分成值台講得出口的話。

為什麼有這個檔：
  2026-09-10 → 09-13 訂閱額度用完，CLI 以 rc=1 結束、stderr 空白，
  原因只寫在 stdout JSON 的 result 欄：「You've hit your limit · resets Sep 13 at 3pm (Asia/Taipei)」。
  bridge 只記 stderr，所以 log 上 8 則全是 `CLAUDE_ERROR rc=1 stderr=`，
  LINE 上只回「本體呼叫失敗」，主人在 LINE 問「沒有額度了嗎？」也沒人答得出來。

純函式、零依賴，tests/test_claude_failure.py 有測。
"""
import re

GENERIC_REPLY = "（本體呼叫失敗，稍後再試或檢查 line_bridge.log）"
# 呼叫端沒給主人名時的中性稱呼（kit 泛用化：本檔不得出現任何特定人名）。
DEFAULT_OWNER = "主人"

# 只認訂閱額度用盡的字樣；API 429 之類幾秒就過的不算
_LIMIT_PAT = re.compile(r"hit your limit|usage limit|limit reached", re.I)
_RESET_PAT = re.compile(r"\bresets?\s+(.+)$", re.I)


def is_limit_text(text):
    """result 文字是不是「額度用完」。"""
    return bool(text) and bool(_LIMIT_PAT.search(text))


def limit_reply(text, owner=DEFAULT_OWNER):
    """額度用盡的話術。owner 由呼叫端傳入（line_bridge 給 kit_config 的 owner_name）——
    本檔是要隨 kit 出貨給客戶的，寫死任何一個人的名字都會出現在別人的產品裡。"""
    m = _RESET_PAT.search((text or "").strip())
    when = m.group(1).strip() if m else "Anthropic 沒有說"
    return ("【通道】值台的 Claude 額度用完了，暫時回不了話。\n"
            f"恢復時間：{when}\n"
            "這段期間的訊息都有收到、都有留紀錄。\n"
            f"急事請直接聯絡{owner or DEFAULT_OWNER}本人。")


def classify_failure(returncode, result_text, stderr, is_error=False, owner=DEFAULT_OWNER):
    """回 (kind, reply)。kind ∈ {"limit", "unknown"}。

    returncode / stderr 目前只留作日後分類用；額度判斷看 result 文字。
    """
    text = (result_text or "").strip()
    if is_limit_text(text):
        return "limit", limit_reply(text, owner)
    return "unknown", GENERIC_REPLY
