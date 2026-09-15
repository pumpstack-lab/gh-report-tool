#!/usr/bin/env python3
"""
report.html 本文消失バグの検証（2026-09-15）。本番Supabase・本番URLは一切使わない。
python3 -m http.server でローカル配信し、REST/RPC応答を全てモックする。

背景（本番 reports_history 実測・9/4〜9/15）:
  本文の消失/大幅短縮の候補を13件検出したが、うち多くは推敲による短縮で、
  9/15 3-2ホームの当日分には消失が無かったことを後に実測で確認している。
  それでも下記2点はコードの欠陥として実在したため修正した。
  ① 保存成功パスでも applyServerState を「取り込み」の意味で呼んでいたため
     lastSaved が永久に進まず、同じ欄の2回目以降の保存が必ず偽の競合になっていた。
  ② applyDeferredOrImmediate が result.current の全キーを textarea へ書き戻していたため、
     保存の往復中に打った文字が送信時スナップショットへ巻き戻っていた。

実行:
  cd "gh-report-tool" && python3 scripts/verify_report_no_data_loss.py
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
GH = 6
DATE = "2026-09-05"

RESIDENTS = [
    {"id": 101, "name": "山田太郎", "gh_num": GH, "active": True, "sort_order": 1},
    {"id": 102, "name": "佐藤花子", "gh_num": GH, "active": True, "sort_order": 2},
]

FAKE_SESSION = {
    "access_token": "fake-token",
    "token_type": "bearer",
    "expires_in": 3600,
    "expires_at": int(time.time()) + 3600,
    "refresh_token": "fake-refresh",
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "staff@example.com"},
}

EXISTING_REPORT = {
    "id": 1, "gh_num": GH, "gh_name": "こもれびホームマハロ", "report_date": DATE,
    "reporter": "", "workers": [],
    "residents": {"山田太郎": "既存A", "佐藤花子": "既存B"},
    "shortage": "[]", "photos": [],
    "updated_at": "2026-09-05T00:00:00.000000+00:00",
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
    time.sleep(0.8)
    return proc


def setup_routes(page, rpc_calls, pending_routes, auto_responses):
    """RPCは auto_responses があれば即答、無ければ route を保留して手動で答える。"""
    def handle_rest(route):
        req = route.request
        url = req.url
        if "/rest/v1/rpc/report_save_partial" in url:
            try:
                payload = json.loads(req.post_data or "null")
            except Exception:
                payload = req.post_data
            rpc_calls.append(payload)
            if auto_responses:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(auto_responses.pop(0)))
            else:
                pending_routes.append(route)
            return
        if "/rest/v1/reports" in url and req.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(EXISTING_REPORT))
            return
        if "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(RESIDENTS))
            return
        route.fulfill(status=200, content_type="application/json", body="[]")

    page.route("**/rest/v1/**", handle_rest)


def open_page(browser, rpc_calls, pending_routes, auto_responses):
    page = browser.new_page()
    page.on("dialog", lambda d: d.accept())  # 競合の破壊的操作はconfirmを挟む
    # ログイン画面（2026-09-09導入）を通すため、supabase-js v2 のセッションを先に置く
    page.add_init_script(
        "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', "
        + json.dumps(json.dumps(FAKE_SESSION)) + ");"
    )
    page.route("**/auth/v1/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(FAKE_SESSION)))
    setup_routes(page, rpc_calls, pending_routes, auto_responses)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=8000)
    return page


def type_into(ta, text):
    ta.fill(text)
    ta.dispatch_event("input")


def case1_no_false_conflict(pw):
    """①同じ欄に2回続けて書いても偽の競合にならない（2回目のbaseがサーバー現在値）。"""
    print("\n--- ケース①: 同じ欄を続けて書いても偽の競合が出ない ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    auto = [
        {"ok": True, "current": {"residents": {"山田太郎": "一回目", "佐藤花子": "既存B"},
                                 "reporter": "", "workers": [], "photos": [], "shortage": "[]"}},
        {"ok": True, "current": {"residents": {"山田太郎": "一回目二回目", "佐藤花子": "既存B"},
                                 "reporter": "", "workers": [], "photos": [], "shortage": "[]"}},
    ]
    page = open_page(browser, calls, pending, auto)
    ta = page.locator(".resident-entry textarea").first

    type_into(ta, "一回目")
    page.wait_for_timeout(3600)
    type_into(ta, "一回目二回目")
    page.wait_for_timeout(3600)

    ok_two = len(calls) == 2
    record("保存RPCが2本飛ぶ", ok_two, f"実際: {len(calls)}本")

    base2 = (calls[1].get("p_base") or {}).get("residents", {}) if len(calls) >= 2 else {}
    ok_base = base2.get("山田太郎") == "一回目"
    record("2回目のbaseがサーバー現在値『一回目』になっている（偽の競合を出さない）",
           ok_base, json.dumps(base2, ensure_ascii=False))

    no_banner = page.locator(".resident-entry .conflict-banner").count() == 0
    record("競合バナーが出ていない", no_banner)

    browser.close()
    return ok_two and ok_base and no_banner


def case2_no_revert_during_roundtrip(pw):
    """②保存の往復中に打った文字が、応答処理で巻き戻らない。"""
    print("\n--- ケース②: 保存の往復中に打った文字が巻き戻らない ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    page = open_page(browser, calls, pending, [])
    ta_a = page.locator(".resident-entry textarea").first
    ta_b = page.locator(".resident-entry textarea").nth(1)

    type_into(ta_a, "既存A追記")
    page.wait_for_timeout(3600)
    ok_inflight = len(pending) == 1
    record("保存RPCが飛んで応答待ちになっている", ok_inflight, f"保留数: {len(pending)}")
    if not ok_inflight:
        browser.close()
        return False

    # 往復中に職員が書き足し、別の利用者欄へ移る（Aはフォーカスを失い無防備になる）
    type_into(ta_a, "既存A追記さらに追記")
    ta_b.focus()

    pending[0].fulfill(status=200, content_type="application/json", body=json.dumps(
        {"ok": True, "current": {"residents": {"山田太郎": "既存A追記", "佐藤花子": "他端末が書いたB"},
                                 "reporter": "", "workers": [], "photos": [], "shortage": "[]"}}))
    page.wait_for_timeout(800)

    a_val = ta_a.input_value()
    ok_a = a_val == "既存A追記さらに追記"
    record("往復中に打った文字が残っている（送信時スナップショットへ巻き戻らない）", ok_a, a_val)

    # 応答が返った時点でBは入力中（フォーカス中）なので、書き換えずに保留する
    b_val_focused = ta_b.input_value()
    ok_b_focused = b_val_focused == "既存B"
    record("入力中の欄は応答が来ても書き換えない", ok_b_focused, b_val_focused)

    # フォーカスを外したら、保留していた他端末の内容が入る
    ta_b.evaluate("el => el.blur()")
    page.wait_for_timeout(300)
    b_val = ta_b.input_value()
    ok_b = b_val == "他端末が書いたB"
    record("フォーカス離脱後に他端末の内容を取り込む", ok_b, b_val)

    browser.close()
    return ok_a and ok_b_focused and ok_b


def case3_merge_keeps_both(pw):
    """③競合時に『両方残す』で双方の記録が失われない。"""
    print("\n--- ケース③: 競合時に『両方残す』で双方が残る ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    auto = [
        {"ok": False, "conflicts": {"residents": ["山田太郎"]},
         "current": {"residents": {"山田太郎": "他端末が書いた本文", "佐藤花子": "既存B"},
                     "reporter": "", "workers": [], "photos": [], "shortage": "[]"}},
        {"ok": True, "current": {"residents": {"山田太郎": "他端末が書いた本文\n自分が書いた本文", "佐藤花子": "既存B"},
                                 "reporter": "", "workers": [], "photos": [], "shortage": "[]"}},
    ]
    page = open_page(browser, calls, pending, auto)
    ta = page.locator(".resident-entry textarea").first

    type_into(ta, "自分が書いた本文")
    page.wait_for_timeout(3600)

    has_banner = page.locator(".resident-entry .conflict-banner").count() == 1
    record("本物の競合ではバナーが出る", has_banner)

    has_merge = page.locator(".btn-conflict-merge").count() == 1
    record("『両方残す』ボタンがある", has_merge)
    if not (has_banner and has_merge):
        browser.close()
        return False

    page.locator(".btn-conflict-merge").first.click()
    merged = ta.input_value()
    ok_merged = "他端末が書いた本文" in merged and "自分が書いた本文" in merged
    record("画面に双方の本文が残る", ok_merged, merged.replace("\n", " / "))

    page.wait_for_timeout(3600)
    ok_sent = len(calls) == 2
    record("合体した本文の保存RPCが飛ぶ", ok_sent, f"実際: {len(calls)}本")

    sent_val = ""
    base_val = None
    if len(calls) >= 2:
        sent_val = (calls[1].get("p_patch") or {}).get("residents", {}).get("山田太郎", "")
        base_val = (calls[1].get("p_base") or {}).get("residents", {}).get("山田太郎")
    ok_payload = "他端末が書いた本文" in sent_val and "自分が書いた本文" in sent_val
    record("送信内容に双方の本文が入っている", ok_payload, sent_val.replace("\n", " / "))
    ok_base = base_val == "他端末が書いた本文"
    record("baseがサーバー現在値になっている（CASを通る）", ok_base, str(base_val))

    browser.close()
    return ok_merged and ok_sent and ok_payload and ok_base


def case4_retry_and_unsaved_banner(pw):
    """④保存に失敗したら自動で送り直し、未保存の表示が消えない。"""
    print("\n--- ケース④: 保存失敗→自動再送＋未保存の消えない表示 ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    page = open_page(browser, calls, pending, [])
    ta = page.locator(".resident-entry textarea").first

    # 最初の保存を500で失敗させる
    fail_then_ok = {"n": 0}

    def handle(route):
        if "/rest/v1/rpc/report_save_partial" in route.request.url:
            calls.append(json.loads(route.request.post_data or "null"))
            fail_then_ok["n"] += 1
            if fail_then_ok["n"] == 1:
                route.fulfill(status=500, content_type="application/json",
                              body=json.dumps({"message": "通信エラー"}))
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(
                    {"ok": True, "current": {"residents": {"山田太郎": "失敗しても届く本文", "佐藤花子": "既存B"},
                                             "reporter": "", "workers": [], "photos": [], "shortage": "[]"}}))
            return
        route.fulfill(status=200, content_type="application/json", body="[]")

    page.route("**/rest/v1/**", handle)
    type_into(ta, "失敗しても届く本文")
    page.wait_for_timeout(3600)

    ok_failed = len(calls) == 1
    record("1回目の保存が失敗として記録される", ok_failed, f"呼び出し {len(calls)}本")

    banner = page.locator("#unsaved-banner")
    shown = banner.is_visible() and "未保存" in banner.inner_text()
    record("未保存の表示が出る", shown, banner.inner_text()[:60])

    # 自動再送（1回目の待ちは5秒）
    page.wait_for_timeout(7000)
    ok_retry = len(calls) >= 2
    record("入力しなくても自動で送り直す", ok_retry, f"呼び出し {len(calls)}本")

    page.wait_for_timeout(500)
    gone = not page.locator("#unsaved-banner").is_visible()
    record("保存できたら未保存の表示が消える", gone)

    browser.close()
    return ok_failed and shown and ok_retry and gone


def case5_conflict_left_alone_is_visible(pw):
    """⑤競合を放置している間、その欄が保存されないことが画面に出続ける（本番3-2の事故）。"""
    print("\n--- ケース⑤: 競合放置中は「保存されません」が出続ける ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    auto = [
        {"ok": False, "conflicts": {"residents": ["山田太郎"]},
         "current": {"residents": {"山田太郎": "他端末の本文", "佐藤花子": "既存B"},
                     "reporter": "", "workers": [], "photos": [], "shortage": "[]"}},
    ]
    page = open_page(browser, calls, pending, auto)
    ta = page.locator(".resident-entry textarea").first
    type_into(ta, "自分の本文")
    page.wait_for_timeout(3600)

    b = page.locator("#unsaved-banner")
    shown = b.is_visible()
    txt = b.inner_text() if shown else ""
    record("競合中は未保存の表示が出る", shown, txt[:70])
    named = "山田太郎" in txt
    record("どの利用者の欄かが名前で分かる", named)

    # 放置したまま10秒経っても消えない
    page.wait_for_timeout(10000)
    still = page.locator("#unsaved-banner").is_visible()
    record("放置しても表示が消えない", still)

    # 「両方残す」で解消すると消える
    page.locator(".btn-conflict-merge").first.click()
    page.wait_for_timeout(500)
    gone = not page.locator("#unsaved-banner").is_visible()
    record("解消したら表示が消える", gone)

    browser.close()
    return shown and named and still and gone


def case6_draft_survives_reload(pw):
    """⑥保存できないまま再読み込みしても、書きかけが端末に残り復元できる。"""
    print("\n--- ケース⑥: 保存前に再読み込みしても書きかけが残る ---")
    browser = pw.chromium.launch()
    ctx = browser.new_context()
    calls, pending = [], []

    def prep(page):
        page.on("dialog", lambda d: d.accept())
        page.add_init_script(
            "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', "
            + json.dumps(json.dumps(FAKE_SESSION)) + ");")
        page.route("**/auth/v1/**", lambda r: r.fulfill(
            status=200, content_type="application/json", body=json.dumps(FAKE_SESSION)))

        def h(route):
            u = route.request.url
            if "rpc/report_save_partial" in u:
                calls.append(json.loads(route.request.post_data or "null"))
                route.fulfill(status=500, content_type="application/json",
                              body=json.dumps({"message": "通信エラー"}))
                return
            if "/rest/v1/reports" in u and route.request.method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(EXISTING_REPORT)); return
            if "/rest/v1/residents" in u:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(RESIDENTS)); return
            route.fulfill(status=200, content_type="application/json", body="[]")
        page.route("**/rest/v1/**", h)

    page = ctx.new_page(); prep(page)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".resident-entry textarea", timeout=8000)
    type_into(page.locator(".resident-entry textarea").first, "サーバーに届かなかった本文")
    page.wait_for_timeout(4000)
    record("保存は失敗している", len(calls) >= 1, f"{len(calls)}本")

    stored = page.evaluate("() => localStorage.getItem('report_draft_6_2026-09-05')")
    record("書きかけが端末に控えられている", bool(stored) and "届かなかった" in (stored or ""), (stored or "")[:50])

    # 同じブラウザ文脈で再読み込み（＝端末のlocalStorageは残る）
    page2 = ctx.new_page(); prep(page2)
    page2.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page2.wait_for_selector(".resident-entry textarea", timeout=8000)
    page2.wait_for_timeout(1200)

    offer = page2.locator("#draft-restore-banner")
    shown = offer.is_visible()
    record("再読み込み後に復元の案内が出る", shown, offer.inner_text()[:60] if shown else "")
    if not shown:
        ctx.close(); browser.close(); return False

    page2.locator("#draft-restore-yes").click()
    page2.wait_for_timeout(500)
    restored = page2.locator(".resident-entry textarea").first.input_value()
    ok = restored == "サーバーに届かなかった本文"
    record("押すと本文が戻る", ok, restored)

    ctx.close(); browser.close()
    return bool(stored) and shown and ok


def case7_short_stay_conflict_has_picker(pw):
    """⑦短期入所欄の競合でも選択UIが出る（以前は出せず永久に未保存だった）。"""
    print("\n--- ケース⑦: 短期入所欄の競合にも選択UIが出る ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    auto = [
        {"ok": False, "conflicts": {"residents": ["__short_stay_1__"]},
         "current": {"residents": {"山田太郎": "既存A", "佐藤花子": "既存B", "__short_stay_1__": "他端末の短期入所本文"},
                     "reporter": "", "workers": [], "photos": [], "shortage": "[]"}},
    ]
    page = open_page(browser, calls, pending, auto)
    ss = page.locator(".short-stay-entry textarea").first
    ok_exists = page.locator(".short-stay-entry").count() > 0
    record("短期入所欄が存在する（マハロ）", ok_exists)
    if not ok_exists:
        browser.close(); return False

    type_into(ss, "自分が書いた短期入所本文")
    page.wait_for_timeout(3600)

    banner = page.locator(".short-stay-entry .conflict-banner")
    shown = banner.count() == 1
    record("短期入所欄に選択UIが出る", shown)
    if not shown:
        browser.close(); return False

    page.locator(".short-stay-entry .btn-conflict-merge").first.click()
    page.wait_for_timeout(300)
    merged = ss.input_value()
    ok = "他端末の短期入所本文" in merged and "自分が書いた短期入所本文" in merged
    record("両方残すで双方が残る", ok, merged.replace("\n", " / "))

    browser.close()
    return shown and ok


def case8_sticky_not_hidden_by_unsaved(pw):
    """⑧未保存が出ていても、担当者の通知（委託料に直結）が隠れない。"""
    print("\n--- ケース⑧: 消えない通知は未保存に隠されない ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    page = open_page(browser, calls, pending, [])
    # 未保存と消えない通知を同時に立てる
    page.evaluate("""() => {
        window.__setSticky('担当者／不足品が他の職員に更新されました。担当者欄を確認してください');
        window.__setUnsaved('⚠️ 未保存の入力があります（保存を再試行中）。画面を閉じないでください');
    }""")
    page.wait_for_timeout(300)

    sticky = page.locator("#top-conflict-banner")
    unsaved = page.locator("#unsaved-banner")
    ok_sticky = sticky.is_visible()
    record("担当者の通知が表示される", ok_sticky, sticky.inner_text()[:40] if ok_sticky else "")
    ok_unsaved = unsaved.is_visible()
    record("未保存の表示も同時に出る", ok_unsaved)

    shown = page.locator(".load-guard-banner.is-visible").count()
    ok_two = shown == 2
    record("同時に出る帯は2枚まで", ok_two, f"{shown}枚")

    # 4つ全部立てても2枚に収まる
    page.evaluate("""() => {
        window.__setLoadGuard('読み込み中です');
        window.__setDraftRestore('書きかけが残っています');
    }""")
    page.wait_for_timeout(300)
    shown4 = page.locator(".load-guard-banner.is-visible").count()
    ok_max = shown4 == 2
    record("4つ立てても2枚を超えない", ok_max, f"{shown4}枚")
    still = page.locator("#top-conflict-banner").is_visible()
    record("そのときも担当者の通知は残る", still)

    browser.close()
    return ok_sticky and ok_unsaved and ok_two and ok_max and still


def case9_sticky_merged_not_read_from_dom(pw):
    """⑨担当者の警告が出ている時に短期入所の競合が起きても、両方の文言が残る。
    状態ではなくDOMから読み戻していると、絞り込み方次第で担当者の警告が消える。"""
    print("\n--- ケース⑨: 担当者の警告と短期入所の警告が併記される ---")
    browser = pw.chromium.launch()
    calls, pending = [], []
    page = open_page(browser, calls, pending, [])

    # 担当者の警告が出ている状態を作る
    page.evaluate("() => window.__setSticky('担当者／不足品が他の職員に更新されました。担当者欄を確認してください')")
    # そのうえで、表示を絞り込む他の帯も立てる（DOM読み戻しだと担当者側が消える条件）
    page.evaluate("() => { window.__setLoadGuard('読み込み中です'); window.__setUnsaved('未保存の入力があります'); }")
    page.wait_for_timeout(200)

    # 短期入所の競合が後から起きたときの併記処理を走らせる
    page.evaluate("""() => {
        const prev = window.__bannerState.sticky;
        const msg = '一部の欄が他の職員の入力と競合しました。その欄の内容を控えてから管理者へご連絡ください';
        window.__setSticky(prev && prev.indexOf(msg) === -1 ? (prev + ' ／ ' + msg) : (prev || msg));
    }""")
    page.wait_for_timeout(200)

    state = page.evaluate("() => window.__bannerState.sticky")
    ok_both = '担当者' in state and '競合しました' in state
    record("担当者の警告が消えずに併記される", ok_both, state[:80])

    visible_txt = page.locator("#top-conflict-banner").inner_text()
    ok_shown = '担当者' in visible_txt
    record("画面にも担当者の警告が出ている", ok_shown, visible_txt[:60])

    shown = page.locator(".load-guard-banner.is-visible").count()
    ok_two = shown == 2
    record("帯は2枚に収まっている", ok_two, f"{shown}枚")

    browser.close()
    return ok_both and ok_shown and ok_two


def main():
    proc = start_server()
    try:
        with sync_playwright() as pw:
            oks = [case1_no_false_conflict(pw), case2_no_revert_during_roundtrip(pw), case3_merge_keeps_both(pw),
                   case4_retry_and_unsaved_banner(pw), case5_conflict_left_alone_is_visible(pw),
                   case6_draft_survives_reload(pw), case7_short_stay_conflict_has_picker(pw),
                   case8_sticky_not_hidden_by_unsaved(pw), case9_sticky_merged_not_read_from_dom(pw)]
    finally:
        proc.terminate()

    print("\n=== 結果 ===")
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed or not all(oks) else 0


if __name__ == "__main__":
    sys.exit(main())
