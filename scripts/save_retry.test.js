const test = require('node:test');
const assert = require('node:assert/strict');
const { nextRetryDelay, unsavedNotice, MAX_ATTEMPTS } = require('./save_retry.js');

// ─── nextRetryDelay ───────────────────────────────────────
test('nextRetryDelay: 1回目の失敗は5秒後、以降は倍々で60秒が上限', () => {
  assert.equal(nextRetryDelay(1), 5000);
  assert.equal(nextRetryDelay(2), 10000);
  assert.equal(nextRetryDelay(3), 20000);
  assert.equal(nextRetryDelay(4), 40000);
  assert.equal(nextRetryDelay(5), 60000);
  assert.equal(nextRetryDelay(9), 60000);
});

test('nextRetryDelay: 上限回数を超えたら諦める（人が対処する）', () => {
  assert.equal(nextRetryDelay(MAX_ATTEMPTS), 60000);
  assert.equal(nextRetryDelay(MAX_ATTEMPTS + 1), null);
});

test('nextRetryDelay: 0や不正値ではnull', () => {
  assert.equal(nextRetryDelay(0), null);
  assert.equal(nextRetryDelay(undefined), null);
});

// ─── unsavedNotice ────────────────────────────────────────
test('unsavedNotice: 未保存が無ければ何も出さない', () => {
  const r = unsavedNotice({ dirty: false, failedAttempts: 0, pendingConflicts: {}, online: true });
  assert.equal(r.show, false);
});

test('unsavedNotice: 保存に失敗している間は消えない表示を出す', () => {
  const r = unsavedNotice({ dirty: true, failedAttempts: 2, pendingConflicts: {}, online: true });
  assert.equal(r.show, true);
  assert.equal(r.level, 'retrying');
  assert.match(r.message, /未保存/);
  assert.match(r.message, /閉じないで/);
});

test('unsavedNotice: 通信が切れていればその旨を出す', () => {
  const r = unsavedNotice({ dirty: true, failedAttempts: 1, pendingConflicts: {}, online: false });
  assert.equal(r.level, 'offline');
  assert.match(r.message, /通信/);
});

// 2026-09-15 ネイト指摘B-5: 退避先が無い状態で「再読み込み」を促すと、
// サーバーに無い本文が消える＝記録を捨てさせることになる。絶対に言わない。
test('unsavedNotice: 諦めても「再読み込み」は促さない（記録を失わせない指示にする）', () => {
  const r = unsavedNotice({ dirty: true, failedAttempts: MAX_ATTEMPTS + 1, pendingConflicts: {}, online: true });
  assert.equal(r.level, 'giveup');
  assert.doesNotMatch(r.message, /再読み込み|リロード/);
  assert.match(r.message, /端末に控え/);   // localStorage退避があるので人力backupを求めない
  assert.doesNotMatch(r.message, /紙/);
});

test('unsavedNotice: 再試行中の文言に回数を出さない（連続失敗数と一致しないため）', () => {
  const r = unsavedNotice({ dirty: true, failedAttempts: 3, pendingConflicts: {}, online: true });
  assert.equal(r.level, 'retrying');
  assert.doesNotMatch(r.message, /回目/);
});

// 競合バナーを放置している間、その欄は送信対象から外れ続けるのに画面には文字が見えている。
// 未発生だが実在する経路（2026-09-15時点で本番に該当事故は確認できていない）。
test('unsavedNotice: 競合を放置している欄があれば、利用者名を挙げて消えない表示を出す', () => {
  const r = unsavedNotice({
    dirty: false, failedAttempts: 0, online: true,
    pendingConflicts: { residents: { '山田太郎': '相手の本文' } },
  });
  assert.equal(r.show, true);
  assert.equal(r.level, 'conflict');
  assert.match(r.message, /山田太郎/);
  assert.match(r.message, /保存されません/);
});

test('unsavedNotice: 競合が2名までは全員の名前を挙げる', () => {
  const r = unsavedNotice({
    dirty: false, failedAttempts: 0, online: true,
    pendingConflicts: { residents: { '山田太郎': 'a', '佐藤花子': 'b' } },
  });
  assert.match(r.message, /山田太郎/);
  assert.match(r.message, /佐藤花子/);
});

test('unsavedNotice: 競合が3名以上なら2名＋他N名に丸める（スマホで折り返さない）', () => {
  const r = unsavedNotice({
    dirty: false, failedAttempts: 0, online: true,
    pendingConflicts: { residents: { 'A野': 'a', 'B野': 'b', 'C野': 'c', 'D野': 'd' } },
  });
  assert.match(r.message, /他2名/);
  assert.doesNotMatch(r.message, /C野/);
});

test('unsavedNotice: 競合はdirtyでなくても最優先で出す（画面には文字が見えているため）', () => {
  const r = unsavedNotice({
    dirty: false, failedAttempts: 0, online: false,
    pendingConflicts: { residents: { '山田太郎': 'a' } },
  });
  assert.equal(r.level, 'conflict');
});
