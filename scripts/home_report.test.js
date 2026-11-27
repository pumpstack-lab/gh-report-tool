const test = require('node:test');
const assert = require('node:assert/strict');
const HR = require('./home_report.js');

test('formatWareki: 様式の例 2026-05-20 → 令和8年5月20日（水）', () => assert.equal(HR.formatWareki('2026-05-20'), '令和8年5月20日（水）'));
test('formatWareki: 令和元年の初日', () => assert.equal(HR.formatWareki('2019-05-01'), '令和元年5月1日（水）'));
test('formatWareki: 月日の頭の 0 は付けない', () => assert.equal(HR.formatWareki('2027-01-03'), '令和9年1月3日（日）'));
test('formatWareki: 令和より前・形が違う・無い日は空', () => {
  assert.equal(HR.formatWareki('2019-04-30'), '');
  assert.equal(HR.formatWareki('2026-5-20'), '');
  assert.equal(HR.formatWareki('2026-02-30'), '');
  assert.equal(HR.formatWareki(''), '');
  assert.equal(HR.formatWareki(null), '');
});
test('isValidDate', () => {
  assert.equal(HR.isValidDate('2026-11-27'), true);
  assert.equal(HR.isValidDate('2026-13-01'), false);
  assert.equal(HR.isValidDate('2026-02-29'), false);
  assert.equal(HR.isValidDate('2028-02-29'), true);
});
test('homeName: 1〜6 だけ', () => {
  assert.equal(HR.homeName(1), 'こもれびホーム３−２');
  assert.equal(HR.homeName('6'), 'こもれびホームマハロ');
  assert.equal(HR.homeName(0), '');
  assert.equal(HR.homeName(7), '');
  assert.equal(HR.HOMES.length, 6);
});
test('validate: そろっていれば値を整えて返す', () => {
  const r = HR.validate({ report_date: '2026-11-27', gh_num: '3', reporter: '  報告 者  ', body: '本文\r\nです  \n\n' });
  assert.deepEqual(r, { value: { report_date: '2026-11-27', gh_num: 3, reporter: '報告 者', body: '本文\nです' } });
});
test('validate: 足りない所を欄の名前つきで返す（最初の 1 つ）', () => {
  const ok = { report_date: '2026-11-27', gh_num: 3, reporter: 'あ', body: 'い' };
  assert.deepEqual(HR.validate({ ...ok, report_date: '' }), { error: '日付を入れてください', field: 'report_date' });
  assert.deepEqual(HR.validate({ ...ok, gh_num: '' }), { error: 'ホームを選んでください', field: 'gh_num' });
  assert.deepEqual(HR.validate({ ...ok, gh_num: 9 }), { error: 'ホームを選んでください', field: 'gh_num' });
  assert.deepEqual(HR.validate({ ...ok, reporter: '   ' }), { error: '報告者の名前を入れてください', field: 'reporter' });
  assert.deepEqual(HR.validate({ ...ok, body: ' \n ' }), { error: '本文を入れてください', field: 'body' });
});
test('validate: 長すぎる', () => {
  const ok = { report_date: '2026-11-27', gh_num: 3, reporter: 'あ', body: 'い' };
  assert.equal(HR.validate({ ...ok, reporter: 'あ'.repeat(HR.REPORTER_MAX + 1) }).field, 'reporter');
  assert.ok(HR.validate({ ...ok, reporter: 'あ'.repeat(HR.REPORTER_MAX) }).value);
  assert.equal(HR.validate({ ...ok, body: 'い'.repeat(HR.BODY_MAX + 1) }).field, 'body');
  assert.ok(HR.validate({ ...ok, body: 'い'.repeat(HR.BODY_MAX) }).value);
});
test('isDirty: 保存済みと同じなら false（前後の空白・改行の種類は無視）', () => {
  const saved = { report_date: '2026-11-27', gh_num: 3, reporter: 'あ', body: 'い\nう' };
  assert.equal(HR.isDirty({ report_date: '2026-11-27', gh_num: '3', reporter: ' あ ', body: 'い\r\nう\n' }, saved), false);
  assert.equal(HR.isDirty({ ...saved, body: 'い\nうえ' }, saved), true);
  assert.equal(HR.isDirty({ report_date: '2026-11-27', gh_num: '', reporter: '', body: '' }, null), false);
  assert.equal(HR.isDirty({ report_date: '2026-11-27', gh_num: '', reporter: '', body: 'あ' }, null), true);
});
test('listLabel: 一覧の 1 行', () => {
  assert.equal(HR.listLabel({ report_date: '2026-11-27', gh_num: 2, reporter: 'あ' }), '11/27（金） こもれびホーム４');
});
