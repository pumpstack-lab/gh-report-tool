#!/usr/bin/env python3
"""
日付の素早い切替（先の応答が後から着く）と、読み込み中の写真 ✕ の検証（本番非接続）。
verify_report_guard.py のモック基盤をそのまま使う。

実行:
  python3 scripts/verify_date_switch_seq.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402

import verify_report_guard as base  # noqa: E402

BASE = base.BASE
GH = base.GH
DATE = base.DATE
record = base.record

FAKE_SESSION = {
    "access_token": "fake-token", "token_type": "bearer", "expires_in": 3600,
    "expires_at": int(time.time()) + 3600, "refresh_token": "fake-refresh",
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "staff@example.com"},
}


def new_page(browser):
    """ログインの門（auth_gate）を偽セッションで通す。本番には繋がない。"""
    page = base.new_page(browser)
    page.add_init_script(
        "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', "
        + json.dumps(json.dumps(FAKE_SESSION)) + ");"
    )
    page.route("**/auth/v1/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(FAKE_SESSION)))
    return page


PHOTO_REPORT = dict(base.EXISTING_REPORT)
PHOTO_REPORT["photos"] = [{"url": f"{BASE}/scripts/_guard_sp_375.png", "path": "6/2026-09-04/a.png"}]


def setup_routes_by_date(page, delays, write_requests, storage_deletes):
    """reports GET の遅延を日付ごとに変える。Storage の削除は本数を数えるだけ。"""

    def handle_rest(route):
        req = route.request
        url = req.url
        if "/rest/v1/reports" in url and req.method == "GET":
            headers = {"content-type": "application/json"}
            for d, ms in delays.items():
                if f"report_date=eq.{d}" in url and ms:
                    headers["x-mock-delay-ms"] = str(ms)
                    headers["access-control-expose-headers"] = "x-mock-delay-ms"
            row = dict(PHOTO_REPORT)
            route.fulfill(status=200, headers=headers, body=json.dumps(row))
            return
        if "/rest/v1/rpc/report_save_partial" in url:
            write_requests.append(req.url)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "current": {}}))
            return
        if "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(base.RESIDENTS))
            return
        if "/rest/v1/diaper_items" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(base.DIAPER_ITEMS))
            return
        route.fulfill(status=200, content_type="application/json", body="[]")

    def handle_storage(route):
        storage_deletes.append(route.request.method + " " + route.request.url)
        route.fulfill(status=200, content_type="application/json", body="[]")

    page.route("**/rest/v1/**", handle_rest)
    page.route("**/storage/v1/**", handle_storage)


def switch_date(page, d):
    page.evaluate(f"document.getElementById('report-date').value = '{d}'")
    page.evaluate("document.getElementById('report-date').dispatchEvent(new Event('change'))")


def case_a_fast_double_switch(pw):
    print("\n--- ケースA: 日付を素早く 2 回切り替えても、先の（遅い）応答で保存が止まらない ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes, deletes = [], []
    setup_routes_by_date(page, {}, writes, deletes)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=5000)

    page.unroute("**/rest/v1/**")
    page.unroute("**/storage/v1/**")
    # 1 回目（09-05）は 3000ms かかる・2 回目（09-06）は 300ms で返る＝先の応答が後から着く
    setup_routes_by_date(page, {"2026-09-05": 3000, "2026-09-06": 300}, writes, deletes)
    switch_date(page, "2026-09-05")
    page.wait_for_timeout(50)
    switch_date(page, "2026-09-06")

    page.wait_for_function("() => reportLoadedFor === '2026-09-06'", timeout=5000)
    record("2 回目の日付（09-06）の読み込みが先に完了する", True)

    page.wait_for_timeout(3500)  # 1 回目の遅い応答が着く時間を過ぎる
    loaded = page.evaluate("() => reportLoadedFor")
    ok_not_stale = loaded == "2026-09-06"
    record("遅い応答が着いた後も読み込み済みの日付が 09-06 のまま（先の応答は捨てられる）", ok_not_stale, f"実際: {loaded}")

    disabled = page.locator(".resident-entry textarea").first.is_disabled()
    record("入力欄が有効のまま", not disabled)

    ta = page.locator(".resident-entry textarea").first
    ta.fill("09-06 の本文")
    ta.dispatch_event("input")
    page.wait_for_timeout(3400)
    ok_saved = len(writes) >= 1
    record("その後の入力が保存される（保存リクエストが飛ぶ）", ok_saved, f"実際: {len(writes)}本")

    browser.close()
    return ok_not_stale and not disabled and ok_saved


def case_b_photo_remove_during_load(pw):
    print("\n--- ケースB: 読み込み中は写真の ✕ が押せず、Storage の削除も飛ばない ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes, deletes = [], []
    setup_routes_by_date(page, {}, writes, deletes)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=5000)
    page.wait_for_selector(".btn-remove-photo", timeout=5000)
    enabled_after_load = not page.locator(".btn-remove-photo").first.is_disabled()
    record("読み込み完了後は ✕ が押せる", enabled_after_load)

    page.unroute("**/rest/v1/**")
    page.unroute("**/storage/v1/**")
    setup_routes_by_date(page, {"2026-09-05": 3000}, writes, deletes)
    switch_date(page, "2026-09-05")
    page.wait_for_function("() => reportLoadedFor === null", timeout=5000)
    page.wait_for_timeout(200)

    btn_disabled = page.locator(".btn-remove-photo").first.is_disabled()
    record("読み込み中は ✕ が押せない（disabled）", btn_disabled)

    # 画面の disabled をすり抜けて関数を直接呼んでも、削除は飛ばない
    page.evaluate("() => removePhoto(0)")
    page.wait_for_timeout(300)
    ok_no_delete = len(deletes) == 0
    record("読み込み中に消そうとしても Storage の削除リクエストが 0 本", ok_no_delete, f"実際: {len(deletes)}本")
    n_photos = page.evaluate("() => uploadedPhotos.length")
    record("写真の一覧も減っていない", n_photos == 1, f"実際: {n_photos}枚")

    page.wait_for_function("() => reportLoadedFor === '2026-09-05'", timeout=6000)
    page.wait_for_selector(".btn-remove-photo", timeout=5000)
    btn_enabled = not page.locator(".btn-remove-photo").first.is_disabled()
    record("読み込み完了後は ✕ が再び押せる", btn_enabled)
    page.locator(".btn-remove-photo").first.click()
    page.wait_for_timeout(300)
    ok_deleted = len(deletes) == 1 and page.evaluate("() => uploadedPhotos.length") == 0
    record("読み込み完了後に押すと Storage の削除が 1 本飛び、一覧からも消える", ok_deleted, f"削除: {len(deletes)}本")

    browser.close()
    return enabled_after_load and btn_disabled and ok_no_delete and n_photos == 1 and btn_enabled and ok_deleted


def case_c_switch_right_after_open(pw):
    print("\n--- ケースC: ページを開いた直後に日付を変えても、選んだ日付が最後に残る ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes, deletes = [], []
    # 開いた時の日付（09-04）の読み込みは 3000ms かかる・選び直した 09-06 は 300ms
    setup_routes_by_date(page, {DATE: 3000, "2026-09-06": 300}, writes, deletes)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector("#report-date", timeout=5000)
    page.wait_for_timeout(300)
    switch_date(page, "2026-09-06")

    page.wait_for_timeout(4500)  # 初回の遅い応答が着いた後
    loaded = page.evaluate("() => reportLoadedFor")
    ok_user_wins = loaded == "2026-09-06"
    record("最後に残る日付が、選び直した 09-06（開いた時の 09-04 に戻らない）", ok_user_wins, f"実際: {loaded}")
    shown = page.locator("#report-date").input_value()
    record("日付欄の表示も 09-06 のまま", shown == "2026-09-06", f"実際: {shown}")
    n_ta = page.locator(".resident-entry textarea").count()
    disabled = n_ta > 0 and page.locator(".resident-entry textarea").first.is_disabled()
    record("入力欄が作られていて有効", n_ta > 0 and not disabled, f"欄: {n_ta}・disabled={disabled}")
    banner = page.locator("#load-guard-banner").evaluate("el => el.classList.contains('is-visible')")
    record("読み込み中の帯が残っていない", not banner)

    browser.close()
    return ok_user_wins and shown == "2026-09-06" and n_ta > 0 and not disabled and not banner


def main():
    server = base.start_server()
    try:
        with sync_playwright() as pw:
            ra = case_a_fast_double_switch(pw)
            rb = case_b_photo_remove_during_load(pw)
            rc = case_c_switch_right_after_open(pw)
    finally:
        server.terminate()
        server.wait(timeout=5)
    print("\n=== 結果サマリ ===")
    all_ok = all(ok for _, ok, _ in base.results)
    for name, ok, _ in base.results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\nケースA: {'PASS' if ra else 'FAIL'} / ケースB: {'PASS' if rb else 'FAIL'} / ケースC: {'PASS' if rc else 'FAIL'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
