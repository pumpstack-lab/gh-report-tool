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

// ── 日付を素早く 2 回切り替えた時に、先に出した読み込みの応答を捨てる（2026-11-10）
test('createLoadSequence: 後から始めた読み込みがあれば、先の読み込みは古い扱い', () => {
  const { createLoadSequence } = require('./report_guard.js');
  const seq = createLoadSequence();
  const first = seq.begin();
  const second = seq.begin();
  assert.equal(seq.isCurrent(first), false);
  assert.equal(seq.isCurrent(second), true);
});

test('createLoadSequence: 読み込みが 1 本だけなら最新', () => {
  const { createLoadSequence } = require('./report_guard.js');
  const seq = createLoadSequence();
  const only = seq.begin();
  assert.equal(seq.isCurrent(only), true);
});

// ── 写真の ✕ は読み込みが終わった日付でだけ押せる（2026-11-10）
test('canRemovePhoto: 読み込み中（loadedFor=null）は消せない', () => {
  const { canRemovePhoto } = require('./report_guard.js');
  assert.equal(canRemovePhoto({ loadedFor: null, dateISO: '2026-11-10' }), false);
});

test('canRemovePhoto: 別日付の読み込み結果が残っている間は消せない', () => {
  const { canRemovePhoto } = require('./report_guard.js');
  assert.equal(canRemovePhoto({ loadedFor: '2026-11-09', dateISO: '2026-11-10' }), false);
});

test('canRemovePhoto: その日付の読み込みが終わっていれば消せる', () => {
  const { canRemovePhoto } = require('./report_guard.js');
  assert.equal(canRemovePhoto({ loadedFor: '2026-11-10', dateISO: '2026-11-10' }), true);
});
