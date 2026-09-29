// ~/Desktop/01 開発/gh-report-tool/scripts/diaper_stock_label.test.js
// 日報のオムツ入力欄に出す「残り◯枚」の表示ロジック（2026-09-29 オーナー要望）。
// 要望＝「使用量を入力する画面で残量までわかるようにして欲しい。そうすれば明らかにずれていたら分かる」
const assert = require('assert');
const { test } = require('node:test');
const { stockLabel, stockClass, stockUnavailableNote } = require('./diaper_stock_label.js');

test('stockLabel: 通常の在庫は「残り◯枚」', () => {
  assert.strictEqual(stockLabel(80), '残り80枚');
  assert.strictEqual(stockLabel(2), '残り2枚');
});

test('stockLabel: 0枚は「残り0枚」（空欄にしない＝切れていることが伝わる）', () => {
  assert.strictEqual(stockLabel(0), '残り0枚');
});

test('stockLabel: マイナスは符号をそのまま出す（ずれに気づかせるのが目的）', () => {
  // ここを「0枚」や「—」に丸めると、オーナーの「明らかにずれていたら分かる」が達成できない
  assert.strictEqual(stockLabel(-13), '残り−13枚');
  assert.strictEqual(stockLabel(-6), '残り−6枚');
});

test('stockLabel: 数えられない時は何も出さない（嘘の数字を出さない）', () => {
  assert.strictEqual(stockLabel(null), '');
  assert.strictEqual(stockLabel(undefined), '');
  assert.strictEqual(stockLabel(NaN), '');
  assert.strictEqual(stockLabel('80'), '');   // 文字列は受け付けない
});

test('stockClass: マイナスは要確認の見た目にする', () => {
  assert.strictEqual(stockClass(-13), 'minus');
  assert.strictEqual(stockClass(-1), 'minus');
});

test('stockClass: 0枚も要確認（切れている）', () => {
  assert.strictEqual(stockClass(0), 'minus');
});

test('stockClass: 在庫があれば通常表示', () => {
  assert.strictEqual(stockClass(1), 'normal');
  assert.strictEqual(stockClass(80), 'normal');
});

test('stockClass: 数えられない時は表示しない扱い', () => {
  assert.strictEqual(stockClass(null), 'none');
  assert.strictEqual(stockClass(undefined), 'none');
  assert.strictEqual(stockClass(NaN), 'none');
});

test('実データ再現: 2026-09-29 時点の本番値がそのまま出る', () => {
  // 花木さん（棚卸し後・正常）／垂門さん（記録のずれ）／長田さん（本当に切れている）
  assert.strictEqual(stockLabel(80), '残り80枚');
  assert.strictEqual(stockClass(80), 'normal');
  assert.strictEqual(stockLabel(-15), '残り−15枚');
  assert.strictEqual(stockClass(-15), 'minus');
  assert.strictEqual(stockLabel(0), '残り0枚');
  assert.strictEqual(stockClass(0), 'minus');
});

// ─── 取得失敗と「残量ゼロ」を混同させない（2026-09-29 ネイト指摘④） ───
// 在庫の取得に失敗すると残量が1件も出ない。現場が「出ていない＝在庫がある」と
// 誤解するのが怖いので、出せなかったことを画面に伝えられるようにする。

test('stockUnavailableNote: 1件も残量を出せなかった時だけ注意文を返す', () => {
  // 品目はあるのに残量が1件も無い＝取得に失敗している
  assert.strictEqual(
    stockUnavailableNote(3, 0),
    '在庫情報を取得できませんでした（残量は表示されていません）'
  );
});

test('stockUnavailableNote: 一部でも出ていれば何も言わない', () => {
  assert.strictEqual(stockUnavailableNote(3, 1), '');
  assert.strictEqual(stockUnavailableNote(3, 3), '');
});

test('stockUnavailableNote: そもそも品目が無い日は何も言わない（正常）', () => {
  assert.strictEqual(stockUnavailableNote(0, 0), '');
});
