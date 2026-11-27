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
GH = 6  # 短期入所枠のあるホーム
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
            want_object = "vnd.pgrst.object" in (req.headers.get("accept") or "")

            def reply(row, status=200):
                out = {"id": row["id"], "slot": row.get("slot"), "temp_c": row["temp_c"]}
                route.fulfill(status=status, content_type="application/json",
                               body=json.dumps(out if want_object else [out]))

            def subject_of(r):
                return r.get("resident_id") if r.get("resident_id") is not None else r.get("short_stay_key")

            if method == "PATCH" and "id=eq." in url:
                # 追加の測定の行を id 指定で直す（時刻・体温）
                pid = int([q for q in url.split("?")[1].split("&") if q.startswith("id=eq.")][0].split(".")[1])
                target = next((r for r in temp_rows if r.get("id") == pid), None)
                if target is None:
                    route.fulfill(status=406, content_type="application/json", body=json.dumps({"message": "no rows"}))
                    return
                target.update(payload)
                reply(target)
                return
            if method in ("POST", "PATCH"):
                existing = next((r for r in temp_rows
                                  if subject_of(r) == subject_of(payload) and r.get("slot") == payload.get("slot")),
                                 None)
                if existing and "on_conflict=" not in url:
                    # 素の insert で同じ時刻＝一意違反（本番の 23505 相当）
                    route.fulfill(status=409, content_type="application/json",
                                   body=json.dumps({"code": "23505", "message": "duplicate key value"}))
                    return
                if existing:
                    existing.update(payload)
                    new_row = existing
                else:
                    new_row = dict(payload)
                    new_row["id"] = 900 + len(temp_rows) + 1
                    temp_rows.append(new_row)
                reply(new_row)
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
    # 2026-11-27: 利用者タブ導入で既定は1人ずつ表示。この台本は複数の利用者/短期入所枠を
    # 同時に見る前提なので、全員表示へ切り替える。
    toggle = page.locator("#resident-tabs-toggle")
    if toggle.count() > 0 and toggle.is_visible():
        toggle.click()


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


def extra_rows(page):
    return first_resident_row(page).locator('.temp-extra')


def add_extra(page, time_text, temp_text):
    row = first_resident_row(page)
    row.locator('.temp-add-btn').click()
    ex = row.locator('.temp-extra').last
    if time_text is not None:
        ex.locator('.temp-extra-time').fill(time_text)
        ex.locator('.temp-extra-time').dispatch_event("change")
    if temp_text is not None:
        ex.locator('.temp-extra-temp').fill(temp_text)
        ex.locator('.temp-extra-temp').dispatch_event("change")
    page.wait_for_timeout(300)
    return ex


def case10_extra_add(pw):
    print("\n--- ケース10: ＋測り直しを追加 → 19:35・386 → 素の insert 1 本（slot=19:35・38.6）・欄は 38.6 で赤 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page)
    goto_loaded(page)
    ex = add_extra(page, "19:35", "386")
    writes = [c for c in calls if c["method"] in ("POST", "PATCH", "DELETE")]
    body = writes[0]["body"] if writes else {}
    url = writes[0]["url"] if writes else ""
    ok = (len(writes) == 1 and writes[0]["method"] == "POST" and "on_conflict" not in url
          and body.get("slot") == "19:35" and body.get("temp_c") == 38.6 and body.get("resident_id") == 101
          and body.get("report_date") == DATE and "subject_key" not in body
          and ex.locator('.temp-extra-temp').input_value() == "38.6"
          and "is-fever" in (ex.locator('.temp-extra-temp').get_attribute("class") or "")
          and "is-draft" not in (ex.get_attribute("class") or "")
          and (ex.get_attribute("data-id") or "").isdigit())
    record("追加の測定は時刻と体温が揃って 1 本だけ保存・点なし 386 は 38.6・赤", ok,
           f"writes={len(writes)} url={url} body={json.dumps(body, ensure_ascii=False)} id={ex.get_attribute('data-id')}")
    browser.close()
    return ok


def case11_extra_half_no_write(pw):
    print("\n--- ケース11: 時刻だけ／体温だけでは保存しない・入れかけの行は ✕ で確認なしに消える ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page)
    goto_loaded(page)
    add_extra(page, "19:35", None)
    add_extra(page, None, "37.0")
    n_before = extra_rows(page).count()
    extra_rows(page).first.locator('.temp-extra-del').click()
    page.wait_for_timeout(200)
    writes = [c for c in calls if c["method"] in ("POST", "PATCH", "DELETE")]
    ok = len(writes) == 0 and n_before == 2 and extra_rows(page).count() == 1
    record("片方だけでは保存 0 本・入れかけの行は ✕ で消える", ok, f"writes={len(writes)} rows={n_before}->{extra_rows(page).count()}")
    browser.close()
    return ok


def case12_extra_prefill_sorted(pw):
    print("\n--- ケース12: 保存済みの追加測定が「前日の夜→当日の未明」の順で出る・夕と朝の欄とは混ざらない ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    temp_rows = [
        {"id": 811, "resident_id": 101, "short_stay_key": None, "slot": "01:00", "temp_c": 37.2},
        {"id": 812, "resident_id": 101, "short_stay_key": None, "slot": "22:00", "temp_c": 38.1},
        {"id": 813, "resident_id": 101, "short_stay_key": None, "slot": "evening", "temp_c": 38.6},
        {"id": 814, "resident_id": 102, "short_stay_key": None, "slot": "20:00", "temp_c": 36.9},
    ]
    setup_routes(page, temp_rows=temp_rows)
    goto_loaded(page)
    rows = extra_rows(page)
    times = [rows.nth(i).locator('.temp-extra-time').input_value() for i in range(rows.count())]
    temps = [rows.nth(i).locator('.temp-extra-temp').input_value() for i in range(rows.count())]
    evening = first_resident_row(page).locator('.temp-input[data-slot="evening"]').input_value()
    ok = times == ["22:00", "01:00"] and temps == ["38.1", "37.2"] and evening == "38.6"
    record("保存済みの追加測定が流れの順に出る（他の利用者の分は混ざらない）", ok, f"times={times} temps={temps} evening={evening}")
    browser.close()
    return ok


def case13_extra_edit(pw):
    print("\n--- ケース13: 保存済みの行の体温・時刻を直す → id 指定の更新 1 本ずつ・空にしても消えない ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    temp_rows = [{"id": 812, "resident_id": 101, "short_stay_key": None, "slot": "22:00", "temp_c": 38.1}]
    calls = setup_routes(page, temp_rows=temp_rows)
    goto_loaded(page)
    ex = extra_rows(page).first
    ex.locator('.temp-extra-temp').fill("37.9")
    ex.locator('.temp-extra-temp').dispatch_event("change")
    page.wait_for_timeout(300)
    ex.locator('.temp-extra-time').fill("22:30")
    ex.locator('.temp-extra-time').dispatch_event("change")
    page.wait_for_timeout(300)
    writes = [c for c in calls if c["method"] in ("POST", "PATCH", "DELETE")]
    ok_updates = (len(writes) == 2 and all(w["method"] == "PATCH" and "id=eq.812" in w["url"] for w in writes)
                  and writes[0]["body"].get("temp_c") == 37.9 and writes[1]["body"].get("slot") == "22:30")
    ex.locator('.temp-extra-temp').fill("")
    ex.locator('.temp-extra-temp').dispatch_event("change")
    page.wait_for_timeout(300)
    writes2 = [c for c in calls if c["method"] in ("POST", "PATCH", "DELETE")]
    err = first_resident_row(page).locator('.temp-error')
    ok_keep = (len(writes2) == 2 and ex.locator('.temp-extra-temp').input_value() == "37.9"
               and err.is_visible() and "✕" in err.inner_text())
    ok = ok_updates and ok_keep
    record("保存済みの行は id 指定で更新・空にしても消さず元の値に戻して知らせる", ok,
           f"writes={[(w['method'], w['body']) for w in writes]} after_clear={len(writes2)}")
    browser.close()
    return ok


def case14_extra_duplicate_time(pw):
    print("\n--- ケース14: 既にある時刻と同じ時刻の行を足す → 保存 0 本・「同じ時刻の記録があります」 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    temp_rows = [{"id": 812, "resident_id": 101, "short_stay_key": None, "slot": "22:00", "temp_c": 38.1}]
    calls = setup_routes(page, temp_rows=temp_rows)
    goto_loaded(page)
    add_extra(page, "22:00", "37.5")
    writes = [c for c in calls if c["method"] in ("POST", "PATCH", "DELETE")]
    err = first_resident_row(page).locator('.temp-error')
    ok = len(writes) == 0 and err.is_visible() and err.inner_text() == "同じ時刻の記録があります"
    record("同じ時刻の追加は保存 0 本・注意文", ok, f"writes={len(writes)} err={err.inner_text() if err.is_visible() else ''}")
    browser.close()
    return ok


def case15_extra_delete_confirm(pw):
    print("\n--- ケース15: 保存済みの行の ✕ → 確認でやめると 0 本・はいで DELETE 1 本 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    temp_rows = [{"id": 812, "resident_id": 101, "short_stay_key": None, "slot": "07:05", "temp_c": 38.1}]
    calls = setup_routes(page, temp_rows=temp_rows)
    goto_loaded(page)
    messages = []
    answers = [False, True]
    def on_dialog(d):
        messages.append(d.message)
        (d.accept if answers.pop(0) else d.dismiss)()
    page.on("dialog", on_dialog)
    extra_rows(page).first.locator('.temp-extra-del').click()
    page.wait_for_timeout(300)
    after_cancel = len([c for c in calls if c["method"] == "DELETE"])
    rows_after_cancel = extra_rows(page).count()
    extra_rows(page).first.locator('.temp-extra-del').click()
    page.wait_for_timeout(300)
    dels = [c for c in calls if c["method"] == "DELETE"]
    ok = (after_cancel == 0 and rows_after_cancel == 1 and len(dels) == 1 and "id=eq.812" in dels[0]["url"]
          and extra_rows(page).count() == 0 and messages and messages[0].startswith("7:05 の検温"))
    record("✕ は確認つき・やめると消えない・はいで 1 本だけ消える", ok, f"msg={messages[:1]} cancel={after_cancel} dels={len(dels)}")
    browser.close()
    return ok


def case16_labels_and_dotless(pw):
    print("\n--- ケース16: 夕・朝に月日が出る（夕＝前日）・夕に 366 → 36.6 で保存し欄も 36.6 ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page)
    goto_loaded(page)
    row = first_resident_row(page)
    ev = row.locator('[data-slot-date="evening"]').inner_text()
    mo = row.locator('[data-slot-date="morning"]').inner_text()
    inp = row.locator('.temp-input[data-slot="evening"]')
    inp.fill("366")
    inp.dispatch_event("change")
    page.wait_for_timeout(300)
    writes = [c for c in calls if c["method"] in ("POST", "PATCH")]
    ok = (ev == "11/9" and mo == "11/10" and len(writes) == 1 and writes[0]["body"].get("temp_c") == 36.6
          and inp.input_value() == "36.6")
    record("夕・朝の月日（夕は前日）・点なし 366 は 36.6 で保存して欄に見せる", ok,
           f"evening={ev} morning={mo} writes={[w['body'].get('temp_c') for w in writes]} shown={inp.input_value()}")
    browser.close()
    return ok


def case17_extra_disabled_and_width(pw):
    print("\n--- ケース17: 読み込み失敗時は追加ボタンも無効・375px で検温の行が枠からはみ出さない ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page, temp_get_fail=True)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function("() => document.querySelectorAll('.temp-row').length > 0 && !!reportLoadedFor", timeout=5000)
    ok_disabled = first_resident_row(page).locator('.temp-add-btn').is_disabled()
    page.close()
    page = browser.new_page(viewport={"width": 375, "height": 900})
    page.add_init_script(DELAY_INIT_SCRIPT)
    setup_routes(page)
    goto_loaded(page)
    add_extra(page, "19:35", "38.6")
    over = page.evaluate("""() => {
      const row = document.querySelector('.temp-row[data-subject="101"]');
      const box = row.parentElement.getBoundingClientRect();
      return Array.from(row.querySelectorAll('input, button, label')).filter(el => {
        const r = el.getBoundingClientRect(); return r.width > 0 && (r.right > box.right + 0.5 || r.left < box.left - 0.5);
      }).length;
    }""")
    ok = ok_disabled and over == 0
    record("読み込み失敗時は追加ボタン無効・375px ではみ出し 0", ok, f"disabled={ok_disabled} はみ出し={over}")
    browser.close()
    return ok


def case18_sibling_not_wiped(pw):
    print("\n--- ケース18: 夕の保存の返事が遅くても、その間に朝へ打った数字が消えない・両方保存される ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page)
    goto_loaded(page)
    # 書き込みの返事だけ 400ms 遅らせる
    page.evaluate("""() => { const f = window.fetch; window.fetch = async (u, o) => {
      const r = await f(u, o);
      if (String(u).includes('temperature_records') && o && o.method && o.method !== 'GET') await new Promise(x => setTimeout(x, 400));
      return r; }; }""")
    row = first_resident_row(page)
    ev = row.locator('.temp-input[data-slot="evening"]')
    mo = row.locator('.temp-input[data-slot="morning"]')
    ev.fill("36.8")
    ev.dispatch_event("change")
    mo.fill("36.4")           # 夕の返事を待たずに朝へ
    page.wait_for_timeout(700)  # 夕の返事が届く
    kept = mo.input_value()
    mo.dispatch_event("change")
    page.wait_for_timeout(700)
    writes = [c["body"] for c in calls if c["method"] in ("POST", "PATCH")]
    ok = (kept == "36.4" and ev.input_value() == "36.8" and mo.input_value() == "36.4"
          and sorted(set((w.get("slot"), w.get("temp_c")) for w in writes)) == [("evening", 36.8), ("morning", 36.4)])
    record("隣の欄に打っている途中の数字を、先の保存の返事が消さない", ok, f"kept={kept} writes={[(w.get('slot'), w.get('temp_c')) for w in writes]}")
    browser.close()
    return ok


def case19_quiet_save_while_typing(pw):
    print("\n--- ケース19: 欄を離れなくても、打鍵が止まって 1.5 秒で保存・打っている欄の数字は書き換えない・途中の数字で注意文を出さない ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page)
    goto_loaded(page)
    row = first_resident_row(page)
    inp = row.locator('.temp-input[data-slot="evening"]')
    inp.click()
    page.keyboard.type("3")
    page.wait_for_timeout(1900)
    err_mid = row.locator('.temp-error').is_visible()
    w0 = len([c for c in calls if c["method"] in ("POST", "PATCH", "DELETE")])
    page.keyboard.type("6")
    page.wait_for_timeout(1900)
    w1 = [c["body"].get("temp_c") for c in calls if c["method"] in ("POST", "PATCH")]
    shown = inp.input_value()
    page.keyboard.type(".5")
    page.wait_for_timeout(1900)
    w2 = [c["body"].get("temp_c") for c in calls if c["method"] in ("POST", "PATCH")]
    focused = page.evaluate("document.activeElement && document.activeElement.dataset.slot")
    ok = (not err_mid and w0 == 0 and w1 == [36] and shown == "36" and w2 == [36, 36.5]
          and inp.input_value() == "36.5" and focused == "evening")
    record("打ったまま止まると静かに保存・途中の「3」では注意も保存もなし・「36」が「36.0」に化けない", ok,
           f"err_mid={err_mid} w0={w0} w1={w1} shown={shown} w2={w2} focused={focused}")
    browser.close()
    return ok


def case20_flush_on_leave(pw):
    print("\n--- ケース20: 打ってすぐ画面を離れる（1.5 秒待たない）→ 離れる合図で保存が飛ぶ・測り直しの行も同じ ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    calls = setup_routes(page)
    goto_loaded(page)
    row = first_resident_row(page)
    row.locator('.temp-input[data-slot="morning"]').click()
    page.keyboard.type("36.7")
    row.locator('.temp-add-btn').click()
    ex = row.locator('.temp-extra').last
    ex.locator('.temp-extra-time').fill("21:10")
    ex.locator('.temp-extra-temp').click()
    page.keyboard.type("38.2")
    before = len([c for c in calls if c["method"] in ("POST", "PATCH") and c["body"].get("slot") == "21:10"])
    page.evaluate("""() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
      document.dispatchEvent(new Event('visibilitychange')); }""")
    page.wait_for_timeout(400)
    got = sorted((c["body"].get("slot"), c["body"].get("temp_c")) for c in calls if c["method"] in ("POST", "PATCH"))
    ok = before == 0 and ("21:10", 38.2) in got and ("morning", 36.7) in got
    record("画面を離れる合図で、欄を離れていない体温も保存される", ok, f"before={before} got={got}")
    browser.close()
    return ok


def case21_summary_no_html(pw):
    print("\n--- ケース21: まとめ表示は本文・短期入所の氏名・不足品を HTML として解釈しない ---")
    browser = pw.chromium.launch()
    page = new_page(browser)
    setup_routes(page)
    goto_loaded(page)
    evil = '<img src=x onerror="window.__xss=(window.__xss||0)+1">'
    page.locator('.resident-entry textarea').first.fill("本文" + evil + " <b>太字ではない</b>")
    page.locator('.short-stay-entry input').first.fill("短期" + evil)
    page.evaluate("showSummary()")
    page.wait_for_timeout(400)
    body = page.locator('#summary-body')
    text = body.inner_text()
    fired = page.evaluate("window.__xss || 0")
    ok = (body.locator('img').count() == 0 and body.locator('b').count() == 0 and fired == 0
          and "本文<img src=x" in text and "短期<img src=x" in text and "<b>太字ではない</b>" in text)
    record("まとめ表示で仕掛けの文字が動かず、文字のまま読める", ok, f"img={body.locator('img').count()} b={body.locator('b').count()} fired={fired}")
    browser.close()
    return ok


def screenshot_widths(pw):
    print("\n--- スクリーンショット（3幅・夕 37.8・朝 36.5・追加の測定 2 件） ---")
    browser = pw.chromium.launch()
    for width, name in [(375, "sp"), (768, "tablet"), (1280, "pc")]:
        page = browser.new_page(viewport={"width": width, "height": 900}, locale="ja-JP")
        page.add_init_script(DELAY_INIT_SCRIPT)
        setup_routes(page)
        page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
        page.wait_for_function(f"() => tempLoadedForDate === '{DATE}'", timeout=5000)
        row = first_resident_row(page)
        inp = row.locator('.temp-input[data-slot="evening"]')
        inp.fill("37.8")
        inp.dispatch_event("change")
        row.locator('.temp-input[data-slot="morning"]').fill("36.5")
        row.locator('.temp-input[data-slot="morning"]').dispatch_event("change")
        add_extra(page, "22:00", "38.1")
        add_extra(page, "01:00", "37.2")
        row.scroll_into_view_if_needed()
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
            extra = [case10_extra_add(pw), case11_extra_half_no_write(pw), case12_extra_prefill_sorted(pw),
                     case13_extra_edit(pw), case14_extra_duplicate_time(pw), case15_extra_delete_confirm(pw),
                     case16_labels_and_dotless(pw), case17_extra_disabled_and_width(pw),
                     case18_sibling_not_wiped(pw), case19_quiet_save_while_typing(pw), case20_flush_on_leave(pw),
                     case21_summary_no_html(pw)]
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
    labels = [f"ケース{i}" for i in range(1, 22)]
    rs = [r1, r2, r3, r4, r5, r6, r7, r8, r9] + extra
    print("\n" + " / ".join(f"{l}: {'PASS' if r else 'FAIL'}" for l, r in zip(labels, rs)))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
