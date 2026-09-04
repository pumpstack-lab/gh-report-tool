#!/usr/bin/env python3
"""report.html の個人の希望品（蓄積型）検証（本番Supabase・本番URL不使用）。
scripts/verify_report_guard.py と同じfetchラップ手法でRESTをモックする。

実行:
  cd "gh-report-tool" && python3 -m http.server 8792 &
  python3 scripts/verify_personal_items.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8792
BASE = f"http://127.0.0.1:{PORT}"
GH = 1
DATE = "2026-09-04"

RESIDENTS = [
    {"id": 101, "name": "山田太郎", "gh_num": GH, "active": True, "sort_order": 1},
]

OPEN_ITEMS = [
    {"id": 1, "gh_num": GH, "resident_id": 101, "resident_name": "山田太郎",
     "item_text": "歯ブラシ", "requested_on": "2026-09-01", "purchased_at": None},
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


def setup_routes(page, *, items_delay_ms=0, items_fail=False, items_abort=False, items_rows=None, write_requests=None):
    if write_requests is None:
        write_requests = []
    if items_rows is None:
        items_rows = OPEN_ITEMS

    def handle_rest(route):
        req = route.request
        url = req.url
        method = req.method

        if "/rest/v1/personal_shortage_items" in url:
            if method == "GET":
                if items_abort:
                    # fetch() 自体を失敗させる（ネットワーク例外・supabase-js内部エラー相当）。
                    # items_fail=True（HTTP 500応答）とは別経路: こちらは {data, error} すら返らず
                    # await が reject する。loadPersonalItemsOnce() の try/catch を検証する。
                    route.abort("failed")
                    return
                if items_fail:
                    route.fulfill(status=500, body=json.dumps({"message": "mock failure"}))
                    return
                headers = {"content-type": "application/json"}
                if items_delay_ms:
                    headers["x-mock-delay-ms"] = str(items_delay_ms)
                    headers["access-control-expose-headers"] = "x-mock-delay-ms"
                route.fulfill(status=200, headers=headers, body=json.dumps(items_rows))
                return
            if method == "POST":
                try:
                    payload = json.loads(req.post_data or "null")
                except Exception:
                    payload = req.post_data
                write_requests.append({"method": method, "url": url, "body": payload})
                body = payload if isinstance(payload, list) else [payload]
                # INSERT応答: idを補完して返す（フロントがリスト末尾に追加する際に使う想定）
                for row in body:
                    row.setdefault("id", 999)
                route.fulfill(status=201, content_type="application/json", body=json.dumps(body))
                return
            route.fulfill(status=200, content_type="application/json", body="[]")
            return

        if "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(RESIDENTS))
            return

        if "/rest/v1/reports" in url:
            route.fulfill(status=200, content_type="application/json", body="null" if method == "GET" else "[]")
            return

        if "/rest/v1/staff" in url or "/rest/v1/jp_holidays" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return

        if "/rest/v1/diaper_items" in url or "/rest/v1/diaper_events" in url or "/rest/v1/diaper_usage" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return

        route.fulfill(status=200, content_type="application/json", body="[]")

    page.route("**/rest/v1/**", handle_rest)
    return write_requests


DELAY_INIT_SCRIPT = """
(() => {
  const origFetch = window.fetch;
  window.fetch = async (...args) => {
    const res = await origFetch(...args);
    const delay = res.headers.get('x-mock-delay-ms');
    if (delay) {
      await new Promise(r => setTimeout(r, parseInt(delay, 10)));
    }
    return res;
  };
})();
"""


def new_page(browser):
    page = browser.new_page()
    page.add_init_script(DELAY_INIT_SCRIPT)
    return page


def case1_add_disabled_until_loaded_then_insert(pw):
    print("\n--- ケース1: 取得遅延中は追加不可→完了後に追加→INSERT本文が正しい→リストに出る ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes = setup_routes(page, items_delay_ms=2000, items_rows=OPEN_ITEMS)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")

    page.wait_for_selector(".personal-items-block", timeout=5000)
    add_btn = page.locator(".personal-items-block .btn-add-personal-item").first
    disabled_while_loading = add_btn.is_disabled()
    record("取得遅延中は追加ボタンがdisabled", disabled_while_loading)

    page.wait_for_function(
        "() => !document.querySelector('.personal-items-block .btn-add-personal-item').disabled",
        timeout=5000,
    )
    listed_before = page.locator(".personal-items-block .personal-item-row").count()
    record("取得完了後、既存の未購入品目（歯ブラシ）が読み取り専用で表示される",
           listed_before >= 1, f"件数={listed_before}")

    input_el = page.locator(".personal-items-block .personal-item-input").first
    input_el.fill("検証用タオル")
    page.locator(".personal-items-block .btn-add-personal-item").first.click()
    page.wait_for_timeout(600)

    ok_one_write = len(writes) == 1
    record("追加でINSERTが1本飛ぶ", ok_one_write, f"実際: {len(writes)}本")

    body = writes[0]["body"] if writes else {}
    row = body[0] if isinstance(body, list) else body
    ok_body = (
        row.get("resident_id") == 101
        and row.get("resident_name") == "山田太郎"
        and row.get("item_text") == "検証用タオル"
        and row.get("gh_num") == GH
    )
    record("INSERT本文にresident_id(数値)/resident_name/item_text/gh_numが正しく入る", ok_body, json.dumps(row, ensure_ascii=False))
    ok_resident_id_numeric = isinstance(row.get("resident_id"), int)
    record("resident_idが数値型で送られる（文字列/数値の二重キーバグの再発防止）", ok_resident_id_numeric, str(type(row.get("resident_id"))))

    input_cleared = input_el.input_value() == ""
    record("追加成功で入力欄がクリアされる", input_cleared)

    listed_after = page.locator(".personal-items-block .personal-item-row").count()
    record("追加後、リスト末尾に新しい品目が出る", listed_after == listed_before + 1, f"{listed_before}→{listed_after}")

    browser.close()
    return disabled_while_loading and ok_one_write and ok_body and ok_resident_id_numeric and input_cleared and listed_after == listed_before + 1


def case2_load_failure_shows_red_banner(pw):
    print("\n--- ケース2: 取得失敗で赤帯・追加不可 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, items_fail=True)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    banner = page.locator(".personal-items-block .personal-items-unavailable-msg").first
    banner_visible = banner.is_visible()
    banner_text = banner.inner_text() if banner_visible else ""
    record("赤帯「希望品を読み込めませんでした」が表示される",
           banner_visible and "読み込めませんでした" in banner_text, banner_text)

    add_disabled = page.locator(".personal-items-block .btn-add-personal-item").first.is_disabled()
    record("取得失敗時は追加ボタンがdisabled", add_disabled)

    browser.close()
    return banner_visible and "読み込めませんでした" in banner_text and add_disabled


def case2b_load_exception_shows_red_banner(pw):
    print("\n--- ケース2b: 取得が例外(ネットワークエラー等)で失敗しても赤帯・追加不可 ---")
    # 2026-09-04 code-review指摘: {error}を返さず例外を投げた場合、未処理rejectionになり
    # 追加ボタンが永久にdisabledのまま赤帯も出ない事故になる。loadPersonalItemsOnce()の
    # try/catchで既存の失敗経路(personalItemsUnavailable=true)に合流することを検証する。
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, items_abort=True)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    # ネットワーク例外はブラウザ側で指数バックオフ再試行が入るため確定まで数秒かかる
    # （実測: 1s/2s/4s間隔で再試行し約7〜8秒で確定）。固定sleepではなく状態変化を待つ。
    page.wait_for_function("() => personalItemsUnavailable === true", timeout=15000)

    banner = page.locator(".personal-items-block .personal-items-unavailable-msg").first
    banner_visible = banner.is_visible()
    banner_text = banner.inner_text() if banner_visible else ""
    record("例外発生時も赤帯「希望品を読み込めませんでした」が表示される",
           banner_visible and "読み込めませんでした" in banner_text, banner_text)

    add_disabled = page.locator(".personal-items-block .btn-add-personal-item").first.is_disabled()
    record("例外発生時も追加ボタンがdisabled", add_disabled)

    browser.close()
    return banner_visible and "読み込めませんでした" in banner_text and add_disabled


def case3_date_switch_does_not_refetch(pw):
    print("\n--- ケース3: 日付切替で個人の希望品は再取得されない（GHごと1回のみ） ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes = setup_routes(page, items_rows=OPEN_ITEMS)
    fetch_count = {"n": 0}
    page.expose_binding("__noop", lambda source: None)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".personal-items-block .personal-item-row", timeout=5000)

    # ネットワークログでpersonal_shortage_itemsへのGET回数を数える
    counts = {"n": 0}
    def on_request(req):
        if "/rest/v1/personal_shortage_items" in req.url and req.method == "GET":
            counts["n"] += 1
    page.on("request", on_request)

    page.evaluate("document.getElementById('report-date').value = '2026-09-05'")
    page.evaluate("document.getElementById('report-date').dispatchEvent(new Event('change'))")
    page.wait_for_timeout(1000)

    record("日付切替でpersonal_shortage_itemsへのGETが発生しない", counts["n"] == 0, f"実際: {counts['n']}回")

    browser.close()
    return counts["n"] == 0


def case4_duplicate_item_name_blocked(pw):
    print("\n--- ケース4: 同名（trim後完全一致）の重複追加はINSERTせず「すでに登録されています」 ---")
    # ネイト精査指摘（2026-09-04）: サーバー側にunique制約が無いため、フロント側で
    # 未購入リストとの完全一致を見て重複INSERTを防ぐ。入力値は残す。
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes = setup_routes(page, items_rows=OPEN_ITEMS)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".personal-items-block .personal-item-row", timeout=5000)

    input_el = page.locator(".personal-items-block .personal-item-input").first
    add_btn = page.locator(".personal-items-block .btn-add-personal-item").first

    # 既存の未購入品目「歯ブラシ」と同じ名前を追加しようとする
    input_el.fill("歯ブラシ")
    add_btn.click()
    page.wait_for_timeout(400)

    ok_no_insert = len(writes) == 0
    record("同名追加でINSERTが飛ばない", ok_no_insert, f"実際: {len(writes)}本")

    err = page.locator(".personal-items-block .personal-item-add-error").first
    err_visible = err.is_visible()
    err_text = err.inner_text() if err_visible else ""
    record("「すでに登録されています」が表示される",
           err_visible and "すでに登録されています" in err_text, err_text)

    input_preserved = input_el.input_value() == "歯ブラシ"
    record("重複エラー時は入力値が残る", input_preserved, input_el.input_value())

    browser.close()
    return ok_no_insert and err_visible and "すでに登録されています" in err_text and input_preserved


def screenshot_widths(pw):
    print("\n--- スクリーンショット（3幅） ---")
    browser = pw.chromium.launch()
    for width, name in [(375, "sp"), (768, "tablet"), (1280, "pc")]:
        page = new_page(browser)
        page.set_viewport_size({"width": width, "height": 900})
        setup_routes(page, items_rows=OPEN_ITEMS)
        page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        out = ROOT / "scripts" / f"_personal_items_{name}_{width}.png"
        page.screenshot(path=str(out))
        print(f"  saved: {out}")
        page.close()
    browser.close()


def main():
    server = start_server()
    try:
        with sync_playwright() as pw:
            r1 = case1_add_disabled_until_loaded_then_insert(pw)
            r2 = case2_load_failure_shows_red_banner(pw)
            r2b = case2b_load_exception_shows_red_banner(pw)
            r3 = case3_date_switch_does_not_refetch(pw)
            r4 = case4_duplicate_item_name_blocked(pw)
            screenshot_widths(pw)
    finally:
        server.terminate()
        server.wait(timeout=5)

    print("\n=== 結果サマリ ===")
    all_ok = True
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            all_ok = False
    print(f"\nケース1: {'PASS' if r1 else 'FAIL'} / ケース2: {'PASS' if r2 else 'FAIL'} / "
          f"ケース2b: {'PASS' if r2b else 'FAIL'} / ケース3: {'PASS' if r3 else 'FAIL'} / "
          f"ケース4: {'PASS' if r4 else 'FAIL'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
