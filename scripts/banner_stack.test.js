const test = require('node:test');
const assert = require('node:assert/strict');
const { visible, MAX_VISIBLE } = require('./banner_stack.js');

test('visible: 何も無ければ空', () => {
  assert.deepEqual(visible({}), []);
  assert.deepEqual(visible(null), []);
});

test('visible: 1つだけならそれを出す', () => {
  const r = visible({ unsaved: '未保存の入力があります' });
  assert.equal(r.length, 1);
  assert.equal(r[0].key, 'unsaved');
});

// ネイト指摘の核心。競合が起きると reportDirty も立つため、
// 未保存を上位に置くと委託料に直結する通知がほぼ必ず隠れていた。
test('visible: 消えない通知は、未保存が出ていても必ず表示する', () => {
  const r = visible({
    sticky: '担当者が他の職員に更新されました。担当者欄を確認してください',
    unsaved: '未保存の入力があります',
  });
  assert.equal(r.length, 2);
  assert.equal(r[0].key, 'sticky');
  assert.match(r[0].message, /担当者/);
});

test('visible: 消えない通知は常に1枚目に置く', () => {
  const r = visible({ loadGuard: '読み込み中です', sticky: '担当者が更新されました' });
  assert.equal(r[0].key, 'sticky');
});

test('visible: 消えない通知が無ければ、深刻な順に1枚だけ', () => {
  const r = visible({ loadGuard: '読み込み中', unsaved: '未保存', draftRestore: '復元' });
  assert.equal(r.length, 1);
  assert.equal(r[0].key, 'loadGuard');
});

test('visible: 読み込み中が無ければ未保存を出す（復元案内より優先）', () => {
  const r = visible({ unsaved: '未保存', draftRestore: '復元' });
  assert.equal(r.length, 1);
  assert.equal(r[0].key, 'unsaved');
});

test('visible: 復元案内は最後（押せば消える一過性のもの）', () => {
  const r = visible({ draftRestore: '書きかけがあります' });
  assert.equal(r[0].key, 'draftRestore');
});

test('visible: 全部あっても2枚を超えない', () => {
  const r = visible({ sticky: 'a', loadGuard: 'b', unsaved: 'c', draftRestore: 'd' });
  assert.equal(r.length, MAX_VISIBLE);
  assert.equal(r[0].key, 'sticky');
  assert.equal(r[1].key, 'loadGuard');
});

test('visible: 空文字は「無し」として扱う', () => {
  const r = visible({ sticky: '', unsaved: '未保存' });
  assert.equal(r.length, 1);
  assert.equal(r[0].key, 'unsaved');
});
