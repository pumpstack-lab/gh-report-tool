#!/usr/bin/env python3
"""
現場アプリ4画面のログイン画面検証（本番Supabase・本番URL不使用）。
python3 -m http.server でローカル配信し、auth/REST応答を全てモックする。

確認すること:
  1. 未ログインだと4画面すべてでログイン画面が出る
  2. ログイン画面が出ている間はDB（rest/v1）を叩かない
  3. パスワードを間違えると日本語のエラーが出て、画面は開かない
  4. ログインに成功すると画面が開き、本来のデータ取得が走る
  5. セッションがあればログイン画面は出ない（2回目以降）
  6. 3幅（PC/タブレット/スマホ）で崩れない

実行:
  cd "gh-report-tool" && python3 scripts/verify_auth_gate.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8794
BASE = f"http://127.0.0.1:{PORT}"

PAGES = ["index.html", "report.html?gh=1", "history.html", "summary.html?gh=1&date=2026-09-09"]

FAKE_SESSION = {
    "access_token": "fake-token",
    "token_type": "bearer",
    "expires_in": 3600,
    "expires_at": int(time.time()) + 3600,
    "refresh_token": "fake-refresh",
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "staff@example.com"},
}

results = []


def record(label, ok, detail=""):
    results.append((label, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


def make_page(browser, *, logged_in: bool, rest_hits: list, bad_password: bool = False,
              auth_headers: list = None):
    """認証とRESTをモックしたページを作る。"""
    if auth_headers is None:
        auth_headers = []
    ctx = browser.new_context()
    page = ctx.new_page()

    def handle_token(route):
        # signInWithPassword は /auth/v1/token?grant_type=password を叩く
        if bad_password:
            # 本物のGoTrueは400で error_code/msg を返す。supabase-js はこれを
            # AuthApiError.message = msg として通すため、msgに実文言を入れる。
            route.fulfill(status=400, content_type="application/json",
                          body=json.dumps({"error_code": "invalid_credentials",
                                           "msg": "Invalid login credentials",
                                           "error": "invalid_grant",
                                           "error_description": "Invalid login credentials",
                                           "message": "Invalid login credentials"}))
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(FAKE_SESSION))

    def handle_rest(route):
        rest_hits.append(route.request.url)
        auth_headers.append(route.request.headers.get("authorization", ""))
        route.fulfill(status=200, content_type="application/json", body="[]")

    # ⚠️ Playwrightのrouteは「後に登録したものが先に評価される」。
    # 先に汎用の **/auth/v1/** を書くとtokenもそちらに食われるため、
    # 汎用を先に登録し、限定パターン(token)を後に登録する。
    page.route("**/auth/v1/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(FAKE_SESSION.get("user", {}))))
    page.route("**/auth/v1/token**", handle_token)
    page.route("**/rest/v1/**", handle_rest)

    if logged_in:
        # supabase-js v2 は localStorage の sb-<ref>-auth-token にセッションを持つ
        page.add_init_script(
            "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', "
            + json.dumps(json.dumps(FAKE_SESSION)) + ");"
        )
    return ctx, page


def main():
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            # ── ケース1+2: 未ログインでログイン画面が出て、DBを叩かない ──
            print("\n--- ケース1+2: 未ログイン時はログイン画面・DB非アクセス ---")
            for target in PAGES:
                hits = []
                ctx, page = make_page(browser, logged_in=False, rest_hits=hits)
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"{BASE}/{target}")
                page.wait_for_timeout(1200)
                shown = page.locator("#auth-overlay").is_visible()
                name = target.split("?")[0]
                record(f"{name}: ログイン画面が出る", shown)
                record(f"{name}: ログイン前はDBを叩かない", len(hits) == 0,
                       f"rest hits={len(hits)}")
                record(f"{name}: ページエラー0件", not errors, str(errors[:2]))
                ctx.close()

            # ── ケース3: パスワード誤りで日本語エラー・画面は開かない ──
            print("\n--- ケース3: パスワード誤り ---")
            hits = []
            ctx, page = make_page(browser, logged_in=False, rest_hits=hits, bad_password=True)
            page.goto(f"{BASE}/index.html")
            page.wait_for_timeout(800)
            page.fill("#auth-email", "staff@example.com")
            page.fill("#auth-pw", "wrong")
            page.click("#auth-submit")
            page.wait_for_timeout(1200)
            err_text = page.locator("#auth-err").inner_text()
            record("誤パスワードで日本語エラーが出る", "パスワード" in err_text, err_text)
            record("英語のまま出さない", "Invalid login" not in err_text, err_text)
            record("失敗時は画面が開かない", page.locator("#auth-overlay").is_visible())
            record("失敗時もDBを叩かない", len(hits) == 0, f"rest hits={len(hits)}")
            record("再入力できる（ボタンが戻る）",
                   page.locator("#auth-submit").is_enabled())
            ctx.close()

            # ── ケース4: ログイン成功で画面が開く ──
            print("\n--- ケース4: ログイン成功 ---")
            hits = []
            auth_headers = []
            ctx, page = make_page(browser, logged_in=False, rest_hits=hits,
                                  auth_headers=auth_headers)
            page.goto(f"{BASE}/index.html")
            page.wait_for_timeout(800)
            page.fill("#auth-email", "staff@example.com")
            page.fill("#auth-pw", "correct-password")
            page.click("#auth-submit")
            page.wait_for_timeout(1500)
            record("成功するとログイン画面が消える",
                   page.locator("#auth-overlay").count() == 0)
            record("成功後に本来のデータ取得が走る", len(hits) > 0, f"rest hits={len(hits)}")
            # ネイト条件4: ログイン後の1発目が「ログイン済みトークン」で飛んでいるか。
            # 同じclientインスタンスを使い回しているので載るはずだが、実測で確かめる。
            first_auth = auth_headers[0] if auth_headers else ""
            record("ログイン後の1発目にログイン済みトークンが載る",
                   "fake-token" in first_auth,
                   f"header={first_auth[:40]}")
            record("anonキーのままではない",
                   "sb_publishable" not in first_auth,
                   f"header={first_auth[:40]}")
            ctx.close()

            # ── ケース5: セッションがあればログイン画面を出さない ──
            print("\n--- ケース5: 2回目以降（セッションあり） ---")
            for target in PAGES:
                hits = []
                ctx, page = make_page(browser, logged_in=True, rest_hits=hits)
                page.goto(f"{BASE}/{target}")
                page.wait_for_timeout(1200)
                name = target.split("?")[0]
                record(f"{name}: ログイン画面が出ない",
                       page.locator("#auth-overlay").count() == 0)
                record(f"{name}: 通常どおりDBを読む", len(hits) > 0, f"rest hits={len(hits)}")
                ctx.close()

            # ── ケース6: 3幅で崩れない ──
            print("\n--- ケース6: 3幅で崩れない ---")
            for label, width in [("PC", 1280), ("タブレット", 768), ("スマホ", 375)]:
                ctx, page = make_page(browser, logged_in=False, rest_hits=[])
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(f"{BASE}/index.html")
                page.wait_for_timeout(1000)
                no_hscroll = page.evaluate(
                    "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
                record(f"{label}({width}px): 横スクロールなし", no_hscroll)
                record(f"{label}({width}px): 入力欄が見える",
                       page.locator("#auth-pw").is_visible())
                # iOSの自動ズーム回避（16px未満だと拡大される）
                fs = page.evaluate(
                    "() => parseFloat(getComputedStyle(document.querySelector('#auth-pw')).fontSize)")
                record(f"{label}({width}px): 入力欄が16px以上", fs >= 16, f"{fs}px")
                shot = ROOT / "scripts" / f"_auth_{width}.png"
                page.screenshot(path=str(shot), full_page=True)
                print(f"       screenshot: {shot}")
                ctx.close()

            browser.close()
    finally:
        server.terminate()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n=== {passed}/{total} PASS ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
