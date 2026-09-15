const test = require('node:test');
const assert = require('node:assert/strict');
const { draftKey, buildDraft, pickRestorable, isExpired } = require('./report_draft.js');

test('draftKey: ホームと日付でキーが分かれる', () => {
  assert.equal(draftKey(1, '2026-09-15'), 'report_draft_1_2026-09-15');
  assert.notEqual(draftKey(1, '2026-09-15'), draftKey(6, '2026-09-15'));
  assert.notEqual(draftKey(1, '2026-09-15'), draftKey(1, '2026-09-16'));
});

// ─── buildDraft ───────────────────────────────────────────
test('buildDraft: サーバーに入っている本文は退避しない', () => {
  const d = buildDraft(
    { residents: { '山田太郎': '保存済みの本文' } },
    { residents: { '山田太郎': '保存済みの本文' } },
  );
  assert.equal(d, null);
});

test('buildDraft: サーバーと違う本文だけ退避する', () => {
  const d = buildDraft(
    { residents: { '山田太郎': '書き足した本文', '佐藤花子': '保存済み' } },
    { residents: { '山田太郎': '書き足す前', '佐藤花子': '保存済み' } },
  );
  assert.deepEqual(Object.keys(d.residents), ['山田太郎']);
  assert.equal(d.residents['山田太郎'], '書き足した本文');
  assert.equal(typeof d.savedAt, 'number');
});

test('buildDraft: 空欄は退避しない（空で上書きさせないため）', () => {
  const d = buildDraft(
    { residents: { '山田太郎': '', '佐藤花子': '   ' } },
    { residents: { '山田太郎': '消す前の本文' } },
  );
  assert.equal(d, null);
});

test('buildDraft: サーバー側にキーが無い新規の本文も退避する', () => {
  const d = buildDraft({ residents: { '山田太郎': '新しく書いた' } }, { residents: {} });
  assert.equal(d.residents['山田太郎'], '新しく書いた');
});

// ─── pickRestorable ───────────────────────────────────────
test('pickRestorable: サーバーと同じ本文は復元を提案しない', () => {
  const r = pickRestorable({ residents: { '山田太郎': '同じ本文' } }, { '山田太郎': '同じ本文' });
  assert.deepEqual(r, {});
});

test('pickRestorable: サーバーが下書きを前方一致で含めば提案しない（書き足された＝サーバーが新しい）', () => {
  const r = pickRestorable(
    { residents: { '山田太郎': '朝は落ち着いて過ごされていました' } },
    { '山田太郎': '朝は落ち着いて過ごされていました。昼食は全量摂取。' },
  );
  assert.deepEqual(r, {});
});

// ネイト指摘D-2: 福祉の日報は定型句が多く、中間一致で判定すると
// 別人が書いた無関係の本文にヒットして未保存の記述を黙って捨てる。
test('pickRestorable: 短い定型句は、サーバー本文の途中に含まれていても提案する', () => {
  const r = pickRestorable(
    { residents: { '山田太郎': '排便あり' } },
    { '山田太郎': '夕食後に排便あり、その後入浴されました' },
  );
  assert.equal(r['山田太郎'], '排便あり');
});

test('pickRestorable: 十分長くても前方一致でなければ提案する', () => {
  const r = pickRestorable(
    { residents: { '山田太郎': '入浴を拒まれたため清拭で対応' } },
    { '山田太郎': '朝から体調不良。入浴を拒まれたため清拭で対応した。' },
  );
  assert.equal(r['山田太郎'], '入浴を拒まれたため清拭で対応');
});

// ネイト指摘D-1: collectCurrentState は氏名欄をtrimするため、
// サーバー値と素で比較すると永久に不一致になり毎回バナーが出る。
test('buildDraft: 前後の空白だけの違いは「同じ」とみなす（オオカミ少年バナーの防止）', () => {
  const d = buildDraft(
    { residents: { '__short_stay_1__name': '山田 太郎' } },
    { residents: { '__short_stay_1__name': ' 山田 太郎 ' } },
  );
  assert.equal(d, null);
});

test('pickRestorable: 前後の空白だけの違いは復元を提案しない', () => {
  const r = pickRestorable(
    { residents: { '__short_stay_1__name': '山田 太郎' } },
    { '__short_stay_1__name': ' 山田 太郎 ' },
  );
  assert.deepEqual(r, {});
});

test('pickRestorable: サーバーに無い本文は提案する', () => {
  const r = pickRestorable(
    { residents: { '山田太郎': '届かなかった本文' } },
    { '山田太郎': '' },
  );
  assert.equal(r['山田太郎'], '届かなかった本文');
});

test('pickRestorable: 下書きが無ければ何も提案しない', () => {
  assert.deepEqual(pickRestorable(null, { '山田太郎': 'a' }), {});
  assert.deepEqual(pickRestorable({}, { '山田太郎': 'a' }), {});
});

// ─── isExpired ────────────────────────────────────────────
test('isExpired: 7日を超えた下書きは捨てる', () => {
  const now = 1_000_000_000_000;
  const week = 7 * 24 * 60 * 60 * 1000;
  assert.equal(isExpired({ savedAt: now - week + 1000 }, now), false);
  assert.equal(isExpired({ savedAt: now - week - 1000 }, now), true);
});

test('isExpired: savedAtが無い壊れた下書きは捨てる', () => {
  assert.equal(isExpired({}, Date.now()), true);
  assert.equal(isExpired(null, Date.now()), true);
});
