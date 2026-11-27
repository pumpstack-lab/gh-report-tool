#!/usr/bin/env python3
"""
利用者タブ（50音順・1人ずつ表示）の検証（本番Supabase・本番URL不使用）。
scripts/verify_report_guard.py のモック基盤を流用する。

実行:
  python3 scripts/verify_resident_tabs.py
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
GH = 6  # マハロ（短期入所枠あり）
DATE = "2026-09-04"

# 名前の50音順とよみがなの50音順をあえて逆にして、よみがなが効いているか確認する。
# 「佐藤」は名前としては後、よみ「あおき」なので本来は先頭に来る。
RESIDENTS = [
    {"id": 101, "name": "佐藤花子", "gh_num": GH, "active": True, "sort_order": 1},
    {"id": 102, "name": "青木一郎", "gh_num": GH, "active": True, "sort_order": 2},
]
KANA_ROWS = [
    {"resident_id": 101, "kana": "さとうはなこ"},
    {"resident_id": 102, "kana": "あおきいちろう"},
]

EXISTING_REPORT = {
    "id": 1, "gh_num": GH, "gh_name": "こもれびホームマハロ", "report_date": DATE,
    "reporter": "", "workers": [],
    "residents": {"佐藤花子": "既存の本文（佐藤さん）"},
    "shortage": [], "photos": [], "updated_at": "2026-09-03T00:00:00Z",
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
    time.sleep(0.6)
    return proc


FAKE_SESSION = {
    "access_token": "fake-token", "token_type": "bearer", "expires_in": 3600,
    "expires_at": int(time.time()) + 3600, "refresh_token": "fake-refresh",
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "staff@example.com"},
}

DELAY_INIT_SCRIPT = """
(() => {
  const origFetch = window.fetch;
  window.fetch = async (...args) => {
    const res = await origFetch(...args);
    const delay = res.headers.get('x-mock-delay-ms');
    if (delay) { await new Promise(r => setTimeout(r, parseInt(delay, 10))); }
    return res;
  };
})();
"""


def setup_routes(page, *, kana_rows=None, kana_fail=False, report_row=None, write_requests=None):
    if write_requests is None:
        write_requests = []
    if kana_rows is None:
        kana_rows = KANA_ROWS

    def handle_rest(route):
        req = route.request
        url = req.url
        method = req.method

        if "/rest/v1/rpc/report_save_partial" in url:
            try:
                payload = json.loads(req.post_data or "null")
            except Exception:
                payload = req.post_data
            write_requests.append({"method": method, "url": url, "body": payload})
            resp = {"ok": True, "current": (payload or {}).get("p_patch", {})}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(resp))
            return
        if "/rest/v1/reports" in url and method == "GET":
            body = report_row if report_row is not None else None
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
            return
        if "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(RESIDENTS))
            return
        if "/rest/v1/resident_kana" in url:
            if kana_fail:
                route.fulfill(status=403, content_type="application/json", body=json.dumps({"message": "forbidden"}))
                return
            route.fulfill(status=200, content_type="application/json", body=json.dumps(kana_rows))
            return
        route.fulfill(status=200, content_type="application/json", body="[]")

    page.add_init_script(
        "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', " + json.dumps(json.dumps(FAKE_SESSION)) + ");")
    page.route("**/auth/v1/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(FAKE_SESSION)))
    page.route("**/rest/v1/**", handle_rest)
    return write_requests


def new_page(browser, **kwargs):
    page = browser.new_page(**kwargs)
    page.add_init_script(DELAY_INIT_SCRIPT)
    return page


def tab_keys(page):
    return page.evaluate("() => [...document.querySelectorAll('.resident-tab-btn')].map(b => b.dataset.tabKey)")


def case1_kana_order(pw):
    print("\n--- ケース1: タブが50音順（よみがな基準）で並ぶ・短期入所①②は最後 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, report_row=EXISTING_REPORT)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)

    keys = tab_keys(page)
    expected = ["青木一郎", "佐藤花子", "__short_stay_1__", "__short_stay_2__"]
    record("50音順（あおき→さとう）・短期入所①②が最後", keys == expected, str(keys))

    labels = page.evaluate("() => [...document.querySelectorAll('.resident-tab-btn')].map(b => b.textContent.replace(/\\s*\\u2713\\s*$/, ''))")
    record("短期入所のタブ表示名が①②", labels[2] == "短期入所①" and labels[3] == "短期入所②", str(labels))

    browser.close()
    return keys == expected


def case2_click_switches_and_hides_others(pw):
    print("\n--- ケース2: タブを押すとその人だけ開き、他は隠れる（DOMからは消えない） ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, report_row=EXISTING_REPORT)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)

    # 開いた直後は先頭（青木一郎）が開いている
    first_visible = page.locator(".resident-entry[data-name='青木一郎']").first.is_visible()
    second_hidden = not page.locator(".resident-entry[data-name='佐藤花子']").first.is_visible()
    record("開いた直後は50音順の先頭（青木一郎）が開いている", first_visible and second_hidden, f"first={first_visible} second_hidden={second_hidden}")

    in_dom = page.locator(".resident-entry[data-name='佐藤花子']").count() == 1
    record("隠れている人もDOMからは消えていない", in_dom)

    page.locator(".resident-tab-btn[data-tab-key='佐藤花子']").click()
    now_visible = page.locator(".resident-entry[data-name='佐藤花子']").first.is_visible()
    now_other_hidden = not page.locator(".resident-entry[data-name='青木一郎']").first.is_visible()
    record("佐藤花子のタブを押すとその人が開き、青木一郎は隠れる", now_visible and now_other_hidden)

    browser.close()
    return first_visible and second_hidden and in_dom and now_visible and now_other_hidden


def case2b_tab_kept_across_date_switch(pw):
    print("\n--- ケース2B: 日付を切り替えて読み直しても、同じ人のタブが開いたまま ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, report_row=EXISTING_REPORT)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)

    page.locator(".resident-tab-btn[data-tab-key='佐藤花子']").click()
    page.evaluate("document.getElementById('report-date').value = '2026-09-05'")
    page.evaluate("document.getElementById('report-date').dispatchEvent(new Event('change'))")
    page.wait_for_function("() => reportLoadedFor === '2026-09-05'", timeout=8000)

    still_sato = page.locator(".resident-entry[data-name='佐藤花子']").first.is_visible()
    record("日付を切り替えても佐藤花子のタブが開いたまま", still_sato)

    browser.close()
    return still_sato


def case3_hidden_input_still_saved(pw):
    print("\n--- ケース3: 1人目に打つ→2人目に切り替えて打つ→保存の中身に2人分ある ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    writes = setup_routes(page, report_row=EXISTING_REPORT)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)

    ta1 = page.locator(".resident-entry[data-name='青木一郎'] textarea").first
    ta1.fill("青木さんの新しい本文")
    ta1.dispatch_event("input")

    page.locator(".resident-tab-btn[data-tab-key='佐藤花子']").click()
    ta2 = page.locator(".resident-entry[data-name='佐藤花子'] textarea").first
    ta2.fill("佐藤さんの新しい本文")
    ta2.dispatch_event("input")

    page.wait_for_timeout(3500)  # 3秒デバウンス＋マージン
    ok_write = len(writes) >= 1
    patch = (writes[-1]["body"].get("p_patch") or {}).get("residents", {}) if writes else {}
    ok_both = patch.get("青木一郎") == "青木さんの新しい本文" and patch.get("佐藤花子") == "佐藤さんの新しい本文"
    record("隠れていた1人目の入力も保存patchに含まれる（2人分そろう）", ok_write and ok_both, json.dumps(patch, ensure_ascii=False))

    browser.close()
    return ok_write and ok_both


def case4_filled_mark_updates(pw):
    print("\n--- ケース4: 本文を打つ・消すとタブの印（✓）が変わる ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, report_row=EXISTING_REPORT)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)

    # 佐藤花子は既存本文があるので最初から印がついている
    sato_filled_before = page.locator(".resident-tab-btn[data-tab-key='佐藤花子']").evaluate("el => el.classList.contains('resident-tab-filled')")
    record("既存の本文がある人には最初から✓がついている", sato_filled_before)

    aoki_filled_before = page.locator(".resident-tab-btn[data-tab-key='青木一郎']").evaluate("el => el.classList.contains('resident-tab-filled')")
    record("未入力の人には最初✓がついていない", not aoki_filled_before)

    ta1 = page.locator(".resident-entry[data-name='青木一郎'] textarea").first
    ta1.fill("本文あり")
    ta1.dispatch_event("input")
    aoki_filled_after = page.locator(".resident-tab-btn[data-tab-key='青木一郎']").evaluate("el => el.classList.contains('resident-tab-filled')")
    record("本文を打つと✓がつく", aoki_filled_after)

    ta1.fill("")
    ta1.dispatch_event("input")
    aoki_filled_cleared = page.locator(".resident-tab-btn[data-tab-key='青木一郎']").evaluate("el => el.classList.contains('resident-tab-filled')")
    record("本文を消すと✓が消える", not aoki_filled_cleared)

    browser.close()
    return sato_filled_before and not aoki_filled_before and aoki_filled_after and not aoki_filled_cleared


def case5_show_all_toggle(pw):
    print("\n--- ケース5: 「全員を表示」を押すと縦に並び、もう一度押すと1人ずつに戻る ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, report_row=EXISTING_REPORT)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)

    page.locator("#resident-tabs-toggle").click()
    all_visible = (
        page.locator(".resident-entry[data-name='青木一郎']").first.is_visible()
        and page.locator(".resident-entry[data-name='佐藤花子']").first.is_visible()
    )
    record("全員を表示を押すと全員の欄が見える", all_visible)

    page.locator("#resident-tabs-toggle").click()
    back_to_one = (
        page.locator(".resident-entry[data-name='青木一郎']").first.is_visible()
        and not page.locator(".resident-entry[data-name='佐藤花子']").first.is_visible()
    )
    record("もう一度押すと1人ずつ表示に戻る", back_to_one)

    browser.close()
    return all_visible and back_to_one


def case6_kana_unavailable_falls_back(pw):
    print("\n--- ケース6: よみがなが読めない時は今の並び（sort_order）のまま動く・日報は止まらない ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, report_row=EXISTING_REPORT, kana_fail=True)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)

    keys = tab_keys(page)
    # kanaが読めない→sort_order順（佐藤花子sort_order=1が先、青木一郎sort_order=2が後）、短期入所は最後
    expected = ["佐藤花子", "青木一郎", "__short_stay_1__", "__short_stay_2__"]
    record("よみがなが読めない時はsort_order順で並ぶ", keys == expected, str(keys))
    record("画面のエラーが出ない（日報は止まらない）", errors == [], str(errors))

    ta = page.locator(".resident-entry[data-name='佐藤花子'] textarea").first
    enabled = ta.is_enabled()
    record("入力欄は使える（止まっていない）", enabled)

    browser.close()
    return keys == expected and errors == [] and enabled


def case7_hidden_entry_autoexpand_on_open(pw):
    print("\n--- ケース7: 隠れていた欄を開くと textarea の高さが測り直される ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, report_row=EXISTING_REPORT)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)

    # 佐藤花子は隠れている間に長文があるが、高さはまだ測れていない（min-heightのまま）はず
    ta = page.locator(".resident-entry[data-name='佐藤花子'] textarea").first
    long_text = "\n".join(["長い本文の行" + str(i) for i in range(20)])
    ta.evaluate(f"(el) => {{ el.value = {json.dumps(long_text)}; }}")  # 高さ測定だけ見たいのでinputは発火させない

    page.locator(".resident-tab-btn[data-tab-key='佐藤花子']").click()
    height_after_open = ta.evaluate("el => el.scrollHeight")
    style_height = ta.evaluate("el => parseInt(el.style.height || '0', 10)")
    ok = style_height > 0 and style_height >= height_after_open - 2
    record("タブを開いた時に高さが測り直される（autoExpandやり直し）", ok, f"style_height={style_height} scrollHeight={height_after_open}")

    browser.close()
    return ok


def case8_widths_no_overflow_no_errors(pw):
    print("\n--- ケース8: スマホ390・タブレット820・パソコン1280で横にはみ出さない・画面のエラー0 ---")
    browser = pw.chromium.launch()
    all_ok = True
    for width, name in [(390, "sp"), (820, "tablet"), (1280, "pc")]:
        page = new_page(browser, viewport={"width": width, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        setup_routes(page, report_row=EXISTING_REPORT)
        page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
        page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)
        vw = page.evaluate("document.documentElement.clientWidth")
        sw = page.evaluate("document.documentElement.scrollWidth")
        no_overflow = sw <= vw + 1
        record(f"幅{width}（{name}）: 横にはみ出さない", no_overflow, f"vw={vw} sw={sw}")
        record(f"幅{width}（{name}）: 画面のエラー0", errors == [], str(errors))
        out = ROOT / "scripts" / f"_resident_tabs_{name}_{width}.png"
        page.screenshot(path=str(out), full_page=True)
        print(f"  saved: {out}")
        all_ok = all_ok and no_overflow and errors == []
        page.close()
    browser.close()
    return all_ok


def main():
    server = start_server()
    try:
        with sync_playwright() as pw:
            r1 = case1_kana_order(pw)
            r2 = case2_click_switches_and_hides_others(pw)
            r2b = case2b_tab_kept_across_date_switch(pw)
            r3 = case3_hidden_input_still_saved(pw)
            r4 = case4_filled_mark_updates(pw)
            r5 = case5_show_all_toggle(pw)
            r6 = case6_kana_unavailable_falls_back(pw)
            r7 = case7_hidden_entry_autoexpand_on_open(pw)
            r8 = case8_widths_no_overflow_no_errors(pw)
    finally:
        server.terminate()
        server.wait(timeout=5)

    print("\n=== 結果サマリ ===")
    all_ok = all(ok for _, ok, _ in results)
    for name, ok, _ in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\nケース1: {'PASS' if r1 else 'FAIL'} / ケース2: {'PASS' if r2 else 'FAIL'} / "
          f"ケース2B: {'PASS' if r2b else 'FAIL'} / ケース3: {'PASS' if r3 else 'FAIL'} / ケース4: {'PASS' if r4 else 'FAIL'} / "
          f"ケース5: {'PASS' if r5 else 'FAIL'} / ケース6: {'PASS' if r6 else 'FAIL'} / "
          f"ケース7: {'PASS' if r7 else 'FAIL'} / ケース8: {'PASS' if r8 else 'FAIL'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
