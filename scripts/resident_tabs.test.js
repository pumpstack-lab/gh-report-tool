const test = require('node:test');
const assert = require('node:assert/strict');
const { sortByKana, hasText } = require('./resident_tabs.js');

// ─── sortByKana ───────────────────────────────────────────
test('sortByKana: よみがなの50音順で並ぶ', () => {
  const items = [
    { key: 'b', kana: 'さとう' },
    { key: 'a', kana: 'あおき' },
  ];
  const sorted = sortByKana(items);
  assert.deepEqual(sorted.map(i => i.key), ['a', 'b']);
});

test('sortByKana: よみがなの空白は無視して並べる', () => {
  const items = [
    { key: 'a', kana: 'さ とう' },
    { key: 'b', kana: 'あおき　' }, // 全角スペース
  ];
  const sorted = sortByKana(items);
  assert.deepEqual(sorted.map(i => i.key), ['b', 'a']);
});

test('sortByKana: よみがなの無い人は後ろ、その中はsort_order順', () => {
  const items = [
    { key: 'noKanaB', kana: null, sortOrder: 2 },
    { key: 'hasKana', kana: 'あおき', sortOrder: 99 },
    { key: 'noKanaA', kana: null, sortOrder: 1 },
  ];
  const sorted = sortByKana(items);
  assert.deepEqual(sorted.map(i => i.key), ['hasKana', 'noKanaA', 'noKanaB']);
});

test('sortByKana: 空文字のkanaも「よみがな無し」扱いで後ろに回る', () => {
  const items = [
    { key: 'empty', kana: '', sortOrder: 1 },
    { key: 'has', kana: 'あ', sortOrder: 99 },
  ];
  const sorted = sortByKana(items);
  assert.deepEqual(sorted.map(i => i.key), ['has', 'empty']);
});

test('sortByKana: 短期入所①②など末尾固定の項目はtrailing=trueで常に最後、互いの順は入力順', () => {
  const items = [
    { key: 'short2', kana: null, sortOrder: 1, trailing: true },
    { key: 'resident', kana: 'あおき', sortOrder: 1 },
    { key: 'short1', kana: null, sortOrder: 0, trailing: true },
  ];
  const sorted = sortByKana(items);
  assert.deepEqual(sorted.map(i => i.key), ['resident', 'short2', 'short1']);
});

test('sortByKana: 元の配列を破壊しない', () => {
  const items = [{ key: 'b', kana: 'い' }, { key: 'a', kana: 'あ' }];
  const copy = items.slice();
  sortByKana(items);
  assert.deepEqual(items, copy);
});

// ─── hasText ──────────────────────────────────────────────
test('hasText: 本文があればtrue', () => {
  assert.equal(hasText('今日は元気でした'), true);
});

test('hasText: 空文字はfalse', () => {
  assert.equal(hasText(''), false);
});

test('hasText: 空白・改行だけはfalse', () => {
  assert.equal(hasText('   \n\t　'), false);
});

test('hasText: null/undefinedはfalse', () => {
  assert.equal(hasText(null), false);
  assert.equal(hasText(undefined), false);
});
