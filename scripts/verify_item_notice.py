#!/usr/bin/env python3
"""report.html の「個人の希望品」に出す決め打ちの注意書き（対象の方＝綿棒禁止）の検証。
本番 Supabase・本番 URL は使わない（verify_personal_items.py のモック基盤を流用）。

実行:
  python3 scripts/verify_item_notice.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402

import verify_personal_items as pi  # noqa: E402

GH = 1  # 見本のホーム（実際の所属とは無関係。公開される置き場なので実際のホームを書かない）
DATE = "2026-11-20"
OUT = Path(__file__).resolve().parent

FAKE_SESSION = {
    "access_token": "fake-token", "token_type": "bearer", "expires_in": 3600,
    "expires_at": int(time.time()) + 3600, "refresh_token": "fake-refresh",
    "user": {"id": "11111111-1111-1111-1111-111111111111", "email": "staff@example.com"},
}

RESIDENTS = [
    {"id": 14, "name": "見本　一郎", "gh_num": GH, "active": True, "sort_order": 1},
    {"id": 15, "name": "架空　花子", "gh_num": GH, "active": True, "sort_order": 2},
    {"id": 16, "name": "架空　太郎", "gh_num": GH, "active": True, "sort_order": 3},
]
ITEMS = [
    {"id": 1, "gh_num": GH, "resident_id": 15, "resident_name": "架空　花子",
     "item_text": "ハンドクリーム", "requested_on": "2026-11-18", "purchased_at": None},
]


def open_page(browser, width, drop_script=False):
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.add_init_script(
        "window.localStorage.setItem('sb-vqeoutrlvdydxenaspas-auth-token', "
        + json.dumps(json.dumps(FAKE_SESSION)) + ");"
    )
    pi.RESIDENTS = RESIDENTS
    pi.setup_routes(page, items_rows=ITEMS)
    page.route("**/auth/v1/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(FAKE_SESSION)))
    if drop_script:
        page.route("**/scripts/item_notice.js*", lambda r: r.abort("failed"))
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{pi.BASE}/report.html?gh={GH}&date={DATE}", wait_until="domcontentloaded")
    page.wait_for_selector(".personal-items-block", timeout=8000)
    page.wait_for_function(
        "() => !document.querySelector('.personal-items-block .btn-add-personal-item').disabled",
        timeout=8000)
    return page, errors


def notices(page):
    return page.evaluate("""() => [...document.querySelectorAll('.personal-items-block')].map(b => ({
      name: b.dataset.residentName,
      notice: (b.querySelector('.personal-items-notice') || {}).textContent || '',
      label: b.querySelector('.personal-items-label').textContent,
    }))""")


def main():
    proc = pi.start_server()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (375, 768, 1280):
                page, errors = open_page(browser, width)
                got = {n["name"]: n for n in notices(page)}
                pi.record(f"幅{width}: 対象の方の欄に「※綿棒禁止」", got["架空　花子"]["notice"] == "※綿棒禁止", str(got["架空　花子"]))
                pi.record(f"幅{width}: 他の方（同じ名字の方も）には出ない",
                          got["見本　一郎"]["notice"] == "" and got["架空　太郎"]["notice"] == "")
                box = page.locator(".personal-items-notice").bounding_box()
                vw = page.evaluate("document.documentElement.clientWidth")
                sw = page.evaluate("document.documentElement.scrollWidth")
                # 幅375 では元から別の欄（LABEL/SPAN）が 10px はみ出す（この変更の前後で同じ 385・2026-11-20 実測）。
                # ここでは「注意書きそのものが画面内に収まるか」と「注意書きの有無で横幅が変わらないか」を見る。
                page.evaluate("document.querySelectorAll('.personal-items-notice').forEach(e => e.style.display = 'none')")
                sw_without = page.evaluate("document.documentElement.scrollWidth")
                page.evaluate("document.querySelectorAll('.personal-items-notice').forEach(e => e.style.display = '')")
                pi.record(f"幅{width}: 表示が画面内・表示の有無で横幅が変わらない",
                          box is not None and box["x"] + box["width"] <= vw and sw == sw_without,
                          f"box={box} vw={vw} sw={sw} sw_without={sw_without}")
                color = page.evaluate("""() => { const s = getComputedStyle(document.querySelector('.personal-items-notice'));
                    return [s.color, s.backgroundColor, s.fontSize, s.fontWeight]; }""")
                pi.record(f"幅{width}: 色と大きさ（実測）", color == ["rgb(163, 35, 28)", "rgb(253, 236, 234)", "13px", "700"], str(color))
                pi.record(f"幅{width}: 画面のエラー 0", errors == [], str(errors))
                page.locator(".personal-items-notice").scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / f"_item_notice_report_{width}.png"))
                # 追加は従来どおり動く（表示を足しただけで入力を止めていない）
                if width == 375:
                    blk = page.locator(".personal-items-block[data-resident-id='15']")
                    blk.locator(".personal-item-input").fill("靴下")
                    blk.locator(".btn-add-personal-item").click()
                    page.wait_for_function(
                        "() => document.querySelector(\".personal-items-block[data-resident-id='15'] .personal-items-list\").textContent.includes('靴下')",
                        timeout=5000)
                    pi.record("対象の方の欄で希望品の追加は従来どおりできる", True)
                page.close()
            # 部品が読めなくても欄は出る（注意書きだけ出ない・画面は壊れない）
            page, errors = open_page(browser, 375, drop_script=True)
            got = notices(page)
            pi.record("部品が読めない時も希望品の欄は 3 人分出る", len(got) == 3 and all(n["notice"] == "" for n in got), str(got))
            pi.record("部品が読めない時も画面のエラー 0", errors == [], str(errors))
            browser.close()
    finally:
        proc.terminate()
    failed = [r for r in pi.results if not r[1]]
    print(f"\n合計 {len(pi.results)} 項目 / 失敗 {len(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
