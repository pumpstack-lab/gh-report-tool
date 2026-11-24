const test = require('node:test');
const assert = require('node:assert/strict');
const B = require('./bath_logic.js');

const st = (o) => Object.assign({ choice: '', sh: null, sm: null, eh: null, em: null }, o);

test('HOURS: 日報の流れの順（15時〜23時→0時〜14時）で 24 個', () => {
  assert.equal(B.HOURS.length, 24);
  assert.deepEqual(B.HOURS.slice(0, 3), [15, 16, 17]);
  assert.deepEqual(B.HOURS.slice(8, 11), [23, 0, 1]);
  assert.equal(B.HOURS[23], 14);
});
test('MINUTES: 10 分刻み', () => assert.deepEqual(B.MINUTES, [0, 10, 20, 30, 40, 50]));
test('orderChoices: 1〜n', () => assert.deepEqual(B.orderChoices(3), [1, 2, 3]));
test('timeLabel: 分 → 時:分', () => {
  assert.equal(B.timeLabel(17 * 60), '17:00'); assert.equal(B.timeLabel(7 * 60 + 50), '7:50'); assert.equal(B.timeLabel(null), '');
});

test('decide: 未選択 → 消す', () => assert.deepEqual(B.decide(st({})), { action: 'delete' }));
test('decide: 順番より先に時刻を選んだ → 保存も削除もせず順番を促す', () => {
  assert.deepEqual(B.decide(st({ sh: 17 })), { action: 'none', hint: B.HINT_ORDER });
  assert.deepEqual(B.decide(st({ sh: 17, sm: 0, eh: 17, em: 20 })), { action: 'none', hint: B.HINT_ORDER });
});
test('decide: 事業所で入浴 → 時刻なしで保存', () => {
  assert.deepEqual(B.decide(st({ choice: 'facility', sh: 17, sm: 0, eh: 17, em: 20 })),
    { action: 'save', fields: { kind: 'facility', bath_order: null, start_min: null, end_min: null }, minutes: null });
});
test('decide: 入浴なし → 時刻なしで保存', () => {
  assert.deepEqual(B.decide(st({ choice: 'none' })).fields, { kind: 'none', bath_order: null, start_min: null, end_min: null });
});
test('decide: 番号だけ（時刻まだ）→ 順番だけ保存・開始を促す', () => {
  const d = B.decide(st({ choice: '2' }));
  assert.equal(d.action, 'save');
  assert.deepEqual(d.fields, { kind: 'home', bath_order: 2, start_min: null, end_min: null });
  assert.equal(d.minutes, null); assert.equal(d.hint, B.HINT_START);
});
test('decide: 開始だけ → 開始だけ保存・終了を促す（入浴を始めた時に打って閉じても残る）', () => {
  const d = B.decide(st({ choice: '1', sh: 17, sm: 0, eh: 17 }));
  assert.deepEqual(d.fields, { kind: 'home', bath_order: 1, start_min: 1020, end_min: null });
  assert.equal(d.minutes, null); assert.equal(d.hint, B.HINT_END);
});
test('decide: 開始の時だけ（分まだ）・終了だけ → 時刻は保存しない', () => {
  assert.deepEqual(B.decide(st({ choice: '1', sh: 17, eh: 17 })).fields, { kind: 'home', bath_order: 1, start_min: null, end_min: null });
  const d = B.decide(st({ choice: '1', eh: 17, em: 20 }));
  assert.deepEqual(d.fields, { kind: 'home', bath_order: 1, start_min: null, end_min: null }); assert.equal(d.hint, B.HINT_START);
});
test('decide: 日をまたぐ 23:50〜0:10 → 20 分で保存', () => {
  assert.deepEqual(B.decide(st({ choice: '1', sh: 23, sm: 50, eh: 0, em: 10 })),
    { action: 'save', fields: { kind: 'home', bath_order: 1, start_min: 1430, end_min: 10 }, minutes: 20 });
});
test('decide: 朝の入浴 7:00〜7:20 は 20 分・朝→夕（7:00〜17:00）は 3 時間超えで保存しない', () => {
  assert.equal(B.decide(st({ choice: '1', sh: 7, sm: 0, eh: 7, em: 20 })).minutes, 20);
  assert.deepEqual(B.decide(st({ choice: '1', sh: 7, sm: 0, eh: 17, em: 0 })), { action: 'none', error: B.ORDER_ERROR });
});
test('decide: 昼の 15 時をまたぐ 14:50〜15:10 も 20 分で保存', () => {
  assert.deepEqual(B.decide(st({ choice: '1', sh: 14, sm: 50, eh: 15, em: 10 })),
    { action: 'save', fields: { kind: 'home', bath_order: 1, start_min: 890, end_min: 910 }, minutes: 20 });
});
test('decide: 打ち間違い 17:00〜5:00（12 時間）は保存しない・ちょうど 3 時間は通す・3 時間 10 分は通さない', () => {
  assert.deepEqual(B.decide(st({ choice: '1', sh: 17, sm: 0, eh: 5, em: 0 })), { action: 'none', error: B.ORDER_ERROR });
  assert.equal(B.decide(st({ choice: '1', sh: 17, sm: 0, eh: 20, em: 0 })).minutes, 180);
  assert.deepEqual(B.decide(st({ choice: '1', sh: 17, sm: 0, eh: 20, em: 10 })), { action: 'none', error: B.ORDER_ERROR });
});
test('decide: 全部の組み合わせ（144×144）で、保存するのは 10〜180 分の時だけ・分はひと回りの差と一致', () => {
  let saved = 0;
  for (let s = 0; s < 1440; s += 10) for (let e = 0; e < 1440; e += 10) {
    const d = B.decide(st({ choice: '1', sh: Math.floor(s / 60), sm: s % 60, eh: Math.floor(e / 60), em: e % 60 }));
    const span = (e - s + 1440) % 1440;
    if (span >= 10 && span <= 180) { assert.equal(d.action, 'save'); assert.equal(d.minutes, span); assert.equal(d.fields.start_min, s); assert.equal(d.fields.end_min, e); saved++; }
    else assert.deepEqual(d, { action: 'none', error: B.ORDER_ERROR });
  }
  assert.equal(saved, 144 * 18);
});
test('pendingTimes: 開始がそろう前に時刻のどれかを選んでいる間だけ true', () => {
  assert.equal(B.pendingTimes(st({ choice: '1' })), false);                         // 順番だけ
  assert.equal(B.pendingTimes(st({ choice: '1', sh: 17, eh: 17 })), true);          // 開始の時だけ
  assert.equal(B.pendingTimes(st({ choice: '1', eh: 17, em: 20 })), true);          // 終了だけ先に
  assert.equal(B.pendingTimes(st({ choice: '1', sh: 17, sm: 0, eh: 17 })), false);  // 開始はそろった（開始は保存される）
  assert.equal(B.pendingTimes(st({ choice: '1', sh: 17, sm: 0, eh: 17, em: 20 })), false);
});
test('stateFromRecord: 開始だけ保存済み', () => {
  assert.deepEqual(B.stateFromRecord({ kind: 'home', bath_order: 1, start_min: 1020, end_min: null }), { choice: '1', sh: 17, sm: 0, eh: null, em: null });
});
test('decide: 開始と終了がそろう → 分を出して保存', () => {
  const d = B.decide(st({ choice: '1', sh: 17, sm: 0, eh: 17, em: 20 }));
  assert.deepEqual(d, { action: 'save', fields: { kind: 'home', bath_order: 1, start_min: 1020, end_min: 1040 }, minutes: 20 });
});
test('decide: 時をまたぐ 17:50〜18:10 → 20 分', () => {
  assert.equal(B.decide(st({ choice: '3', sh: 17, sm: 50, eh: 18, em: 10 })).minutes, 20);
});
test('decide: 終了が開始と同じ・前 → 保存しない', () => {
  assert.deepEqual(B.decide(st({ choice: '1', sh: 17, sm: 20, eh: 17, em: 20 })), { action: 'none', error: B.ORDER_ERROR });
  assert.deepEqual(B.decide(st({ choice: '1', sh: 18, sm: 0, eh: 17, em: 50 })), { action: 'none', error: B.ORDER_ERROR });
});
test('decide: 1 時間を超えたら保存はするが確認の注意', () => {
  const d = B.decide(st({ choice: '1', sh: 17, sm: 0, eh: 18, em: 10 }));
  assert.equal(d.action, 'save'); assert.equal(d.minutes, 70); assert.equal(d.warn, B.LONG_WARN);
  assert.equal(B.decide(st({ choice: '1', sh: 17, sm: 0, eh: 18, em: 0 })).warn, undefined);
});
test('decide: 番号でない値は消す扱いにしない（壊れた値で既存の記録を消さない）', () => {
  assert.deepEqual(B.decide(st({ choice: 'abc' })), { action: 'none', error: B.CHOICE_ERROR });
  assert.deepEqual(B.decide(st({ choice: '0' })), { action: 'none', error: B.CHOICE_ERROR });
});

test('stateFromRecord: 保存済みの行 → 画面の選択', () => {
  assert.deepEqual(B.stateFromRecord({ kind: 'home', bath_order: 2, start_min: 1050, end_min: 1080 }), { choice: '2', sh: 17, sm: 30, eh: 18, em: 0 });
  assert.deepEqual(B.stateFromRecord({ kind: 'facility', bath_order: null, start_min: null, end_min: null }), st({ choice: 'facility' }));
  assert.deepEqual(B.stateFromRecord(null), st({}));
});
test('sameFields: 保存済みと同じなら送らない', () => {
  const f = { kind: 'home', bath_order: 1, start_min: 1020, end_min: 1040 };
  assert.equal(B.sameFields(f, Object.assign({ id: 9 }, f)), true);
  assert.equal(B.sameFields(f, Object.assign({}, f, { end_min: 1050 })), false);
  assert.equal(B.sameFields(f, null), false);
});
test('duplicateOrders: 同じ番号が 2 人以上いる番号だけ', () => {
  assert.deepEqual(B.duplicateOrders(['1', '2', '2', 'facility', 'none', '', '3', '3', '3']), ['2', '3']);
  assert.deepEqual(B.duplicateOrders(['1', '2', 'facility', 'facility']), []);
});
