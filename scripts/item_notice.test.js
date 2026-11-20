const test = require('node:test');
const assert = require('node:assert/strict');
const { noticeFor, decorateName } = require('./item_notice.js');

// ⚠️ 実在の利用者の氏名は書かない（公開される置き場のため）。名前はすべて架空。

test('noticeFor: 対象の番号（数値でも文字列でも）に「※綿棒禁止」', () => {
  assert.equal(noticeFor(15), '※綿棒禁止');
  assert.equal(noticeFor('15'), '※綿棒禁止');
});

test('noticeFor: 対象でない番号・空・短期入所の内部キーには出さない', () => {
  assert.equal(noticeFor(14), '');
  assert.equal(noticeFor(150), '');
  assert.equal(noticeFor('1'), '');
  assert.equal(noticeFor(null), '');
  assert.equal(noticeFor(undefined), '');
  assert.equal(noticeFor(''), '');
  assert.equal(noticeFor('__short_stay_1__'), '');
});

test('decorateName: 対象だけ名前の後ろに半角空白で「※綿棒禁止」を付ける', () => {
  assert.equal(decorateName(15, '架空　花子'), '架空　花子 ※綿棒禁止');
  assert.equal(decorateName(14, '架空　太郎'), '架空　太郎');
  assert.equal(decorateName(null, null), '');
});
