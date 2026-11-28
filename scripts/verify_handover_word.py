#!/usr/bin/env python3
"""
申し送りを足しても、日報の Word 出力・まとめ表示・保存する中身が変わらないことの検証。
同じにせデータで「申し送りを足す前の版（origin/main）」と「今の版」を開き、Word の中身（document.xml ほか全部品）を突き合わせる。

実行:
  python3 scripts/verify_handover_word.py <足す前の版のフォルダ>
"""
import hashlib
import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_resident_tabs as base  # noqa: E402
import verify_handover as ho  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OLD = Path(sys.argv[1]).resolve()
DATE = ho.DATE
results = []


def record(name, ok, detail=""):
    results.append(bool(ok)); print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def serve(folder, port):
    p = subprocess.Popen([sys.executable, "-m", "http.server", str(port)], cwd=str(folder), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.7)
    return p


def run(browser, port, with_handover):
    """日報を開き、2 人に本文を打ち、Word を出して部品ごとの中身を返す。保存で送った中身も返す。"""
    page = base.new_page(browser, viewport={"width": 390, "height": 800})
    writes = base.setup_routes(page, report_row=base.EXISTING_REPORT)
    if with_handover:
        page.route("**/rest/v1/rpc/handover_for_home", lambda r: r.fulfill(
            status=200, content_type="application/json", body=json.dumps(ho.payload(DATE))))
    page.on("dialog", lambda d: d.accept())
    page.goto(f"http://127.0.0.1:{port}/report.html?gh={base.GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_function(f"() => reportLoadedFor === '{DATE}'", timeout=8000)
    if with_handover:
        page.wait_for_selector("#handover-band:not([hidden])")
        page.wait_for_selector(".handover-box", state="attached")
    page.locator("#resident-tabs-toggle").click()            # 全員を表示
    for name, text in [("青木一郎", "夕食は完食。\n21 時に就寝。\n\n朝は 6 時に起床。"), ("佐藤花子", "既存の本文（佐藤さん）\n入浴あり。")]:
        ta = page.locator(f".resident-entry[data-name='{name}'] > textarea").first
        ta.fill(text)
    shot = page.locator("#residents-container").inner_text()
    with page.expect_download(timeout=30000) as dl:
        page.locator(".btn-word").click()
    data = Path(dl.value.path()).read_bytes()
    parts = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in sorted(z.namelist()):
            parts[n] = z.read(n)
    page.wait_for_timeout(2500)   # 自動保存を待つ
    saved = [w["body"] for w in writes if isinstance(w.get("body"), dict)]
    name = dl.value.suggested_filename
    page.close()
    return parts, saved, name, shot


def strip_time(xml: bytes) -> bytes:
    """Word の部品のうち、作った時刻だけは毎回変わるので比べる前に落とす。"""
    import re
    return re.sub(rb"<dcterms:(created|modified)[^>]*>[^<]*</dcterms:\1>", b"", xml)


def main():
    old_srv, new_srv = serve(OLD, 8801), serve(ROOT, 8802)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            old_parts, old_saved, old_name, _ = run(browser, 8801, False)
            new_parts, new_saved, new_name, shot = run(browser, 8802, True)
            none_parts, _, _, _ = run(browser, 8802, False)
            browser.close()
        record("（準備）今の版では申し送りの箱が画面に出ている", "今日の申し送り" in shot and "固定申し送り" in shot)
        record("Word のファイル名が同じ", old_name == new_name, f"{old_name} / {new_name}")
        record("Word の部品の一覧が同じ", list(old_parts) == list(new_parts), str(list(new_parts)))
        doc_old, doc_new = old_parts["word/document.xml"], new_parts["word/document.xml"]
        record("Word の本文（document.xml）が 1 バイトも変わらない", doc_old == doc_new,
               f"{hashlib.sha256(doc_old).hexdigest()[:12]} / {hashlib.sha256(doc_new).hexdigest()[:12]}・{len(doc_old)} バイト")
        diff = [n for n in old_parts if strip_time(old_parts[n]) != strip_time(new_parts.get(n, b""))]
        record("ほかの部品（書式・設定など）も同じ（作った時刻を除く）", not diff, str(diff))
        text = doc_new.decode("utf-8")
        record("Word に本文が入っている（空の比較になっていない）", "夕食は完食。" in text and "入浴あり。" in text and "青木一郎さん" in text)
        record("Word に申し送りの文・注意文が混ざらない",
               not any(s in text for s in ["申し送り", "爪切り", "朝食後の薬", "処方の内容", "前回の文", "届いた"]))
        record("申し送りが 1 件も無い日も同じ Word", none_parts["word/document.xml"] == doc_old)
        strip = lambda bodies: [{k: v for k, v in (b.get("p_patch") or {}).items()} for b in bodies]  # noqa: E731
        record("保存で送る中身が同じ（申し送りの文が日報に混ざらない）", strip(old_saved) == strip(new_saved) and len(new_saved) > 0,
               json.dumps(strip(new_saved), ensure_ascii=False)[:200])
    finally:
        old_srv.terminate(); new_srv.terminate()
    print(f"\n{sum(results)}/{len(results)} 通過")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
