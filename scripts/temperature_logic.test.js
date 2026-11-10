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
