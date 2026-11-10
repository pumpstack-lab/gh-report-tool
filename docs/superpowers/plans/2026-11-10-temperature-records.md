# 業務日報 検温欄（夕・朝）実装計画 — 現場側（gh-report-tool）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 日報の利用者枠・短期入所①②に「検温 夕／朝」の数字欄を足し、別表 `temperature_records` に保存する（37.5 以上は赤）。

**Architecture:** 排便記録（bowel）・見回り（patrol）と同じ型。純粋関数は `scripts/temperature_logic.js`（UMD・node テスト）、画面の配線は `report.html` に追加、保存は supabase-js で upsert／delete。読み込みは `loadDateData`／`init` の排便の直後で待ち、`tempLoadedForDate` が一致する間だけ欄が有効。

**Tech Stack:** 素の JS（UMD）、node:test、supabase-js v2、Playwright（本番非接続・`scripts/verify_report_guard.py` のモック基盤）。

**設計書:** `docs/superpowers/specs/2026-11-10-temperature-records-design.md`

---

### Task 1: migration

**Files:**
- Create: `migrations/2026-11-10_temperature_records.sql`

- [ ] **Step 1: 書く**

```sql
-- ~/Desktop/01 開発/gh-report-tool/migrations/2026-11-10_temperature_records.sql
-- 検温（夕・朝）。設計: docs/superpowers/specs/2026-11-10-temperature-records-design.md §2
-- reports.residents には入れない（差分保存の CAS と競合するため・bowel_records と同じ理由）。
-- report_date は「朝の日付」（管理画面の見出し 10/4 夜 → 10/5 朝 と同じ）。evening は前夜の値。
-- 短期入所①②は resident_id が無いので short_stay_key で持つ。
-- 非破壊・冪等。⚠️ 本番適用は Getter 本体が行う。

create table if not exists temperature_records (
  id             bigserial primary key,
  gh_num         integer not null,
  report_date    date not null,
  resident_id    bigint references residents(id),
  short_stay_key text,                                  -- '__short_stay_1__' / '__short_stay_2__'
  resident_name  text not null,                         -- 表示用スナップショット
  slot           text not null check (slot in ('evening','morning')),
  temp_c         numeric(3,1) not null check (temp_c between 35.0 and 42.0),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint temperature_records_subject check ((resident_id is not null) <> (short_stay_key is not null))
);
create unique index if not exists temperature_records_resident_uniq
  on temperature_records (gh_num, report_date, resident_id, slot) where resident_id is not null;
create unique index if not exists temperature_records_short_stay_uniq
  on temperature_records (gh_num, report_date, short_stay_key, slot) where short_stay_key is not null;
create index if not exists temperature_records_date_idx on temperature_records (report_date, gh_num);
alter table temperature_records enable row level security;
drop policy if exists authenticated_all on temperature_records;
create policy authenticated_all on temperature_records for all to authenticated using (true) with check (true);

-- ─── 適用後の確認（Getter 本体・本番） ───
--   \d temperature_records ／ select polname from pg_policies where tablename='temperature_records';
--   もう一度流してエラーにならないこと（冪等）
```

- [ ] **Step 2: コミット** `git add migrations && git commit -m "feat(temp): temperature_records の migration"`

### Task 2: 純粋関数 `scripts/temperature_logic.js`（TDD）

**Files:**
- Create: `scripts/temperature_logic.js`, `scripts/temperature_logic.test.js`

- [ ] **Step 1: 失敗するテスト**

```js
const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeTemp, isFever, TEMP_MIN, TEMP_MAX } = require('./temperature_logic.js');

test('normalizeTemp: 36.5 → 36.5', () => assert.deepEqual(normalizeTemp('36.5'), { value: 36.5 }));
test('normalizeTemp: 全角・空白混じり "３７．２ " → 37.2', () => assert.deepEqual(normalizeTemp('３７．２ '), { value: 37.2 }));
test('normalizeTemp: 整数 37 → 37.0', () => assert.deepEqual(normalizeTemp('37'), { value: 37 }));
test('normalizeTemp: 空 → null（消す）', () => assert.deepEqual(normalizeTemp('  '), { value: null }));
test('normalizeTemp: 小数2桁は受けない', () => assert.equal(normalizeTemp('36.55').error, '35.0〜42.0 で入れてください（小数1桁）'));
test('normalizeTemp: 範囲外 34.9 / 42.1', () => {
  assert.ok(normalizeTemp('34.9').error); assert.ok(normalizeTemp('42.1').error);
  assert.deepEqual(normalizeTemp('35.0'), { value: 35 }); assert.deepEqual(normalizeTemp('42.0'), { value: 42 });
});
test('normalizeTemp: 数字でない', () => assert.ok(normalizeTemp('abc').error));
test('isFever: 37.4 は平熱・37.5 から赤', () => { assert.equal(isFever(37.4), false); assert.equal(isFever(37.5), true); assert.equal(isFever(null), false); });
test('定数', () => { assert.equal(TEMP_MIN, 35.0); assert.equal(TEMP_MAX, 42.0); });
```

- [ ] **Step 2: 実行して失敗を確認** `node --test scripts/temperature_logic.test.js` → MODULE_NOT_FOUND
- [ ] **Step 3: 実装**

```js
// 検温の判定（純粋関数）。report.html と node の両方から読む UMD。
(function (root, factory) {
  const mod = factory();
  if (typeof module === 'object' && module.exports) module.exports = mod;
  if (typeof root !== 'undefined') root.TemperatureLogic = mod;
})(typeof window !== 'undefined' ? window : this, function () {
  const TEMP_MIN = 35.0, TEMP_MAX = 42.0, FEVER_FROM = 37.5;
  const RANGE_ERROR = '35.0〜42.0 で入れてください（小数1桁）';
  function toHalfWidth(s) {
    return String(s).replace(/[０-９．]/g, ch => ch === '．' ? '.' : String.fromCharCode(ch.charCodeAt(0) - 0xFEE0));
  }
  /** 入力文字列 → {value: number|null} か {error: string}。空は null（記録を消す）。 */
  function normalizeTemp(text) {
    const t = toHalfWidth(text == null ? '' : text).trim();
    if (t === '') return { value: null };
    if (!/^\d{2}(\.\d)?$/.test(t)) return { error: RANGE_ERROR };
    const v = Number(t);
    if (v < TEMP_MIN || v > TEMP_MAX) return { error: RANGE_ERROR };
    return { value: v };
  }
  function isFever(v) { return typeof v === 'number' && v >= FEVER_FROM; }
  function formatTemp(v) { return typeof v === 'number' ? v.toFixed(1) : ''; }
  return { normalizeTemp, isFever, formatTemp, TEMP_MIN, TEMP_MAX, FEVER_FROM, RANGE_ERROR };
});
```

- [ ] **Step 4: 通過を確認** `node --test scripts/*.test.js` → 全通過
- [ ] **Step 5: コミット** `git add scripts/temperature_logic.js scripts/temperature_logic.test.js && git commit -m "feat(temp): 検温の判定（範囲・37.5 の赤）"`

### Task 3: report.html の配線

**Files:**
- Modify: `report.html`

- [ ] **Step 1: 読み込み** `<script src="scripts/report_guard.js?v=2"></script>` の直後に `<script src="scripts/temperature_logic.js?v=1"></script>`
- [ ] **Step 2: CSS**（`.bowel-block` の定義の近く）

```css
.temp-row { display:flex; align-items:center; gap:8px; margin-top:10px; font-size:13px; flex-wrap:wrap; }
.temp-label { font-weight:bold; color:#c2570c; }
.temp-field { display:flex; align-items:center; gap:4px; }
.temp-input { width:5.5em; padding:8px 6px; font-size:16px; border:1px solid #d9c7b8; border-radius:8px; text-align:center; background:#fff; }
.temp-input:disabled { background:#f3efeb; color:#999; }
.temp-input.is-fever { border-color:#c0392b; color:#c0392b; font-weight:bold; background:#fdecea; }
.temp-error { flex-basis:100%; font-size:12px; color:#c0392b; }
.temp-unavailable { flex-basis:100%; font-size:12px; color:#c0392b; }
```

- [ ] **Step 3: 状態と読み込み**（`let bowelLoadedForDate` の近く）

```js
    // ─── 検温（夕・朝）。設計: docs/superpowers/specs/2026-11-10-temperature-records-design.md ───
    let tempLoadedForDate = null;        // 読み込みが完了している日付（未完了/失敗なら null）
    let tempRecords = {};                // key: `${subject}|${slot}` → {id, temp_c}。subject は resident_id か short_stay_key
    function tempKey(subject, slot) { return `${subject}|${slot}`; }
    async function loadTemperatureRecords(dateISO) {
      tempLoadedForDate = null; tempRecords = {};
      const { data, error } = await db.from('temperature_records')
        .select('id, resident_id, short_stay_key, slot, temp_c')
        .eq('gh_num', parseInt(ghNum)).eq('report_date', dateISO);
      if (error) { console.error('temperature_records load failed:', error.message); return; } // 表が無い本番でも日報は止めない
      (data || []).forEach(r => { tempRecords[tempKey(r.resident_id != null ? String(r.resident_id) : r.short_stay_key, r.slot)] = { id: r.id, temp_c: Number(r.temp_c) }; });
      tempLoadedForDate = dateISO;
    }
```

- [ ] **Step 4: 描画と保存**

```js
    /** subject: 利用者は String(resident_id)、短期入所は '__short_stay_N__'。nameFn: 保存時の表示名を返す関数 */
    function renderTemperatureRow(container, subject, nameFn) {
      const row = document.createElement('div');
      row.className = 'temp-row'; row.dataset.subject = subject;
      row.innerHTML = `
        <span class="temp-label">検温</span>
        <label class="temp-field">夕 <input type="number" class="temp-input" data-slot="evening" step="0.1" min="35" max="42" inputmode="decimal" placeholder="36.5" disabled></label>
        <span>／</span>
        <label class="temp-field">朝 <input type="number" class="temp-input" data-slot="morning" step="0.1" min="35" max="42" inputmode="decimal" placeholder="36.5" disabled></label>
        <div class="temp-error" style="display:none"></div>
        <div class="temp-unavailable" style="display:none">検温を読み込めませんでした。再読み込みしてください</div>`;
      row.querySelectorAll('.temp-input').forEach(inp => {
        inp.addEventListener('change', () => persistTemperature(row, subject, nameFn, inp));
        inp.addEventListener('input', () => { const n = TemperatureLogic.normalizeTemp(inp.value); inp.classList.toggle('is-fever', !n.error && TemperatureLogic.isFever(n.value)); });
      });
      container.appendChild(row);
      refreshTemperatureRow(row);
      return row;
    }
    function refreshTemperatureRow(row) {
      const subject = row.dataset.subject;
      row.querySelectorAll('.temp-input').forEach(inp => {
        const rec = tempRecords[tempKey(subject, inp.dataset.slot)];
        inp.value = rec ? TemperatureLogic.formatTemp(rec.temp_c) : '';
        inp.classList.toggle('is-fever', !!rec && TemperatureLogic.isFever(rec.temp_c));
        inp.disabled = tempLoadedForDate !== dateEl.value;
      });
      row.querySelector('.temp-unavailable').style.display = tempLoadedForDate ? 'none' : '';
    }
    function refreshAllTemperatureRows() { document.querySelectorAll('.temp-row').forEach(refreshTemperatureRow); }
    async function persistTemperature(row, subject, nameFn, inp) {
      const errEl = row.querySelector('.temp-error');
      errEl.style.display = 'none';
      if (tempLoadedForDate !== dateEl.value) { refreshTemperatureRow(row); return; } // 日付切替の隙間で別日付に書かない
      const n = TemperatureLogic.normalizeTemp(inp.value);
      if (n.error) { errEl.textContent = n.error; errEl.style.display = ''; return; } // 保存しない・値は欄に残す
      const slot = inp.dataset.slot, key = tempKey(subject, slot), prev = tempRecords[key];
      if ((prev ? prev.temp_c : null) === n.value) { refreshTemperatureRow(row); return; }
      const isShortStay = subject.startsWith('__short_stay_');
      if (n.value === null) {
        if (!prev) return;
        const { error } = await db.from('temperature_records').delete().eq('id', prev.id);
        if (error) { errEl.textContent = '保存できませんでした。通信を確認してもう一度お試しください'; errEl.style.display = ''; refreshTemperatureRow(row); return; }
        delete tempRecords[key]; refreshTemperatureRow(row); return;
      }
      const payload = { gh_num: parseInt(ghNum), report_date: dateEl.value, slot, temp_c: n.value, resident_name: nameFn(), updated_at: new Date().toISOString(),
        resident_id: isShortStay ? null : parseInt(subject, 10), short_stay_key: isShortStay ? subject : null };
      const { data, error } = await db.from('temperature_records')
        .upsert(payload, { onConflict: isShortStay ? 'gh_num,report_date,short_stay_key,slot' : 'gh_num,report_date,resident_id,slot' })
        .select('id, temp_c').single();
      if (error) { errEl.textContent = '保存できませんでした。通信を確認してもう一度お試しください'; errEl.style.display = ''; refreshTemperatureRow(row); return; }
      tempRecords[key] = { id: data.id, temp_c: Number(data.temp_c) };
      refreshTemperatureRow(row);
    }
```

  ⚠️ 部分一意インデックス（where 付き）への `onConflict` は PostgREST が受けない場合がある。その時は upsert をやめ、`prev` があれば `update().eq('id', prev.id)`、無ければ `insert()` にする（二重 insert は一意インデックスで弾かれるので再読み込みして上書き）。Playwright のモックでは upsert/insert/update いずれも POST/PATCH で記録できるようにしておく。

- [ ] **Step 5: 利用者枠と短期入所枠に差し込む**
  - 利用者：`const bowelBlock = renderBowelSection(div, r.id, r.name);` の**直前**に `renderTemperatureRow(div, String(r.id), () => r.name);`
  - 短期入所：Task の `entry.innerHTML = ...` の後に `renderTemperatureRow(entry, entry.dataset.shortStayKey, () => entry.querySelector('.short-stay-name-input').value.trim() || `短期入所${['①','②'][n-1]}`);`
- [ ] **Step 6: 読み込みの位置** `loadDateData` と `init` の `await loadBowelRecords(dateISO);` の直後に `await loadTemperatureRecords(dateISO);`（連番チェック `if (!reportLoadSeq.isCurrent(loadSeq)) return;` は loadDateData 側のみ、既存と同じ位置に）。`rerenderPatrolBlocks();` の直後に `refreshAllTemperatureRows();`
- [ ] **Step 7: 無効化** `setFormInputsDisabled` の selector に `'.temp-input, '` を追加し、`.temp-input` は `el.disabled = isDisabled || tempLoadedForDate !== dateEl.value;`（patrol-checkbox と同じ書き方）
- [ ] **Step 8: 手で開いて確認** `python3 -m http.server 8791` → 既存の verify_report_guard のモックで欄が出ること
- [ ] **Step 9: コミット** `git commit -am "feat(temp): 日報に検温 夕／朝 の欄（利用者・短期入所①②・37.5 以上は赤・別表に保存）"`

### Task 4: Playwright 検証 `scripts/verify_temperature_records.py`

**Files:**
- Create: `scripts/verify_temperature_records.py`（`verify_date_switch_seq.py` の `new_page`／偽セッション・`verify_report_guard.py` の `start_server`／`record` を流用）

- [ ] **Step 1: ケースを書く**（モック：`**/rest/v1/temperature_records` GET→固定行、POST/PATCH/DELETE→本文を配列に記録し `[{"id":901,"temp_c":...}]` を返す）
  1. 読み込み後、利用者 1 人目の夕に `36.5` → change → 書き込み 1 本・body に `slot:'evening'`,`temp_c:36.5`,`resident_id:101`,`report_date:DATE`
  2. 同じ欄に `36.5` を再入力 → 書き込み 0 本（同値は書かない）
  3. `37.5` → `.is-fever` が付く・`getComputedStyle(color)` が `rgb(192, 57, 43)`。`37.4` → 付かない
  4. `36.55` → 書き込み 0 本・`.temp-error` が表示・文言一致
  5. 空にする（既存行あり）→ DELETE 1 本・欄が空
  6. 短期入所①に名前「検証太郎」＋朝 `36.8` → body に `short_stay_key:'__short_stay_1__'`,`resident_id:null`,`resident_name:'検証太郎'`
  7. 日付切替で reports GET を 3000ms 遅らせ、ロード中は `.temp-input` が disabled・直接 `dispatchEvent(change)` しても書き込み 0 本
  8. temperature_records GET を 500 で返す → 欄 disabled・`.temp-unavailable` 表示・本文 textarea は使える
  9. 3 幅スクショ `scripts/_temperature_{375,768,1280}.png`（夕に 37.8 を入れた赤の状態）
- [ ] **Step 2: 実行** `python3 scripts/verify_temperature_records.py` → 全 PASS。Task 3 の実装を外した状態で落ちることも 1 回確認
- [ ] **Step 3: 近隣の回帰** `python3 scripts/verify_bowel_records.py`／`verify_patrol_records.py`／`verify_date_switch_seq.py` → FAIL 0
- [ ] **Step 4: コミット** `git add scripts/verify_temperature_records.py scripts/_temperature_*.png && git commit -m "test(temp): 検温欄の Playwright 検証（9 ケース・3 幅）"`

---

## 自己レビュー（計画の）

- 設計書 §2 → Task 1、§3 → Task 2・3、§6（node・Playwright）→ Task 2・4。§4（管理画面）は care-stack-absence 側の計画 `docs/superpowers/plans/2026-11-10-temperature-admin.md`
- 名前の一貫性：`TemperatureLogic.normalizeTemp/isFever/formatTemp`、`tempLoadedForDate`、`tempRecords`、`renderTemperatureRow`、`refreshAllTemperatureRows`、`persistTemperature`、`loadTemperatureRecords`
