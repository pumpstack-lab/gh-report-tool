#!/usr/bin/env python3
"""
report.html 検温（夕・朝）UIの検証（本番Supabase・本番URL不使用）。
python3 -m http.server でローカル配信し、REST応答を全てモックする。
設計: docs/superpowers/specs/2026-11-10-temperature-records-design.md
計画: docs/superpowers/plans/2026-11-10-temperature-records.md Task 4

実行:
  cd "gh-report-tool" && python3 scripts/verify_temperature_records.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"
GH = 6  # マハロ（短期入所枠あり）
DATE = "2026-11-10"

RESIDENTS = [
    {"id": 101, "name": "山田太郎", "gh_num": GH, "active": True, "sort_order": 1},
    {"id": 102, "name": "佐藤花子", "gh_num": GH, "active": True, "sort_order": 2},
]

FAKE_SESSION = {
    "access_token": "fake-token", "token_type": "bearer", "expires_in": 3600,
    "expires_at": int(time.time()) + 3600, "refresh_token": "fake-refresh",
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "staff@example.com"},
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


def setup_routes(page, *, temp_rows=None, temp_calls=None,
                  temp_get_delay_ms=0, temp_get_fail=False, reports_delay_ms=0):
    """
    temp_rows: temperature_records GETが返す初期行（list）。upsert成功時はidを払って追記する。
    temp_calls: POST/PATCH/DELETE本文を記録する配列。
    temp_get_delay_ms: temperature_records GETをこのmsだけ遅らせる（ブラウザ側fetchラップで実現）。
    temp_get_fail: temperature_records GETを500にする（表が無い本番相当）。
    reports_delay_ms: reports GETを遅らせる（日付切替ロード中の検証用）。
    """
    if temp_rows is None:
        temp_rows = []
    if temp_calls is None:
        temp_calls = []

    def handle_rest(route):
        req = route.request
        url = req.url
        method = req.method

        if "/rest/v1/temperature_records" in url:
            if method == "GET":
                if temp_get_fail:
                    route.fulfill(status=500, content_type="application/json",
                                   body=json.dumps({"message": "mock failure"}))
                    return
                headers = {"content-type": "application/json"}
                if temp_get_delay_ms:
                    headers["x-mock-delay-ms"] = str(temp_get_delay_ms)
                    headers["access-control-expose-headers"] = "x-mock-delay-ms"
                route.fulfill(status=200, headers=headers, body=json.dumps(temp_rows))
                return
            try:
                payload = json.loads(req.post_data or "null")
            except Exception:
                payload = req.post_data
            temp_calls.append({"method": method, "url": url, "body": payload})
            if method in ("POST", "PATCH"):
                # upsert。onConflict先に一致する既存行をidで更新、無ければ新規発行。
                subject_key = ("resident_id", payload.get("resident_id")) if payload.get("resident_id") is not None \
                    else ("short_stay_key", payload.get("short_stay_key"))
                existing = next((r for r in temp_rows
                                  if r.get(subject_key[0]) == subject_key[1] and r.get("slot") == payload.get("slot")),
                                 None)
                if existing:
                    existing.update(payload)
                    new_row = existing
                else:
                    new_row = dict(payload)
                    new_row["id"] = 900 + len(temp_rows) + 1
                    temp_rows.append(new_row)
                route.fulfill(status=200, content_type="application/json",
                               body=json.dumps([{"id": new_row["id"], "temp_c": new_row["temp_c"]}]))
                return
            if method == "DELETE":
                m = [p for p in url.split("?")[1].split("&") if p.startswith("id=eq.")]
                del_id = int(m[0].split(".")[1]) if m else None
                temp_rows[:] = [r for r in temp_rows if r.get("id") != del_id]
                route.fulfill(status=200, content_type="application/json", body="[]")
                return
            route.fulfill(status=200, content_type="application/json", body="{}")
            return

        if "/rest/v1/rpc/report_save_partial" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "current": {}}))
            return
        if "/rest/v1/reports" in url and method == "GET":
            headers = {"content-type": "application/json"}
            if reports_delay_ms:
                headers["x-mock-delay-ms"] = str(reports_delay_ms)
                headers["access-control-expose-headers"] = "x-mock-delay-ms"
            route.fulfill(status=200, headers=headers, body="null")
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
        if "/rest/v1/personal_shortage_items" in url or "/rest/v1/personal_shortage" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return
        if "/rest/v1/bowel_records" in url or "/rest/v1/patrol_records" in url:
            route.fulfill(status=200, content_type="application/json", body="[]")
            return
        route.fulfill(status=200, content_type="application/json", body="[]")

    page.add_init_script(
        "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', "
        + json.dumps(json.dumps(FAKE_SESSION)) + ");"
    )
    page.route("**/auth/v1/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(FAKE_SESSION)))
    page.route("**/rest/v1/**", handle_rest)
    return temp_calls


def new_page(browser):
    page = browser.new_page()
    page.add_init_script(DELAY_INIT_SCRIPT)
    return page


def goto_loaded(page, date=DATE, **kwargs):
    page.goto(f"{BASE}/report.html?gh={GH}&date={date}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => tempLoadedForDate === '{date}'", timeout=5000)


def first_resident_row(page):
    return page.locator('.temp-row[data-subject="101"]')


def case1_input_and_save(pw):
    print("\n--- ケース1: 利用者1人目の夕に36.5 → change → 書き込み1本（slot/temp_c/resident_id/report_date） ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page)
    goto_loaded(page)
    row = first_resident_row(page)
    inp = row.locator('.temp-input[data-slot="evening"]')
    inp.fill("36.5")
    inp.dispatch_event("change")
    page.wait_for_timeout(300)
    writes = [c for c in calls if c["method"] in ("POST", "PATCH")]
    ok_count = len(writes) == 1
    body = writes[0]["body"] if writes else {}
    url = writes[0]["url"] if writes else ""
    ok_body = (body.get("slot") == "evening" and body.get("temp_c") == 36.5
               and body.get("resident_id") == 101 and body.get("report_date") == DATE)
    # 部分一意索引2本ではなく生成列subject_keyの1本の一意索引をarbiterにする（本番42P10対策）
    ok_conflict = "on_conflict=gh_num%2Creport_date%2Csubject_key%2Cslot" in url
    ok_no_subject_key_in_payload = "subject_key" not in body  # 生成列なのでpayloadには入れない
    ok = ok_count and ok_body and ok_conflict and ok_no_subject_key_in_payload
    record("書き込みが1本・内容が正しい・on_conflictがsubject_key1本", ok,
           f"url={url} body={json.dumps(body, ensure_ascii=False)}")
    browser.close()
    return ok


def case2_same_value_no_write(pw):
    print("\n--- ケース2: 同じ欄に36.5を再入力 → 書き込み0本（同値は書かない） ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    temp_rows = [{"id": 801, "resident_id": 101, "short_stay_key": None, "slot": "evening", "temp_c": 36.5}]
    calls = setup_routes(page, temp_rows=temp_rows)
    goto_loaded(page)
    row = first_resident_row(page)
    inp = row.locator('.temp-input[data-slot="evening"]')
    ok_prefill = inp.input_value() == "36.5"
    inp.fill("36.5")
    inp.dispatch_event("change")
    page.wait_for_timeout(300)
    writes = [c for c in calls if c["method"] in ("POST", "PATCH", "DELETE")]
    ok = ok_prefill and len(writes) == 0
    record("既存値と同じ入力では書き込みが飛ばない", ok, f"prefill={ok_prefill} writes={len(writes)}")
    browser.close()
    return ok


def case3_fever_color(pw):
    print("--- ケース3: 37.5でis-feverが付き赤・37.4では付かない ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page)
    goto_loaded(page)
    row = first_resident_row(page)
    inp = row.locator('.temp-input[data-slot="morning"]')
    inp.fill("37.5")
    inp.dispatch_event("input")
    page.wait_for_timeout(50)
    has_fever_class = inp.evaluate("el => el.classList.contains('is-fever')")
    color = inp.evaluate("el => getComputedStyle(el).color")
    ok_fever = has_fever_class and color == "rgb(192, 57, 43)"
    record("37.5でis-feverが付き色がrgb(192, 57, 43)", ok_fever, f"class={has_fever_class} color={color}")

    inp.fill("37.4")
    inp.dispatch_event("input")
    page.wait_for_timeout(50)
    no_fever_class = inp.evaluate("el => el.classList.contains('is-fever')")
    ok_no_fever = not no_fever_class
    record("37.4ではis-feverが付かない", ok_no_fever)
    browser.close()
    return ok_fever and ok_no_fever


def case4_out_of_range_error(pw):
    print("\n--- ケース4: 36.55 → 書き込み0本・.temp-errorが表示・文言一致 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page)
    goto_loaded(page)
    row = first_resident_row(page)
    inp = row.locator('.temp-input[data-slot="evening"]')
    inp.evaluate("el => el.value = '36.55'")  # type=numberだがstep制約を跨いで直接テキストを入れる
    inp.dispatch_event("change")
    page.wait_for_timeout(300)
    writes = [c for c in calls if c["method"] in ("POST", "PATCH", "DELETE")]
    err = row.locator(".temp-error")
    err_visible = err.is_visible()
    err_text = err.inner_text() if err_visible else ""
    ok = len(writes) == 0 and err_visible and err_text == "35.0〜42.0 で入れてください（小数1桁）"
    record("範囲外（小数2桁）は保存0本・注意文一致", ok, f"writes={len(writes)} text={err_text}")
    browser.close()
    return ok


def case5_clear_deletes(pw):
    print("\n--- ケース5: 空にする（既存行あり）→ DELETE 1本・欄が空 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    temp_rows = [{"id": 802, "resident_id": 101, "short_stay_key": None, "slot": "morning", "temp_c": 36.8}]
    calls = setup_routes(page, temp_rows=temp_rows)
    goto_loaded(page)
    row = first_resident_row(page)
    inp = row.locator('.temp-input[data-slot="morning"]')
    ok_prefill = inp.input_value() == "36.8"
    inp.fill("")
    inp.dispatch_event("change")
    page.wait_for_timeout(300)
    deletes = [c for c in calls if c["method"] == "DELETE"]
    ok_val = inp.input_value() == ""
    ok = ok_prefill and len(deletes) == 1 and ok_val
    record("空にするとDELETEが1本飛び欄が空になる", ok, f"prefill={ok_prefill} deletes={len(deletes)} val='{inp.input_value()}'")
    browser.close()
    return ok


def case6_short_stay(pw):
    print("\n--- ケース6: 短期入所①に名前「検証太郎」＋朝36.8 → short_stay_key等が正しい ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page)
    goto_loaded(page)
    ss_entry = page.locator('.short-stay-entry[data-short-stay-key="__short_stay_1__"]')
    ss_entry.locator(".short-stay-name-input").fill("検証太郎")
    inp = ss_entry.locator('.temp-input[data-slot="morning"]')
    inp.fill("36.8")
    inp.dispatch_event("change")
    page.wait_for_timeout(300)
    writes = [c for c in calls if c["method"] in ("POST", "PATCH")]
    body = writes[0]["body"] if writes else {}
    url = writes[0]["url"] if writes else ""
    ok_conflict = "on_conflict=gh_num%2Creport_date%2Csubject_key%2Cslot" in url
    ok = (len(writes) == 1 and body.get("short_stay_key") == "__short_stay_1__"
          and body.get("resident_id") is None and body.get("resident_name") == "検証太郎"
          and body.get("slot") == "morning" and body.get("temp_c") == 36.8 and ok_conflict)
    record("短期入所枠の保存内容が正しい・on_conflictがsubject_key1本", ok, f"url={url} body={json.dumps(body, ensure_ascii=False)}")
    browser.close()
    return ok


def case7_disabled_during_load_no_write(pw):
    print("\n--- ケース7: 日付切替中は.temp-inputがdisabled・直接changeを飛ばしても書き込み0本 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page)
    goto_loaded(page)

    page.unroute("**/rest/v1/**")
    setup_routes(page, temp_calls=calls, reports_delay_ms=3000)
    page.evaluate("document.getElementById('report-date').value = '2026-11-11'")
    page.evaluate("document.getElementById('report-date').dispatchEvent(new Event('change'))")
    page.wait_for_timeout(200)  # loadDateData冒頭のsetFormInputsDisabled(true)が効くのを待つ

    row = first_resident_row(page)
    inp = row.locator('.temp-input[data-slot="evening"]')
    ok_disabled = inp.is_disabled()
    # disabledをすり抜けて直接changeを発火させても保存されないことを確認（ガードはJS側のtempLoadedForDate比較）
    inp.evaluate("el => { el.disabled = false; el.value = '38.0'; el.dispatchEvent(new Event('change', {bubbles:true})); }")
    page.wait_for_timeout(300)
    writes = [c for c in calls if c["method"] in ("POST", "PATCH", "DELETE")]
    ok = ok_disabled and len(writes) == 0
    record("ロード中はdisabled・直接changeでも書き込み0本", ok, f"disabled={ok_disabled} writes={len(writes)}")
    browser.close()
    return ok


def case9_bad_input_does_not_delete(pw):
    print("\n--- ケース9: 既存値36.5の欄に badInput になる入力（'36e' 等）→ DELETE 0本・エラー文表示 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    temp_rows = [{"id": 803, "resident_id": 101, "short_stay_key": None, "slot": "evening", "temp_c": 36.5}]
    calls = setup_routes(page, temp_rows=temp_rows)
    goto_loaded(page)
    row = first_resident_row(page)
    inp = row.locator('.temp-input[data-slot="evening"]')
    ok_prefill = inp.input_value() == "36.5"
    inp.click()
    inp.evaluate("el => el.select()")
    page.keyboard.type("36e")  # type=numberで badInput になる入力（value は '' になる）
    ok_bad_input = inp.evaluate("el => el.validity.badInput")
    inp.dispatch_event("change")
    page.wait_for_timeout(300)
    writes = [c for c in calls if c["method"] in ("POST", "PATCH", "DELETE")]
    err = row.locator(".temp-error")
    err_visible = err.is_visible()
    ok = ok_prefill and ok_bad_input and len(writes) == 0 and err_visible
    record("badInputは保存0本・エラー文表示（既存値を黙って消さない）", ok,
           f"prefill={ok_prefill} badInput={ok_bad_input} writes={len(writes)} err_visible={err_visible}")
    browser.close()
    return ok


def case8_load_failure_unavailable(pw):
    print("\n--- ケース8: temperature_records GETが500 → 欄disabled・.temp-unavailable表示・本文は使える ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, temp_get_fail=True)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=5000)
    page.wait_for_timeout(500)
    row = first_resident_row(page)
    ok_disabled = row.locator('.temp-input[data-slot="evening"]').is_disabled()
    ok_unavailable = row.locator(".temp-unavailable").is_visible()
    ta = page.locator(".resident-entry textarea").first
    ta.fill("本文は使えることの確認")
    ta.dispatch_event("input")
    ok_textarea = ta.input_value() == "本文は使えることの確認" and not ta.is_disabled()
    ok = ok_disabled and ok_unavailable and ok_textarea
    record("読み込み失敗時は検温欄のみ無効・本文は使える", ok,
           f"disabled={ok_disabled} unavailable={ok_unavailable} textarea_ok={ok_textarea}")
    browser.close()
    return ok


def screenshot_widths(pw):
    print("\n--- スクリーンショット（3幅・夕に37.8を入れた赤の状態） ---")
    browser = pw.chromium.launch()
    for width, name in [(375, "sp"), (768, "tablet"), (1280, "pc")]:
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.add_init_script(DELAY_INIT_SCRIPT)
        setup_routes(page)
        page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
        page.wait_for_function(f"() => tempLoadedForDate === '{DATE}'", timeout=5000)
        row = first_resident_row(page)
        inp = row.locator('.temp-input[data-slot="evening"]')
        inp.fill("37.8")
        inp.dispatch_event("input")
        page.wait_for_timeout(200)
        out = ROOT / "scripts" / f"_temperature_{width}.png"
        page.screenshot(path=str(out))
        print(f"  saved: {out}")
        page.close()
    browser.close()


def main():
    server = start_server()
    try:
        with sync_playwright() as pw:
            r1 = case1_input_and_save(pw)
            r2 = case2_same_value_no_write(pw)
            r3 = case3_fever_color(pw)
            r4 = case4_out_of_range_error(pw)
            r5 = case5_clear_deletes(pw)
            r6 = case6_short_stay(pw)
            r7 = case7_disabled_during_load_no_write(pw)
            r8 = case8_load_failure_unavailable(pw)
            r9 = case9_bad_input_does_not_delete(pw)
            screenshot_widths(pw)
    finally:
        server.terminate()
        server.wait(timeout=5)

    print("\n=== 結果サマリ ===")
    all_ok = True
    for name, ok, _ in results:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}")
        if not ok:
            all_ok = False
    labels = ["ケース1", "ケース2", "ケース3", "ケース4", "ケース5", "ケース6", "ケース7", "ケース8", "ケース9"]
    rs = [r1, r2, r3, r4, r5, r6, r7, r8, r9]
    print("\n" + " / ".join(f"{l}: {'PASS' if r else 'FAIL'}" for l, r in zip(labels, rs)))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
