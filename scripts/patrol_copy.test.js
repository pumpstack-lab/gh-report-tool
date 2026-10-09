// /Users/Yutalow420/Desktop/01 開発/gh-report-tool/scripts/patrol_copy.test.js
const assert = require('assert');
const { test } = require('node:test');
const { PATROL_SLOTS, buildPatrolCopyText, slotLabel } = require('./patrol_copy.js');

test('PATROL_SLOTS: 4枠が夜の順に並ぶ', () => {
  assert.deepStrictEqual(PATROL_SLOTS.map(s => s.key), ['22:30', '23:30', '01:00', '05:00']);
  assert.deepStrictEqual(PATROL_SLOTS.map(s => s.label), ['22:30', '23:30', '1:00', '5:00']);
});

test('slotLabel: keyから表示ラベル（未知のkeyはそのまま返す）', () => {
  assert.strictEqual(slotLabel('01:00'), '1:00');
  assert.strictEqual(slotLabel('03:00'), '03:00');
});

test('buildPatrolCopyText: チェック済みをPATROL_SLOTSの順に並べる（保存順に依存しない）', () => {
  const text = buildPatrolCopyText('山田太郎', [{ slot: '05:00' }, { slot: '22:30' }, { slot: '01:00' }]);
  assert.strictEqual(text, '山田太郎さん　見回り　22:30　1:00　5:00');
});

test('buildPatrolCopyText: 0件なら空文字（コピーボタン非表示の判定に使う）', () => {
  assert.strictEqual(buildPatrolCopyText('山田太郎', []), '');
  assert.strictEqual(buildPatrolCopyText('山田太郎', undefined), '');
});

test('buildPatrolCopyText: 未知のslotは落とさずkeyのまま末尾に出す', () => {
  const text = buildPatrolCopyText('山田太郎', [{ slot: '03:00' }, { slot: '23:30' }]);
  assert.strictEqual(text, '山田太郎さん　見回り　23:30　03:00');
});

test('buildPatrolCopyText: 同じslotが重複しても1回だけ', () => {
  const text = buildPatrolCopyText('山田太郎', [{ slot: '22:30' }, { slot: '22:30' }]);
  assert.strictEqual(text, '山田太郎さん　見回り　22:30');
});
