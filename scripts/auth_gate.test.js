const test = require('node:test');
const assert = require('node:assert');

const { needsLogin, describeAuthError, isSessionValid } = require('./auth_gate.js');

// ─── needsLogin: セッションの有無だけで判定する ───

test('セッションが無ければログインが要る', () => {
  assert.strictEqual(needsLogin(null), true);
  assert.strictEqual(needsLogin(undefined), true);
});

test('セッションがあればログインは要らない', () => {
  assert.strictEqual(needsLogin({ user: { id: 'u1' }, access_token: 't' }), false);
});

test('userの無いセッションは無効として扱う', () => {
  // supabase-jsが壊れたセッションを返した場合に素通ししない
  assert.strictEqual(needsLogin({ access_token: 't' }), true);
});

// ─── isSessionValid: 期限切れを検出する ───

test('期限が未来なら有効', () => {
  const future = Math.floor(Date.now() / 1000) + 3600;
  assert.strictEqual(isSessionValid({ user: { id: 'u1' }, expires_at: future }), true);
});

test('期限が過去なら無効', () => {
  const past = Math.floor(Date.now() / 1000) - 10;
  assert.strictEqual(isSessionValid({ user: { id: 'u1' }, expires_at: past }), false);
});

test('expires_atが無いセッションは有効とみなす（自動更新に任せる）', () => {
  // supabase-jsがrefreshを管理するため、期限情報が無いだけで蹴らない
  assert.strictEqual(isSessionValid({ user: { id: 'u1' } }), true);
});

test('セッションそのものが無ければ無効', () => {
  assert.strictEqual(isSessionValid(null), false);
});

// ─── describeAuthError: 現場が読んで分かる日本語にする ───

test('認証情報の誤りは「パスワードが違う」と伝える', () => {
  const msg = describeAuthError({ message: 'Invalid login credentials' });
  assert.match(msg, /パスワード/);
  // 英語のまま出さない
  assert.doesNotMatch(msg, /Invalid login credentials/);
});

test('通信エラーは電波の問題だと分かる文言にする', () => {
  const msg = describeAuthError({ message: 'Failed to fetch' });
  assert.match(msg, /通信|電波|ネット/);
});

test('未知のエラーでも必ず何か日本語が返る', () => {
  const msg = describeAuthError({ message: 'something unexpected happened' });
  assert.ok(msg.length > 0);
  assert.match(msg, /[ぁ-んァ-ン一-龥]/);
});

test('errorがnullでも落ちない', () => {
  const msg = describeAuthError(null);
  assert.ok(msg.length > 0);
});

test('レート制限は時間をおくよう伝える', () => {
  const msg = describeAuthError({ message: 'Email rate limit exceeded' });
  assert.match(msg, /しばらく|時間/);
});
