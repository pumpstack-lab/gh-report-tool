#!/usr/bin/env python3
"""
houkoku.html（ホーム報告書）の意地悪な使い方の検証（本番Supabase・本番URL不使用・名前と本文は全部架空）。
verify_home_report.py のまね（DB・写真の置き場）を使う。ふつうの流れは verify_home_report.py、こちらは壊れやすい場面だけ。

実行:
  cd "gh-report-tool" && python3 scripts/verify_home_report_edge.py            # chromium + webkit
"""
import io
import json
import sys
import time

from playwright.sync_api import sync_playwright

import verify_home_report as V
from verify_home_report import Mock, check, fill_form, open_page, status, writes, results

SLOW_UPLOAD = """
(() => {
  const orig = window.fetch;
  window.__slow = 0;
  window.fetch = async (...a) => {
    const url = String(a[0] && a[0].url || a[0]);
    if (window.__slow && url.includes('/storage/v1/object/home-report-photos/')) await new Promise(r => setTimeout(r, window.__slow));
    if (window.__slowRest && url.includes('/rest/v1/home_reports') && (a[1] && a[1].method && a[1].method !== 'GET')) await new Promise(r => setTimeout(r, window.__slowRest));
    return orig(...a);
  };
})();
"""


def exif_jpeg(w, h, orientation):
    """向きの印（EXIF）つきの JPEG。画素は w×h のまま、表示の時に回す指定だけ持つ（スマホの縦撮りと同じ形）。"""
    from PIL import Image
    im = Image.new("RGB", (w, h), (60, 140, 90))
    for x in range(w // 2):                      # 左半分を別の色に（回った向きを見分ける）
        for y in range(0, h, 7):
            im.putpixel((x, y), (230, 230, 60))
    exif = Image.Exif(); exif[0x0112] = orientation
    buf = io.BytesIO(); im.save(buf, "JPEG", exif=exif.tobytes(), quality=85)
    return {"name": "tate.jpg", "mimeType": "image/jpeg", "buffer": buf.getvalue()}


def img_dims(page, sel=".ph img"):
    return page.evaluate(f"(() => {{ const i = document.querySelector('{sel}'); return [i.naturalWidth, i.naturalHeight]; }})()")


def stub_print(page):
    page.evaluate("(() => { window.__printed = 0; window.print = () => { window.__printed++; }; })()")


def run(pw, engine):
    browser = getattr(pw, engine).launch()
    print(f"\n=== {engine} ===")

    # 1. 縦に撮った写真（向きの印つき）
    mock = Mock()
    ctx, page, errors = open_page(browser, mock)
    fill_form(page, gh="1", reporter="見本 太郎", body="向きの見本")
    page.set_input_files("#in-photo", exif_jpeg(1200, 800, 6))       # 画素は横長・表示は縦長
    page.wait_for_timeout(900)
    w, h = img_dims(page)
    check("縦に撮った写真（向きの印つき）が、縦のまま入る", page.locator(".ph").count() == 1 and w == 800 and h == 1200, f"{w}x{h}")
    key = mock.uploads[-1] if mock.uploads else ""
    if mock.files.get(key):
        fmt, size = V.jpeg_size(mock.files[key])
        from PIL import Image
        ex = Image.open(io.BytesIO(mock.files[key])).getexif()
        check("送る写真そのものが縦になっていて、向きの印や付属情報は付いていない", size == (800, 1200) and len(ex) == 0, f"{size} 付属情報 {len(ex)} 件")

    # 2. とても大きい写真
    t = time.perf_counter()
    page.set_input_files("#in-photo", V.photo_file("big.png", 6000, 4500))
    page.wait_for_function("document.querySelectorAll('.ph').length === 2", timeout=30000)
    dt = time.perf_counter() - t
    w, h = img_dims(page, ".ph:nth-child(2) img")
    check("とても大きい写真（6000×4500）も縮めて入る・固まらない", w == 1600 and h == 1200 and dt < 15, f"{w}x{h}・{dt:.1f} 秒")
    key = mock.uploads[-1]
    if mock.files.get(key):
        check("縮めた写真は置き場の上限（3MB）よりずっと小さい", len(mock.files[key]) < 1_000_000, f"{len(mock.files[key]) // 1024}KB")
    ctx.close()

    # 3. 送っている最中の操作
    mock = Mock()
    ctx, page, errors2 = open_page(browser, mock); errors += errors2
    page.add_init_script(SLOW_UPLOAD)
    page.reload(wait_until="networkidle"); page.wait_for_timeout(300)
    fill_form(page, gh="2", reporter="見本 次郎", body="送っている最中の見本")
    page.evaluate("window.__slow = 1500")
    page.set_input_files("#in-photo", V.photo_file("s.png", 400, 300))
    page.wait_for_timeout(300)
    check("写真を送っている間は、保存・印刷・写真を選ぶ が押せない",
          page.is_disabled("#btn-save") and page.is_disabled("#btn-print") and page.is_disabled("#btn-photo"))
    page.locator(".item").first.click(force=True)
    page.wait_for_timeout(150)
    check("送っている間に一覧の行を押しても、開いている内容は切り替わらない", page.input_value("#in-body") == "送っている最中の見本")
    check("送っている間は「書きかけを捨てる」も押せない（送り終えた写真が別の報告書に付かない）", page.is_disabled("#btn-discard"))
    page.evaluate("document.getElementById('btn-discard').click(); document.getElementById('btn-save').click()")
    page.wait_for_timeout(1900)
    check("送り終わると写真が 1 枚入り、押せるようになる・途中の保存は走っていない",
          page.locator(".ph").count() == 1 and page.is_enabled("#btn-save") and not writes(mock))
    page.evaluate("window.__slow = 0")

    # 4. 保存している最中の操作
    page.evaluate("window.__slowRest = 1200")
    page.click("#btn-save")
    page.wait_for_timeout(200)
    page.evaluate("document.getElementById('btn-save').click(); document.getElementById('btn-print').click();")
    check("保存している間は、写真を外すボタンも押せない", page.is_disabled(".ph button") and page.is_disabled("#btn-photo"))
    page.wait_for_timeout(1700)
    check("保存中に保存と印刷を重ねて押しても、書き込みは 1 本だけ", len(writes(mock)) == 1 and status(page) == "保存しました", f"{len(writes(mock))} 本")
    page.evaluate("window.__slowRest = 0")
    page.wait_for_timeout(1600)
    stub_print(page)
    page.evaluate("document.getElementById('btn-print').click(); document.getElementById('btn-print').click();")
    page.wait_for_timeout(500)
    check("印刷を 2 回続けて押しても、印刷は 1 回", page.evaluate("window.__printed") == 1, str(page.evaluate("window.__printed")))
    ctx.close()

    # 5. 通信が切れた時・ログインが切れた時
    mock = Mock()
    ctx, page, errors2 = open_page(browser, mock); errors += errors2
    fill_form(page, gh="3", reporter="見本 三郎", body="通信が切れた時の見本")
    page.route("**/rest/v1/home_reports**", lambda r: r.abort() if r.request.method != "GET" else r.fallback())
    page.click("#btn-save"); page.wait_for_timeout(500)
    check("通信が切れている時の保存 → 知らせる・内容はそのまま・端末に残る",
          "保存できませんでした" in status(page) and page.input_value("#in-body") == "通信が切れた時の見本"
          and "通信が切れた時の見本" in (page.evaluate("localStorage.getItem('houkoku_draft_v1')") or ""))
    page.unroute("**/rest/v1/home_reports**"); page.route("**/rest/v1/home_reports**", mock.handle)
    page.route("**/rest/v1/home_reports**", lambda r: r.fulfill(status=401, content_type="application/json", body=json.dumps({"code": "PGRST301", "message": "JWT expired"})) if r.request.method != "GET" else r.fallback())
    page.click("#btn-save"); page.wait_for_timeout(500)
    check("ログインが切れている時の保存 → 知らせる・内容はそのまま", "保存できませんでした" in status(page) and page.input_value("#in-body") == "通信が切れた時の見本")
    page.unroute("**/rest/v1/home_reports**"); page.route("**/rest/v1/home_reports**", mock.handle)
    page.click("#btn-save"); page.wait_for_timeout(500)
    check("通信が戻ってからもう一度押すと保存でき、2 枚にならない", status(page) == "保存しました" and sum(1 for r in mock.rows if r["body"] == "通信が切れた時の見本") == 1)
    page.route("**/storage/v1/object/home-report-photos/**", lambda r: r.abort())
    page.set_input_files("#in-photo", V.photo_file("x.png", 300, 300)); page.wait_for_timeout(600)
    check("通信が切れている時の写真 → 入れずに知らせる・画面は使える", page.locator(".ph").count() == 0 and "送れませんでした" in status(page) and page.is_enabled("#btn-save"))
    ctx.close()

    # 6. 2 つの画面で同じ報告書を開いて直す
    mock = Mock()
    ctx, a, errors2 = open_page(browser, mock); errors += errors2
    b = ctx.new_page()
    b.route("**/auth/v1/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(V.FAKE_SESSION)))
    b.route("**/rest/v1/home_reports**", mock.handle); b.route("**/storage/v1/**", mock.storage)
    b.goto(V.BASE + "/houkoku.html", wait_until="networkidle"); b.wait_for_timeout(300)
    a.locator('.item[data-id$="0001"]').click(); b.locator('.item[data-id$="0001"]').click()
    a.fill("#in-body", "画面 A が先に直した"); a.click("#btn-save"); a.wait_for_timeout(450)
    b.fill("#in-body", "画面 B が後から直した"); b.click("#btn-save"); b.wait_for_timeout(450)
    row = next(r for r in mock.rows if r["id"].endswith("0001"))
    check("2 つの画面で同じ報告書を直す → 後から保存した方は上書きせず知らせる", row["body"] == "画面 A が先に直した" and "ほかの端末" in status(b))
    check("後から直した方の文章は、画面と端末に残っている", b.input_value("#in-body") == "画面 B が後から直した")
    a.once("dialog", lambda d: d.accept()); a.click("#btn-delete"); a.wait_for_timeout(450)
    b.click("#btn-save"); b.wait_for_timeout(450)
    check("片方で消された報告書を、もう片方で保存 → 生き返らせず知らせる", row["deleted_at"] and row["body"] == "画面 A が先に直した" and "ほかの端末" in status(b))
    ctx.close()

    # 7. 文字の境目・変わった文字
    mock = Mock()
    ctx, page, errors2 = open_page(browser, mock); errors += errors2
    evil = '<img src=x onerror="window.__xss=1"> \'"; DROP TABLE home_reports;-- 𠮷野家 👨‍👩‍👧 ‮反転'
    fill_form(page, gh="4", body=evil)
    page.click("#btn-save"); page.wait_for_timeout(450)
    sent = writes(mock)[-1]["body"]
    check("記号・絵文字・タグのような文字も、そのまま保存され、画面では文字として出る",
          sent["body"] == evil and page.evaluate("window.__xss") is None and page.locator(".item img, .item b").count() == 0
          and evil[:20] in page.locator(".item .x").first.inner_text())
    stub_print(page); page.click("#btn-print"); page.wait_for_timeout(300)
    check("紙にも文字として出る", page.evaluate("document.getElementById('p-body').textContent") == evil and page.locator("#sheet img").count() == 0)
    page.click("#btn-new")
    fill_form(page, gh="4", reporter="見本", body="あ" * 8000)
    page.click("#btn-save"); page.wait_for_timeout(450)
    check("本文ちょうど 8000 字は保存できる", status(page) == "保存しました" and "8000 / 8000" in page.inner_text("#count"))
    page.fill("#in-body", "あ" * 8001)
    n = len(writes(mock)); page.click("#btn-save"); page.wait_for_timeout(300)
    check("8001 字は保存せず、何字かを知らせる・数字が赤くなる", len(writes(mock)) == n and "8000 文字まで" in status(page) and "over" in page.get_attribute("#count", "class"))
    page.fill("#in-body", "😀" * 4000)
    page.click("#btn-save"); page.wait_for_timeout(450)
    check("絵文字 4000 個（画面の数え方で 8000）は保存できる＝DB の数え方（4000）より厳しい側", status(page) == "保存しました")
    page.fill("#in-date", "")
    n = len(writes(mock)); page.click("#btn-save"); page.wait_for_timeout(300)
    check("日付を空にすると保存せず知らせる", len(writes(mock)) == n and "日付を入れてください" in status(page))

    # 8. キーボードだけで使える（事務所のパソコン）
    page.fill("#in-date", "2026-11-27")
    page.focus("#in-date"); page.keyboard.press("Enter"); page.wait_for_timeout(200)
    check("日付の欄で Enter を押しても、画面が飛んだり消えたりしない", page.url.endswith("/houkoku.html") and page.input_value("#in-body") == "😀" * 4000)
    order = []
    page.focus("#in-date")
    for _ in range(40):
        page.keyboard.press("Tab")
        i = page.evaluate("document.activeElement && (document.activeElement.id || document.activeElement.className)")
        order.append(i)
        if i == "btn-print":
            break
    need = ["in-gh", "in-body", "btn-photo", "in-size", "btn-save", "btn-print"]
    pos = [order.index(x) if x in order else -1 for x in need]
    if engine == "chromium":      # Safari 系は Tab でボタンを飛ばすのが既定（OS の設定）。事務所のパソコン（Windows の Edge／Chrome）と同じ系統で見る
        check("Tab キーで 日付→ホーム→本文→写真→文字の大きさ→保存→印刷 の順に進める", -1 not in pos and pos == sorted(pos), " ".join(str(o) for o in order[:12]))
    check("押す所には全部、読み上げ用の名前がある",
          page.evaluate("[...document.querySelectorAll('button, select, input, textarea')].filter(e => !e.hidden && e.offsetParent).every(e => (e.labels && e.labels.length) || e.getAttribute('aria-label') || e.textContent.trim())"))
    check("画面のエラー 0 件", not errors, " / ".join(errors[:3]))
    ctx.close()
    browser.close()


def main():
    proc = V.start_server()
    try:
        with sync_playwright() as pw:
            for eng in [a for a in sys.argv[1:] if a in ("chromium", "webkit")] or ["chromium", "webkit"]:
                run(pw, eng)
    finally:
        proc.terminate()
    ng = [r for r in results if not r[1]]
    print(f"\n{'=' * 40}\n合計 {len(results)} / NG {len(ng)}")
    for name, _, detail in ng:
        print(f"  ❌ {name}  {detail}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
