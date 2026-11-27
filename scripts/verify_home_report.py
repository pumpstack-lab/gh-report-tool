#!/usr/bin/env python3
"""
houkoku.html（ホーム報告書）の検証（本番Supabase・本番URL不使用）。
python3 -m http.server でローカル配信し、REST応答を全てモックする。名前・本文は全部架空。
設計: docs/superpowers/specs/2026-11-27-home-report-design.md

実行:
  cd "gh-report-tool" && python3 scripts/verify_home_report.py            # chromium + webkit
  python3 scripts/verify_home_report.py --pdf <出力先.pdf>                  # 印刷の見た目を PDF に出す（chromium）
"""
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8811
BASE = f"http://127.0.0.1:{PORT}"
WIDTHS = [("PC", 1280, 900), ("タブレット", 820, 1100), ("スマホ", 390, 844)]

FAKE_SESSION = {
    "access_token": "fake-token", "token_type": "bearer", "expires_in": 3600,
    "expires_at": int(time.time()) + 3600, "refresh_token": "fake-refresh",
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "staff@example.com"},
}
SAMPLE_BODY = "見本の本文です。\n\n・架空の出来事その1\n・架空の出来事その2\n\n以上、報告します。"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  — {detail}" if detail else ""))
    return ok


def seed_rows():
    return [
        {"id": "aaaaaaaa-0000-4000-8000-000000000001", "gh_num": 2, "report_date": "2026-11-20", "reporter": "見本 一郎",
         "body": "先週の見本の報告です。\n2 行目。", "updated_at": "2026-11-20T09:00:00.000000+00:00", "deleted_at": None},
        {"id": "aaaaaaaa-0000-4000-8000-000000000002", "gh_num": 6, "report_date": "2026-11-25", "reporter": "見本 花子",
         "body": "<b>太字にならない</b>見本", "updated_at": "2026-11-25T09:00:00.000000+00:00", "deleted_at": None},
    ]


class Mock:
    """home_reports の REST を、本番の決まり（一意・更新時刻で絞る・消さずに隠す）どおりにまねる。"""

    def __init__(self, rows=None):
        self.rows = seed_rows() if rows is None else rows
        self.calls = []
        self.fail_writes = 0      # この回数だけ書き込みを 500 にする
        self.fail_list = False
        self.lose_reply = 0       # この回数だけ「DB には入ったが返事が落ちた」をまねる
        self.tick = 0

    def stamp(self):
        self.tick += 1
        return f"2026-11-27T10:00:{self.tick:02d}.000000+00:00"

    def handle(self, route):
        req = route.request
        q = parse_qs(urlparse(req.url).query)
        method = req.method

        def out(data, status=200):
            route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

        def match(r):
            for key, vals in q.items():
                v = vals[0]
                if key in ("select", "order", "limit"):
                    continue
                if v.startswith("eq."):
                    if str(r.get(key)) != v[3:]:
                        return False
                elif v == "is.null":
                    if r.get(key) is not None:
                        return False
            return True

        if method == "GET":
            self.calls.append({"method": "GET", "url": req.url})
            if self.fail_list:
                return out({"message": "mock failure"}, 500)
            rows = [r for r in self.rows if match(r)]
            rows.sort(key=lambda r: (r["report_date"], r["id"]), reverse=True)
            return out(rows[: int(q.get("limit", ["1000"])[0])])

        payload = json.loads(req.post_data or "null")
        self.calls.append({"method": method, "url": req.url, "body": payload})
        if method == "DELETE":
            return out({"code": "42501", "message": "permission denied"}, 403)
        if self.fail_writes > 0:
            self.fail_writes -= 1
            return out({"message": "mock failure"}, 500)
        if method == "POST":
            if any(r["id"] == payload["id"] for r in self.rows):
                return out({"code": "23505", "message": "duplicate key value"}, 409)
            row = {**payload, "updated_at": self.stamp(), "deleted_at": None}
            self.rows.append(row)
            if self.lose_reply > 0:
                self.lose_reply -= 1
                return route.abort()
            return out([row], 201)
        if method == "PATCH":
            hit = [r for r in self.rows if match(r)]
            for r in hit:
                r.update(payload)
                r["updated_at"] = self.stamp()
            return out(hit)
        return out({}, 400)


def start_server():
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
                            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.7)
    return proc


def open_page(browser, mock, w=1280, h=900, logged_in=True, path="/houkoku.html"):
    ctx = browser.new_context(viewport={"width": w, "height": h}, timezone_id="Asia/Tokyo")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if logged_in:
        ctx.add_init_script(
            "if (!window.localStorage.getItem('sb-vqeoutrlvdydxenaspas-auth-token')) "
            "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', "
            + json.dumps(json.dumps(FAKE_SESSION)) + ");")
    page.route("**/auth/v1/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(FAKE_SESSION)))
    page.route("**/rest/v1/home_reports**", mock.handle)
    page.route("**/rest/v1/reports**", lambda r: r.fulfill(status=200, content_type="application/json", body="[]"))
    page.goto(BASE + path, wait_until="networkidle")
    page.wait_for_timeout(250)
    return ctx, page, errors


def fill_form(page, gh="3", reporter="見本 太郎", body=SAMPLE_BODY, date=None):
    if date:
        page.fill("#in-date", date)
    page.select_option("#in-gh", gh)
    page.fill("#in-reporter", reporter)
    page.fill("#in-body", body)


def writes(mock):
    return [c for c in mock.calls if c["method"] != "GET"]


def status(page):
    return page.inner_text("#status")


def no_overflow(page):
    return page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def run_engine(pw, engine):
    browser = getattr(pw, engine).launch()
    today = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 9 * 3600))

    for label, w, h in WIDTHS:
        print(f"\n=== {engine} / {label} ({w}x{h}) ===")
        mock = Mock()
        ctx, page, errors = open_page(browser, mock, w, h)

        # 1. 開いた時
        check("欄が最初から 4 つとも見えている", all(page.is_visible(s) for s in ("#in-date", "#in-gh", "#in-reporter", "#in-body")))
        check("日付は今日（日本の暦）", page.input_value("#in-date") == today, page.input_value("#in-date"))
        check("ホームは 6 つ＋「選んでください」", page.locator("#in-gh option").count() == 7)
        check("報告者は空（共用の端末なので覚えない）", page.input_value("#in-reporter") == "")
        check("一覧に保存済みの 2 件（新しい順）", [x.get_attribute("data-id")[-1] for x in page.locator(".item").all()] == ["2", "1"])
        check("開く時の DB への依頼は 1 回", len(mock.calls) == 1, str(len(mock.calls)))
        check("一覧の本文は文字のまま出る（太字にならない）", page.locator(".item b").count() == 0 and "<b>" in page.locator(".item .x").first.inner_text())
        check("横にはみ出さない", no_overflow(page))
        check("入力欄の文字は 16px 以上（iPhone で勝手に拡大しない）",
              page.evaluate("[...document.querySelectorAll('input,select,textarea')].every(e => parseFloat(getComputedStyle(e).fontSize) >= 16)"))
        check("押す所は高さ 44px 以上",
              page.evaluate("[...document.querySelectorAll('button:not([hidden]), select, input')].filter(e => e.offsetParent).every(e => e.getBoundingClientRect().height >= 44)"))

        # 2. 入力の不足
        page.click("#btn-save")
        check("空のまま保存 → ホームの欄を指して知らせる・書き込み 0", "ホームを選んでください" in status(page) and not writes(mock), status(page))
        page.select_option("#in-gh", "3")
        page.click("#btn-save")
        check("報告者が空 → 知らせる", "報告者" in status(page))
        page.fill("#in-reporter", "見本 太郎")
        page.click("#btn-save")
        check("本文が空 → 知らせる・書き込み 0", "本文" in status(page) and not writes(mock))

        # 3. 保存 → 一覧に出る
        fill_form(page)
        check("打つと「書きかけを捨てる」が出る", page.is_visible("#btn-discard"))
        page.click("#btn-save")
        page.wait_for_timeout(400)
        w1 = writes(mock)
        check("保存 → 書き込み 1 本（POST）", len(w1) == 1 and w1[0]["method"] == "POST", str([c["method"] for c in w1]))
        body = w1[0]["body"] if w1 else {}
        check("送る中身：日付・ホーム・報告者・本文・画面で作った番号",
              body.get("gh_num") == 3 and body.get("reporter") == "見本 太郎" and body.get("body") == SAMPLE_BODY
              and body.get("report_date") == today and len(str(body.get("id", ""))) == 36, json.dumps(body, ensure_ascii=False)[:120])
        check("「保存しました」", status(page) == "保存しました", status(page))
        check("保存した報告書が一覧の先頭に出て、開いている印が付く",
              page.locator(".item").count() == 3 and "current" in (page.locator(".item").first.get_attribute("class") or ""))
        check("保存後は下書きが端末に残らない", page.evaluate("localStorage.getItem('houkoku_draft_v1')") is None)
        page.click("#btn-save")
        page.wait_for_timeout(250)
        check("変えずにもう一度保存 → 書き込みは増えない", len(writes(mock)) == 1)

        # 4. 直す（読んだ時の更新時刻で絞る）
        page.fill("#in-body", SAMPLE_BODY + "\n追記です。")
        page.click("#btn-save")
        page.wait_for_timeout(400)
        w2 = writes(mock)
        check("直して保存 → PATCH 1 本・更新時刻で絞っている",
              len(w2) == 2 and w2[1]["method"] == "PATCH" and "updated_at=eq." in w2[1]["url"] and "deleted_at=is.null" in w2[1]["url"], w2[-1]["url"][-90:])
        check("直した本文が DB に入った・行は増えない", len(mock.rows) == 3 and mock.rows[-1]["body"].endswith("追記です。"))

        # 5. ほかの端末で先に直された
        mock.rows[-1]["updated_at"] = "2026-11-27T11:11:11.000000+00:00"
        page.fill("#in-body", "上書きしてはいけない本文")
        page.click("#btn-save")
        page.wait_for_timeout(400)
        check("ほかの端末で直されていたら上書きしない・知らせる",
              "ほかの端末" in status(page) and not mock.rows[-1]["body"].startswith("上書き"), status(page)[:30])
        check("その時、書いた内容は端末に残る", "上書きしてはいけない本文" in (page.evaluate("localStorage.getItem('houkoku_draft_v1')") or ""))
        ctx.close()

        # 6. 保存の失敗 → 残る → もう一度で 1 枚だけ
        mock = Mock()
        ctx, page, errors2 = open_page(browser, mock, w, h)
        errors += errors2
        fill_form(page)
        mock.fail_writes = 1
        page.click("#btn-save")
        page.wait_for_timeout(400)
        check("保存に失敗 → 知らせる・欄の中身はそのまま", "保存できませんでした" in status(page) and page.input_value("#in-body") == SAMPLE_BODY)
        mock.lose_reply = 1
        page.click("#btn-save")
        page.wait_for_timeout(500)
        check("DB には入ったが返事が落ちた → 失敗と知らせる", "保存できませんでした" in status(page) and len(mock.rows) == 3)
        page.click("#btn-save")
        page.wait_for_timeout(500)
        check("もう一度押しても 2 枚にならない（同じ番号を直す）", len(mock.rows) == 3 and status(page) == "保存しました", f"行 {len(mock.rows)} / {status(page)}")

        # 7. 2 回続けて押しても 1 本
        page.click("#btn-new")
        fill_form(page, gh="1", reporter="見本 次郎", body="二度押しの見本")
        page.evaluate("document.getElementById('btn-save').click(); document.getElementById('btn-save').click();")
        page.wait_for_timeout(500)
        check("保存を 2 回続けて押しても 1 枚", sum(1 for r in mock.rows if r["body"] == "二度押しの見本") == 1)
        check("次に書く時、ホームは直前のホームが入っている", page.click("#btn-new") is None and page.input_value("#in-gh") == "1" and page.input_value("#in-reporter") == "")

        # 8. 一覧から開く・絞る・消す
        page.locator('.item[data-id$="0002"]').click()
        check("一覧から開く → 欄に入る", page.input_value("#in-gh") == "6" and page.input_value("#in-reporter") == "見本 花子" and page.input_value("#in-date") == "2026-11-25")
        check("開いた時は「新しく書く」「この報告書を消す」が出る", page.is_visible("#btn-new") and page.is_visible("#btn-delete"))
        page.select_option("#filter-gh", "6")
        page.wait_for_timeout(350)
        check("ホームで絞る → そのホームだけ", page.locator(".item").count() == 1)
        page.select_option("#filter-gh", "")
        page.wait_for_timeout(350)
        page.once("dialog", lambda d: d.accept())
        page.click("#btn-delete")
        page.wait_for_timeout(450)
        last = writes(mock)[-1]
        check("消す → 行は消さず、消した時刻を入れるだけ（DELETE を使わない）",
              last["method"] == "PATCH" and "deleted_at" in last["body"] and all(c["method"] != "DELETE" for c in mock.calls))
        check("消した報告書は一覧から消える・DB には残る",
              page.locator('.item[data-id$="0002"]').count() == 0 and any(r["id"].endswith("0002") and r["deleted_at"] for r in mock.rows))
        check("消した後は新しい報告書の画面に戻る", status(page) == "消しました" and page.input_value("#in-body") == "")

        # 9. 書きかけ：黙って戻さない
        fill_form(page, gh="4", reporter="見本 三郎", body="書きかけの見本")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(300)
        check("開き直すと、書きかけは黙って戻さず知らせを出す（誰の・いつの）",
              page.is_visible("#draft-card") and "見本 三郎" in page.inner_text("#draft-text") and page.input_value("#in-body") == "")
        page.click("#btn-draft-use")
        check("「続きを書く」→ 欄に戻る", page.input_value("#in-body") == "書きかけの見本" and page.input_value("#in-gh") == "4" and not page.is_visible("#draft-card"))
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(300)
        page.once("dialog", lambda d: d.accept())
        page.click("#btn-draft-drop")
        check("「捨てる」→ 端末から消える", page.evaluate("localStorage.getItem('houkoku_draft_v1')") is None and not page.is_visible("#draft-card"))
        page.evaluate("localStorage.setItem('houkoku_draft_v1', JSON.stringify({id:null,newId:'x',at:Date.now()-4*86400000,report_date:'2026-11-20',gh_num:'1',reporter:'古い 見本',body:'古い書きかけ'}))")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(300)
        check("3 日を過ぎた書きかけは出さずに消す", not page.is_visible("#draft-card") and page.evaluate("localStorage.getItem('houkoku_draft_v1')") is None)

        # 10. 印刷：保存してから刷る・紙の中身
        page.evaluate("(() => { window.__printed = 0; window.print = () => { window.__printed++; }; })()")
        fill_form(page, gh="6", reporter="見本 四郎", body="印刷の見本\n<i>斜めにならない</i>", date="2026-05-20")
        n0 = len(writes(mock))
        page.click("#btn-print")
        page.wait_for_timeout(500)
        check("印刷する → 先に保存（書き込み 1 本）してから印刷が 1 回", len(writes(mock)) == n0 + 1 and page.evaluate("window.__printed") == 1)
        check("紙の日付は様式どおりの和暦", page.evaluate("document.getElementById('p-date').textContent") == "令和8年5月20日（水）")
        check("紙のホームの欄にホームの名前", page.evaluate("document.getElementById('p-home').textContent") == "こもれびホームマハロ")
        check("紙の本文は文字のまま・改行も残る",
              page.evaluate("document.getElementById('p-body').textContent") == "印刷の見本\n<i>斜めにならない</i>" and page.locator("#p-body i").count() == 0)
        check("印鑑の枠 3 つは空", page.evaluate("[...document.querySelectorAll('#sheet tr.r2 td')].every(td => td.textContent === '')"))
        check("画面では紙は見えない", not page.is_visible("#sheet"))
        mock.fail_writes = 1
        page.fill("#in-body", "保存できない時の見本")
        page.once("dialog", lambda d: d.accept())
        page.click("#btn-print")
        page.wait_for_timeout(500)
        check("保存に失敗しても、確かめた上で印刷はできる", page.evaluate("window.__printed") == 2 and page.evaluate("document.getElementById('p-body').textContent") == "保存できない時の見本")

        # 11. 一覧が読めない時
        mock.fail_list = True
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(300)
        check("一覧を読めない時は知らせる・入力はできる", "読み込めませんでした" in page.inner_text("#list") and page.is_enabled("#in-body"))
        check("画面のエラー 0 件", not errors, " / ".join(errors[:3]))
        ctx.close()

    # 件数が多い時
    print(f"\n=== {engine} / 件数が多い時・入口・未ログイン ===")
    many = [{"id": f"bbbbbbbb-0000-4000-8000-{i:012d}", "gh_num": 1 + i % 6, "report_date": f"2026-10-{1 + i % 28:02d}",
             "reporter": "見本 太郎", "body": f"見本 {i}", "updated_at": "2026-10-01T00:00:00.000000+00:00", "deleted_at": None} for i in range(45)]
    mock = Mock(many)
    ctx, page, errors = open_page(browser, mock)
    check("一覧は 30 件まで＋「もっと前の報告書を見る」", page.locator(".item").count() == 30 and page.is_visible("#btn-more"))
    page.click("#btn-more")
    page.wait_for_timeout(350)
    check("押すと残りも出て、ボタンは消える", page.locator(".item").count() == 45 and not page.is_visible("#btn-more"))
    ctx.close()

    ctx, page, errors = open_page(browser, Mock(), path="/index.html")
    check("ホームを選ぶ画面に「ホーム報告書を書く」がある", page.is_visible("#btn-houkoku") and page.locator(".gh-btn").count() == 6)
    check("入口の画面は横にはみ出さない", no_overflow(page))
    page.click("#btn-houkoku")
    page.wait_for_load_state("networkidle")
    check("押すと報告書の画面へ", page.url.endswith("/houkoku.html") and page.is_visible("#in-body"))
    page.click(".page-header a")
    page.wait_for_load_state("networkidle")
    check("「‹」でホームを選ぶ画面へ戻る", page.url.endswith("/index.html"))
    ctx.close()

    mock = Mock()
    ctx, page, errors = open_page(browser, mock, logged_in=False)
    check("ログインしていない時はログインの画面が覆い、一覧は読みに行かない", page.locator("#auth-overlay").count() == 1 and not mock.calls)
    ctx.close()
    browser.close()


def make_pdf(pw, out):
    browser = pw.chromium.launch()
    mock = Mock([])
    ctx, page, _ = open_page(browser, mock)
    page.evaluate("(() => { window.print = () => {}; })()")
    long_body = "　本日の報告です（これは見本の文章で、中身は架空です）。\n\n" + "\n".join(
        f"{i}．見本の文章です。ここに報告の内容が入ります。長い行は紙の幅で折り返されます。" for i in range(1, 9)) + "\n\n以上、報告します。"
    fill_form(page, gh="3", reporter="見本 太郎", body=long_body, date="2026-05-20")
    page.click("#btn-print")
    page.wait_for_timeout(500)
    page.pdf(path=out, prefer_css_page_size=True, print_background=False)
    print("PDF:", out)
    browser.close()


def main():
    proc = start_server()
    try:
        with sync_playwright() as pw:
            if "--pdf" in sys.argv:
                make_pdf(pw, sys.argv[sys.argv.index("--pdf") + 1])
                return 0
            engines = [a for a in sys.argv[1:] if a in ("chromium", "webkit")] or ["chromium", "webkit"]
            for eng in engines:
                run_engine(pw, eng)
    finally:
        proc.terminate()
    ng = [r for r in results if not r[1]]
    print(f"\n{'=' * 40}\n合計 {len(results)} / NG {len(ng)}")
    for name, _, detail in ng:
        print(f"  ❌ {name}  {detail}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
