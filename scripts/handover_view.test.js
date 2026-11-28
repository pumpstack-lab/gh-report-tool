const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./handover_view.js');

const D = '2026-11-28';
const data = {
  facilities: [
    { key: 'respoir', submitted_at: null, reporter: null, notice: null },
    { key: 'komoan', submitted_at: '2026-11-28T07:12:00+00:00', reporter: '報告者A', notice: '明日は早く送ります' },
    { key: 'btype', submitted_at: '2026-11-28T16:05:00+09:00', reporter: '報告者B', notice: '  ' },
  ],
  notes: [
    { resident_id: 1, facility: 'komoan', target_date: D, body: '今日の文', updated_at: '2026-11-28T09:02:00+00:00' },
    { resident_id: 1, facility: 'komoan', target_date: '2026-11-27', body: '前回の文', updated_at: '2026-11-27T07:00:00+00:00' },
    { resident_id: 2, facility: 'respoir', target_date: '2026-11-26', body: '前回だけ', updated_at: '2026-11-26T07:00:00+00:00' },
    { resident_id: 3, facility: 'btype', target_date: D, body: '   ', updated_at: null },
  ],
  fixed: [
    { id: 9, resident_id: 2, body: '薬の確認', source: 'gh', start_date: '2026-11-20', until_date: D, created_by: '入れた人' },
    { id: 8, resident_id: 1, body: '綿棒は使わない', source: 'komoan', start_date: '2026-11-01', until_date: null, created_by: '' },
    { id: 7, resident_id: 1, body: '来週まで', source: 'respoir', start_date: '2026-11-01', until_date: '2026-12-03', created_by: 'x' },
  ],
};

test('timeLabel: 日本時間の時刻にする', () => {
  assert.equal(H.timeLabel('2026-11-28T07:12:00+00:00'), '16:12');
  assert.equal(H.timeLabel('2026-11-28T16:05:00+09:00'), '16:05');
  assert.equal(H.timeLabel('2026-11-28T15:30:00Z'), '0:30');
  assert.equal(H.timeLabel(null), '');
  assert.equal(H.timeLabel('こわれた値'), '');
});

test('build: 帯は決まった事業所の順で「届いた／まだ」', () => {
  const v = H.build(data, D);
  assert.deepEqual(v.status.map(s => s.text), ['レスポアール まだ', 'B型 16:05 届いた', 'こも庵 16:12 届いた']);
  assert.deepEqual(v.status.map(s => s.sent), [false, true, true]);
});

test('build: 全体連絡は届いていて中身のあるものだけ', () => {
  const v = H.build(data, D);
  assert.deepEqual(v.notices, [{ name: 'こも庵', body: '明日は早く送ります', reporter: '報告者A' }]);
});

test('build: 当日分と前回分を人ごとに分ける・空の文は出さない', () => {
  const v = H.build(data, D);
  assert.deepEqual(v.byResident['1'].today, [{ name: 'こも庵', body: '今日の文', time: '18:02' }]);
  assert.deepEqual(v.byResident['1'].prev, [{ name: 'こも庵', body: '前回の文', day: '11/27' }]);
  assert.deepEqual(v.byResident['2'].today, []);
  assert.deepEqual(v.byResident['2'].prev, [{ name: 'レスポアール', body: '前回だけ', day: '11/26' }]);
  assert.equal(v.byResident['3'], undefined);
  assert.deepEqual(v.todayIds, ['1']);
});

test('build: 固定は出どころ・期限・入れた人。最終日は「今日まで」', () => {
  const v = H.build(data, D);
  assert.deepEqual(v.byResident['2'].fixed, [{ id: 9, body: '薬の確認', meta: 'グループホーム・今日まで・入れた人：入れた人', lastDay: true }]);
  assert.deepEqual(v.byResident['1'].fixed.map(f => f.meta), ['こも庵・期限なし', 'レスポアール・12/3 まで・入れた人：x']);
  assert.deepEqual(v.fixedIds.sort(), ['1', '2']);
});

test('build: 文は加工しない（仕込み文もそのままの文字で返す）', () => {
  const evil = '<img src=x onerror="alert(1)">';
  const v = H.build({ facilities: [{ key: 'komoan', submitted_at: '2026-11-28T07:00:00Z', notice: evil, reporter: evil }],
    notes: [{ resident_id: 5, facility: 'komoan', target_date: D, body: evil, updated_at: null }],
    fixed: [{ id: 1, resident_id: 5, body: evil, source: 'gh', until_date: null, created_by: evil }] }, D);
  assert.equal(v.notices[0].body, evil);
  assert.equal(v.byResident['5'].today[0].body, evil);
  assert.equal(v.byResident['5'].fixed[0].body, evil);
});

test('build: 空・こわれた返り値でも落ちない', () => {
  for (const bad of [null, undefined, {}, { facilities: 'x', notes: null, fixed: 3 }]) {
    const v = H.build(bad, D);
    assert.deepEqual(v.status, []);
    assert.equal(v.any, false);
  }
});

test('shouldRefresh: 5 分以上たっていれば取り直す', () => {
  assert.equal(H.shouldRefresh(0, 1000), true);
  assert.equal(H.shouldRefresh(1000, 1000 + 4 * 60 * 1000), false);
  assert.equal(H.shouldRefresh(1000, 1000 + 5 * 60 * 1000), true);
});
