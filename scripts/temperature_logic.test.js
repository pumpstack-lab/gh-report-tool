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

const TL = require('./temperature_logic.js');
test('normalizeTemp: 点なしの 3 桁 "366" → 36.6・"375" → 37.5', () => {
  assert.deepEqual(normalizeTemp('366'), { value: 36.6 }); assert.deepEqual(normalizeTemp('375'), { value: 37.5 });
});
test('normalizeTemp: 点なし 3 桁でも範囲外は受けない（"349"・"421"・"999"）', () => {
  assert.ok(normalizeTemp('349').error); assert.ok(normalizeTemp('421').error); assert.ok(normalizeTemp('999').error);
});
test('normalizeTemp: 4 桁は受けない', () => assert.ok(normalizeTemp('3665').error));
test('isTimeSlot', () => {
  assert.equal(TL.isTimeSlot('19:35'), true); assert.equal(TL.isTimeSlot('00:00'), true);
  assert.equal(TL.isTimeSlot('24:00'), false); assert.equal(TL.isTimeSlot('7:05'), false);
  assert.equal(TL.isTimeSlot('evening'), false); assert.equal(TL.isTimeSlot(null), false);
});
test('normalizeTime: いろいろな打ち方', () => {
  assert.deepEqual(TL.normalizeTime('19:35'), { value: '19:35' });
  assert.deepEqual(TL.normalizeTime('7:05'), { value: '07:05' });
  assert.deepEqual(TL.normalizeTime('１９：３５'), { value: '19:35' });
  assert.deepEqual(TL.normalizeTime('1935'), { value: '19:35' });
  assert.deepEqual(TL.normalizeTime(''), { value: null });
  assert.ok(TL.normalizeTime('25:00').error); assert.ok(TL.normalizeTime('19:60').error); assert.ok(TL.normalizeTime('夜').error);
});
test('sortTimeSlots: 前日の夕方〜夜が先・当日の未明〜日中が後・夕と朝の区分は除く・重複は 1 つ', () => {
  assert.deepEqual(TL.sortTimeSlots(['01:00', '22:00', 'evening', '19:35', '10:00', 'morning', '22:00', '15:00', '14:59']),
    ['15:00', '19:35', '22:00', '01:00', '10:00', '14:59']);
  assert.deepEqual(TL.sortTimeSlots(null), []);
});
test('timeLabel: 先頭の 0 を落とす', () => { assert.equal(TL.timeLabel('07:05'), '7:05'); assert.equal(TL.timeLabel('19:35'), '19:35'); });
test('slotDateLabels: 夕は前日・朝は日報の日付（月またぎ・年またぎ）', () => {
  assert.deepEqual(TL.slotDateLabels('2026-11-21'), { evening: '11/20', morning: '11/21' });
  assert.deepEqual(TL.slotDateLabels('2026-12-01'), { evening: '11/30', morning: '12/1' });
  assert.deepEqual(TL.slotDateLabels('2027-01-01'), { evening: '12/31', morning: '1/1' });
  assert.deepEqual(TL.slotDateLabels(''), { evening: '', morning: '' });
});
