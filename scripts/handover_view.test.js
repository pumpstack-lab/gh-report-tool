const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('./handover_view.js');

// 日報の日付は 11/28（土）。この日報が指すのは 11/27（金）の夕方〜11/28 の朝＝主に出すのは 11/27 の日中の申し送り
const D = '2026-11-28', Y = '2026-11-27';
const day = (date, at, more) => Object.assign({ date, submitted_at: at, updated_at: at, reporter: '報告者A', notice: '' }, more || {});
const data = {
  facilities: [
    { key: 'respoir', running: true, days: [] },
    { key: 'komoan', running: true, days: [day(Y, '2026-11-27T07:12:00+00:00', { notice: '明日は早く送ります', updated_at: '2026-11-27T09:02:00+00:00' })] },
    { key: 'btype', running: true, days: [day(Y, '2026-11-27T16:05:00+09:00', { notice: '  ' }), day(D, '2026-11-28T15:40:00+09:00', { notice: '当日の連絡', reporter: '報告者B' })] },
    { key: 'hana', running: false, days: [] },
  ],
  notes: [
    { resident_id: 1, facility: 'komoan', target_date: Y, body: '前の日の文', updated_at: '2026-11-27T09:02:00+00:00' },
    { resident_id: 1, facility: 'btype', target_date: D, body: '当日の夕方に届いた文', updated_at: '2026-11-28T06:40:00+00:00' },
    { resident_id: 2, facility: 'respoir', target_date: '2026-11-25', body: '前回だけ', updated_at: '2026-11-25T07:00:00+00:00' },
    { resident_id: 3, facility: 'btype', target_date: Y, body: '   ', updated_at: null },
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

test('shiftDay・dayLabel: 月またぎ・年またぎ・曜日', () => {
  assert.equal(H.shiftDay('2026-12-01', -1), '2026-11-30');
  assert.equal(H.shiftDay('2027-01-01', -1), '2026-12-31');
  assert.equal(H.shiftDay('2026-03-01', -1), '2026-02-28');
  assert.equal(H.dayLabel('2026-11-27'), '11/27（金）');
  assert.equal(H.dayLabel('こわれた値'), '');
});

test('build: 主に出すのは日報の前の日。帯はその日の「届いた／まだ」を決まった順で', () => {
  const v = H.build(data, D);
  assert.equal(v.mainDate, Y);
  assert.equal(v.mainLabel, '11/27（金）');
  assert.deepEqual(v.status.map(s => s.text), ['レスポアール まだ', 'B型 16:05 届いた', 'こも庵 16:12 届いた（18:02 に直し）']);
  assert.equal(v.quiet, false);
});

test('build: 始めていない事業所（running=false）の「まだ」は出さない', () => {
  const v = H.build(data, D);
  assert.equal(v.status.some(s => s.key === 'hana'), false);
});

test('build: 前の日にどこも送っていなければ quiet（休みの日に「まだ」を並べない）', () => {
  const v = H.build({ facilities: [{ key: 'komoan', running: true, days: [] }, { key: 'btype', running: true, days: [] }], notes: [], fixed: [] }, D);
  assert.equal(v.quiet, true);
  assert.deepEqual(v.status.map(s => s.sent), [false, false]);
});

test('build: 日報と同じ日付に届いた分は別に知らせる', () => {
  const v = H.build(data, D);
  assert.deepEqual(v.extra, ['B型 15:40 届いた']);
});

test('build: 全体連絡は届いていて中身のあるものだけ・日付つき', () => {
  const v = H.build(data, D);
  assert.deepEqual(v.notices, [
    { name: 'こも庵', day: '11/27（金）', body: '明日は早く送ります', reporter: '報告者A' },
    { name: 'B型', day: '11/28（土）', body: '当日の連絡', reporter: '報告者B' },
  ]);
});

test('build: 前の日と当日の分は開いて出す・それより前は「前回」・空の文は出さない', () => {
  const v = H.build(data, D);
  assert.deepEqual(v.byResident['1'].main, [
    { name: 'こも庵', day: '11/27（金）', body: '前の日の文', time: '18:02' },
    { name: 'B型', day: '11/28（土）', body: '当日の夕方に届いた文', time: '15:40' },
  ]);
  assert.deepEqual(v.byResident['1'].prev, []);
  assert.deepEqual(v.byResident['2'].main, []);
  assert.deepEqual(v.byResident['2'].prev, [{ name: 'レスポアール', day: '11/25（水）', body: '前回だけ', time: '16:00' }]);
  assert.equal(v.byResident['3'], undefined);
  assert.deepEqual(v.markIds, ['1']);
});

test('build: 固定は出どころ・期限・入れた人。最終日は「今日まで」', () => {
  const v = H.build(data, D);
  assert.deepEqual(v.byResident['2'].fixed, [{ id: 9, body: '薬の確認', meta: 'グループホーム・今日まで・入れた人：入れた人', lastDay: true }]);
  assert.deepEqual(v.byResident['1'].fixed.map(f => f.meta), ['こも庵・期限なし', 'レスポアール・12/3 まで・入れた人：x']);
  assert.deepEqual(v.fixedIds.sort(), ['1', '2']);
});

test('build: 文は加工しない（仕込み文もそのままの文字で返す）', () => {
  const evil = '<img src=x onerror="alert(1)">';
  const v = H.build({ facilities: [{ key: 'komoan', running: true, days: [day(Y, '2026-11-27T07:00:00Z', { notice: evil, reporter: evil })] }],
    notes: [{ resident_id: 5, facility: 'komoan', target_date: Y, body: evil, updated_at: null }],
    fixed: [{ id: 1, resident_id: 5, body: evil, source: 'gh', until_date: null, created_by: evil }] }, D);
  assert.equal(v.notices[0].body, evil);
  assert.equal(v.byResident['5'].main[0].body, evil);
  assert.equal(v.byResident['5'].fixed[0].body, evil);
});

test('build: 空・こわれた返り値でも落ちない', () => {
  for (const bad of [null, undefined, {}, [], { facilities: 'x', notes: null, fixed: 3 }, { facilities: [{ key: 'komoan' }], notes: [{}], fixed: [{}] }]) {
    const v = H.build(bad, D);
    assert.equal(Array.isArray(v.status), true);
    assert.deepEqual(v.markIds, []);
  }
});

test('shouldRefresh: 5 分以上たっていれば取り直す', () => {
  assert.equal(H.shouldRefresh(0, 1000), true);
  assert.equal(H.shouldRefresh(1000, 1000 + 4 * 60 * 1000), false);
  assert.equal(H.shouldRefresh(1000, 1000 + 5 * 60 * 1000), true);
});
