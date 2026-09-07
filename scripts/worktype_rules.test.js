const test = require('node:test');
const assert = require('node:assert/strict');
const { shiftBaseDate, isClosedDay, workTypeWarning } = require('./worktype_rules.js');

// ─── shiftBaseDate ────────────────────────────────────────
test('shiftBaseDate: weekday_nightは報告日の前日を返す', () => {
  assert.equal(shiftBaseDate('2026-08-02', 'weekday_night'), '2026-08-01');
});

test('shiftBaseDate: holiday_nightは報告日の前日を返す', () => {
  assert.equal(shiftBaseDate('2026-08-16', 'holiday_night'), '2026-08-15');
});

test('shiftBaseDate: holiday_dayは報告日そのもの', () => {
  assert.equal(shiftBaseDate('2026-08-16', 'holiday_day'), '2026-08-16');
});

test('shiftBaseDate: holiday_day_nightは報告日そのもの', () => {
  assert.equal(shiftBaseDate('2026-08-16', 'holiday_day_night'), '2026-08-16');
});

test('shiftBaseDate: six_hourは報告日そのもの', () => {
  assert.equal(shiftBaseDate('2026-08-16', 'six_hour'), '2026-08-16');
});

test('shiftBaseDate: 未知の種別/nullは報告日そのものを返す（安全側）', () => {
  assert.equal(shiftBaseDate('2026-08-16', null), '2026-08-16');
  assert.equal(shiftBaseDate('2026-08-16', 'unknown'), '2026-08-16');
});

test('shiftBaseDate: 月またぎ（9/1の報告→8/31の勤務）', () => {
  assert.equal(shiftBaseDate('2026-09-01', 'weekday_night'), '2026-08-31');
});

test('shiftBaseDate: 年またぎ（1/1の報告→前年12/31の勤務）', () => {
  assert.equal(shiftBaseDate('2027-01-01', 'holiday_night'), '2026-12-31');
});

test('shiftBaseDate: うるう年（2028/3/1の報告→2028/2/29の勤務）', () => {
  assert.equal(shiftBaseDate('2028-03-01', 'weekday_night'), '2028-02-29');
});

test('shiftBaseDate: うるう年でない年の3/1（2027/3/1の報告→2027/2/28の勤務）', () => {
  assert.equal(shiftBaseDate('2027-03-01', 'weekday_night'), '2027-02-28');
});

// ─── isClosedDay ──────────────────────────────────────────
test('isClosedDay: 土曜はtrue', () => {
  assert.equal(isClosedDay('2026-08-15', new Set()), true); // 2026-08-15は土曜
});

test('isClosedDay: 日曜はtrue', () => {
  assert.equal(isClosedDay('2026-08-16', new Set()), true); // 2026-08-16は日曜
});

test('isClosedDay: 平日かつholidaySetに無ければfalse', () => {
  assert.equal(isClosedDay('2026-08-17', new Set()), false); // 2026-08-17は月曜
});

test('isClosedDay: 国民の祝日（holidaySetに登録済み）はtrue', () => {
  assert.equal(isClosedDay('2026-08-11', new Set(['2026-08-11'])), true); // 山の日
});

test('isClosedDay: 休園日（kind=closedとして登録済み）もholidaySetに含めればtrue', () => {
  // holidaySetは呼び出し側で national/closed 両方をマージして渡す想定
  assert.equal(isClosedDay('2026-08-14', new Set(['2026-08-14'])), true);
});

// ─── workTypeWarning ──────────────────────────────────────
test('workTypeWarning: 前日が休日なのにweekday_night(平日種別)なら警告', () => {
  // 報告日8/16(日)の前日は8/15(土・休日) → weekday_nightは平日種別なので警告
  const w = workTypeWarning('weekday_night', '2026-08-16', new Set());
  assert.match(w, /⚠️/);
});

test('workTypeWarning: 前日が平日なのにholiday_night(休日種別)なら警告', () => {
  // 報告日8/18(火)の前日は8/17(月・平日) → holiday_nightは休日種別なので警告
  const w = workTypeWarning('holiday_night', '2026-08-18', new Set());
  assert.match(w, /⚠️/);
});

test('workTypeWarning: 前日が休日でholiday_night(休日種別)なら警告なし', () => {
  // 報告日8/16(日)の前日は8/15(土・休日) → holiday_nightは休日種別なので一致・警告なし
  const w = workTypeWarning('holiday_night', '2026-08-16', new Set());
  assert.equal(w, '');
});

test('workTypeWarning: holiday_day(休日種別)は「報告日そのもの」で休日判定する', () => {
  // 報告日8/15(土)そのものが休日 → holiday_dayは休日種別なので一致・警告なし
  const w = workTypeWarning('holiday_day', '2026-08-15', new Set());
  assert.equal(w, '');
  // 報告日8/17(月)は平日 → holiday_dayは休日種別なので警告
  const w2 = workTypeWarning('holiday_day', '2026-08-17', new Set());
  assert.match(w2, /⚠️/);
});

test('workTypeWarning: holiday_day_nightも報告日そのもので判定する', () => {
  const w = workTypeWarning('holiday_day_night', '2026-08-17', new Set());
  assert.match(w, /⚠️/);
});

test('workTypeWarning: six_hourは常に警告なし（holiday: null）', () => {
  assert.equal(workTypeWarning('six_hour', '2026-08-17', new Set()), '');
});

test('workTypeWarning: work_typeが空/未知なら警告なし', () => {
  assert.equal(workTypeWarning(null, '2026-08-17', new Set()), '');
  assert.equal(workTypeWarning('unknown', '2026-08-17', new Set()), '');
});

test('workTypeWarning: 月またぎでも前日基準で正しく判定する（9/1報告・前日8/31が休日）', () => {
  // 8/31を休園日として登録した場合を想定
  const w = workTypeWarning('weekday_night', '2026-09-01', new Set(['2026-08-31']));
  assert.match(w, /⚠️/);
});
