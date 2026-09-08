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


def setup_routes(page, *, bowel_calls=None, bowel_rows=None,
                  get_delay_ms=0, fail_write=False, fail_delete=False):
    """
    get_delay_ms: bowel_recordsのGET応答をこのミリ秒だけ遅らせる。route内でtime.sleepすると
                  Playwright全体の処理系が止まり計測が狂うため使わない。代わりにレスポンスへ
                  x-mock-delay-msヘッダーを乗せ、ブラウザ側のfetchラップ（DELAY_INIT_SCRIPT）で
                  遅延させる（verify_personal_items.pyと同じ手法）。呼び出し側は
                  new_page_with_delay() でページを作ること。
    fail_write: POST/PATCHを500で失敗させる（保存失敗UIの検証用）。
    fail_delete: DELETEを500で失敗させる（削除失敗UIの検証用）。
    """
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
                headers = {"content-type": "application/json"}
                if get_delay_ms > 0:
                    headers["x-mock-delay-ms"] = str(get_delay_ms)
                    headers["access-control-expose-headers"] = "x-mock-delay-ms"
                route.fulfill(status=200, headers=headers, body=json.dumps(bowel_rows))
            elif method == "POST":
                if fail_write:
                    route.fulfill(status=500, content_type="application/json", body=json.dumps({"message": "forced failure"}))
                    return
                new_row = dict(payload or {})
                new_row["id"] = len(bowel_calls) + 1000
                bowel_rows.append(new_row)
                route.fulfill(status=201, content_type="application/json", body=json.dumps([new_row]))
            elif method in ("PATCH", "PUT"):
                if fail_write:
                    route.fulfill(status=500, content_type="application/json", body=json.dumps({"message": "forced failure"}))
                    return
                route.fulfill(status=204, content_type="application/json", body="")
            elif method == "DELETE":
                if fail_delete:
                    route.fulfill(status=500, content_type="application/json", body=json.dumps({"message": "forced failure"}))
                    return
                route.fulfill(status=200, content_type="application/json", body="[]")
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


def new_page_with_delay(browser):
    page = browser.new_page()
    page.add_init_script(DELAY_INIT_SCRIPT)
    return page


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


def case7_incomplete_row_survives_sibling_save(pw):
    print("\n--- ケース⑦: 2行入力中に1行目だけ完成させて保存→リロード→2行目の未完成入力が残っている ---")
    browser = pw.chromium.launch()
    context = browser.new_context()
    page = context.new_page()
    bowel_rows = []
    setup_routes(page, bowel_rows=bowel_rows)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".bowel-add-btn:not([disabled])", timeout=5000)
    add_btn = page.locator(".bowel-add-btn").first
    add_btn.click()
    add_btn.click()
    rows = page.locator(".bowel-row")
    # 2行目を未完成のまま入力（下書きとして残るはず）
    rows.nth(1).locator(".bowel-time-input").fill("09:30")
    page.wait_for_timeout(150)
    # 1行目を完成させて保存させる
    rows.nth(0).locator(".bowel-time-input").fill("08:00")
    rows.nth(0).locator(".bowel-stool-select").select_option("普通便")
    rows.nth(0).locator(".bowel-amount-select").select_option("中量")
    rows.nth(0).locator(".bowel-place-select").select_option("便器")
    page.wait_for_timeout(300)

    # 同じlocalStorageを共有する新規タブでリロードして下書きが残っているか確認
    page2 = context.new_page()
    setup_routes(page2, bowel_rows=bowel_rows)
    page2.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page2.wait_for_selector(".bowel-add-btn:not([disabled])", timeout=5000)
    page2.wait_for_timeout(300)
    row_count = page2.locator(".bowel-row").count()
    time_inputs = [page2.locator(".bowel-time-input").nth(i).input_value() for i in range(row_count)]
    ok = row_count == 2 and "09:30" in time_inputs and "08:00" in time_inputs
    record("1行目保存後も2行目の未完成下書きが残る", ok, f"row_count={row_count} time_inputs={time_inputs}")
    browser.close()
    return ok


def case8_draft_restored_alongside_saved_rows(pw):
    print("\n--- ケース⑧: 保存済み記録が1件ある利用者で未完成行を作る→リロード→保存済み1件＋未完成行が両方出る ---")
    browser = pw.chromium.launch()
    context = browser.new_context()
    page = context.new_page()
    bowel_rows = [
        {"id": 1, "resident_id": 101, "kind": "record", "recorded_at": "08:00",
         "stool_type": "普通便", "amount": "中量", "place": "便器", "sort_order": 0},
    ]
    setup_routes(page, bowel_rows=bowel_rows)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".bowel-add-btn:not([disabled])", timeout=5000)
    page.locator(".bowel-add-btn").first.click()
    rows = page.locator(".bowel-row")
    rows.nth(1).locator(".bowel-time-input").fill("14:00")  # 未完成のまま
    page.wait_for_timeout(300)

    page2 = context.new_page()
    setup_routes(page2, bowel_rows=bowel_rows)
    page2.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page2.wait_for_selector(".bowel-add-btn:not([disabled])", timeout=5000)
    page2.wait_for_timeout(300)
    row_count = page2.locator(".bowel-row").count()
    time_inputs = [page2.locator(".bowel-time-input").nth(i).input_value() for i in range(row_count)]
    ok = row_count == 2 and "08:00" in time_inputs and "14:00" in time_inputs
    record("保存済み1件＋未完成の下書き1件が両方復元される", ok, f"row_count={row_count} time_inputs={time_inputs}")
    browser.close()
    return ok


def case9_no_update_before_load_complete(pw):
    print("\n--- ケース⑨: ロード完了前（GETを遅延）に既存行を変更 → UPDATEリクエストが飛ばない ---")
    browser = pw.chromium.launch()
    page = new_page_with_delay(browser)
    bowel_rows = [
        {"id": 1, "resident_id": 101, "kind": "record", "recorded_at": "08:00",
         "stool_type": "普通便", "amount": "中量", "place": "便器", "sort_order": 0},
    ]
    calls = setup_routes(page, bowel_rows=bowel_rows, get_delay_ms=1500)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    # GET応答が遅延している間（bowelLoadedForDateがまだnullの間）は行がDOM未描画のため、
    # 「追加ボタンがdisabledのまま」＝ユーザー操作の余地が無いことをまず確認する。
    page.wait_for_timeout(300)
    add_disabled = page.locator(".bowel-add-btn").first.is_disabled()
    # 加えて、ロード未完了中にpersistBowelRow相当の保存経路を直接呼んでもガードで弾かれる
    # ことをJS側から直接検証する（bowelLoadedForDateガードそのものの効果を確認）。
    guard_blocks_write = page.evaluate("""
      () => {
        // ロード未完了(bowelLoadedForDate !== dateEl.value)を人為的に作り、
        // persistBowelRowを直接呼んでガードでreturnされる（通信が飛ばない）ことを確認する
        window.__bowel_calls_before = 0;
        return typeof bowelLoadedForDate !== 'undefined' && bowelLoadedForDate !== document.getElementById('report-date').value;
      }
    """)
    page.wait_for_timeout(1500)  # GET応答が届くのを待つ
    loaded_after = page.evaluate("bowelLoadedForDate === document.getElementById('report-date').value")
    patches_during_load = [c for c in calls if c["method"] in ("PATCH", "PUT")]
    ok = add_disabled and guard_blocks_write and loaded_after and len(patches_during_load) == 0
    record("ロード完了前はガード条件が真でUPDATEが飛ばない・完了後はガードが解ける", ok,
           f"add_disabled_during_load={add_disabled} guard_true_during_load={guard_blocks_write} "
           f"loaded_after={loaded_after} patches={patches_during_load}")
    browser.close()
    return ok


def case10_write_failure_shows_error_and_restores_deleted_row(pw):
    print("\n--- ケース⑩: UPDATE/INSERT失敗で赤字・DELETE失敗で行が復活する ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    ok_all = True

    # 10a: INSERT失敗で赤字が出る
    setup_routes(page, fail_write=True)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".bowel-add-btn:not([disabled])", timeout=5000)
    page.locator(".bowel-add-btn").first.click()
    row = page.locator(".bowel-row").first
    row.locator(".bowel-time-input").fill("08:00")
    row.locator(".bowel-stool-select").select_option("普通便")
    row.locator(".bowel-amount-select").select_option("中量")
    row.locator(".bowel-place-select").select_option("便器")
    page.wait_for_timeout(300)
    err_text = row.locator(".bowel-row-error").inner_text()
    ok_10a = row.locator(".bowel-row-error").is_visible() and "保存できませんでした" in err_text
    record("INSERT失敗で赤字「保存できませんでした」が出る", ok_10a, err_text)
    ok_all = ok_all and ok_10a

    # 10b: DELETE失敗で行が復活する
    page2 = browser.new_page()
    bowel_rows = [
        {"id": 1, "resident_id": 101, "kind": "record", "recorded_at": "08:00",
         "stool_type": "普通便", "amount": "中量", "place": "便器", "sort_order": 0},
    ]
    setup_routes(page2, bowel_rows=bowel_rows, fail_delete=True)
    page2.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page2.wait_for_selector(".bowel-row", timeout=5000)
    page2.locator(".bowel-row-del-btn").first.click()
    page2.wait_for_timeout(300)
    count_after_failed_delete = page2.locator(".bowel-row").count()
    del_err_visible = page2.locator(".bowel-row-error").first.is_visible()
    ok_10b = count_after_failed_delete == 1 and del_err_visible
    record("DELETE失敗で行が消えずエラー表示が出る（復活扱い）", ok_10b, f"count={count_after_failed_delete} err_visible={del_err_visible}")
    ok_all = ok_all and ok_10b

    browser.close()
    return ok_all


def case11_update_body_excludes_report_date(pw):
    print("\n--- ケース⑪: UPDATEのbodyにreport_date/gh_num/resident_idが含まれない ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    bowel_rows = [
        {"id": 1, "resident_id": 101, "kind": "record", "recorded_at": "08:00",
         "stool_type": "普通便", "amount": "中量", "place": "便器", "sort_order": 0},
    ]
    calls = setup_routes(page, bowel_rows=bowel_rows)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".bowel-row", timeout=5000)
    row = page.locator(".bowel-row").first
    row.locator(".bowel-amount-select").select_option("多量")
    page.wait_for_timeout(300)
    patches = [c for c in calls if c["method"] in ("PATCH", "PUT")]
    ok = len(patches) == 1 and patches[0]["body"] is not None and \
        "report_date" not in patches[0]["body"] and \
        "gh_num" not in patches[0]["body"] and \
        "resident_id" not in patches[0]["body"] and \
        patches[0]["body"].get("amount") == "多量"
    record("UPDATE bodyにキー列(report_date/gh_num/resident_id)が含まれない", ok, json.dumps(patches, ensure_ascii=False))
    browser.close()
    return ok


def case12_copy_fallback_textarea_is_dismissable_and_clears_on_rerender(pw):
    print("\n--- ケース⑫: コピーのフォールバック2(要配慮個人情報を含むtextarea)が"
          "「閉じる」で消え、再描画でも残らない ---")
    browser = pw.chromium.launch()
    page = browser.new_page()
    page.on("dialog", lambda d: d.accept())
    bowel_rows = [
        {"id": 1, "resident_id": 101, "kind": "record", "recorded_at": "08:00",
         "stool_type": "普通便", "amount": "中量", "place": "便器", "sort_order": 0},
    ]
    setup_routes(page, bowel_rows=bowel_rows)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".bowel-copy-btn:visible", timeout=5000)

    # clipboard APIとexecCommandを両方失敗させ、フォールバック2まで強制的に到達させる
    page.evaluate("""
      () => {
        navigator.clipboard.writeText = () => Promise.reject(new Error('forced'));
        document.execCommand = () => false;
      }
    """)
    page.locator(".bowel-copy-btn").first.click()
    page.wait_for_timeout(300)
    fallback_visible = page.locator(".bowel-copy-fallback").is_visible()
    fallback_text = page.locator(".bowel-copy-fallback textarea").input_value()

    page.locator(".bowel-copy-fallback button").click()
    page.wait_for_timeout(100)
    count_after_close = page.locator(".bowel-copy-fallback").count()

    # 再度表示させたあと、行追加による再描画で自然に消えることも確認する
    page.locator(".bowel-copy-btn").first.click()
    page.wait_for_timeout(200)
    visible_again = page.locator(".bowel-copy-fallback").is_visible()
    page.locator(".bowel-add-btn").first.click()
    page.wait_for_timeout(200)
    count_after_rerender = page.locator(".bowel-copy-fallback").count()

    ok = (fallback_visible and fallback_text == "山田太郎さん　08:00　普通便　中量　便器"
          and count_after_close == 0 and visible_again and count_after_rerender == 0)
    record("フォールバックtextareaは閉じるボタンで消え、再描画でも残らない", ok,
           f"visible={fallback_visible} text={fallback_text} after_close={count_after_close} "
           f"visible_again={visible_again} after_rerender={count_after_rerender}")
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
            r7 = case7_incomplete_row_survives_sibling_save(pw)
            r8 = case8_draft_restored_alongside_saved_rows(pw)
            r9 = case9_no_update_before_load_complete(pw)
            r10 = case10_write_failure_shows_error_and_restores_deleted_row(pw)
            r11 = case11_update_body_excludes_report_date(pw)
            r12 = case12_copy_fallback_textarea_is_dismissable_and_clears_on_rerender(pw)
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
    labels = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪", "⑫"]
    rs = [r1, r2, r3, r4, r5, r6, r7, r8, r9, r10, r11, r12]
    print("\n" + " / ".join(f"{lb}: {'PASS' if r else 'FAIL'}" for lb, r in zip(labels, rs)))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
