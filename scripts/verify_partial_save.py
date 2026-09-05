#!/usr/bin/env python3
"""
report.html の差分保存（根治）検証（本番Supabase・本番URL不使用）。
python3 -m http.server でローカル配信し、REST/RPC応答を全てモックする。

実行:
  cd "gh-report-tool" && python3 -m http.server 8792 &
  python3 scripts/verify_partial_save.py
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
GH = 6  # マハロ
DATE = "2026-09-05"

RESIDENTS = [
    {"id": 101, "name": "山田太郎", "gh_num": GH, "active": True, "sort_order": 1},
    {"id": 102, "name": "佐藤花子", "gh_num": GH, "active": True, "sort_order": 2},
]

DIAPER_ITEMS = []  # 本検証では不足なし想定（loadDiaperUsageは即resolveでよい）

EXISTING_REPORT = {
    "id": 1,
    "gh_num": GH,
    "gh_name": "こもれびホームマハロ",
    "report_date": DATE,
    "reporter": "",
    "workers": [],
    "residents": {"山田太郎": "既存の本文（山田さん）", "佐藤花子": "既存の本文（佐藤さん）"},
    "shortage": "[]",
    "photos": [],
    "updated_at": "2026-09-05T00:00:00.000000+00:00",
}

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


def setup_routes(page, *, rpc_responses=None, rpc_calls=None, report_row=None):
    """全RESTエンドポイントをモックする。rpc_responsesはFIFOのリスト（呼ばれるたびに1件pop）。"""
    if rpc_calls is None:
        rpc_calls = []
    if rpc_responses is None:
        rpc_responses = []

    def handle_rest(route):
        req = route.request
        url = req.url
        method = req.method

        if "/rest/v1/rpc/report_save_partial" in url:
            try:
                payload = json.loads(req.post_data or "null")
            except Exception:
                payload = req.post_data
            rpc_calls.append({"method": method, "url": url, "body": payload})
            resp = rpc_responses.pop(0) if rpc_responses else {"ok": True, "current": {}}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(resp))
            return
        if "/rest/v1/reports" in url and method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(report_row))
            return
        if "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(RESIDENTS))
            return
        if "/rest/v1/staff" in url or "/rest/v1/jp_holidays" in url:
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
    return rpc_calls


def new_page(browser):
    return browser.new_page()


def case1_two_tabs_different_residents_both_survive(pw):
    print("\n--- ケース①: 2タブで別々の利用者を編集→両方残る ---")
    browser = pw.chromium.launch()
    page_a = new_page(browser)
    page_b = new_page(browser)
    calls_a = setup_routes(page_a, report_row=EXISTING_REPORT,
                            rpc_responses=[{"ok": True, "current": {"residents": {"山田太郎": "Aが書いた本文", "佐藤花子": "既存の本文（佐藤さん）"}}}])
    calls_b = setup_routes(page_b, report_row=EXISTING_REPORT,
                            rpc_responses=[{"ok": True, "current": {"residents": {"山田太郎": "既存の本文（山田さん）", "佐藤花子": "Bが書いた本文"}}}])

    page_a.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page_b.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page_a.wait_for_selector(".resident-entry textarea", timeout=5000)
    page_b.wait_for_selector(".resident-entry textarea", timeout=5000)

    ta_a = page_a.locator(".resident-entry textarea").first  # 山田太郎
    ta_b = page_b.locator(".resident-entry textarea").nth(1)  # 佐藤花子
    ta_a.fill("Aが書いた本文")
    ta_a.dispatch_event("input")
    ta_b.fill("Bが書いた本文")
    ta_b.dispatch_event("input")

    page_a.wait_for_timeout(3500)  # 3秒デバウンス
    page_b.wait_for_timeout(500)

    ok_a_sent = len(calls_a) == 1
    ok_b_sent = len(calls_b) == 1
    record("Aの保存RPCが1本飛ぶ", ok_a_sent, f"実際: {len(calls_a)}本")
    record("Bの保存RPCが1本飛ぶ", ok_b_sent, f"実際: {len(calls_b)}本")

    a_patch = calls_a[0]["body"]["p_patch"] if calls_a else {}
    b_patch = calls_b[0]["body"]["p_patch"] if calls_b else {}
    record("Aのpatchには山田太郎だけ入っている（佐藤花子は含まれない）",
           a_patch.get("residents") == {"山田太郎": "Aが書いた本文"}, json.dumps(a_patch, ensure_ascii=False))
    record("Bのpatchには佐藤花子だけ入っている（山田太郎は含まれない）",
           b_patch.get("residents") == {"佐藤花子": "Bが書いた本文"}, json.dumps(b_patch, ensure_ascii=False))

    browser.close()
    return ok_a_sent and ok_b_sent and a_patch.get("residents") == {"山田太郎": "Aが書いた本文"} and b_patch.get("residents") == {"佐藤花子": "Bが書いた本文"}


def case2_conflict_shows_banner_and_keeps_input(pw):
    print("\n--- ケース②: 同じ利用者を古いタブで編集→conflictで保存されず赤帯・入力は画面に残る ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page, report_row=EXISTING_REPORT, rpc_responses=[
        {"ok": False, "conflicts": {"residents": ["山田太郎"]},
         "current": {"residents": {"山田太郎": "他端末が書いた本文", "佐藤花子": "既存の本文（佐藤さん）"}}},
        {"ok": True, "current": {"residents": {"山田太郎": "自分が書いた新本文", "佐藤花子": "既存の本文（佐藤さん）"}}},
    ])
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)

    ta = page.locator(".resident-entry textarea").first
    ta.fill("自分が書いた新本文")
    ta.dispatch_event("input")
    page.wait_for_timeout(3500)

    conflict_banner_visible = page.locator(".resident-entry .conflict-banner").first.is_visible()
    record("conflictバナーが表示される", conflict_banner_visible)

    kept_value = ta.input_value()
    record("入力内容が画面に残っている（上書きされない）", kept_value == "自分が書いた新本文", kept_value)

    other_text = page.locator(".resident-entry .conflict-banner").first.inner_text()
    record("相手の内容が表示される", "他端末が書いた本文" in other_text, other_text)

    # コーディネーター指摘1（ブロッカー）: 「自分の内容を使う」を押した後、
    # 次の保存RPCのbaseがサーバー現在値に更新されていて（＝lastSavedを更新している）、
    # ok=trueで通ること（更新していないと同じbaseを送り続け永久にconflictするバグの再現テスト）。
    page.locator(".btn-conflict-keep-mine").first.click()
    page.wait_for_timeout(3500)  # 「自分の内容を使う」はscheduleAutoSave→3秒デバウンス
    ok_second_call_sent = len(calls) == 2
    record("『自分の内容を使う』後、次の保存RPCが飛ぶ", ok_second_call_sent, f"実際: {len(calls)}本")

    second_base_residents = {}
    if len(calls) >= 2:
        second_base_residents = (calls[1]["body"].get("p_base") or {}).get("residents", {})
    ok_base_updated = second_base_residents.get("山田太郎") == "他端末が書いた本文"
    record("2回目のbaseがサーバー現在値(他端末が書いた本文)になっている（無限conflict修正）",
           ok_base_updated, json.dumps(second_base_residents, ensure_ascii=False))

    banner_gone = page.locator(".resident-entry .conflict-banner").count() == 0
    record("『自分の内容を使う』後、バナーが消える", banner_gone)

    browser.close()
    return (conflict_banner_visible and kept_value == "自分が書いた新本文" and "他端末が書いた本文" in other_text
            and ok_second_call_sent and ok_base_updated and banner_gone)


def case3_debounce_3s(pw):
    print("\n--- ケース③: 3秒デバウンス（800msでは保存されない） ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page, report_row=EXISTING_REPORT, rpc_responses=[{"ok": True, "current": {}}])
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)

    ta = page.locator(".resident-entry textarea").first
    ta.fill("テスト本文")
    ta.dispatch_event("input")

    page.wait_for_timeout(1200)
    ok_not_yet = len(calls) == 0
    record("1.2秒後はまだ保存されていない（3秒デバウンス）", ok_not_yet, f"実際: {len(calls)}本")

    page.wait_for_timeout(2500)
    ok_sent = len(calls) == 1
    record("3秒後には保存される", ok_sent, f"実際: {len(calls)}本")

    browser.close()
    return ok_not_yet and ok_sent


def case4_hidden_flushes_immediately(pw):
    print("\n--- ケース④: タブを隠すと即保存（visibilitychange） ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page, report_row=EXISTING_REPORT, rpc_responses=[{"ok": True, "current": {}}])
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)

    ta = page.locator(".resident-entry textarea").first
    ta.fill("隠す直前の入力")
    ta.dispatch_event("input")

    page.wait_for_timeout(200)  # 3秒デバウンス未満
    page.evaluate("""
      Object.defineProperty(document, 'hidden', { value: true, configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
    """)
    page.wait_for_timeout(300)

    ok_flushed = len(calls) == 1
    record("visibilitychange(hidden)で即座に保存リクエストが飛ぶ", ok_flushed, f"実際: {len(calls)}本")

    browser.close()
    return ok_flushed


def case5_new_date_creation(pw):
    print("\n--- ケース⑤: 新規日の作成 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page, report_row=None, rpc_responses=[{"ok": True, "current": {"residents": {"山田太郎": "初日の記録"}}}])
    page.goto(f"{BASE}/report.html?gh={GH}&date=2026-09-06", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)

    ta = page.locator(".resident-entry textarea").first
    ta.fill("初日の記録")
    ta.dispatch_event("input")
    page.wait_for_timeout(3500)

    ok_sent = len(calls) == 1
    record("既存レコードが無い日でも保存RPCが1本飛ぶ", ok_sent, f"実際: {len(calls)}本")

    browser.close()
    return ok_sent


def case6_blank_resident_does_not_block_others_save(pw):
    print("\n--- ケース⑥: 新規作成で空欄のまま残った利用者が、他人の本文まで巻き込んでconflict却下しない（最重要ブロッカー） ---")
    # 実測再現（コーディネーター報告）:
    # A: 新規日を作成（全員空文字で作られる） patch={"residents":{"山田太郎":"","佐藤花子":""}}
    # B: Aより前から画面を開いていた（lastSaved={}）。山田だけ書いて保存
    #    patch={"residents":{"山田太郎":"Bが書いた本文","佐藤花子":""}} base={"residents":{}}
    #    修正前は conflicts.residents=["佐藤花子","山田太郎"] で ok=false になり、
    #    Bの本文が1文字も入らなかった。修正後は佐藤花子はそもそもpatchに乗らないため通る。
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page, report_row=EXISTING_REPORT, rpc_responses=[
        {"ok": True, "current": {"residents": {"山田太郎": "Bが書いた本文", "佐藤花子": "既存の本文（佐藤さん）"}}},
    ])
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)

    # 山田太郎だけ書く。佐藤花子は既存本文のまま触らない（=lastSavedと一致・patchに乗らないのが正しい）。
    ta = page.locator(".resident-entry textarea").first
    ta.fill("Bが書いた本文")
    ta.dispatch_event("input")
    page.wait_for_timeout(3500)

    ok_sent = len(calls) == 1
    record("保存RPCが1本飛ぶ", ok_sent, f"実際: {len(calls)}本")

    patch_residents = {}
    if calls:
        patch_residents = (calls[0]["body"].get("p_patch") or {}).get("residents", {})
    ok_only_yamada = patch_residents == {"山田太郎": "Bが書いた本文"}
    record("patchには山田太郎だけが入る（佐藤花子は含まれずconflictにならない）",
           ok_only_yamada, json.dumps(patch_residents, ensure_ascii=False))

    saved_text = page.locator("#draft-indicator").inner_text()
    ok_no_conflict_shown = "競合" not in saved_text and "保存しました" in saved_text
    record("conflictにならず『保存しました』が出る", ok_no_conflict_shown, saved_text)

    browser.close()
    return ok_sent and ok_only_yamada and ok_no_conflict_shown


def screenshot_widths(pw):
    print("\n--- スクリーンショット（3幅） ---")
    browser = pw.chromium.launch()
    for width, name in [(375, "sp"), (768, "tablet"), (1280, "pc")]:
        page = browser.new_page(viewport={"width": width, "height": 900})
        setup_routes(page, report_row=EXISTING_REPORT, rpc_responses=[
            {"ok": False, "conflicts": {"residents": ["山田太郎"]},
             "current": {"residents": {"山田太郎": "他端末が書いた本文"}}}
        ])
        page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
        page.wait_for_selector(".resident-entry textarea", timeout=5000)
        ta = page.locator(".resident-entry textarea").first
        ta.fill("自分が書いた本文")
        ta.dispatch_event("input")
        page.wait_for_timeout(3500)
        out = ROOT / "scripts" / f"_partial_save_{name}_{width}.png"
        page.screenshot(path=str(out))
        print(f"  saved: {out}")
        page.close()
    browser.close()


def main():
    server = start_server()
    try:
        with sync_playwright() as pw:
            r1 = case1_two_tabs_different_residents_both_survive(pw)
            r2 = case2_conflict_shows_banner_and_keeps_input(pw)
            r3 = case3_debounce_3s(pw)
            r4 = case4_hidden_flushes_immediately(pw)
            r5 = case5_new_date_creation(pw)
            r6 = case6_blank_resident_does_not_block_others_save(pw)
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
