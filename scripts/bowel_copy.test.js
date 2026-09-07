// /Users/Yutalow420/Desktop/01 開発/gh-report-tool/scripts/bowel_copy.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const { buildBowelCopyText } = require('./bowel_copy.js');

test('buildBowelCopyText: 0件は空文字を返す', () => {
  assert.equal(buildBowelCopyText('山田太郎', []), '');
});

test('buildBowelCopyText: 1件は氏名+時間+性状+量+便器を全角スペース区切りで1行返す', () => {
  const records = [
    { recorded_at: '08:00', stool_type: '普通便', amount: '中量', place: '便器' },
  ];
  assert.equal(
    buildBowelCopyText('山田太郎', records),
    '山田太郎さん　08:00　普通便　中量　便器'
  );
});

test('buildBowelCopyText: 複数件は時刻順に改行して並べる（入力順が逆でも並べ替える）', () => {
  const records = [
    { recorded_at: '14:30', stool_type: '軟便', amount: '少量', place: 'パッド内' },
    { recorded_at: '08:00', stool_type: '普通便', amount: '中量', place: '便器' },
  ];
  assert.equal(
    buildBowelCopyText('山田太郎', records),
    '山田太郎さん　08:00　普通便　中量　便器\n山田太郎さん　14:30　軟便　少量　パッド内'
  );
});

test('buildBowelCopyText: kind=noneの行は含めない（排便なしはコピー対象外）', () => {
  const records = [
    { kind: 'none', recorded_at: null, stool_type: null, amount: null, place: null },
    { recorded_at: '08:00', stool_type: '普通便', amount: '中量', place: '便器' },
  ];
  assert.equal(
    buildBowelCopyText('山田太郎', records),
    '山田太郎さん　08:00　普通便　中量　便器'
  );
});

test('buildBowelCopyText: 並び順はrecorded_atの文字列昇順のみで決める（sort_orderは無視する）', () => {
  // sort_orderが逆でもrecorded_atの昇順で並ぶこと（設計§7-2: 二重管理を避けるため）
  const records = [
    { recorded_at: '20:00', stool_type: '硬便', amount: '微量', place: '失便', sort_order: 0 },
    { recorded_at: '09:00', stool_type: '下痢便', amount: '多量', place: '便器', sort_order: 1 },
  ];
  assert.equal(
    buildBowelCopyText('佐藤花子', records),
    '佐藤花子さん　09:00　下痢便　多量　便器\n佐藤花子さん　20:00　硬便　微量　失便'
  );
});

test('buildBowelCopyText: 全件kind=noneなら空文字（コピーボタン非表示の判定にも使える）', () => {
  const records = [
    { kind: 'none', recorded_at: null, stool_type: null, amount: null, place: null },
  ];
  assert.equal(buildBowelCopyText('山田太郎', records), '');
});
