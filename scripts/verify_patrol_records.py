#!/usr/bin/env python3
"""
report.html 見回りチェックUIの検証（本番Supabase・本番URL不使用）。
python3 -m http.server でローカル配信し、REST応答を全てモックする。
モックされない Supabase 宛リクエストは abort する。

実行:
  cd "gh-report-tool" && python3 scripts/verify_patrol_records.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"
GH = 6
DATE = "2026-10-09"
RESIDENTS = [{"id": 101, "name": "山田太郎", "gh_num": GH, "active": True, "sort_order": 1}]
JSON = "application/json"
# 既存 verify_*.py（verify_partial_save.py）と同じ偽セッション。ログイン画面を通すためだけに使う
FAKE_SESSION = {
    "access_token": "fake-token", "token_type": "bearer", "expires_in": 3600,
    "expires_at": int(time.time()) + 3600, "refresh_token": "fake-refresh",
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "staff@example.com"},
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


def setup_routes(page, *, rows=None, get_fail=False, post_fail=False, blocked=None):
    """patrol_records の呼び出しを calls に溜める。rows は GET の応答。"""
    calls = []
    rows = list(rows or [])
    blocked = blocked if blocked is not None else []

    def catch_all(route):
        host = urlparse(route.request.url).hostname or ""
        if host in ("127.0.0.1", "localhost") or host.endswith("jsdelivr.net"):
            route.continue_()
        else:
            blocked.append(route.request.url)
            route.abort()

    def handle_rest(route):
        req = route.request
        url, method = req.url, req.method
        if "/rest/v1/patrol_records" in url:
            try:
                body = json.loads(req.post_data or "null")
            except Exception:
                body = req.post_data
            calls.append({"method": method, "url": url, "body": body, "headers": req.headers})
            if method == "GET":
                if get_fail:
                    route.fulfill(status=500, content_type=JSON, body=json.dumps({"message": "forced"}))
                else:
                    route.fulfill(status=200, content_type=JSON, body=json.dumps(rows))
            elif method == "POST":
                if post_fail:
                    route.fulfill(status=500, content_type=JSON, body=json.dumps({"message": "forced"}))
                else:
                    route.fulfill(status=201, content_type=JSON, body=json.dumps([{"id": 2}]))
            elif method == "DELETE":
                route.fulfill(status=200, content_type=JSON, body="[]")
            else:
                route.fulfill(status=200, content_type=JSON, body="{}")
            return
        if "/rest/v1/reports" in url and method == "GET":
            route.fulfill(status=200, content_type=JSON, body="null")
        elif "/rest/v1/residents" in url:
            route.fulfill(status=200, content_type=JSON, body=json.dumps(RESIDENTS))
        else:
            route.fulfill(status=200, content_type=JSON, body="[]")

    page.route("**/*", catch_all)
    page.add_init_script(
        "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', "
        + json.dumps(json.dumps(FAKE_SESSION)) + ");"
    )
    page.route("**/auth/v1/**", lambda r: r.fulfill(
        status=200, content_type=JSON, body=json.dumps(FAKE_SESSION)))
    page.route("**/rest/v1/**", handle_rest)
    return calls, blocked


def open_page(pw, **kw):
    browser = pw.chromium.launch()
    page = browser.new_page()
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    calls, blocked = setup_routes(page, **kw)
    page.goto(f"{BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".patrol-block", timeout=5000)
    return browser, page, calls, blocked


def wait_loaded(page):
    page.wait_for_selector(".patrol-checkbox:not([disabled])", timeout=5000)


def case1(pw):
    browser, page, calls, blocked = open_page(pw, rows=[])
    n = page.locator(".patrol-block").count()
    cbs = page.locator(".patrol-checkbox").count()
    labels = [t.strip() for t in page.locator(".patrol-slots label").all_inner_texts()]
    ok = n == 1 and cbs == 4 and labels == ["22:30", "23:30", "1:00", "5:00"]
    record("1. patrol-block 1つ・チェック4つ・ラベル順", ok, f"{n} {cbs} {labels}")
    browser.close()
    return ok and not blocked


def case2(pw):
    browser, page, calls, _ = open_page(pw, rows=[{"id": 1, "resident_id": 101, "slot": "22:30"}])
    wait_loaded(page)
    states = [page.locator(f'.patrol-checkbox[data-slot="{s}"]').is_checked() for s in ["22:30", "23:30", "01:00", "05:00"]]
    copy_vis = page.locator(".patrol-copy-btn").is_visible()
    ok = states == [True, False, False, False] and copy_vis
    record("2. GET応答の22:30だけchecked・コピーボタン表示", ok, f"{states} copy={copy_vis}")
    browser.close()
    return ok


def case3(pw):
    browser, page, calls, _ = open_page(pw, rows=[{"id": 1, "resident_id": 101, "slot": "22:30"}])
    wait_loaded(page)
    page.locator('.patrol-checkbox[data-slot="23:30"]').click()
    page.wait_for_timeout(400)
    posts = [c for c in calls if c["method"] == "POST"]
    prefer = posts[0]["headers"].get("prefer", "") if posts else ""
    body = posts[0]["body"] if posts else {}
    if isinstance(body, list):
        body = body[0]
    page.locator(".patrol-copy-btn").click()
    page.wait_for_timeout(200)
    clip = page.evaluate("navigator.clipboard.readText()")
    ok = (len(posts) == 1 and "resolution=ignore-duplicates" in prefer
          and body.get("slot") == "23:30" and body.get("resident_name") == "山田太郎"
          and clip == "山田太郎さん　見回り　22:30　23:30")
    record("3. 23:30 ON→POST(ignore-duplicates)・コピー文面", ok, f"prefer={prefer} body={body} clip={clip}")
    browser.close()
    return ok


def case4(pw):
    browser, page, calls, _ = open_page(pw, rows=[{"id": 1, "resident_id": 101, "slot": "22:30"}])
    wait_loaded(page)
    page.once("dialog", lambda d: d.accept())
    page.locator('.patrol-checkbox[data-slot="22:30"]').click()
    page.wait_for_timeout(400)
    dels = [c for c in calls if c["method"] == "DELETE"]
    checked = page.locator('.patrol-checkbox[data-slot="22:30"]').is_checked()
    ok = len(dels) == 1 and "id=eq.1" in dels[0]["url"] and not checked
    record("4. 22:30 OFF+accept→DELETE id=eq.1・unchecked", ok, f"dels={[d['url'] for d in dels]} checked={checked}")
    browser.close()
    return ok


def case5(pw):
    browser, page, calls, _ = open_page(pw, rows=[{"id": 1, "resident_id": 101, "slot": "22:30"}])
    wait_loaded(page)
    page.once("dialog", lambda d: d.dismiss())
    page.locator('.patrol-checkbox[data-slot="22:30"]').click()
    page.wait_for_timeout(400)
    dels = [c for c in calls if c["method"] == "DELETE"]
    checked = page.locator('.patrol-checkbox[data-slot="22:30"]').is_checked()
    ok = len(dels) == 0 and checked
    record("5. OFF+dismiss→DELETEなし・checkedのまま", ok, f"dels={len(dels)} checked={checked}")
    browser.close()
    return ok


def case6(pw):
    browser, page, calls, _ = open_page(pw, rows=[], post_fail=True)
    wait_loaded(page)
    page.locator('.patrol-checkbox[data-slot="23:30"]').click()
    page.wait_for_timeout(400)
    checked = page.locator('.patrol-checkbox[data-slot="23:30"]').is_checked()
    err = page.locator(".patrol-error").is_visible()
    ok = (not checked) and err
    record("6. POST 500→チェックが戻りエラー表示", ok, f"checked={checked} err={err}")
    browser.close()
    return ok


def case7(pw):
    browser, page, calls, _ = open_page(pw, get_fail=True)
    page.wait_for_selector(".patrol-unavailable-msg", state="visible", timeout=5000)
    dis = [page.locator(f'.patrol-checkbox[data-slot="{s}"]').is_disabled() for s in ["22:30", "23:30", "01:00", "05:00"]]
    ok = all(dis) and page.locator(".patrol-unavailable-msg").is_visible()
    record("7. GET 500→4つdisabled・読み込み失敗メッセージ", ok, f"{dis}")
    browser.close()
    return ok


def main():
    server = start_server()
    try:
        with sync_playwright() as pw:
            rs = [f(pw) for f in (case1, case2, case3, case4, case5, case6, case7)]
    finally:
        server.terminate()
        server.wait(timeout=5)
    print("\n=== 結果サマリ ===")
    for name, ok, _ in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    sys.exit(0 if all(rs) else 1)


if __name__ == "__main__":
    main()
