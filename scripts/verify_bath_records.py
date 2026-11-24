#!/usr/bin/env python3
"""
report.html 入浴の記録（マハロ）の画面確認（本番 Supabase・本番 URL 不使用）。
python3 -m http.server でこの作業フォルダを配信し、REST 応答を全てモックする。
設計: docs/superpowers/specs/2026-11-24-bath-records-design.md

実行:
  cd "gh-report-bath" && python3 scripts/verify_bath_records.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8806
BASE = f"http://127.0.0.1:{PORT}"
GH = 6
DATE = "2026-11-24"
RESIDENTS = [
    {"id": 101, "name": "見本一郎", "gh_num": GH, "active": True, "sort_order": 1},
    {"id": 102, "name": "見本二郎", "gh_num": GH, "active": True, "sort_order": 2},
]
FAKE_SESSION = {
    "access_token": "fake-token", "token_type": "bearer", "expires_in": 3600,
    "expires_at": int(time.time()) + 3600, "refresh_token": "fake-refresh",
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "staff@example.com"},
}
results = []
SEQ = [0]
T0 = "2026-11-24T00:00:00+00:00"  # 見本の行の更新時刻


def record(name, ok, detail=""):
    results.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def setup(page, *, rows=None, calls=None, get_fail=False, post_delay=0, gets=None, post_fail=None, stamp_never_matches=False, drop_reply=None):
    rows = [] if rows is None else rows
    calls = [] if calls is None else calls
    gets = [] if gets is None else gets

    def subject_of(r):
        return r.get("resident_id") if r.get("resident_id") is not None else r.get("short_stay_key")

    def handle(route):
        req = route.request
        url, method = req.url, req.method
        if "/rest/v1/bath_records" in url:
            q = {k: vals[0] for k, vals in parse_qs(urlparse(url).query).items()}
            if method == "GET":
                gets.append(url)
                if get_fail:
                    route.fulfill(status=404, content_type="application/json", body=json.dumps({"code": "42P01", "message": "no table"}))
                    return
                # 行に report_date がある時は、問い合わせの日付の行だけ返す（日付切替の確認用）
                want = q.get("report_date", "").replace("eq.", "")
                out = [r for r in rows if "report_date" not in r or not want or r["report_date"] == want]
                # 1 人ぶんの読み直し（ぶつかった時）
                if "resident_id" in q:
                    out = [r for r in out if str(r.get("resident_id")) == q["resident_id"].replace("eq.", "")]
                if "short_stay_key" in q:
                    out = [r for r in out if r.get("short_stay_key") == q["short_stay_key"].replace("eq.", "")]
                route.fulfill(status=200, content_type="application/json", body=json.dumps(out))
                return
            payload = json.loads(req.post_data) if req.post_data else None
            calls.append({"method": method, "url": url, "body": payload})
            if post_delay:
                time.sleep(post_delay / 1000)
            if post_fail and post_fail[0] > 0:
                post_fail[0] -= 1
                route.fulfill(status=500, content_type="application/json", body=json.dumps({"message": "mock failure"}))
                return
            cols = ("id", "kind", "bath_order", "start_min", "end_min", "updated_at")

            def match():
                """id と「読んだ時の更新時刻」の両方が合う行だけ（本番の .eq('id').eq('updated_at') と同じ）"""
                rid = int(q.get("id", "eq.0").replace("eq.", ""))
                if "updated_at" not in q:   # id だけで絞る送り方
                    return next((r for r in rows if r.get("id") == rid), None)
                if stamp_never_matches:      # 更新時刻での絞り込みが本番で効かなかった場合の再現
                    return None
                stamp = q.get("updated_at", "").replace("eq.", "")
                return next((r for r in rows if r.get("id") == rid and r.get("updated_at") == stamp), None)

            if method == "DELETE":
                target = match()
                if target is None:
                    route.fulfill(status=200, content_type="application/json", body="[]")
                    return
                rows[:] = [r for r in rows if r is not target]
                route.fulfill(status=200, content_type="application/json", body=json.dumps([{"id": target["id"]}]))
                return
            if method == "PATCH":
                target = match()
                if target is None:
                    route.fulfill(status=200, content_type="application/json", body="[]")
                    return
                target.update(payload)
                if drop_reply and drop_reply[0] > 0:   # 保存先には入ったが、返事だけ届かなかった
                    drop_reply[0] -= 1
                    route.abort()
                    return
                route.fulfill(status=200, content_type="application/json", body=json.dumps([{k: target.get(k) for k in cols}]))
                return
            # POST＝新しい行。同じ人・同じ日の行がもうあれば一意違反（本番の 23505）
            existing = next((r for r in rows if subject_of(r) == subject_of(payload)
                             and r.get("report_date", payload.get("report_date")) == payload.get("report_date")), None)
            if existing:
                route.fulfill(status=409, content_type="application/json", body=json.dumps({"code": "23505", "message": "duplicate key value"}))
                return
            SEQ[0] += 1
            row = dict(payload, id=700 + SEQ[0])
            rows.append(row)
            route.fulfill(status=201, content_type="application/json", body=json.dumps([{k: row.get(k) for k in cols}]))
            return
        if "/rest/v1/rpc/" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "current": {}}))
            return
        if "/rest/v1/reports" in url and method == "GET":
            route.fulfill(status=200, content_type="application/json", body="null")
            return
        if "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(RESIDENTS))
            return
        route.fulfill(status=200, content_type="application/json", body="[]")

    page.add_init_script(
        "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', " + json.dumps(json.dumps(FAKE_SESSION)) + ");")
    page.route("**/auth/v1/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(FAKE_SESSION)))
    page.route("**/rest/v1/**", handle)
    return rows, calls, gets


def open_page(browser, gh=GH, width=390, **kw):
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    dialogs = kw.pop("dialogs", None)
    accept = kw.pop("accept_dialog", True)   # 「消しますか？」の答え（既定は はい）

    def on_dialog(d):
        if dialogs is not None:
            dialogs.append(d.message)
        d.accept() if accept else d.dismiss()
    page.on("dialog", on_dialog)
    rows, calls, gets = setup(page, **kw)
    page.goto(f"{BASE}/report.html?gh={gh}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)
    return page, rows, calls, gets, errors


def row(page, i=0):
    return page.locator(".bath-row").nth(i)


def settle(page, calls, n, timeout=3000):
    end = time.time() + timeout / 1000
    while time.time() < end and len(calls) < n:
        page.wait_for_timeout(50)
    page.wait_for_timeout(150)


def main():
    busy = subprocess.run(["lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.strip()
    if busy:
        print(f"配信の残りがあります（{PORT} 番）。止めてからやり直してください:\n{busy}")
        sys.exit(2)
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT)], cwd=str(ROOT),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.7)
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()

            # 1. 行の数と選択肢
            page, rows, calls, gets, errors = open_page(b)
            record("マハロ：入浴の行が 入居者2＋短期入所2＝4 つ出る", page.locator(".bath-row").count() == 4)
            opts = row(page).locator(".bath-choice option").all_inner_texts()
            record("順番の選択肢＝選ぶ・1〜4番・事業所で入浴・入浴なし", opts == ["選ぶ", "1番", "2番", "3番", "4番", "事業所で入浴", "入浴なし"], str(opts))
            record("読み込みは 1 回だけ", len(gets) == 1, str(len(gets)))
            record("時刻欄は最初から見えている", row(page).locator(".bath-times").is_visible())
            # 順番より先に時刻を選ぶ→送らず、順番を促す
            r3 = row(page, 3)
            r3.locator(".bath-sh").select_option("19")
            page.wait_for_timeout(300)
            record("順番より先に時刻を選ぶ→送らない・「順番を選ぶと保存されます」", calls == [] and "順番を選ぶと保存されます" in r3.locator(".bath-msg-main").inner_text())
            r3.locator(".bath-sh").select_option("")
            r3.locator(".bath-eh").select_option("")
            page.wait_for_timeout(200)
            hours = row(page).locator(".bath-sh option").all_inner_texts()
            record("時の並びは 15時 から", hours[:3] == ["時", "15時", "16時"] and len(hours) == 25, str(hours[:3]))

            # 2. 番号だけ先に入れる
            row(page).locator(".bath-choice").select_option("1")
            settle(page, calls, 1)
            body = calls[-1]["body"] if calls else {}
            record("番号だけ選ぶ→順番だけ保存（時刻は空）", len(calls) == 1 and body.get("kind") == "home" and body.get("bath_order") == 1
                   and body.get("start_min") is None and body.get("end_min") is None and body.get("resident_id") == 101
                   and body.get("report_date") == DATE and body.get("gh_num") == GH, json.dumps(body, ensure_ascii=False))
            record("最初の保存は新しい行として入れる（上書き方式を使わない）", calls[-1]["method"] == "POST" and "on_conflict" not in calls[-1]["url"], calls[-1]["url"])
            record("時刻欄が出て、開始を促す", row(page).locator(".bath-times").is_visible() and "開始の時刻" in row(page).locator(".bath-msg-main").inner_text())
            record("「保存しました」が出る", row(page).locator(".bath-saved").is_visible())

            # 3. 開始→終了→分
            row(page).locator(".bath-sh").select_option("17")
            record("開始の時を選ぶと終了の時だけ同じ時になる（分は空）", row(page).locator(".bath-eh").input_value() == "17" and row(page).locator(".bath-em").input_value() == "")
            page.wait_for_timeout(300)
            record("開始の時だけ（分まだ）では送らない・「保存しました」も出さない", len(calls) == 1 and not row(page).locator(".bath-saved").is_visible(), str(len(calls)))
            row(page).locator(".bath-sm").select_option("0")
            settle(page, calls, 2)
            body = calls[-1]["body"]
            record("開始がそろったら開始だけ保存（終了は空）", len(calls) == 2 and body.get("start_min") == 1020 and body.get("end_min") is None, json.dumps(body, ensure_ascii=False))
            record("2 回目からは「読んだ時の更新時刻のまま」の行だけを書き換える", calls[-1]["method"] == "PATCH" and "id=eq." in calls[-1]["url"] and "updated_at=eq." in calls[-1]["url"], calls[-1]["url"])
            record("見出しの横に「11/23夕〜11/24朝」", row(page).locator(".bath-date").inner_text() == "11/23夕〜11/24朝", row(page).locator(".bath-date").inner_text())
            record("終了を促す文が出る", "終了の時刻" in row(page).locator(".bath-msg-main").inner_text())
            row(page).locator(".bath-em").select_option("20")
            settle(page, calls, 3)
            body = calls[-1]["body"]
            record("17:00〜17:20 → 開始 1020・終了 1040 で保存", len(calls) == 3 and body.get("start_min") == 1020 and body.get("end_min") == 1040, json.dumps(body, ensure_ascii=False))
            record("かかった時間「20分」が出る", row(page).locator(".bath-mins").inner_text() == "20分")
            record("注意文は消える", not row(page).locator(".bath-msg-main").is_visible())

            # 4. 終了が前
            row(page).locator(".bath-eh").select_option("16")
            page.wait_for_timeout(300)
            record("終了が開始より前→赤字・送らない・分は消える", len(calls) == 3 and "終了が開始より前" in row(page).locator(".bath-msg-main").inner_text()
                   and row(page).locator(".bath-mins").inner_text() == "")
            row(page).locator(".bath-eh").select_option("18")
            row(page).locator(".bath-em").select_option("10")
            settle(page, calls, 5)
            record("1時間超え（70分）→保存はする・確認の注意", calls[-1]["body"].get("end_min") == 1090 and "1時間を超えて" in row(page).locator(".bath-msg-main").inner_text()
                   and row(page).locator(".bath-mins").inner_text() == "70分", str(len(calls)))

            # 5. 重なり
            n = len(calls)
            row(page, 1).locator(".bath-choice").select_option("1")
            settle(page, calls, n + 1)
            record("同じ番号が 2 人→両方に注意（止めない）", row(page, 0).locator(".bath-msg-dup").is_visible() and row(page, 1).locator(".bath-msg-dup").is_visible()
                   and calls[-1]["body"].get("resident_id") == 102)
            # 6. 事業所
            n = len(calls)
            row(page, 1).locator(".bath-choice").select_option("facility")
            settle(page, calls, n + 1)
            body = calls[-1]["body"]
            record("事業所で入浴→時刻欄なし・順番と時刻は空で保存・重なりの注意が消える", body.get("kind") == "facility" and body.get("bath_order") is None and body.get("start_min") is None
                   and not row(page, 1).locator(".bath-times").is_visible() and not row(page, 0).locator(".bath-msg-dup").is_visible(), json.dumps(body, ensure_ascii=False))
            # 7. 未選択に戻す＝消す
            n = len(calls)
            row(page, 1).locator(".bath-choice").select_option("")
            settle(page, calls, n + 1)
            record("「選ぶ」に戻す→その行を消す", calls[-1]["method"] == "DELETE" and all(r.get("resident_id") != 102 for r in rows), calls[-1]["method"])
            # 時刻つきの行を「選ぶ」に戻す→時刻欄も空になって消える（時刻が残って「順番を促す」だけになり、記録が残ることがない）
            n = len(calls)
            row(page, 0).locator(".bath-choice").select_option("")
            settle(page, calls, n + 1)
            record("時刻つきの行を「選ぶ」に戻す→消える・時刻欄も空", calls[-1]["method"] == "DELETE" and all(r.get("resident_id") != 101 for r in rows)
                   and row(page, 0).locator(".bath-sh").input_value() == "" and row(page, 0).locator(".bath-em").input_value() == "" and not row(page, 0).locator(".bath-msg-main").is_visible())
            # 8. 短期入所
            n = len(calls)
            row(page, 2).locator(".bath-choice").select_option("none")
            settle(page, calls, n + 1)
            body = calls[-1]["body"]
            record("短期入所①→枠の番号で保存（入浴なし）", body.get("short_stay_key") == "__short_stay_1__" and body.get("resident_id") is None and body.get("kind") == "none", json.dumps(body, ensure_ascii=False))
            # 9. 続けて選んでも最後の選択が残る
            n = len(calls)
            r4 = row(page, 3)
            r4.locator(".bath-choice").select_option("2")
            r4.locator(".bath-choice").select_option("3")
            r4.locator(".bath-choice").select_option("4")
            page.wait_for_timeout(900)
            last = [r for r in rows if r.get("short_stay_key") == "__short_stay_2__"]
            record("続けて選び直す→最後の選択（4番）が保存先に残る", len(last) == 1 and last[0].get("bath_order") == 4, json.dumps(last, ensure_ascii=False))
            record("横にはみ出さない（幅 390）", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            page.screenshot(path="/tmp/bath_report_390.png", full_page=True)
            record("画面のエラー 0", errors == [], str(errors))
            page.close()

            # 10. 保存済みの表示
            saved = [
                {"id": 1, "resident_id": 101, "short_stay_key": None, "kind": "home", "bath_order": 2, "start_min": 1050, "end_min": 1080, "updated_at": T0},
                {"id": 2, "resident_id": 102, "short_stay_key": None, "kind": "facility", "bath_order": None, "start_min": None, "end_min": None, "updated_at": T0},
            ]
            page, rows, calls, gets, errors = open_page(b, rows=saved)
            r1 = row(page)
            record("保存済み：2番 17:30〜18:00・30分 が開いた時に出る", r1.locator(".bath-choice").input_value() == "2" and r1.locator(".bath-sh").input_value() == "17"
                   and r1.locator(".bath-sm").input_value() == "30" and r1.locator(".bath-eh").input_value() == "18" and r1.locator(".bath-em").input_value() == "0"
                   and r1.locator(".bath-mins").inner_text() == "30分")
            record("保存済み：事業所で入浴 が出る", row(page, 1).locator(".bath-choice").input_value() == "facility")
            record("開いただけでは何も送らない", calls == [], str(calls))
            # 同じ値を選び直しても送らない
            r1.locator(".bath-em").select_option("0")
            page.wait_for_timeout(300)
            record("同じ値を選び直しても送らない", calls == [], str(calls))
            page.close()

            # 11. ほかのホームには出さない
            page, rows, calls, gets, errors = open_page(b, gh=1)
            record("マハロ以外：入浴の行なし・読み込みにも行かない", page.locator(".bath-row").count() == 0 and gets == [] and errors == [], f"{len(gets)} {errors}")
            page.close()

            # 12. 表が読めない時
            page, rows, calls, gets, errors = open_page(b, get_fail=True)
            r1 = row(page)
            record("読めない時：注意文を出して選べなくする・日報は止めない", r1.locator(".bath-unavailable").is_visible() and r1.locator(".bath-choice").is_disabled()
                   and page.locator(".resident-entry textarea").first.is_enabled() and errors == [], str(errors))
            page.close()

            # 13. 保存に時間がかかる間の連続操作
            page, rows, calls, gets, errors = open_page(b, post_delay=400)
            r1 = row(page)
            r1.locator(".bath-choice").select_option("1")
            r1.locator(".bath-sh").select_option("17")
            r1.locator(".bath-sm").select_option("10")
            r1.locator(".bath-em").select_option("30")
            page.wait_for_timeout(1800)
            mine = [r for r in rows if r.get("resident_id") == 101]
            record("遅い回線で続けて選ぶ→最後の状態（17:10〜17:30）が残る・送る回数は選んだ回数（4）より少ない", len(mine) == 1 and mine[0].get("start_min") == 1030 and mine[0].get("end_min") == 1050 and len(calls) < 4,
                   f"{json.dumps(mine, ensure_ascii=False)} calls={len(calls)}")
            page.close()

            # 13-2. 開始だけ保存済みを開き直す（入浴を始めた時に打って閉じた後）
            started = [{"id": 5, "resident_id": 101, "short_stay_key": None, "kind": "home", "bath_order": 1, "start_min": 1020, "end_min": None, "updated_at": T0}]
            page, rows, calls, gets, errors = open_page(b, rows=started)
            r1 = row(page)
            record("開始だけ保存済み→開き直しても開始 17:00 が残り、終了を促す", r1.locator(".bath-sh").input_value() == "17" and r1.locator(".bath-sm").input_value() == "0"
                   and r1.locator(".bath-eh").input_value() == "" and "終了の時刻" in r1.locator(".bath-msg-main").inner_text() and calls == [])
            # 日をまたぐ入浴
            r1.locator(".bath-sh").select_option("23")
            r1.locator(".bath-sm").select_option("50")
            r1.locator(".bath-eh").select_option("0")
            r1.locator(".bath-em").select_option("10")
            page.wait_for_timeout(700)
            mine = [r for r in rows if r.get("resident_id") == 101]
            record("日をまたぐ 23:50〜0:10 → 20分で保存", r1.locator(".bath-mins").inner_text() == "20分" and mine[0].get("start_min") == 1430 and mine[0].get("end_min") == 10, json.dumps(mine, ensure_ascii=False))
            page.close()

            # 13-3. 保存に失敗→自動で送り直す
            page, rows, calls, gets, errors = open_page(b, post_fail=[1])
            r1 = row(page)
            r1.locator(".bath-choice").select_option("none")
            page.wait_for_timeout(600)
            record("保存に失敗→赤字で知らせる・「保存しました」は出さない", "保存できていません" in r1.locator(".bath-msg-main").inner_text() and not r1.locator(".bath-saved").is_visible())
            page.wait_for_timeout(3600)
            mine = [r for r in rows if r.get("resident_id") == 101]
            record("3 秒後に自動で送り直して保存・赤字が消える", len(mine) == 1 and mine[0].get("kind") == "none" and r1.locator(".bath-saved").is_visible() and not r1.locator(".bath-msg-main").is_visible(), f"{mine} calls={len(calls)}")
            page.close()

            # 13-4. 日付を切り替える→その日付の記録に入れ替わる・別の日付に書かない
            dated = [{"id": 31, "report_date": DATE, "gh_num": GH, "resident_id": 101, "short_stay_key": None, "kind": "home", "bath_order": 2, "start_min": 1050, "end_min": 1080, "updated_at": T0}]
            page, rows, calls, gets, errors = open_page(b, rows=dated)
            r1 = row(page)
            page.evaluate("() => { const d = document.getElementById('report-date'); d.value = '2026-11-23'; d.dispatchEvent(new Event('change', { bubbles: true })); }")
            page.wait_for_function("() => reportLoadedFor === '2026-11-23' && bathLoadedForDate === '2026-11-23'", timeout=8000)
            r1 = row(page)
            record("日付切替：前の日付の入浴が残らない（未選択・時刻も空）・見出しは 11/22夕〜11/23朝", r1.locator(".bath-choice").input_value() == "" and r1.locator(".bath-sh").input_value() == "" and r1.locator(".bath-em").input_value() == ""
                   and r1.locator(".bath-date").inner_text() == "11/22夕〜11/23朝", r1.locator(".bath-date").inner_text())
            r1.locator(".bath-choice").select_option("facility")
            settle(page, calls, 1)
            body = calls[-1]["body"] if calls else {}
            old = [r for r in rows if r.get("id") == 31][0]
            record("日付切替後の保存は切り替えた日付に入る・前の日付の行は変わらない", body.get("report_date") == "2026-11-23" and old.get("kind") == "home" and old.get("start_min") == 1050 and len(rows) == 2, json.dumps(body, ensure_ascii=False))
            page.evaluate(f"() => {{ const d = document.getElementById('report-date'); d.value = '{DATE}'; d.dispatchEvent(new Event('change', {{ bubbles: true }})); }}")
            page.wait_for_function(f"() => reportLoadedFor === '{DATE}' && bathLoadedForDate === '{DATE}'", timeout=8000)
            r1 = row(page)
            record("元の日付に戻す→2番 17:30〜18:00・30分 が戻る", r1.locator(".bath-choice").input_value() == "2" and r1.locator(".bath-mins").inner_text() == "30分" and errors == [], str(errors))
            page.close()

            # 13-5. 保存済みの順番が選択肢より大きい（入居者が減った後など）
            big = [{"id": 41, "resident_id": 101, "short_stay_key": None, "kind": "home", "bath_order": 7, "start_min": None, "end_min": None, "updated_at": T0}]
            page, rows, calls, gets, errors = open_page(b, rows=big)
            record("選択肢より大きい保存済みの順番（7番）も選ばれた状態で出る・開いただけでは送らない", row(page).locator(".bath-choice").input_value() == "7"
                   and row(page).locator(".bath-times").is_visible() and calls == [])
            page.close()

            # 13-6. 「選ぶ」に戻す＝消す前に確かめる。やめたら消さず、保存済みの内容に戻る
            one = lambda: [{"id": 51, "resident_id": 101, "short_stay_key": None, "kind": "home", "bath_order": 2, "start_min": 1050, "end_min": 1080, "updated_at": T0}]
            dl = []
            page, rows, calls, gets, errors = open_page(b, rows=one(), dialogs=dl, accept_dialog=False)
            r1 = row(page)
            r1.locator(".bath-choice").select_option("")
            page.wait_for_timeout(500)
            record("「選ぶ」に戻す→「消しますか？」と聞く", dl == ["この方の入浴の記録を消しますか？"], str(dl))
            record("やめる→消さない・2番 17:30〜18:00・30分 に戻る", calls == [] and len(rows) == 1 and r1.locator(".bath-choice").input_value() == "2"
                   and r1.locator(".bath-sh").input_value() == "17" and r1.locator(".bath-mins").inner_text() == "30分", str(calls))
            # 記録の無い人を「選ぶ」のままにしても聞かない
            row(page, 1).locator(".bath-sh").select_option("17")
            row(page, 1).locator(".bath-sh").select_option("")
            record("記録の無い人では聞かない", len(dl) == 1)
            page.close()

            # 13-7. ほかの端末が先に変えていた→黙って上書きしない
            page, rows, calls, gets, errors = open_page(b, rows=one())
            r1 = row(page)
            rows[0].update({"bath_order": 3, "start_min": 1140, "end_min": 1160, "updated_at": "2026-11-24T01:00:00+00:00"})  # 別の端末が 3番 19:00〜19:20 に変えた
            r1.locator(".bath-em").select_option("10")   # この端末は古い画面のまま、終了を 18:10 にしようとする
            page.wait_for_timeout(900)
            record("書き換え：ほかの端末の変更を上書きしない・最新（3番 19:00〜19:20）を出して知らせる", rows[0]["bath_order"] == 3 and rows[0]["start_min"] == 1140 and rows[0]["end_min"] == 1160
                   and r1.locator(".bath-choice").input_value() == "3" and r1.locator(".bath-sh").input_value() == "19" and r1.locator(".bath-mins").inner_text() == "20分"
                   and "ほかの端末で先に変更" in r1.locator(".bath-msg-main").inner_text() and not r1.locator(".bath-saved").is_visible(), json.dumps(rows, ensure_ascii=False))
            n = len(calls)
            r1.locator(".bath-em").select_option("30")   # 最新を見たうえで選び直すと保存できる
            settle(page, calls, n + 1)
            record("最新を見てから選び直すと保存できる（19:00〜19:30）", rows[0]["end_min"] == 1170 and r1.locator(".bath-mins").inner_text() == "30分" and r1.locator(".bath-saved").is_visible())
            record("ぶつかった時に読み直すのはその人の記録だけ（ほかの人の欄は読み直さない）", len(gets) == 2 and "resident_id=eq.101" in gets[1], str(gets[1:]))
            page.close()

            # ぶつかりの読み直し中に、別の人の保存が終わっても、その人の記録と表示が残る
            page, rows, calls, gets, errors = open_page(b, rows=one(), post_delay=300)
            r1, r2x = row(page), row(page, 1)
            rows[0].update({"bath_order": 3, "updated_at": "2026-11-24T01:00:00+00:00"})
            r1.locator(".bath-em").select_option("10")        # 1 人目：ぶつかる
            r2x.locator(".bath-choice").select_option("none")  # 2 人目：同時に新しく入れる
            page.wait_for_timeout(2200)
            two = [r for r in rows if r.get("resident_id") == 102]
            n = len(calls)
            r2x.locator(".bath-choice").select_option("facility")  # 2 人目を続けて書き換える（記録が画面に残っていれば PATCH・無ければ POST→ぶつかり）
            page.wait_for_timeout(1200)
            record("1 人目のぶつかりと 2 人目の保存が重なっても、2 人目は保存済み・続けて書き換えられる（2 行にならない・知らせも出ない）",
                   len(two) == 1 and calls[n]["method"] == "PATCH" and two[0]["kind"] == "facility" and r2x.locator(".bath-saved").is_visible()
                   and not r2x.locator(".bath-msg-main").is_visible() and "ほかの端末で先に変更" in r1.locator(".bath-msg-main").inner_text(), f"{calls[n]['method']} {json.dumps(two, ensure_ascii=False)}")
            page.close()

            page, rows, calls, gets, errors = open_page(b)
            r2 = row(page, 1)
            rows.append({"id": 61, "gh_num": GH, "report_date": DATE, "resident_id": 102, "short_stay_key": None, "resident_name": "見本二郎", "kind": "facility", "bath_order": None, "start_min": None, "end_min": None, "updated_at": T0})  # 別の端末が先に入れた
            r2.locator(".bath-choice").select_option("none")
            page.wait_for_timeout(900)
            mine = [r for r in rows if r.get("resident_id") == 102]
            record("新しく入れる：ほかの端末が先に入れていた→2 行にならず、先の内容（事業所で入浴）を出して知らせる", len(mine) == 1 and mine[0]["kind"] == "facility"
                   and r2.locator(".bath-choice").input_value() == "facility" and "ほかの端末で先に変更" in r2.locator(".bath-msg-main").inner_text(), json.dumps(mine, ensure_ascii=False))
            page.close()

            page, rows, calls, gets, errors = open_page(b, rows=one())
            r1 = row(page)
            rows[0].update({"end_min": 1090, "updated_at": "2026-11-24T01:00:00+00:00"})
            r1.locator(".bath-choice").select_option("")   # 古い画面から消そうとする（確認は はい）
            page.wait_for_timeout(900)
            record("消す：ほかの端末が先に変えていた→消さず、最新（17:30〜18:10・40分）を出して知らせる", len(rows) == 1 and r1.locator(".bath-choice").input_value() == "2"
                   and r1.locator(".bath-mins").inner_text() == "40分" and "ほかの端末で先に変更" in r1.locator(".bath-msg-main").inner_text() and errors == [], str(errors))
            page.close()

            # 13-7b. 安全弁：更新時刻での絞り込みが効かない保存先でも、書き換えと削除ができる（画面の選択は消えない）
            page, rows, calls, gets, errors = open_page(b, rows=one(), stamp_never_matches=True)
            r1 = row(page)
            r1.locator(".bath-em").select_option("20")   # 17:30〜18:20
            page.wait_for_timeout(1200)
            record("絞り込みが効かない保存先でも書き換えできる（17:30〜18:20・50分）・知らせは出さない", rows[0]["end_min"] == 1100 and r1.locator(".bath-em").input_value() == "20"
                   and r1.locator(".bath-mins").inner_text() == "50分" and r1.locator(".bath-saved").is_visible() and not r1.locator(".bath-msg-main").is_visible(), json.dumps(rows, ensure_ascii=False))
            r1.locator(".bath-choice").select_option("")
            page.wait_for_timeout(1200)
            record("絞り込みが効かない保存先でも消せる", rows == [] and r1.locator(".bath-choice").input_value() == "" and errors == [], json.dumps(rows, ensure_ascii=False))
            page.close()

            # 13-7c. 保存先には入ったが返事だけ届かなかった→自動の送り直しで「ほかの端末」と誤って知らせない
            page, rows, calls, gets, errors = open_page(b, rows=one(), drop_reply=[1])
            r1 = row(page)
            r1.locator(".bath-em").select_option("20")
            page.wait_for_timeout(4500)
            record("返事だけ届かなかった時：送り直しで保存済みになる・誤った知らせを出さない", rows[0]["end_min"] == 1100 and r1.locator(".bath-saved").is_visible()
                   and not r1.locator(".bath-msg-main").is_visible() and r1.locator(".bath-mins").inner_text() == "50分", r1.locator(".bath-msg-main").inner_text())
            page.close()

            # 13-7d. 返事だけ届かなかった後、送り直しを待たずに続きを選ぶ→自分の保存を「ほかの端末」と取り違えない・選んだ続きが残る
            page, rows, calls, gets, errors = open_page(b, rows=one(), drop_reply=[1])
            r1 = row(page)
            r1.locator(".bath-em").select_option("20")   # 17:30〜18:20（保存先には入るが返事が届かない）
            page.wait_for_timeout(700)
            r1.locator(".bath-em").select_option("30")   # 送り直し（3 秒後）を待たずに続きを選ぶ：17:30〜18:30
            page.wait_for_timeout(1500)
            record("自分の保存を取り違えない：知らせを出さず、後から選んだ 17:30〜18:30（60分）が保存される", rows[0]["end_min"] == 1110 and r1.locator(".bath-em").input_value() == "30"
                   and r1.locator(".bath-mins").inner_text() == "60分" and "ほかの端末" not in r1.locator(".bath-msg-main").inner_text(), f"{rows[0]['end_min']} / {r1.locator('.bath-msg-main').inner_text()}")
            page.wait_for_timeout(3500)
            record("その後の自動の送り直しでも崩れない（保存済み・知らせなし）", rows[0]["end_min"] == 1110 and r1.locator(".bath-saved").is_visible() and not r1.locator(".bath-msg-main").is_visible() and errors == [], r1.locator(".bath-msg-main").inner_text())
            page.close()

            # 13-7e. 3 回の送り直しで諦めた後、通信が戻ったら送る
            page, rows, calls, gets, errors = open_page(b, post_fail=[4])
            r1 = row(page)
            r1.locator(".bath-choice").select_option("none")
            page.wait_for_timeout(10500)
            gave_up = "読み込み直してください" in r1.locator(".bath-msg-main").inner_text() and len([r for r in rows if r.get("resident_id") == 101]) == 0
            page.evaluate("window.dispatchEvent(new Event('online'))")
            page.wait_for_timeout(900)
            mine = [r for r in rows if r.get("resident_id") == 101]
            record("3 回で諦めた後、通信が戻ると送り直して保存される", gave_up and len(mine) == 1 and mine[0]["kind"] == "none" and r1.locator(".bath-saved").is_visible() and not r1.locator(".bath-msg-main").is_visible(), f"gave_up={gave_up} {mine}")
            page.close()

            # 13-7g. 保存に失敗して送り直しを待っている間に日付を切り替える→切り替え先の日付には書かない
            page, rows, calls, gets, errors = open_page(b, post_fail=[1])
            r1 = row(page)
            r1.locator(".bath-choice").select_option("none")
            page.wait_for_timeout(500)
            page.evaluate("() => { const d = document.getElementById('report-date'); d.value = '2026-11-23'; d.dispatchEvent(new Event('change', { bubbles: true })); }")
            page.wait_for_function("() => reportLoadedFor === '2026-11-23' && bathLoadedForDate === '2026-11-23'", timeout=8000)
            n = len(calls)
            page.wait_for_timeout(3800)
            record("送り直し待ちの間に日付を切り替える→切り替え先には何も書かない・欄は未選択・赤字も持ち越さない", len(calls) == n and rows == [] and row(page).locator(".bath-choice").input_value() == ""
                   and not row(page).locator(".bath-msg-main").is_visible() and errors == [], f"calls {n}→{len(calls)} rows={rows}")
            page.close()

            # 13-7f. 時刻を入れてある人を「事業所で入浴」に変える＝時刻が消える操作も確かめる
            dl = []
            page, rows, calls, gets, errors = open_page(b, rows=one(), dialogs=dl, accept_dialog=False)
            r1 = row(page)
            r1.locator(".bath-choice").select_option("facility")
            page.wait_for_timeout(400)
            record("時刻のある人を事業所に変える→聞く・やめたら 2番 17:30〜18:00 のまま", dl == ["入れてある入浴の時刻が消えます。変えますか？"] and calls == [] and r1.locator(".bath-choice").input_value() == "2" and r1.locator(".bath-mins").inner_text() == "30分", str(dl))
            page.close()
            dl = []
            page, rows, calls, gets, errors = open_page(b, rows=[{"id": 71, "resident_id": 101, "short_stay_key": None, "kind": "home", "bath_order": 2, "start_min": None, "end_min": None, "updated_at": T0}], dialogs=dl)
            row(page).locator(".bath-choice").select_option("none")
            page.wait_for_timeout(500)
            record("時刻の無い人（順番だけ）を入浴なしに変える時は聞かない・保存される", dl == [] and rows[0]["kind"] == "none")
            page.close()

            # 13-8. 昼の 15 時をまたぐ入浴・打ち間違い
            page, rows, calls, gets, errors = open_page(b)
            r1 = row(page)
            r1.locator(".bath-choice").select_option("1")
            r1.locator(".bath-sh").select_option("14"); r1.locator(".bath-sm").select_option("50")
            r1.locator(".bath-eh").select_option("15"); r1.locator(".bath-em").select_option("10")
            page.wait_for_timeout(700)
            mine = [r for r in rows if r.get("resident_id") == 101]
            record("昼の 15 時をまたぐ 14:50〜15:10 → 20分で保存", r1.locator(".bath-mins").inner_text() == "20分" and mine and mine[0].get("start_min") == 890 and mine[0].get("end_min") == 910, json.dumps(mine, ensure_ascii=False))
            n = len(calls)
            r1.locator(".bath-sh").select_option("17"); r1.locator(".bath-sm").select_option("0")
            r1.locator(".bath-eh").select_option("5"); r1.locator(".bath-em").select_option("0")
            page.wait_for_timeout(700)
            mine = [r for r in rows if r.get("resident_id") == 101]
            record("打ち間違い 17:00〜5:00 → 赤字・分は出さない・終了 5:00 は保存されない", "3時間を超えて" in r1.locator(".bath-msg-main").inner_text() and r1.locator(".bath-mins").inner_text() == ""
                   and mine[0].get("end_min") != 300, json.dumps(mine, ensure_ascii=False))
            page.close()

            # 13-9. 幅 375：担当者の注記で画面が横にはみ出さない（入浴より前からあった崩れ）
            page, rows, calls, gets, errors = open_page(b, width=375)
            record("幅 375 で横にはみ出さない", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), str(page.evaluate("document.documentElement.scrollWidth")))
            page.close()

            # 14. パソコン幅
            page, rows, calls, gets, errors = open_page(b, width=1280, rows=saved)
            page.screenshot(path="/tmp/bath_report_1280.png", full_page=True)
            page.close()
            b.close()
    finally:
        server.terminate()
        server.wait(timeout=5)
    bad = [n for n, ok in results if not ok]
    print(f"\n=== {len(results) - len(bad)}/{len(results)} 通過 ===")
    for n in bad:
        print("FAIL:", n)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
