#!/usr/bin/env python3
"""
report.html 本文消失バグの検証（2026-09-15）。本番Supabase・本番URLは一切使わない。
python3 -m http.server でローカル配信し、REST/RPC応答を全てモックする。

背景（本番 reports_history 実測・9/4〜9/15）:
  本文の消失/大幅短縮を13件検出（EMPTIED 5件・SHRUNK 8件）。原因は2つ。
  ① 保存成功パスでも applyServerState を「取り込み」の意味で呼んでいたため
     lastSaved が永久に進まず、同じ欄の2回目以降の保存が必ず偽の競合になっていた。
  ② applyDeferredOrImmediate が result.current の全キーを textarea へ書き戻していたため、
     保存の往復中に打った文字が送信時スナップショットへ巻き戻っていた。

実行:
  cd "gh-report-tool" && python3 scripts/verify_report_no_data_loss.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8793
BASE = f"http://127.0.0.1:{PORT}"
GH = 6
DATE = "2026-09-05"

RESIDENTS = [
    {"id": 101, "name": "山田太郎", "gh_num": GH, "active": True, "sort_order": 1},
    {"id": 102, "name": "佐藤花子", "gh_num": GH, "active": True, "sort_order": 2},
]

FAKE_SESSION = {
    "access_token": "fake-token",
    "token_type": "bearer",
    "expires_in": 3600,
    "expires_at": int(time.time()) + 3600,
    "refresh_token": "fake-refresh",
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "staff@example.com"},
}

EXISTING_REPORT = {
    "id": 1, "gh_num": GH, "gh_name": "こもれびホームマハロ", "report_date": DATE,
    "reporter": "", "workers": [],
    "residents": {"山田太郎": "既存A", "佐藤花子": "既存B"},
    "shortage": "[]", "photos": [],
    "updated_at": "2026-09-05T00:00:00.000000+00:00",
}

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def start_server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.8)
    return proc


def setup_routes(page, rpc_calls, pending_routes, auto_responses):
    """RPCは auto_responses があれば即答、無ければ route を保留して手動で答える。"""
    def handle_rest(route):
        req = route.request
        url = req.url
        if "/rest/v1/rpc/report_save_partial" in url:
            try:
                payload = json.loads(req.post_data or "null")
            except Exception:
                payload = req.post_data
            rpc_calls.append(payload)
            if auto_responses:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(auto_responses.pop(0)))
            else:
                pending_routes.append(route)
            return
        if "/rest/v1/reports" in url and req.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(EXISTING_REPORT))
            return
        if "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(RESIDENTS))
            return
        route.fulfill(status=200, content_type="application/json", body="[]")

    page.route("**/rest/v1/**", handle_rest)


def open_page(browser, rpc_calls, pending_routes, auto_responses):
    page = browser.new_page()
    page.on("dialog", lambda d: d.accept())  # 競合の破壊的操作はconfirmを挟む
    # ログイン画面（2026-09-09導入）を通すため、supabase-js v2 のセッションを先に置く
    page.add_init_script(
        "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', "
        + json.dumps(json.dumps(FAKE_SESSION)) + ");"
    )
    page.route("**/auth/v1/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(FAKE_SESSION)))
    setup_routes(page, rpc_calls, pending_routes, auto_responses)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=8000)
    return page


def type_into(ta, text):
    ta.fill(text)
    ta.dispatch_event("input")


def case1_no_false_conflict(pw):
    """①同じ欄に2回続けて書いても偽の競合にならない（2回目のbaseがサーバー現在値）。"""
    print("\n--- ケース①: 同じ欄を続けて書いても偽の競合が出ない ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    auto = [
        {"ok": True, "current": {"residents": {"山田太郎": "一回目", "佐藤花子": "既存B"},
                                 "reporter": "", "workers": [], "photos": [], "shortage": "[]"}},
        {"ok": True, "current": {"residents": {"山田太郎": "一回目二回目", "佐藤花子": "既存B"},
                                 "reporter": "", "workers": [], "photos": [], "shortage": "[]"}},
    ]
    page = open_page(browser, calls, pending, auto)
    ta = page.locator(".resident-entry textarea").first

    type_into(ta, "一回目")
    page.wait_for_timeout(3600)
    type_into(ta, "一回目二回目")
    page.wait_for_timeout(3600)

    ok_two = len(calls) == 2
    record("保存RPCが2本飛ぶ", ok_two, f"実際: {len(calls)}本")

    base2 = (calls[1].get("p_base") or {}).get("residents", {}) if len(calls) >= 2 else {}
    ok_base = base2.get("山田太郎") == "一回目"
    record("2回目のbaseがサーバー現在値『一回目』になっている（偽の競合を出さない）",
           ok_base, json.dumps(base2, ensure_ascii=False))

    no_banner = page.locator(".resident-entry .conflict-banner").count() == 0
    record("競合バナーが出ていない", no_banner)

    browser.close()
    return ok_two and ok_base and no_banner


def case2_no_revert_during_roundtrip(pw):
    """②保存の往復中に打った文字が、応答処理で巻き戻らない。"""
    print("\n--- ケース②: 保存の往復中に打った文字が巻き戻らない ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    page = open_page(browser, calls, pending, [])
    ta_a = page.locator(".resident-entry textarea").first
    ta_b = page.locator(".resident-entry textarea").nth(1)

    type_into(ta_a, "既存A追記")
    page.wait_for_timeout(3600)
    ok_inflight = len(pending) == 1
    record("保存RPCが飛んで応答待ちになっている", ok_inflight, f"保留数: {len(pending)}")
    if not ok_inflight:
        browser.close()
        return False

    # 往復中に職員が書き足し、別の利用者欄へ移る（Aはフォーカスを失い無防備になる）
    type_into(ta_a, "既存A追記さらに追記")
    ta_b.focus()

    pending[0].fulfill(status=200, content_type="application/json", body=json.dumps(
        {"ok": True, "current": {"residents": {"山田太郎": "既存A追記", "佐藤花子": "他端末が書いたB"},
                                 "reporter": "", "workers": [], "photos": [], "shortage": "[]"}}))
    page.wait_for_timeout(800)

    a_val = ta_a.input_value()
    ok_a = a_val == "既存A追記さらに追記"
    record("往復中に打った文字が残っている（送信時スナップショットへ巻き戻らない）", ok_a, a_val)

    # 応答が返った時点でBは入力中（フォーカス中）なので、書き換えずに保留する
    b_val_focused = ta_b.input_value()
    ok_b_focused = b_val_focused == "既存B"
    record("入力中の欄は応答が来ても書き換えない", ok_b_focused, b_val_focused)

    # フォーカスを外したら、保留していた他端末の内容が入る
    ta_b.evaluate("el => el.blur()")
    page.wait_for_timeout(300)
    b_val = ta_b.input_value()
    ok_b = b_val == "他端末が書いたB"
    record("フォーカス離脱後に他端末の内容を取り込む", ok_b, b_val)

    browser.close()
    return ok_a and ok_b_focused and ok_b


def case3_merge_keeps_both(pw):
    """③競合時に『両方残す』で双方の記録が失われない。"""
    print("\n--- ケース③: 競合時に『両方残す』で双方が残る ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    auto = [
        {"ok": False, "conflicts": {"residents": ["山田太郎"]},
         "current": {"residents": {"山田太郎": "他端末が書いた本文", "佐藤花子": "既存B"},
                     "reporter": "", "workers": [], "photos": [], "shortage": "[]"}},
        {"ok": True, "current": {"residents": {"山田太郎": "他端末が書いた本文\n自分が書いた本文", "佐藤花子": "既存B"},
                                 "reporter": "", "workers": [], "photos": [], "shortage": "[]"}},
    ]
    page = open_page(browser, calls, pending, auto)
    ta = page.locator(".resident-entry textarea").first

    type_into(ta, "自分が書いた本文")
    page.wait_for_timeout(3600)

    has_banner = page.locator(".resident-entry .conflict-banner").count() == 1
    record("本物の競合ではバナーが出る", has_banner)

    has_merge = page.locator(".btn-conflict-merge").count() == 1
    record("『両方残す』ボタンがある", has_merge)
    if not (has_banner and has_merge):
        browser.close()
        return False

    page.locator(".btn-conflict-merge").first.click()
    merged = ta.input_value()
    ok_merged = "他端末が書いた本文" in merged and "自分が書いた本文" in merged
    record("画面に双方の本文が残る", ok_merged, merged.replace("\n", " / "))

    page.wait_for_timeout(3600)
    ok_sent = len(calls) == 2
    record("合体した本文の保存RPCが飛ぶ", ok_sent, f"実際: {len(calls)}本")

    sent_val = ""
    base_val = None
    if len(calls) >= 2:
        sent_val = (calls[1].get("p_patch") or {}).get("residents", {}).get("山田太郎", "")
        base_val = (calls[1].get("p_base") or {}).get("residents", {}).get("山田太郎")
    ok_payload = "他端末が書いた本文" in sent_val and "自分が書いた本文" in sent_val
    record("送信内容に双方の本文が入っている", ok_payload, sent_val.replace("\n", " / "))
    ok_base = base_val == "他端末が書いた本文"
    record("baseがサーバー現在値になっている（CASを通る）", ok_base, str(base_val))

    browser.close()
    return ok_merged and ok_sent and ok_payload and ok_base


def main():
    proc = start_server()
    try:
        with sync_playwright() as pw:
            oks = [case1_no_false_conflict(pw), case2_no_revert_during_roundtrip(pw), case3_merge_keeps_both(pw)]
    finally:
        proc.terminate()

    print("\n=== 結果 ===")
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed or not all(oks) else 0


if __name__ == "__main__":
    sys.exit(main())
