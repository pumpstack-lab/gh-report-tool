#!/usr/bin/env python3
"""
report.html の勤務種別・前日基準判定の検証（本番Supabase・本番URL不使用）。
python3 -m http.server でローカル配信し、REST応答を全てモックする。

実行:
  cd "gh-report-tool" && python3 scripts/verify_worktype_prevday.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8794
BASE = f"http://127.0.0.1:{PORT}"
GH = 6
DATE = "2026-08-16"  # 日曜（前日8/15は土曜=休日）

RESIDENTS = [{"id": 101, "name": "山田太郎", "gh_num": GH, "active": True, "sort_order": 1}]

STAFF = [
    {"id": "staff-201", "last_name": "石田", "first_name": "花子", "staff_type": "sewanin", "sort_order": 1, "active": True},
]

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def start_server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.6)
    return proc


def setup_routes(page, *, holidays=None, report_row=None):
    if holidays is None:
        holidays = []
    if report_row is None:
        report_row = None

    def handle_rest(route):
        url = route.request.url
        method = route.request.method
        if "/rest/v1/rpc/report_save_partial" in url:
            route.fulfill(status=200, content_type="application/json",
                           body=json.dumps({"ok": True, "current": {}}))
            return
        if "/rest/v1/reports" in url and method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(report_row))
            return
        if "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(RESIDENTS))
            return
        if "/rest/v1/staff" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(STAFF))
            return
        if "/rest/v1/jp_holidays" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(holidays))
            return
        if "/rest/v1/diaper_items" in url or "/rest/v1/diaper_events" in url or "/rest/v1/diaper_usage" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return
        if "/rest/v1/personal_shortage_items" in url or "/rest/v1/bowel_records" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return
        route.fulfill(status=200, content_type="application/json", body="[]")

    page.route("**/rest/v1/**", handle_rest)


def case1_indicator_shows_prev_day(pw):
    print("\n--- ケース①: 報告日を変えると「◯月◯日(◯)の勤務です」が前日で更新される ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    setup_routes(page, holidays=[])
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)
    text = page.locator("#holiday-indicator").inner_text()
    # DATE=2026-08-16(日)の前日は2026-08-15(土)＝休日
    ok = "8月15日" in text and "休園日" in text
    record("前日(8/15・休園日)が表示される", ok, text)
    browser.close()
    return ok


def case2_saturday_prev_day_warns_weekday_night(pw):
    print("\n--- ケース②: 土曜の前日を持つ報告でweekday_nightを選ぶと警告が出る ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    setup_routes(page, holidays=[])
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)

    page.once("dialog", lambda d: d.accept())  # confirm()を確定で受ける
    page.locator("#btn-add-worker").click()
    selects = page.locator("#workers-container select")
    selects.nth(0).select_option("staff-201")
    selects.nth(1).select_option("weekday_night")
    page.wait_for_timeout(200)

    warn_text = page.locator("#workers-container").inner_text()
    # 警告文言中の勤務日はWorktypeRules.shiftBaseDateの戻り値そのまま(YYYY-MM-DD)で表示される
    ok = "⚠️" in warn_text and "2026-08-15" in warn_text
    record("weekday_night選択で警告と勤務日(2026-08-15)が出る", ok, warn_text)
    browser.close()
    return ok


def case3_closed_day_registered_makes_weekday_holiday(pw):
    print("\n--- ケース③: 休園日を登録すると平日でも休日扱いになる ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    # 2026-08-18(火)を報告日にすると前日は2026-08-17(月・平日)。
    # 8/17を休園日として登録すると休日扱いになるはず
    setup_routes(page, holidays=[{"holiday_date": "2026-08-17", "kind": "closed"}])
    page.goto(f"{BASE}/report.html?gh={GH}&date=2026-08-18", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)
    text = page.locator("#holiday-indicator").inner_text()
    ok = "8月17日" in text and "休園日" in text
    record("休園日登録済みの前日が休園日表示になる", ok, text)
    browser.close()
    return ok


def screenshot_widths(pw):
    print("\n--- スクリーンショット（3幅） ---")
    browser = pw.chromium.launch()
    for width, name in [(375, "sp"), (768, "tablet"), (1280, "pc")]:
        page = browser.new_page(viewport={"width": width, "height": 900})
        setup_routes(page, holidays=[])
        page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
        page.wait_for_selector(".resident-entry textarea", timeout=5000)
        out = ROOT / "scripts" / f"_worktype_prevday_{name}_{width}.png"
        page.screenshot(path=str(out))
        print(f"  saved: {out}")
        page.close()
    browser.close()


def main():
    server = start_server()
    try:
        with sync_playwright() as pw:
            r1 = case1_indicator_shows_prev_day(pw)
            r2 = case2_saturday_prev_day_warns_weekday_night(pw)
            r3 = case3_closed_day_registered_makes_weekday_holiday(pw)
            screenshot_widths(pw)
    finally:
        server.terminate()
        server.wait(timeout=5)

    print("\n=== 結果サマリ ===")
    all_ok = True
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}")
        if not ok:
            all_ok = False
    print(f"\n①: {'PASS' if r1 else 'FAIL'} / ②: {'PASS' if r2 else 'FAIL'} / ③: {'PASS' if r3 else 'FAIL'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
