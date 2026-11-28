#!/usr/bin/env python3
"""
事業所からの申し送り（日報に読むだけで出す）の検証（本番 Supabase・本番 URL 不使用）。
scripts/verify_resident_tabs.py のモック基盤を流用する。名前は架空。

実行:
  python3 scripts/verify_handover.py
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_resident_tabs as base  # noqa: E402

base.PORT = 8797
base.BASE = f"http://127.0.0.1:{base.PORT}"
GH, DATE, NEXT = base.GH, "2026-09-04", "2026-09-05"
SHOTS = Path(os.environ.get("SHOT_DIR", "/tmp"))
EVIL = '<img src=x onerror="window.__pwned=1">昼食は完食'
A, S = "青木一郎", "佐藤花子"   # base.RESIDENTS の 102・101
results = []


def record(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def payload(date, late=False):
    if date != DATE:
        return {"facilities": [{"key": "komoan", "submitted_at": None, "reporter": None, "notice": None}], "notes": [], "fixed": []}
    notes = [
        {"resident_id": 101, "facility": "komoan", "target_date": DATE, "body": EVIL + "\n爪切りをお願いします。", "updated_at": "2026-09-04T07:12:00+00:00"},
        {"resident_id": 101, "facility": "komoan", "target_date": "2026-09-03", "body": "前回の文です。", "updated_at": "2026-09-03T07:00:00+00:00"},
    ]
    if late:
        notes.append({"resident_id": 102, "facility": "respoir", "target_date": DATE, "body": "後から届いた文", "updated_at": "2026-09-04T08:30:00+00:00"})
    return {
        "facilities": [
            {"key": "komoan", "submitted_at": "2026-09-04T07:12:00+00:00", "reporter": "架空職員", "notice": "明日は 15 分早く送ります。" + EVIL},
            {"key": "respoir", "submitted_at": "2026-09-04T08:30:00+00:00" if late else None, "reporter": "架空職員" if late else None, "notice": "" if late else None},
        ],
        "notes": notes,
        "fixed": [{"id": 1, "resident_id": 102, "body": "朝食後の薬を確認" + EVIL, "source": "gh", "start_date": "2026-09-01",
                   "until_date": DATE, "created_by": "架空ホーム職員"}],
    }


def open_page(browser, state, width=375):
    page = base.new_page(browser, viewport={"width": width, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    base.setup_routes(page, report_row=base.EXISTING_REPORT)

    def rpc(route):
        state["calls"] += 1
        if state.get("fail"):
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"message": "boom"}))
            return
        if state.get("missing"):
            route.fulfill(status=404, content_type="application/json", body=json.dumps({"code": "PGRST202", "message": "not found"}))
            return
        body = json.loads(route.request.post_data or "{}")
        state["args"] = body
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload(body.get("p_date"), state.get("late"))))

    page.route("**/rest/v1/rpc/handover_for_home", rpc)
    page.goto(f"{base.BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)
    return page, errors


def entry(page, name):
    return page.locator(f".resident-entry[data-name='{name}']")


def main():
    server = base.start_server()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            # ── 1. ふつうの日 ──
            state = {"calls": 0}
            page, errors = open_page(browser, state)
            page.wait_for_selector("#handover-band:not([hidden])")
            record("関数にホームと日付を渡す", state["args"] == {"p_gh": GH, "p_date": DATE}, str(state.get("args")))
            band = page.inner_text("#handover-band")
            record("帯に 届いた／まだ が出る", "こも庵 16:12 届いた" in band and "レスポアール まだ" in band, band[:80])
            record("帯に全体連絡と報告者", "こも庵 の全体連絡" in band and "明日は 15 分早く" in band and "報告者：架空職員" in band)
            jumps = page.locator("#handover-band .handover-jump").all_inner_texts()
            record("帯に申し送りのある人の名前（今日・固定）", jumps == [S, A], str(jumps))
            marks = page.evaluate("() => [...document.querySelectorAll('.resident-tab-btn')].filter(b => b.querySelector('.resident-tab-ho')).map(b => b.dataset.tabKey)")
            record("タブの印は今日の申し送りがある人だけ", marks == [S], str(marks))

            # 先頭（50 音順）の人＝固定だけの人
            box = entry(page, A).locator(".handover-box")
            txt = box.inner_text()
            record("固定申し送りが入力欄の上に出る（出どころ・今日まで・入れた人）",
                   "📌 固定申し送り" in txt and "グループホーム" in txt and "今日まで" in txt and "入れた人：架空ホーム職員" in txt, txt[:90])
            record("注意文が出る", "処方の内容と所定の手順で確かめて" in txt)
            order = entry(page, A).evaluate("e => { const k = [...e.children]; return k.findIndex(c => c.classList.contains('handover-box')) < k.findIndex(c => c.tagName === 'TEXTAREA'); }")
            record("箱は本文の入力欄より上", order)
            href = box.locator("a.handover-link").get_attribute("href")
            record("固定を足す・終えるの入口がその人を指す", href.endswith(f"/handover/fixed?gh={GH}&rid=102"), href)

            # 帯の名前を押すとその人へ
            page.locator("#handover-band .handover-jump", has_text=S).click()
            record("帯の名前を押すとその人のタブが開く", entry(page, S).is_visible() and not entry(page, A).is_visible())
            txt = entry(page, S).locator(".handover-box").inner_text()
            record("今日の申し送り（事業所名・時刻・改行）", "今日の申し送り" in txt and "こも庵・16:12" in txt and "爪切りをお願いします。" in txt, txt[:90])
            det = entry(page, S).locator("details.handover-prev")
            record("前回分は畳んで出る", det.count() == 1 and det.evaluate("d => !d.open") and "9/3" in det.locator("summary").inner_text())
            record("仕込み文が動かない（文字のまま出る）",
                   page.evaluate("window.__pwned === undefined") and page.locator("#handover-band img, .handover-box img").count() == 0
                   and "<img src=x" in txt)
            record("読むだけ（箱の中に入力欄が無い）", page.locator(".handover-box textarea, .handover-box input, #handover-band textarea").count() == 0)
            record("375px で横にはみ出さない", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            page.screenshot(path=str(SHOTS / "_report_handover_375.png"), full_page=True)

            # 既存の本文と保存はそのまま
            ta = entry(page, S).locator(":scope > textarea").first
            record("既存の本文はそのまま入っている", ta.input_value() == "既存の本文（佐藤さん）")

            # ── 2. 開きっぱなしの間に届いた分：入力中の人の箱は動かさない ──
            page.locator(f".resident-tab-btn[data-tab-key='{A}']").click()
            ta_a = entry(page, A).locator(":scope > textarea").first
            ta_a.click(); ta_a.type("入力中")
            before = entry(page, A).locator(".handover-box").inner_text()
            state["late"] = True
            calls = state["calls"]
            page.evaluate("handoverFetchedAt = Date.now() - 6 * 60 * 1000; document.dispatchEvent(new Event('visibilitychange'));")
            page.wait_for_function("document.getElementById('handover-band').textContent.includes('レスポアール 17:30 届いた')")
            record("前面に戻ると取り直す（5 分以上）", state["calls"] == calls + 1)
            record("入力中の人の箱は差し替えない", entry(page, A).locator(".handover-box").inner_text() == before and ta_a.input_value() == "入力中")
            page.locator("#report-date").focus()
            page.wait_for_function(f"document.querySelector(\".resident-entry[data-name='{A}'] .handover-box\").textContent.includes('後から届いた文')")
            record("欄を離れると新しい申し送りが出る・打った文は残る", ta_a.input_value() == "入力中")
            calls = state["calls"]
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'));")
            page.wait_for_timeout(300)
            record("5 分たっていなければ取り直さない", state["calls"] == calls)

            # ── 3. 日付を変えると前の日の分は消える ──
            page.fill("#report-date", NEXT)
            page.dispatch_event("#report-date", "change")
            page.wait_for_function(f"() => reportLoadedFor === '{NEXT}'", timeout=8000)
            page.wait_for_function("document.getElementById('handover-band').textContent.includes('こも庵 まだ')")
            record("別の日では前の日の申し送りが残らない",
                   page.locator(".handover-box").count() == 0 and page.locator(".resident-tab-ho").count() == 0
                   and "届いた" not in page.inner_text("#handover-band"))
            record("申し送りの無い人にも固定の入口だけは出る", entry(page, A).locator("a.handover-link").count() == 1)
            page.fill("#report-date", DATE); page.dispatch_event("#report-date", "change")
            page.wait_for_function("document.querySelectorAll('.handover-box').length > 0")
            page.route("**/rest/v1/reports*", lambda r: r.fulfill(status=500, content_type="application/json", body='{"message":"boom"}') if r.request.method == "GET" else r.fallback())
            page.fill("#report-date", "2026-09-06"); page.dispatch_event("#report-date", "change")
            page.wait_for_timeout(1500)
            record("日報の読み込みが失敗した日にも、前の日の申し送りは残らない",
                   page.locator(".handover-box").count() == 0 and page.locator(".resident-tab-ho").count() == 0 and "届いた" not in page.inner_text("#handover-band"),
                   str(page.evaluate("[document.getElementById('report-date').value, handoverDate, reportLoadedFor, document.querySelectorAll('.handover-box').length, document.getElementById('handover-band').hidden, document.querySelectorAll('.resident-tab-ho').length, document.getElementById('handover-band').innerText]")))
            page.unroute("**/rest/v1/reports*")
            record("画面のエラーが無い", not errors, "; ".join(errors))
            page.close()

            # ── 4. 幅 1280 ──
            page, errors = open_page(browser, {"calls": 0}, width=1280)
            page.wait_for_selector("#handover-band:not([hidden])")
            record("1280px で横にはみ出さない", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            page.screenshot(path=str(SHOTS / "_report_handover_1280.png"), full_page=True)
            page.close()

            # ── 5. 関数がまだ無い環境では何も出さず、日報はそのまま使える ──
            page, errors = open_page(browser, {"calls": 0, "missing": True})
            page.wait_for_timeout(500)
            record("関数が無い間は帯も箱も出ない", page.locator("#handover-band").is_hidden() and page.locator(".handover-box-slot").count() == 0)
            record("関数が無くても日報は開ける", entry(page, A).locator(":scope > textarea").first.is_visible() and not errors)
            page.close()

            # ── 6. 読み込み失敗は帯で知らせる（日報は止めない） ──
            page, errors = open_page(browser, {"calls": 0, "fail": True})
            page.wait_for_selector("#handover-band:not([hidden])")
            record("読み込み失敗を帯で知らせる", "読み込めませんでした" in page.inner_text("#handover-band"))
            state6 = page.evaluate("handoverSeq")
            page.unroute("**/rest/v1/rpc/handover_for_home")
            page.route("**/rest/v1/rpc/handover_for_home", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(payload(DATE))))
            page.locator("#handover-band .handover-jump", has_text="もう一度読み込む").click()
            page.wait_for_function("document.getElementById('handover-band').textContent.includes('届いた')")
            record("「もう一度読み込む」で出し直せる", page.locator(".handover-box").count() >= 1)
            record("失敗しても日報は開ける", entry(page, A).locator(":scope > textarea").first.is_visible() and not errors)
            browser.close()
    finally:
        server.terminate()
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} 通過")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
