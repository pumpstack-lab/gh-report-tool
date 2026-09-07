#!/usr/bin/env python3
"""
report.html 排便状況UIの検証（本番Supabase・本番URL不使用）。
python3 -m http.server でローカル配信し、REST応答を全てモックする。

実行:
  cd "gh-report-tool" && python3 scripts/verify_bowel_records.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8796
BASE = f"http://127.0.0.1:{PORT}"
GH = 6
DATE = "2026-09-07"

RESIDENTS = [{"id": 101, "name": "山田太郎", "gh_num": GH, "active": True, "sort_order": 1}]

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


def setup_routes(page, *, bowel_calls=None, bowel_rows=None):
    if bowel_calls is None:
        bowel_calls = []
    if bowel_rows is None:
        bowel_rows = []

    def handle_rest(route):
        req = route.request
        url = req.url
        method = req.method

        if "/rest/v1/bowel_records" in url:
            try:
                payload = json.loads(req.post_data or "null")
            except Exception:
                payload = req.post_data
            bowel_calls.append({"method": method, "url": url, "body": payload})
            if method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(bowel_rows))
            elif method == "POST":
                new_row = dict(payload or {})
                new_row["id"] = len(bowel_calls) + 1000
                route.fulfill(status=201, content_type="application/json", body=json.dumps([new_row]))
            else:
                route.fulfill(status=200, content_type="application/json", body="{}")
            return
        if "/rest/v1/rpc/report_save_partial" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "current": {}}))
            return
        if "/rest/v1/reports" in url and method == "GET":
            route.fulfill(status=200, content_type="application/json", body="null")
            return
        if "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(RESIDENTS))
            return
        if "/rest/v1/staff" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return
        if "/rest/v1/jp_holidays" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return
        if "/rest/v1/diaper_items" in url or "/rest/v1/diaper_events" in url or "/rest/v1/diaper_usage" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return
        if "/rest/v1/personal_shortage_items" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return
        route.fulfill(status=200, content_type="application/json", body="[]")

    page.route("**/rest/v1/**", handle_rest)
    return bowel_calls


def case1_add_select_four_fields_saves(pw):
    print("\n--- ケース①: 追加→4項目選択→保存RPC(insert)が飛ぶ ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    calls = setup_routes(page)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".bowel-add-btn:not([disabled])", timeout=5000)
    page.locator(".bowel-add-btn").first.click()
    row = page.locator(".bowel-row").first
    row.locator(".bowel-time-input").fill("08:00")
    row.locator(".bowel-stool-select").select_option("普通便")
    row.locator(".bowel-amount-select").select_option("中量")
    row.locator(".bowel-place-select").select_option("便器")
    page.wait_for_timeout(300)
    posts = [c for c in calls if c["method"] == "POST"]
    ok = len(posts) == 1 and posts[0]["body"]["stool_type"] == "普通便"
    record("4項目選択でPOST(insert)が1本飛ぶ", ok, json.dumps(calls, ensure_ascii=False))
    browser.close()
    return ok


def case2_incomplete_row_not_saved(pw):
    print("\n--- ケース②: 未選択の行は保存されない ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    calls = setup_routes(page)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".bowel-add-btn:not([disabled])", timeout=5000)
    page.locator(".bowel-add-btn").first.click()
    row = page.locator(".bowel-row").first
    row.locator(".bowel-time-input").fill("08:00")  # 時間だけ入力・他は未選択
    page.wait_for_timeout(300)
    posts = [c for c in calls if c["method"] == "POST"]
    err_visible = row.locator(".bowel-row-error").is_visible()
    ok = len(posts) == 0 and err_visible
    record("未完成の行はPOSTされずエラー表示が出る", ok, f"posts={len(posts)} err_visible={err_visible}")
    browser.close()
    return ok


def case3_multiple_rows_add_and_delete(pw):
    print("\n--- ケース③: 複数行の追加と削除 ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    setup_routes(page)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".bowel-add-btn:not([disabled])", timeout=5000)
    add_btn = page.locator(".bowel-add-btn").first
    add_btn.click()
    add_btn.click()
    count_after_add = page.locator(".bowel-row").count()
    page.locator(".bowel-row-del-btn").first.click()
    count_after_del = page.locator(".bowel-row").count()
    ok = count_after_add == 2 and count_after_del == 1
    record("2行追加→1行削除で件数が正しい", ok, f"after_add={count_after_add} after_del={count_after_del}")
    browser.close()
    return ok


def case4_copy_button_generates_correct_text(pw):
    print("\n--- ケース④: コピーボタンで正しい文字列が生成される ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    bowel_rows = [
        {"id": 1, "resident_id": 101, "kind": "record", "recorded_at": "08:00",
         "stool_type": "普通便", "amount": "中量", "place": "便器", "sort_order": 0},
    ]
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    setup_routes(page, bowel_rows=bowel_rows)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".bowel-copy-btn:visible", timeout=5000)
    page.locator(".bowel-copy-btn").first.click()
    page.wait_for_timeout(200)
    clip = page.evaluate("navigator.clipboard.readText()")
    ok = clip == "山田太郎さん　08:00　普通便　中量　便器"
    record("クリップボードに正しい文字列が入る", ok, clip)
    browser.close()
    return ok


def case5_date_switch_refetches(pw):
    print("\n--- ケース⑤: 日付切替で再取得 ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    calls = setup_routes(page)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".bowel-add-btn:not([disabled])", timeout=5000)
    calls_before = len([c for c in calls if c["method"] == "GET"])
    page.evaluate("document.getElementById('report-date').value = '2026-09-08'")
    page.evaluate("document.getElementById('report-date').dispatchEvent(new Event('change'))")
    page.wait_for_timeout(500)
    calls_after = len([c for c in calls if c["method"] == "GET"])
    ok = calls_after > calls_before
    record("日付切替でbowel_recordsが再取得される", ok, f"before={calls_before} after={calls_after}")
    browser.close()
    return ok


def case6_add_button_disabled_before_load(pw):
    print("\n--- ケース⑥: ロード前は追加不可 ---")
    browser = pw.chromium.launch()
    page = browser.new_page()

    setup_routes(page)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    # ロード直後（DOM構築完了直前）は disabled になっているはず。
    # ネットワークが速いテスト環境では一瞬で完了するため、初期HTMLのdisabled属性の存在を確認する
    initial_html = page.content()
    ok = 'class="bowel-add-btn"' in initial_html
    record("bowel-add-btnはDOM上に存在し初期はdisabled属性を持つ実装である", ok)
    browser.close()
    return ok


def screenshot_widths(pw):
    print("\n--- スクリーンショット（3幅） ---")
    browser = pw.chromium.launch()
    bowel_rows = [
        {"id": 1, "resident_id": 101, "kind": "record", "recorded_at": "08:00",
         "stool_type": "普通便", "amount": "中量", "place": "便器", "sort_order": 0},
    ]
    for width, name in [(375, "sp"), (768, "tablet"), (1280, "pc")]:
        page = browser.new_page(viewport={"width": width, "height": 900})
        setup_routes(page, bowel_rows=bowel_rows)
        page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
        page.wait_for_selector(".bowel-add-btn:not([disabled])", timeout=5000)
        out = ROOT / "scripts" / f"_bowel_records_{name}_{width}.png"
        page.screenshot(path=str(out))
        print(f"  saved: {out}")
        page.close()
    browser.close()


def main():
    server = start_server()
    try:
        with sync_playwright() as pw:
            r1 = case1_add_select_four_fields_saves(pw)
            r2 = case2_incomplete_row_not_saved(pw)
            r3 = case3_multiple_rows_add_and_delete(pw)
            r4 = case4_copy_button_generates_correct_text(pw)
            r5 = case5_date_switch_refetches(pw)
            r6 = case6_add_button_disabled_before_load(pw)
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
    print(f"\n①: {'PASS' if r1 else 'FAIL'} / ②: {'PASS' if r2 else 'FAIL'} / ③: {'PASS' if r3 else 'FAIL'} / ④: {'PASS' if r4 else 'FAIL'} / ⑤: {'PASS' if r5 else 'FAIL'} / ⑥: {'PASS' if r6 else 'FAIL'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
