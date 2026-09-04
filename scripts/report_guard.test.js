const test = require('node:test');
const assert = require('node:assert/strict');
const { canSaveReport, shouldWarnUnsaved } = require('./report_guard.js');

test('canSaveReport: ロード未完了(loadedFor=null)なら保存しない', () => {
  assert.equal(canSaveReport({ loadedFor: null, dateISO: '2026-09-04', dirty: true }), false);
});

test('canSaveReport: loadedFor が別日付なら保存しない（日付切替中の混線防止）', () => {
  assert.equal(canSaveReport({ loadedFor: '2026-09-03', dateISO: '2026-09-04', dirty: true }), false);
});

test('canSaveReport: loadedFor一致でもdirty=falseなら保存しない（未入力の空押し保存を防ぐ）', () => {
  assert.equal(canSaveReport({ loadedFor: '2026-09-04', dateISO: '2026-09-04', dirty: false }), false);
});

test('canSaveReport: loadedFor一致かつdirty=trueなら保存してよい', () => {
  assert.equal(canSaveReport({ loadedFor: '2026-09-04', dateISO: '2026-09-04', dirty: true }), true);
});

test('shouldWarnUnsaved: ロード未完了で入力ありなら警告を出す', () => {
  assert.equal(shouldWarnUnsaved({ loadedFor: null, dateISO: '2026-09-04', dirty: true }), true);
});

test('shouldWarnUnsaved: ロード未完了でも入力が無ければ警告不要', () => {
  assert.equal(shouldWarnUnsaved({ loadedFor: null, dateISO: '2026-09-04', dirty: false }), false);
});

test('shouldWarnUnsaved: 正常に保存できる状態なら警告不要', () => {
  assert.equal(shouldWarnUnsaved({ loadedFor: '2026-09-04', dateISO: '2026-09-04', dirty: true }), false);
});
