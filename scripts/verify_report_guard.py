#!/usr/bin/env python3
"""
report.html の空上書き防止ガード検証（本番Supabase・本番URL不使用）。
python3 -m http.server でローカル配信し、REST応答を全てモックする。

実行:
  cd "gh-report-tool" && python3 -m http.server 8791 &
  python3 scripts/verify_report_guard.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"
GH = 6  # マハロ（短期入所枠あり）を使う
DATE = "2026-09-04"

RESIDENTS = [
    {"id": 101, "name": "山田太郎", "gh_num": GH, "active": True, "sort_order": 1},
    {"id": 102, "name": "佐藤花子", "gh_num": GH, "active": True, "sort_order": 2},
]

# ケース5用: loadDiaperUsage が diaper_usage への GET を実際に発行する条件
# （diaperItemIds.length > 0）を満たすため、利用者に紐づくオムツ品目を1件用意する。
# personal_shortage_items へのGET移行（2026-09-04）により、loadDateData の復元待ちを
# 遅延させる唯一の手段が diaper_usage の delay になったため必須（品目が無いと
# loadDiaperUsage が即resolveし、reportLoadedFor が復元完了前に立ってしまう）。
DIAPER_ITEMS = [
    {"id": "diaper-item-1", "resident_id": 101, "name": "テープ止め", "maker": "検証メーカー",
     "item_type": "diaper", "active": True},
]

EXISTING_REPORT = {
    "id": 1,
    "gh_num": GH,
    "gh_name": "こもれびホームマハロ",
    "report_date": DATE,
    "reporter": "旧担当者",
    "workers": [],
    "residents": {
        "山田太郎": "既存の本文（山田さん）",
        "佐藤花子": "既存の本文（佐藤さん）",
    },
    "shortage": [],
    "photos": [],
    "updated_at": "2026-09-03T00:00:00Z",
}

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def start_server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.6)
    return proc


def setup_routes(page, *, reports_delay_ms=0, reports_fail=False, report_row=None, write_requests=None, writes_delay_ms=0, restore_delay_ms=0):
    """全RESTエンドポイントをモックし、reports に対するPOST/PATCH本数を記録する配列を返す。

    ⚠️ 遅延は Python 側の time.sleep ではなく、モック応答ヘッダに遅延時間を埋め込み、
    ブラウザ側(fetch拡張)で setTimeout してから本来の処理へ渡す方式にする。
    Playwrightのsync API route.fulfill() を別スレッドから呼ぶのは未サポート
    （実測: greenlet.error が発生しテストが不安定になった）。Python側でtime.sleep()を
    直接呼ぶとIPCイベントループごと止まり page.evaluate 等の計測が壊れるため、
    どちらも避けてブラウザ側で遅延を実現する。
    """
    if write_requests is None:
        write_requests = []

    def handle_rest(route):
        req = route.request
        url = req.url
        method = req.method

        if "/rest/v1/reports" in url:
            if method == "GET":
                if reports_fail:
                    route.fulfill(status=500, body=json.dumps({"message": "mock failure"}))
                    return
                body = report_row if report_row is not None else None
                headers = {"content-type": "application/json"}
                if reports_delay_ms:
                    # supabase-jsのfetch先はモックでもcross-origin（本番URLのまま）扱いのため、
                    # カスタムヘッダはAccess-Control-Expose-Headersが無いとJS側から見えない
                    headers["x-mock-delay-ms"] = str(reports_delay_ms)
                    headers["access-control-expose-headers"] = "x-mock-delay-ms"
                route.fulfill(status=200, headers=headers, body=json.dumps(body))
                return
            if method in ("POST", "PATCH"):
                try:
                    payload = json.loads(req.post_data or "null")
                except Exception:
                    payload = req.post_data
                write_requests.append({"method": method, "url": url, "body": payload})
                body = payload if isinstance(payload, list) else [payload]
                headers = {"content-type": "application/json"}
                if writes_delay_ms:
                    headers["x-mock-delay-ms"] = str(writes_delay_ms)
                    headers["access-control-expose-headers"] = "x-mock-delay-ms"
                route.fulfill(status=201, headers=headers, body=json.dumps(body))
                return
            route.fulfill(status=200, content_type="application/json", body="[]")
            return

        if "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(RESIDENTS))
            return

        if "/rest/v1/staff" in url or "/rest/v1/jp_holidays" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return

        if "/rest/v1/diaper_items" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(DIAPER_ITEMS))
            return

        if "/rest/v1/diaper_events" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return

        if "/rest/v1/diaper_usage" in url:
            headers = {"content-type": "application/json"}
            if restore_delay_ms and method == "GET":
                headers["x-mock-delay-ms"] = str(restore_delay_ms)
                headers["access-control-expose-headers"] = "x-mock-delay-ms"
            route.fulfill(status=200, headers=headers, body="[]")
            return

        if "/rest/v1/personal_shortage" in url:
            headers = {"content-type": "application/json"}
            if restore_delay_ms and method == "GET":
                headers["x-mock-delay-ms"] = str(restore_delay_ms)
                headers["access-control-expose-headers"] = "x-mock-delay-ms"
            route.fulfill(status=200, headers=headers, body="[]")
            return

        route.fulfill(status=200, content_type="application/json", body="[]")

    page.route("**/rest/v1/**", handle_rest)
    return write_requests


# fetch を差し替え、レスポンスヘッダ x-mock-delay-ms が付いていれば
# ブラウザ側の setTimeout で遅らせてから呼び出し元へ返す。Python側では待たない。
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


def get_banner_text(page):
    return page.locator("#load-guard-banner").inner_text()


def is_banner_visible(page):
    return page.locator("#load-guard-banner").evaluate(
        "el => el.classList.contains('is-visible')"
    )


def case1_load_pending_no_overwrite(pw):
    print("\n--- ケース1: ロード完了前の入力で上書き保存されない（日付切替後の再ロード中） ---")
    # 実際の消失事故の経路: 初回 init() は residents/reports を Promise.all で同時待機するため
    # textareaは常にロード完了後にしか生成されず入力できない。危険なのは「日付切替」時。
    # loadDateData() は既存のtextarea DOMをそのまま残して disabled=true にするだけなので、
    # ロード未完了中に(誤って)有効化されたtextareaへ入力される余地が残る。ここを検証する。
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes = setup_routes(page, reports_delay_ms=0, report_row=EXISTING_REPORT)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function("() => reportLoadedFor === '2026-09-04'", timeout=5000)

    # ここから reports GET を遅延させて日付を切り替える（loadDateDataが呼ばれる経路）
    writes.clear()
    page.unroute("**/rest/v1/**")
    setup_routes(page, reports_delay_ms=3000, report_row=EXISTING_REPORT, write_requests=writes)
    page.evaluate("document.getElementById('report-date').value = '2026-09-05'")
    page.evaluate("document.getElementById('report-date').dispatchEvent(new Event('change'))")

    page.wait_for_function("() => reportLoadedFor === null", timeout=5000)
    ta = page.locator(".resident-entry textarea").first
    ta.evaluate("el => { el.disabled = false; el.value = '緊急入力テスト'; el.dispatchEvent(new Event('input', {bubbles:true})); }")

    still_pending = page.evaluate("() => reportLoadedFor === null")
    record("入力時点でロード未完了(reportLoadedFor=null)だった", still_pending)

    page.wait_for_timeout(1800)  # 800ms自動保存タイマー分待つが、reports GETはまだ返っていない(3000ms delay)
    ok_no_write = len(writes) == 0
    record("ロード完了前は保存リクエストが0本", ok_no_write, f"実際: {len(writes)}本")

    banner_visible = is_banner_visible(page)
    banner_text = get_banner_text(page) if banner_visible else ""
    record("赤の注意文「読み込み中です」が表示される", banner_visible and "読み込み中です" in banner_text, banner_text)

    ind_text = page.locator("#draft-indicator").inner_text()
    record("「保存しました」が出ていない（ロード完了前）", "保存しました" not in ind_text, ind_text)

    # ロード完了まで待つ（3000ms delay。すでに1800ms待機済みなので残りを待つ）
    page.wait_for_function(
        "() => reportLoadedFor === '2026-09-05'",
        timeout=5000,
    )
    page.wait_for_function(
        "() => !document.getElementById('load-guard-banner').classList.contains('is-visible')",
        timeout=5000,
    )
    banner_visible_after = is_banner_visible(page)
    record("ロード完了後は注意文が消える", not banner_visible_after)

    browser.close()
    return ok_no_write and banner_visible and "保存しました" not in ind_text and not banner_visible_after


def case2_normal_save_preserves_others(pw):
    print("\n--- ケース2: ロード完了後の入力は保存され、他利用者の本文が残る ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes = setup_routes(page, reports_delay_ms=0, report_row=EXISTING_REPORT)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)
    page.wait_for_function(
        "() => !document.getElementById('load-guard-banner').classList.contains('is-visible')",
        timeout=5000,
    )

    # 既存本文が復元されていることを確認
    first_val = page.locator(".resident-entry textarea").first.input_value()
    second_val_before = page.locator(".resident-entry textarea").nth(1).input_value()
    record("既存の他利用者の本文が最初から表示されている", second_val_before == "既存の本文（佐藤さん）", second_val_before)

    ta = page.locator(".resident-entry textarea").first
    ta.fill("山田さんの新しい本文")
    ta.dispatch_event("input")

    page.wait_for_timeout(1200)  # 800ms自動保存 + マージン
    ok_one_write = len(writes) == 1
    record("upsertリクエストが1本飛ぶ", ok_one_write, f"実際: {len(writes)}本")

    residents_in_body = {}
    if writes:
        body = writes[0]["body"]
        row = body[0] if isinstance(body, list) else body
        residents_in_body = row.get("residents", {})
    preserved = residents_in_body.get("佐藤花子") == "既存の本文（佐藤さん）"
    record("保存bodyに佐藤さんの既存本文が残っている（空上書きになっていない）", preserved, json.dumps(residents_in_body, ensure_ascii=False))

    updated = residents_in_body.get("山田太郎") == "山田さんの新しい本文"
    record("保存bodyに山田さんの新しい本文が入っている", updated, residents_in_body.get("山田太郎"))

    ind_text = page.locator("#draft-indicator").inner_text()
    record("「保存しました」が表示される", "保存しました" in ind_text, ind_text)

    browser.close()
    return ok_one_write and preserved and updated


def case2b_keystroke_during_inflight_save_not_lost(pw):
    print("\n--- ケース2B: 保存送信中の追加入力が消えず2本目のupsertで送信される ---")
    # dirty=false を保存成功後に立てると、送信中(await中)に打った最後の文字が
    # 「dirty=trueで新タイマーが立つ→送信成功でdirty=falseに戻される→タイマー発火時にcanSaveが
    #  cleanで保存されない」という抜け穴になる。dirty=falseは送信直前（DOM値スナップショット直後）に
    # 下ろし、成功時には触らない設計で防ぐ（2026-09-04 Getter指摘）。
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes = setup_routes(page, reports_delay_ms=0, report_row=EXISTING_REPORT, writes_delay_ms=800)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)
    page.wait_for_function(
        "() => !document.getElementById('load-guard-banner').classList.contains('is-visible')",
        timeout=5000,
    )

    ta = page.locator(".resident-entry textarea").first
    ta.fill("山田さんの本文A")
    ta.dispatch_event("input")

    # 800ms後に自動保存が始まり、upsertレスポンスはさらに800ms遅延する。
    # そのレスポンス待ち(in-flight)の間にもう1文字入力する。
    page.wait_for_timeout(1000)  # 800ms自動保存タイマー経過→1本目のupsertがinflightのはず
    ta.evaluate("el => { el.value += '追記'; el.dispatchEvent(new Event('input', {bubbles:true})); }")

    # 1本目の応答(800ms delay)が返り、2本目の自動保存(800ms後)も完了するまで待つ
    page.wait_for_timeout(2200)

    ok_two_writes = len(writes) == 2
    record("送信中の追加入力でupsertが合計2本飛ぶ", ok_two_writes, f"実際: {len(writes)}本")

    last_body = {}
    if len(writes) >= 2:
        body = writes[1]["body"]
        row = body[0] if isinstance(body, list) else body
        last_body = row.get("residents", {})
    contains_latest = last_body.get("山田太郎") == "山田さんの本文A追記"
    record("2本目のbodyに最後の文字（追記）が含まれる", contains_latest, last_body.get("山田太郎"))

    browser.close()
    return ok_two_writes and contains_latest


def case3_fetch_failure_disables_inputs(pw):
    print("\n--- ケース3: reports GET失敗で全入力欄がdisabled・赤い注意文 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, reports_fail=True)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    banner_visible = is_banner_visible(page)
    banner_text = get_banner_text(page) if banner_visible else ""
    record(
        "赤で「読み込みに失敗しました」が表示される",
        banner_visible and "読み込みに失敗しました" in banner_text,
        banner_text,
    )

    reporter_select_count = page.locator("#workers-container select").count()
    shortage_btn_disabled = page.locator("#btn-add-shortage").is_disabled()
    record("＋項目を追加ボタンがdisabled", shortage_btn_disabled)

    color = page.locator("#load-guard-banner").evaluate("el => getComputedStyle(el).color")
    record("注意文の色情報を取得できた（赤系であることの参考値）", bool(color), color)

    browser.close()
    return banner_visible and "読み込みに失敗しました" in banner_text and shortage_btn_disabled


def case4_date_switch_no_stale_save(pw):
    print("\n--- ケース4: 日付切替時、未dirtyな旧日付やロード未完了の新日付では保存が飛ばない ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes = setup_routes(page, reports_delay_ms=1500, report_row=EXISTING_REPORT)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => !document.getElementById('load-guard-banner').classList.contains('is-visible')",
        timeout=5000,
    )

    # 何も入力せず日付を切り替える → previousDate向けの保存は飛ばない（dirty=false）
    page.evaluate(f"document.getElementById('report-date').value = '2026-09-05'")
    page.evaluate("document.getElementById('report-date').dispatchEvent(new Event('change'))")
    page.wait_for_timeout(300)
    ok_no_write_on_clean_switch = len(writes) == 0
    record("入力なしでの日付切替では保存リクエストが飛ばない", ok_no_write_on_clean_switch, f"実際: {len(writes)}本")

    # 新日付（2026-09-05）はロード中（1500ms delay）。その間に入力しても保存されない
    page.wait_for_selector(".resident-entry textarea", timeout=5000)
    ta = page.locator(".resident-entry textarea").first
    ta.evaluate("el => { el.disabled = false; el.value = '新日付での緊急入力'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
    page.wait_for_timeout(1000)  # 800ms自動保存タイマー分。まだ1500ms delay中のはず
    ok_no_write_during_new_load = len(writes) == 0
    record("新日付ロード完了前の入力でも保存が飛ばない", ok_no_write_during_new_load, f"実際: {len(writes)}本")

    browser.close()
    return ok_no_write_on_clean_switch and ok_no_write_during_new_load


def case5_restore_gap_no_partial_overwrite(pw):
    print("\n--- ケース5: reports即応答でもフォーム復元(diaper)完了前は保存されない ---")
    # code-review指摘(2026-09-04): reportsのSELECT直後にreportLoadedForを立てると、
    # 復元用await（loadDiaperUsage）の隙間に打鍵された場合、
    # canSaveが真になり「半分しか復元されていないフォーム」で上書き保存が飛んでしまう
    # ＝今回防ぎたい事故そのもの。reportsは即応答・diaperだけ1.5秒遅延させ、
    # その隙間の入力で保存が飛ばないこと／復元完了後のupsert bodyに既存本文が全部残ることを検証する。
    # （personal_shortage_items は2026-09-04の蓄積型移行でGHごと1回だけ取得する方式になり、
    #  loadDateDataの復元待ちから外れたため、ここでは扱わない）
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes = setup_routes(page, reports_delay_ms=0, report_row=EXISTING_REPORT, restore_delay_ms=1500)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function("() => reportLoadedFor === '2026-09-04'", timeout=5000)

    # 日付切替でloadDateDataを起動（reportsは即応答、diaper/personal_shortageが1.5秒遅延する）
    writes.clear()
    page.unroute("**/rest/v1/**")
    setup_routes(page, reports_delay_ms=0, report_row=EXISTING_REPORT, write_requests=writes, restore_delay_ms=1500)
    page.evaluate("document.getElementById('report-date').value = '2026-09-05'")
    page.evaluate("document.getElementById('report-date').dispatchEvent(new Event('change'))")

    # reports SELECTは即返るが、復元用awaitがまだ終わっていない（reportLoadedForはnullのはず）
    page.wait_for_function("() => reportLoadedFor === null", timeout=5000)
    still_pending = page.evaluate("() => reportLoadedFor === null")
    record("reports即応答後もフォーム復元完了までreportLoadedForはnullのまま", still_pending)

    ta = page.locator(".resident-entry textarea").first
    ta.evaluate("el => { el.disabled = false; el.value = '復元中の緊急入力'; el.dispatchEvent(new Event('input', {bubbles:true})); }")

    page.wait_for_timeout(1200)  # 800ms自動保存タイマー分待つが、復元(1.5秒delay)はまだ終わっていないはず
    ok_no_write_during_restore = len(writes) == 0
    record("フォーム復元中の入力では保存リクエストが飛ばない", ok_no_write_during_restore, f"実際: {len(writes)}本")

    # 復元完了まで待つ
    page.wait_for_function("() => reportLoadedFor === '2026-09-05'", timeout=5000)
    # 復元完了時点でDOMはサーバー内容と一致しているはず（さっきの緊急入力は復元で上書きされ破棄される）
    restored_val = ta.input_value()
    record("復元完了時にDOMがサーバー内容に一致している（復元中の入力は破棄される）", restored_val == "既存の本文（山田さん）", restored_val)

    # 復元完了後にあらためて入力すると保存される。bodyに他利用者の既存本文が全部残っていること
    ta.fill("復元完了後の新しい本文")
    ta.dispatch_event("input")
    page.wait_for_timeout(1200)
    ok_one_write_after_restore = len(writes) == 1
    record("復元完了後の入力ではupsertが1本飛ぶ", ok_one_write_after_restore, f"実際: {len(writes)}本")

    residents_in_body = {}
    if writes:
        body = writes[0]["body"]
        row = body[0] if isinstance(body, list) else body
        residents_in_body = row.get("residents", {})
    preserved = residents_in_body.get("佐藤花子") == "既存の本文（佐藤さん）"
    record("復元完了後のupsert bodyに既存本文が全部残っている（佐藤さん分）", preserved, json.dumps(residents_in_body, ensure_ascii=False))

    browser.close()
    return (
        still_pending
        and ok_no_write_during_restore
        and restored_val == "既存の本文（山田さん）"
        and ok_one_write_after_restore
        and preserved
    )


def screenshot_widths(pw):
    print("\n--- スクリーンショット（3幅・赤注意文の見切れ確認） ---")
    browser = pw.chromium.launch()
    for width, name in [(375, "sp"), (768, "tablet"), (1280, "pc")]:
        page = browser.new_page(viewport={"width": width, "height": 900})
        setup_routes(page, reports_fail=True)
        page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        out = ROOT / "scripts" / f"_guard_{name}_{width}.png"
        page.screenshot(path=str(out))
        print(f"  saved: {out}")
        page.close()
    browser.close()


def main():
    server = start_server()
    try:
        with sync_playwright() as pw:
            r1 = case1_load_pending_no_overwrite(pw)
            r2 = case2_normal_save_preserves_others(pw)
            r2b = case2b_keystroke_during_inflight_save_not_lost(pw)
            r3 = case3_fetch_failure_disables_inputs(pw)
            r4 = case4_date_switch_no_stale_save(pw)
            r5 = case5_restore_gap_no_partial_overwrite(pw)
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
    print(f"\nケース1: {'PASS' if r1 else 'FAIL'} / ケース2: {'PASS' if r2 else 'FAIL'} / ケース2B: {'PASS' if r2b else 'FAIL'} / ケース3: {'PASS' if r3 else 'FAIL'} / ケース4: {'PASS' if r4 else 'FAIL'} / ケース5: {'PASS' if r5 else 'FAIL'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
